"""应急咨询链路编排（ADR-009 时刻分层，智能应急咨询 §二/§五）。

编排流程（代码持有控制流——应急面受限自治）：
- start：红线判定 →（命中：高危桶卡+指引/走失流程｜未命中：桶卡+阶段单点问题）
- advance：阶段回答 → 状态替换 → 阶段卡/下一问 →（阶段流结束）触发方案生成
- _generate_plan：并行预取（档案+检索）→ 预注入 → 强制 Skill 单轮四段式 →
  契约校验 → SSE 推送 → 兜底信号后校验 → 落库
- followup：追问轮（红线门逐条生效 + rag_search 白名单 + 自由文本）

安全底线：红线判定/免责声明/兜底信号全部代码层，零 LLM 参与。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from py_db.models.consultation import Consultation, ConsultationSession
from py_logger import logger
from py_schemas.emergency import (
    DISCLAIMER_TEXT,
    ConsultStreamCreateRequest,
    EmergencyPlan,
    FallbackNoticeDto,
    RedlineGuideDto,
    SafetyCardDto,
    SourceRef,
)
from py_schemas.enums import (
    BehaviorBucket,
    FallbackSignal,
    GateResult,
    TurnType,
)
from py_schemas.streaming import SseEventType
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crisis.safety_layer import SafetyLayer
from app.modules.crisis.service import CrisisService
from app.modules.crisis.slot_filler import ProfileSnapshot
from app.modules.emergency.deterministic_fallback import (
    FALLBACK_MESSAGES,
    evaluate_followup_turns,
    evaluate_retrieval,
)
from app.modules.emergency.profile_provider import DbProfileSnapshotProvider
from app.modules.emergency.session_flow import EmergencySessionState, get_session_registry
from app.modules.emergency.stream_hub import get_stream_hub

# 走失一键流程指引（机制 §四：报警话术 + 优先排查水体 + 搜寻分工）
_ELOPEMENT_GUIDANCE = (
    "请立即拨打 110 报警，并按卡片话术说明情况。\n"
    "优先排查附近水体（河流/池塘/景观水池）——走失相关意外首因为溺水。\n"
    "现场分工：一人留守原地等候，一人沿最后出现点向外搜索。"
)

# 红线就医/紧急求助指引（标红置顶，机制 §四）
_REDLINE_GUIDANCE = (
    "当前情况涉及安全风险，本平台建议不能替代专业处置。\n"
    "如出现身体伤害或情况失控，请立即拨打 120；用药相关问题请联系主治医生。"
)


class EmergencyService:
    """应急链路编排服务。"""

    def __init__(
        self,
        crisis_service: CrisisService,
        safety_layer: SafetyLayer,
        session_factory: Any,
        model_factory: Any | None = None,
    ) -> None:
        self._crisis = crisis_service
        self._safety = safety_layer
        self._session_factory = session_factory
        self._model_factory = model_factory  # 测试注入 TestModel 工厂；None = 生产 DeepSeek
        self._registry = get_session_registry()
        self._hub = get_stream_hub()

    # ==================================================================
    # 创建会话（桶选择入口）
    # ==================================================================

    async def start(
        self,
        user_id: str,
        request: ConsultStreamCreateRequest,
        db: AsyncSession,
    ) -> str:
        """桶选择入口：红线判定 → 分支供给 → 返回 session_id。"""
        assert request.bucket is not None  # 契约层已校验
        bucket = request.bucket
        profile_id = str(request.profile_id) if request.profile_id else None

        # 1. 红线判定（代码层零 LLM）
        gate_result = await self._crisis.evaluate_gate(
            db,
            _gate_request(bucket, request.text, profile_id),
            record_event=False,  # 会话创建后统一落库（带 session_id）
        )

        # 2. 创建 DB 会话
        db_session = ConsultationSession(
            user_id=uuid.UUID(user_id),
            profile_id=uuid.UUID(profile_id) if profile_id else None,
            bucket=bucket,
        )
        db.add(db_session)
        await db.flush()
        session_id = str(db_session.id)

        state = EmergencySessionState(
            session_id=session_id,
            user_id=user_id,
            profile_id=profile_id,
            bucket=bucket,
            phase="stage_qa",
        )
        self._registry.put(state)

        snapshot = await self._load_snapshot(db, profile_id)

        # 3. 分支：红线 / 非红线
        if gate_result.gate_result == GateResult.REDLINE:
            await self._crisis.evaluate_gate(
                db,
                _gate_request(bucket, request.text, profile_id),
                session_id=db_session.id,
                record_event=True,
            )
            if bucket == BehaviorBucket.ELOPEMENT:
                state.phase = "elopement"
                await self._serve_elopement_flow(session_id, snapshot, gate_result.gate_trigger or "")
            else:
                state.phase = "redline"
                await self._serve_redline(db, session_id, bucket, snapshot, gate_result.gate_trigger or "")
            await db.commit()
            return session_id

        # 非红线：桶卡 + 首个阶段问题
        await self._serve_bucket_card(db, session_id, bucket, snapshot)
        await self._ask_next_question(state)
        await db.commit()
        return session_id

    # ==================================================================
    # 会话推进（阶段回答 / 补充描述）
    # ==================================================================

    async def advance(
        self,
        session_id: str,
        request: ConsultStreamCreateRequest,
        db: AsyncSession,
    ) -> None:
        """阶段回答推进或文字补充（触发精化重生成）。"""
        state = self._require_state(session_id)

        if request.stage_answer:
            await self._handle_stage_answer(state, request.stage_answer, db)
        elif request.text:
            # 补充文字细节 → 精化重生成（机制 §5.1）
            state.phase = "generating"
            asyncio.create_task(self._generate_plan(state, request.text))

    async def _handle_stage_answer(
        self,
        state: EmergencySessionState,
        answer: str,
        db: AsyncSession,
    ) -> None:
        """阶段回答 → 状态替换 → 阶段卡/下一问/触发生成。"""
        question_id = state.pending_question_id
        if not question_id:
            return

        new_stage, meltdown_type, next_q = self._safety.resolve_stage_answer(
            question_id, answer, state.bucket
        )
        if meltdown_type is not None:
            state.meltdown_type = meltdown_type
        if new_stage is not None:
            state.stage = new_stage
            # 阶段卡替换（槽位填充）
            snapshot = await self._load_snapshot(db, state.profile_id)
            card = await self._safety.get_stage_card(db, state.bucket, new_stage, snapshot)
            if card:
                await self._publish_card(state.session_id, card)
                state.cards_shown.append(card.card_id)

        # DB 同步阶段/分流结论
        await self._sync_session_state(state, db)

        if next_q:
            state.pending_question_id = next_q
            question = self._next_question_by_id(next_q, state.bucket)
            if question:
                await self._publish_question(state.session_id, question)
        else:
            # 阶段流结束 → 触发首份方案生成（后台）
            state.pending_question_id = None
            state.phase = "generating"
            asyncio.create_task(self._generate_plan(state, None))

    # ==================================================================
    # 追问轮
    # ==================================================================

    async def followup(self, session_id: str, text: str, db: AsyncSession) -> None:
        """追问轮（通用 Agent 会话，自由文本，红线门逐条生效）。"""
        state = self._require_state(session_id)
        state.phase = "followup"
        state.followup_count += 1

        # 红线关键词门对每条输入生效（安全不变量）
        gate_result = await self._crisis.evaluate_gate(
            db,
            _gate_request(None, text, state.profile_id),
            session_id=uuid.UUID(session_id),
            record_event=True,
        )
        if gate_result.gate_result == GateResult.REDLINE:
            snapshot = await self._load_snapshot(db, state.profile_id)
            state.phase = "redline"
            await self._serve_redline(db, session_id, state.bucket, snapshot, gate_result.gate_trigger or "")
            return

        asyncio.create_task(self._run_followup(state, text))

    # ==================================================================
    # 未解决标记（兜底信号）
    # ==================================================================

    async def mark_unresolved(self, session_id: str, db: AsyncSession) -> None:
        """用户标记未解决 → 兜底信号（强提示 + 求助指引 + 事件落库）。"""
        state = self._require_state(session_id)
        state.unresolved_marked = True
        await self._publish_fallback(session_id, FallbackSignal.USER_UNRESOLVED)
        await self._log_event(session_id, "fallback_triggered", {"signal": FallbackSignal.USER_UNRESOLVED.value})
        await db.commit()

    # ==================================================================
    # 此刻安全层供给
    # ==================================================================

    async def _serve_bucket_card(
        self,
        db: AsyncSession,
        session_id: str,
        bucket: BehaviorBucket,
        snapshot: ProfileSnapshot | None,
    ) -> None:
        card = await self._safety.get_bucket_card(db, bucket, snapshot)
        if card:
            await self._publish_card(session_id, card)
            state = self._registry.get(session_id)
            if state:
                state.cards_shown.append(card.card_id)

    async def _serve_redline(
        self,
        db: AsyncSession,
        session_id: str,
        bucket: BehaviorBucket,
        snapshot: ProfileSnapshot | None,
        gate_trigger: str,
    ) -> None:
        """红线命中：高危桶卡（标红置顶）+ 就医指引，不进入方案层。"""
        card = await self._safety.get_redline_card(db, bucket, snapshot)
        if card:
            await self._publish_card(session_id, card)
        guide = RedlineGuideDto(
            card=card or SafetyCardDto(card_id="", bucket=bucket, title="紧急情况", content="", variant="redline"),
            guidance=_REDLINE_GUIDANCE,
            gate_trigger=gate_trigger,
        )
        await self._hub.publish(session_id, SseEventType.REDLINE_GUIDE, {"guide": guide.model_dump(mode="json")})
        await self._hub.publish(session_id, SseEventType.DONE, {"finish_reason": "REDLINE"})
        await self._log_event(session_id, "redline_served", {"gate_trigger": gate_trigger})

    async def _serve_elopement_flow(
        self,
        session_id: str,
        snapshot: ProfileSnapshot | None,
        gate_trigger: str,
    ) -> None:
        """走失一键流程：报警话术卡 + 水体提醒 + 搜寻分工（独立流程，跳过常规链路）。"""
        card = await self._build_elopement_card(session_id, snapshot)
        await self._publish_card(session_id, card)
        guide = RedlineGuideDto(card=card, guidance=_ELOPEMENT_GUIDANCE, gate_trigger=gate_trigger)
        await self._hub.publish(session_id, SseEventType.REDLINE_GUIDE, {"guide": guide.model_dump(mode="json")})
        await self._hub.publish(session_id, SseEventType.DONE, {"finish_reason": "REDLINE"})
        await self._log_event(session_id, "elopement_flow_served", {"gate_trigger": gate_trigger})

    async def _build_elopement_card(self, session_id: str, snapshot: ProfileSnapshot | None) -> SafetyCardDto:
        """走失流程卡：库模板优先，缺失回退内置保底模板（含槽位填充）。"""
        factory = self._session_factory()
        async with factory() as db:
            card = await self._safety.get_elopement_card(db, snapshot)
            if card is not None:
                return card
        # 内置保底模板（机制 §四：报警话术 + 档案槽位）
        from app.modules.crisis.slot_filler import fill_slots

        template = (
            "【走失应急】立即报警话术\n"
            "我的孩子{称呼}走失了。{体貌特征}。他是孤独症患者，可能没有危险意识，不会回应呼唤。"
            "他常去的地方：{常去地点}。"
        )
        content, personalized = fill_slots(template, snapshot)
        return SafetyCardDto(
            card_id="builtin-elopement",
            bucket=BehaviorBucket.ELOPEMENT,
            title="走失一键应急",
            content=content,
            personalized=personalized,
            variant="elopement",
        )

    # ==================================================================
    # 完整方案层（Agent 单轮生成）
    # ==================================================================

    async def _generate_plan(self, state: EmergencySessionState, extra_text: str | None) -> None:
        """首份方案生成（并行预取 → 预注入 → 强制 Skill 单轮四段式）。"""
        session_id = state.session_id
        factory = self._session_factory()
        async with factory() as db:
            try:
                # ① 并行预取：档案快照 + rag_search（桶为检索过滤维度）
                snapshot_task = self._load_snapshot(db, state.profile_id)
                retrieval_task = self._rag_search(db, state, extra_text)
                snapshot, slices = await asyncio.gather(snapshot_task, retrieval_task)

                # 检索质量兜底判定（生成前已知——信号随方案事件发出）
                retrieval_signal = evaluate_retrieval(slices)
                state.retrieval_insufficient = retrieval_signal is not None

                # ② 预注入上下文（档案 + Top-K 案例 + 会话记录）
                user_prompt = self._build_plan_prompt(state, snapshot, slices, extra_text)

                # ③ 强制加载 emergency-consult Skill 单轮生成（四段式契约校验）
                plan = await self._run_agent_plan(state, user_prompt)

                if plan is None:
                    # 契约校验失败/模型不可用 → 降级检索结果直出（机制 §九）
                    await self._serve_degraded_plan(state, slices, retrieval_signal)
                    return

                # ④ SSE：result 事件（契约校验通过）
                sources = self._build_sources(slices)
                plan_payload = plan.model_copy(update={"sources": sources})
                await self._hub.publish(
                    session_id,
                    SseEventType.RESULT,
                    {"contract": "EmergencyPlan", "payload": plan_payload.model_dump(mode="json")},
                )

                # ⑤ 兜底信号后校验
                if retrieval_signal:
                    await self._publish_fallback(session_id, retrieval_signal)
                    await self._log_event(session_id, "fallback_triggered", {"signal": retrieval_signal.value})

                await self._hub.publish(session_id, SseEventType.DONE, {"finish_reason": "COMPLETE"})

                # ⑥ 落库（首份方案轮次）
                await self._persist_plan_turn(db, state, plan_payload, slices, extra_text)

                state.phase = "followup"
            except Exception as exc:
                logger.error(
                    service="api-server",
                    message="emergency_plan_generation_failed",
                    extra={"session_id": session_id, "error": str(exc)},
                )
                await self._hub.publish(
                    session_id,
                    SseEventType.ERROR,
                    {"error_code": "LLM_UNAVAILABLE", "detail": "方案生成服务暂不可用，请稍后重试或联系专业机构"},
                )

    async def _run_agent_plan(self, state: EmergencySessionState, user_prompt: str) -> EmergencyPlan | None:
        """Agent 单轮四段式生成（强制 Skill + 契约校验 + 硬超时）。"""
        from app.core.agent_bootstrap import create_emergency_session

        try:
            model = self._model_factory() if self._model_factory else self._build_production_model()
        except RuntimeError:
            return None  # 模型不可用 → 降级路径

        skill_body = self._load_skill_body()
        system_prompt = f"{skill_body}\n\n{DISCLAIMER_TEXT}"

        agent_session = create_emergency_session(
            model=model,
            session_id=state.session_id,
            followup=False,
            output_type=EmergencyPlan,
            system_prompt=system_prompt,
        )

        try:
            # 硬超时（Agent 基座 §5.1）
            output = await asyncio.wait_for(agent_session.run(user_prompt), timeout=60.0)
            if isinstance(output, EmergencyPlan):
                return output
            # output_type 校验失败时 pydantic-ai 抛异常；非契约实例防御
            return None
        except Exception as exc:
            logger.warning(
                service="api-server",
                message="emergency_plan_agent_failed",
                extra={"session_id": state.session_id, "error": str(exc)[:200]},
            )
            return None

    def _build_production_model(self) -> Any:
        from app.core.agent_bootstrap import build_emergency_model

        return build_emergency_model()

    def _load_skill_body(self) -> str:
        """强制加载 emergency-consult Skill 正文（不依赖模型自主选择）。"""
        from pathlib import Path

        skill_md = (
            Path(__file__).resolve().parents[5]
            / "packages/py-agent-extensions/py_agent_extensions/emergency/skills/emergency-consult/SKILL.md"
        )
        if skill_md.exists():
            raw = skill_md.read_text(encoding="utf-8")
            if raw.startswith("---"):
                end = raw.find("\n---", 3)
                if end != -1:
                    return raw[end + 4 :].strip()
            return raw
        return "你是孤独症家庭应急支持专家。按四段式输出应急方案。"

    # ==================================================================
    # 追问轮 Agent
    # ==================================================================

    async def _run_followup(self, state: EmergencySessionState, text: str) -> None:
        """追问轮生成（自由文本 + rag_search 白名单 + chunk 流式）。"""
        session_id = state.session_id
        factory = self._session_factory()
        async with factory() as db:
            try:
                from app.core.agent_bootstrap import create_emergency_session

                model = self._model_factory() if self._model_factory else self._build_production_model()
                agent_session = create_emergency_session(
                    model=model,
                    session_id=f"{session_id}-followup",
                    followup=True,
                )
                prompt = self._build_followup_prompt(state, text)

                reply_parts: list[str] = []
                async for event in agent_session.run_stream(prompt):
                    if event.type == "message_update":
                        delta = str(event.data.get("delta", ""))
                        if delta:
                            reply_parts.append(delta)
                            await self._hub.publish(session_id, SseEventType.CHUNK, {"text": delta})
                    elif event.type == "message_end":
                        if not reply_parts:
                            content = str(event.data.get("content", ""))
                            if content:
                                reply_parts.append(content)
                                await self._hub.publish(session_id, SseEventType.CHUNK, {"text": content})

                reply = "".join(reply_parts) or "（暂无回复）"

                # 追问轮次兜底判定
                followup_signal = evaluate_followup_turns(state.followup_count)
                if followup_signal:
                    await self._publish_fallback(session_id, followup_signal)
                    await self._log_event(session_id, "fallback_triggered", {"signal": followup_signal.value})

                await self._hub.publish(session_id, SseEventType.DONE, {"finish_reason": "COMPLETE"})
                await self._persist_followup_turn(db, state, text, reply)
            except Exception as exc:
                logger.error(
                    service="api-server",
                    message="emergency_followup_failed",
                    extra={"session_id": session_id, "error": str(exc)},
                )
                await self._hub.publish(
                    session_id,
                    SseEventType.ERROR,
                    {"error_code": "LLM_UNAVAILABLE", "detail": "回复生成失败，请稍后重试"},
                )

    # ==================================================================
    # 预取与预注入
    # ==================================================================

    async def _load_snapshot(self, db: AsyncSession, profile_id: str | None) -> ProfileSnapshot | None:
        if not profile_id:
            return None
        provider = DbProfileSnapshotProvider(db)
        return await provider.get_snapshot(profile_id)

    async def _rag_search(self, db: AsyncSession, state: EmergencySessionState, extra_text: str | None) -> list[Any]:
        """rag_search 预取（桶为检索过滤维度）。"""
        from py_rag.embedding import _get_encoder
        from py_rag.retrieval import PgVectorSearch

        query = extra_text or f"{state.bucket.value} 应急干预"
        try:
            engine = PgVectorSearch(embedding_encoder=_get_encoder())
            result = await engine.search(query_text=query, top_k=5, db=db)
            return list(result.results)
        except Exception as exc:
            logger.warning(
                service="api-server",
                message="rag_search_failed",
                extra={"session_id": state.session_id, "error": str(exc)[:200]},
            )
            return []

    def _build_plan_prompt(
        self,
        state: EmergencySessionState,
        snapshot: ProfileSnapshot | None,
        slices: list[Any],
        extra_text: str | None,
    ) -> str:
        """预注入上下文构建（≤5 事件 + Top-K 案例 + 会话记录）。"""
        parts: list[str] = []
        # 会话记录
        parts.append(f"【会话记录】行为桶：{state.bucket.value}（{state.bucket.ui_label}）")
        if state.stage:
            parts.append(f"危机阶段：{state.stage.value}")
        if state.meltdown_type:
            parts.append(f"分流结论：{state.meltdown_type.value}")
        # 档案快照
        if snapshot and snapshot.nickname:
            parts.append(f"【档案】称呼：{snapshot.nickname}")
            if snapshot.triggers:
                parts.append(f"已知触发物：{'、'.join(snapshot.triggers)}")
            if snapshot.communication_methods:
                parts.append(f"沟通方式：{'、'.join(snapshot.communication_methods)}")
        # 案例切片（Top-K）
        if slices:
            parts.append("【参考案例】")
            for i, s in enumerate(slices[:5], 1):
                text = str(getattr(s, "slice_text", ""))[:300]
                parts.append(f"[{i}] {text}")
        if extra_text:
            parts.append(f"【家属补充】{extra_text}")
        parts.append("请按四段式输出应急方案（每段标注来源案例编号）。")
        return "\n".join(parts)

    def _build_followup_prompt(self, state: EmergencySessionState, text: str) -> str:
        parts = [
            f"【会话记录】行为桶：{state.bucket.value}；阶段：{state.stage.value if state.stage else '未判定'}",
            f"【家属追问】{text}",
        ]
        return "\n".join(parts)

    def _build_sources(self, slices: list[Any]) -> list[SourceRef]:
        sources: list[SourceRef] = []
        for s in slices[:5]:
            title = getattr(s, "case_title", None) or "案例库案例"
            sources.append(
                SourceRef(
                    case_id=str(getattr(s, "slice_id", "")) or None,
                    title=title,
                    source_type="案例",
                )
            )
        return sources

    async def _serve_degraded_plan(
        self,
        state: EmergencySessionState,
        slices: list[Any],
        retrieval_signal: FallbackSignal | None,
    ) -> None:
        """降级路径：检索结果直出模板（机制 §九——不允许未校验内容到达家属）。"""
        session_id = state.session_id
        if slices:
            lines = ["以下参考案例来自专家审核案例库，供您参考："]
            for i, s in enumerate(slices[:3], 1):
                lines.append(f"{i}. {str(getattr(s, 'slice_text', ''))[:200]}")
            lines.append("")
            lines.append(f"【就医判断标准】如情况持续或加重，请立即联系专业机构。{DISCLAIMER_TEXT}")
            content = "\n".join(lines)
        else:
            content = (
                "当前无法生成个性化方案。请先确保环境安全（移走危险物品、降低刺激），"
                f"并尽快联系主治医生或专业机构。{DISCLAIMER_TEXT}"
            )
        await self._hub.publish(session_id, SseEventType.CHUNK, {"text": content})
        if retrieval_signal:
            await self._publish_fallback(session_id, retrieval_signal)
        await self._hub.publish(session_id, SseEventType.DONE, {"finish_reason": "PARTIAL"})
        state.phase = "followup"

    # ==================================================================
    # 落库
    # ==================================================================

    async def _persist_plan_turn(
        self,
        db: AsyncSession,
        state: EmergencySessionState,
        plan: EmergencyPlan,
        slices: list[Any],
        extra_text: str | None,
    ) -> None:
        turn = Consultation(
            session_id=uuid.UUID(state.session_id),
            turn_type=TurnType.INITIAL_PLAN,
            behavior_description=extra_text,
            retrieved_case_ids=[str(getattr(s, "slice_id", "")) for s in slices],
            generated_plan=plan.model_dump(mode="json"),
            sources=[s.model_dump(mode="json") for s in plan.sources],
            disclaimer_served=True,
        )
        db.add(turn)
        await db.commit()

    async def _persist_followup_turn(
        self,
        db: AsyncSession,
        state: EmergencySessionState,
        text: str,
        reply: str,
    ) -> None:
        turn = Consultation(
            session_id=uuid.UUID(state.session_id),
            turn_type=TurnType.FOLLOWUP,
            behavior_description=text,
            reply_text=reply,
            disclaimer_served=True,
        )
        db.add(turn)
        await db.commit()

    async def _log_event(self, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
        from py_db.models.consultation import ConsultationLog

        factory = self._session_factory()
        async with factory() as db:
            db.add(
                ConsultationLog(
                    session_id=uuid.UUID(session_id),
                    event_type=event_type,
                    payload=payload,
                )
            )
            await db.commit()

    async def _sync_session_state(self, state: EmergencySessionState, db: AsyncSession) -> None:
        from sqlalchemy import select

        result = await db.execute(
            select(ConsultationSession).where(ConsultationSession.id == uuid.UUID(state.session_id))
        )
        db_session = result.scalars().first()
        if db_session:
            db_session.crisis_stage = state.stage
            db_session.meltdown_type = state.meltdown_type
            await db.commit()

    # ==================================================================
    # 事件发布辅助
    # ==================================================================

    async def _publish_card(self, session_id: str, card: SafetyCardDto) -> None:
        await self._hub.publish(session_id, SseEventType.SAFETY_CARD, {"card": card.model_dump(mode="json")})

    async def _publish_question(self, session_id: str, question: Any) -> None:
        await self._hub.publish(
            session_id, SseEventType.STAGE_QUESTION, {"question": question.model_dump(mode="json")}
        )

    async def _publish_fallback(self, session_id: str, signal: FallbackSignal) -> None:
        message, guidance = FALLBACK_MESSAGES[signal]
        notice = FallbackNoticeDto(signal=signal, message=message, guidance=guidance)
        await self._hub.publish(
            session_id, SseEventType.FALLBACK_NOTICE, {"notice": notice.model_dump(mode="json")}
        )

    async def _ask_next_question(self, state: EmergencySessionState) -> None:
        question = self._safety.next_stage_question(state.bucket, state.stage, state.meltdown_type)
        if question:
            state.pending_question_id = question.question_id
            await self._publish_question(state.session_id, question)
        else:
            # 无阶段问答（占位实现下不会发生，防御）
            state.phase = "generating"
            asyncio.create_task(self._generate_plan(state, None))

    def _next_question_by_id(self, question_id: str, bucket: BehaviorBucket) -> Any | None:
        """按 ID 取下一问（状态机内嵌于 safety_layer，经 next_stage_question 驱动）。"""
        from py_schemas.emergency import StageQuestionDto

        questions = {
            "Q_WANT": ("他这样做，有没有明确想要的东西？", ["有", "没有"]),
            "Q_STOP": ("满足他之后，会停下来吗？", ["会", "不会"]),
            "Q_LISTEN": ("他现在还能听进你说话吗？", ["能", "不能"]),
            "Q_HARM": ("他有没有伤害自己或他人的动作？", ["有", "没有"]),
        }
        if question_id in questions:
            q, opts = questions[question_id]
            return StageQuestionDto(question_id=question_id, question=q, options=opts)
        return None

    def _require_state(self, session_id: str) -> EmergencySessionState:
        state = self._registry.get(session_id)
        if state is None:
            raise KeyError(f"会话不存在或已过期: {session_id}")
        return state


def _gate_request(bucket: BehaviorBucket | None, text: str | None, profile_id: str | None):
    from py_schemas.crisis import RedlineGateRequest

    return RedlineGateRequest(bucket=bucket, text=text, profile_id=profile_id)


__all__ = ["EmergencyService"]
