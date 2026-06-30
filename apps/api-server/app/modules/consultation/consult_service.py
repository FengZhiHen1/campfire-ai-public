"""CSLT-02/08 应急咨询编排 — consult_service。

模块: app.modules.consultation.consult_service
职责: 应急咨询编排实现。ConsultationOrchestratorImpl 继承 BaseConsultationOrchestrator ABC，
      @final 公共入口 start_consultation/search_cases 强制执行前置→执行→后置三步流程。
      模块级便捷函数委托给单例实例，保持 routes.py 的导入兼容。
数据来源:
  - py_rag.hybrid_search: MUST — RAG 语义检索引擎
  - app.modules.crisis: MUST — 危机分级判定（快速规则，无 LLM）
边界:
  - 依赖: py_rag, py_logger, py_schemas, app.modules.crisis, app.core.streaming
  - 被依赖: routes.py
禁止行为:
  - 禁止在 _do_ 钩子中调用 super()
  - 禁止绕过 @final 方法直接调用 _do_ 钩子
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.models.profiles import EventLog, Profile
from py_logger import logger
from py_rag.retrieval import hybrid_search
from py_schemas.consult import (
    SemanticSearchInput,
    SemanticSearchResult,
)

from py_schemas.crisis import (
    CrisisJudgmentResult,
    CrisisJudgmentRequest,
    JudgmentLayerResult,
)
from app.modules.crisis.models import PatientProfileSnapshot
from py_schemas.enums.crisis_enums import CrisisLevel, BehaviorTypeCategory
from app.modules.consultation.plan_generation.blocked_outputs import (
    BLOCKED_PROMPT_TEMPLATES,
    DEFAULT_BLOCKED_TEXT,
    DISCLAIMER_TEXT,
)
from app.modules.consultation.plan_generation.models import (
    EmergencyPlanInput,
    GenerationChunk,
    PromptBuildContext,
)
from app.modules.consultation.plan_generation.prompt_builder import PromptBuilder
from app.modules.consultation.plan_generation.service import _infer_block_variant
from app.modules.consultation.plan_generation.streaming import stream_generate

from .consultation_contract import BaseConsultationOrchestrator
from .types import BehaviorDescription, ProfileSummary, RequestId


# ============================================================================
# ConsultationOrchestratorImpl — 实现 BaseConsultationOrchestrator ABC
# ============================================================================


class ConsultationOrchestratorImpl(BaseConsultationOrchestrator):
    """应急咨询编排实现。继承 BaseConsultationOrchestrator ABC，仅覆写 _do_ 钩子。"""

    # ========================================================================
    # _do_ 钩子
    # ========================================================================

    async def _do_load_profile(
        self,
        profile_id: str | None,
        db: AsyncSession,
    ) -> ProfileSummary:
        if not profile_id:
            return ProfileSummary("（未关联档案）")

        try:
            pid = uuid.UUID(profile_id)
        except ValueError:
            logger.warning("consult", "invalid_profile_id", extra={"profile_id": profile_id})
            return ProfileSummary("（未关联档案）")

        result = await db.execute(
            select(Profile).where(Profile.profile_id == pid)
        )
        profile = result.scalars().first()
        if profile is None:
            logger.warning("consult", "profile_not_found", extra={"profile_id": profile_id})
            return ProfileSummary("（未关联档案）")

        # 计算年龄
        today = date.today()
        age = today.year - profile.birth_date.year
        if today.month < profile.birth_date.month or (
            today.month == profile.birth_date.month
            and today.day < profile.birth_date.day
        ):
            age -= 1

        parts: list[str] = []
        if profile.nickname:
            parts.append(f"- **昵称**：{profile.nickname}")
        parts.append(f"- **年龄**：{age} 岁")
        parts.append(f"- **诊断类型**：{profile.diagnosis_type}")
        parts.append(f"- **主要行为**：{profile.primary_behavior}")
        if profile.sensory_features:
            parts.append(f"- **感官特征**：{'、'.join(profile.sensory_features)}")
        if profile.triggers:
            parts.append(f"- **触发因素**：{'、'.join(profile.triggers)}")
        if profile.medication_notes:
            parts.append(f"- **用药备注**：{profile.medication_notes}")

        # 最近事件（最多 5 条）
        events_result = await db.execute(
            select(EventLog)
            .where(EventLog.profile_id == pid)
            .order_by(desc(EventLog.event_time))
            .limit(5)
        )
        events = events_result.scalars().all()
        if events:
            parts.append("")
            parts.append("- **最近事件**：")
            for i, ev in enumerate(events, start=1):
                parts.append(
                    f"  {i}. {ev.event_time.strftime('%Y-%m-%d')}"
                    f" | {ev.behavior_type}（{ev.severity_level}）"
                    f" — {ev.manifestation[:80]}"
                )

        logger.info(
            service="api-server",
            message="profile_loaded",
            extra={"profile_id": profile_id, "age": age, "event_count": len(events)},
        )
        return ProfileSummary("\n".join(parts))

    async def _do_search_cases(
        self,
        query_text: str,
        behavior_type: list[str] | None,
        emotion_level: str | None,
        request_id: RequestId,
        db: AsyncSession,
    ) -> Any:
        # NOTE: 当前 hybrid_search 为纯语义检索，未接入 behavior_type/emotion_level 标签过滤。
        # 该能力需在 py_rag 检索层扩展后再传递 tag_filters。
        _ = behavior_type, emotion_level

        logger.info(
            service="api-server",
            message="consult_search_started",
            op_type="consult_search",
            extra={"request_id": str(request_id), "query_len": len(query_text), "top_k": 10},
        )

        result: SemanticSearchResult = await hybrid_search(
            query_text=query_text,
            top_k=10,
            request_id=str(request_id),
            db=db,
        )

        logger.info(
            service="api-server",
            message="consult_search_done",
            op_type="consult_search",
            extra={
                "result_count": result.total_count,
                "is_complete": result.is_complete,
                "reason": result.reason,
                "elapsed_ms": result.elapsed_ms,
            },
        )
        return result

    async def _do_judge_crisis(
        self,
        behavior_description: str,
        behavior_type: list[str] | None,
        profile_summary: ProfileSummary,
        profile_id: str | None,
        db: AsyncSession,
    ) -> Any:
        try:
            from app.modules.crisis import judge_crisis

            behavior_type_selection: list[BehaviorTypeCategory] = []
            if behavior_type:
                for bt in behavior_type:
                    try:
                        behavior_type_selection.append(BehaviorTypeCategory(bt))
                    except ValueError:
                        logger.warning("consult", "invalid_behavior_type", extra={"value": bt})

            if not behavior_type_selection:
                behavior_type_selection = [BehaviorTypeCategory.OTHER]

            # 构建患者档案快照注入 CSLT-01
            patient_profile: PatientProfileSnapshot | None = None
            if profile_id:
                try:
                    pid = uuid.UUID(profile_id)
                    result = await db.execute(
                        select(Profile).where(Profile.profile_id == pid)
                    )
                    profile = result.scalars().first()
                    if profile is not None:
                        # 历史行为标签：从主要行为 + 最近事件推导
                        historical_tags: set[str] = set()
                        if profile.primary_behavior:
                            historical_tags.add(profile.primary_behavior)

                        events_result = await db.execute(
                            select(EventLog)
                            .where(EventLog.profile_id == pid)
                            .order_by(desc(EventLog.event_time))
                            .limit(5)
                        )
                        events = events_result.scalars().all()
                        recent_event_records: list[dict[str, Any]] = []
                        for ev in events:
                            if ev.behavior_type:
                                historical_tags.add(ev.behavior_type)
                            recent_event_records.append({
                                "event_type": ev.behavior_type,
                                "severity": ev.severity_level,
                                "occurred_at": ev.event_time.isoformat() if ev.event_time else None,
                                "manifestation": ev.manifestation,
                            })

                        patient_profile = PatientProfileSnapshot(
                            diagnosis_type=profile.diagnosis_type,
                            historical_behavior_tags=sorted(historical_tags),
                            recent_event_records=recent_event_records,
                        )
                except Exception as exc:
                    logger.warning(
                        service="api-server",
                        message="patient_profile_snapshot_build_failed",
                        op_type="crisis_judgment",
                        extra={"profile_id": profile_id, "error": str(exc)},
                    )

            crisis_request = CrisisJudgmentRequest(
                patient_profile=patient_profile,
                behavior_type_selection=behavior_type_selection,
                behavior_description=behavior_description,
            )
            return await judge_crisis(crisis_request)
        except Exception as exc:
            logger.error(
                "consult",
                "crisis_judgment_failed",
                op_type="crisis_judgment_fallback",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            return CrisisJudgmentResult(
                final_level=CrisisLevel.MILD,
                block_deep_response=False,
                judgment_sources=[
                    JudgmentLayerResult(layer_name="Fallback", level=CrisisLevel.MILD)
                ],
                degradation_note="crisis_judgment_failed",
            )

    def _do_build_plan_input(
        self,
        behavior_description: BehaviorDescription,
        profile_summary: ProfileSummary,
        search_result: Any,
        crisis_result: Any,
        request_id: RequestId,
    ) -> Any:
        return EmergencyPlanInput(
            crisis_result=crisis_result,
            search_result=search_result,
            profile_summary=str(profile_summary),
            behavior_description=str(behavior_description),
            request_id=str(request_id),
        )

    def _do_generate_stream(self, plan_input: Any) -> tuple[Any, Any]:
        """返回 (generator, prompt_ctx)，prompt_ctx 用于引用切片反查。

        若 crisis_result.block_deep_response=True，直接返回阻断安全提示生成器，
        不调用 LLM。
        """
        if plan_input.crisis_result.block_deep_response:
            return self._build_blocked_stream(plan_input)

        builder = PromptBuilder()
        messages, ctx = builder.build(plan_input)
        generator = stream_generate(
            input_data=plan_input,
            messages=messages,
            prenumbered_slices=ctx.prenumbered_slices,
        )
        return generator, ctx

    def _build_blocked_stream(
        self,
        plan_input: Any,
    ) -> tuple[Any, Any]:
        """构建 severe 阻断场景下的安全提示流。

        不调用 LLM，直接产出预设安全提示文本 + 免责声明，
        并以 finish_reason=BLOCKED 结束。
        """
        block_variant = _infer_block_variant(plan_input)
        blocked_text = (
            BLOCKED_PROMPT_TEMPLATES[block_variant]
            if block_variant
            else DEFAULT_BLOCKED_TEXT
        )
        full_text = f"{blocked_text}\n\n---\n\n{DISCLAIMER_TEXT}"

        async def _blocked_generator():
            yield GenerationChunk(
                text=full_text,
                section=None,
                is_final=False,
            )
            yield GenerationChunk(
                text="",
                section=None,
                is_final=True,
                finish_reason="BLOCKED",
                raw_full_text=full_text,
            )

        ctx = PromptBuildContext(
            prenumbered_slices=[],
            slice_text_block="",
            profile_markdown=plan_input.profile_summary,
            has_cases=False,
        )
        return _blocked_generator(), ctx

    async def _do_execute_search(self, request: Any, db: AsyncSession) -> Any:
        logger.info(
            service="api-server",
            message="standalone_search_started",
            op_type="standalone_search",
            extra={"request_id": request.request_id, "query_len": len(request.query_text), "top_k": request.top_k},
        )

        result: SemanticSearchResult = await hybrid_search(
            query_text=request.query_text,
            top_k=request.top_k,
            request_id=request.request_id,
            db=db,
        )

        logger.info(
            service="api-server",
            message="standalone_search_done",
            op_type="standalone_search",
            extra={
                "result_count": result.total_count,
                "is_complete": result.is_complete,
                "reason": result.reason,
                "elapsed_ms": result.elapsed_ms,
            },
        )
        return result


# ============================================================================
# 模块级单例 + 便捷函数（routes.py 导入入口）
# ============================================================================

_orchestrator = ConsultationOrchestratorImpl()


async def start_consultation(
    behavior_description: str,
    profile_id: str | None,
    behavior_type: list[str] | None,
    emotion_level: str | None,
    user_id: str,
    db: AsyncSession,
) -> str:
    """启动应急咨询（委托给 ConsultationOrchestratorImpl ABC 单例）。"""
    result = await _orchestrator.start_consultation(
        behavior_description=behavior_description,
        profile_id=profile_id,
        behavior_type=behavior_type,
        emotion_level=emotion_level,
        user_id=user_id,
        db=db,
    )
    return str(result)


async def search_cases(
    request: SemanticSearchInput,
    db: AsyncSession,
) -> SemanticSearchResult:
    """语义检索（委托给 ConsultationOrchestratorImpl ABC 单例）。"""
    return await _orchestrator.search_cases(request=request, db=db)


__all__ = [
    "ConsultationOrchestratorImpl",
    "search_cases",
    "start_consultation",
]
