"""CSLT-02/03/04/08 应急咨询编排 — consult_service。

MVP Phase 1 精简版：
- search_cases() — 语义检索（保留）
- start_consultation() — 端到端咨询触发编排（新增）

编排流程：
  档案标签读取 → RAG 检索 → Prompt 构建 → LLM 流式生成 → SSE 注册 → 返回 session_id
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from py_rag.retrieval import hybrid_search
from py_schemas.consult import (
    SemanticSearchInput,
    SemanticSearchResult,
    TagFilterDto,
)

from app.services.crisis_judgment.enums import CrisisLevel, BehaviorTypeCategory
from app.services.crisis_judgment.models import (
    CrisisJudgmentResult,
    CrisisJudgmentRequest,
    JudgmentLayerResult,
    PatientProfileSnapshot,
)
from app.services.emergency_plan_generation.models import (
    EmergencyPlanInput,
    GenerationChunk,
)
from app.services.emergency_plan_generation.prompt_builder import PromptBuilder
from app.services.emergency_plan_generation.streaming import stream_generate
from app.services.streaming.sse_service import SseStreamingService

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


async def search_cases(
    request: SemanticSearchInput,
    db: AsyncSession,
) -> SemanticSearchResult:
    """RAG 语义检索用例编排。（保留原有实现）"""
    if request is None:
        raise ValueError("request must not be None")
    if db is None:
        raise ValueError("db must not be None")

    query_text: str = request.query_text
    tag_filters = request.tag_filters
    top_k: int = request.top_k
    request_id: str | None = request.request_id

    _logger.info(
        "search_cases_started",
        extra={
            "request_id": request_id,
            "query_len": len(query_text),
            "top_k": top_k,
            "tag_filters": {
                "age_range": tag_filters.age_range,
                "behavior_type": tag_filters.behavior_type,
                "emotion_level": tag_filters.emotion_level,
            },
        },
    )

    result: SemanticSearchResult = await hybrid_search(
        query_text=query_text,
        tag_filters=tag_filters,
        top_k=top_k,
        request_id=request_id,
        db=db,
    )

    _logger.info(
        "search_cases_completed",
        extra={
            "request_id": request_id,
            "result_count": result.total_count,
            "elapsed_ms": result.elapsed_ms,
            "is_complete": result.is_complete,
            "degradation_level": result.degradation_level.value,
        },
    )

    return result


async def start_consultation(
    behavior_description: str,
    profile_id: str | None,
    behavior_type: list[str] | None,
    emotion_level: str | None,
    user_id: str,
    db: AsyncSession,
) -> str:
    """启动一次完整的应急咨询流程，返回 SSE session_id。

    编排步骤：
    1. 若提供 profile_id，读取档案并提取标签构建 TagFilterDto
    2. 调用 hybrid_search 执行 RAG 检索
    3. 构建 EmergencyPlanInput（MVP 跳过危机分级，使用默认 mild）
    4. PromptBuilder 组装 messages
    5. stream_generate 产出 AsyncGenerator
    6. 注册 generator 到 SseStreamingService
    7. 返回 session_id

    Args:
        behavior_description: 家属输入的行为描述。
        profile_id: 关联档案 ID（可选）。
        behavior_type: 前置行为类型（可选）。
        emotion_level: 情绪等级（可选）。
        user_id: 当前匿名用户 UUID 字符串。
        db: 数据库异步会话。

    Returns:
        str: SSE 会话标识符，格式 stream-{uuid4}。
    """
    request_id = str(uuid.uuid4())
    session_id = f"stream-{uuid.uuid4()}"

    # ------------------------------------------------------------------
    # 步骤 1：读取档案并构建标签过滤条件
    # ------------------------------------------------------------------
    tag_filters: TagFilterDto
    profile_summary: str = "（未关联档案）"

    if profile_id:
        from py_db.models.profiles import Profile
        from sqlalchemy import select

        result = await db.execute(
            select(Profile).where(Profile.profile_id == profile_id)
        )
        profile: Profile | None = result.scalars().first()
        if profile:
            # 构建档案摘要 Markdown
            profile_parts: list[str] = []
            if profile.diagnosis_type:
                profile_parts.append(f"- **诊断类型**：{profile.diagnosis_type}")
            if profile.primary_behavior:
                profile_parts.append(f"- **主要行为类型**：{profile.primary_behavior}")
            if profile.birth_date:
                from datetime import date
                age = (date.today() - profile.birth_date).days // 365
                profile_parts.append(f"- **年龄**：约 {age} 岁")
            profile_summary = "\n".join(profile_parts) if profile_parts else "（档案信息有限）"

            # 查询近期事件日志，注入个性化历史
            profile_summary = await _inject_event_history(
                db=db,
                profile_id=profile_id,
                behavior_type=behavior_type[0] if behavior_type else None,
                profile_summary=profile_summary,
            )

            # 构建 PatientProfileSnapshot（供危机分级使用）
            patient_profile = PatientProfileSnapshot(
                diagnosis_type=profile.diagnosis_type,
                historical_behavior_tags=_extract_behavior_tags(profile),
            )

            # 构建 tag_filters
            age_range_str = _map_age_to_range(profile.birth_date)
            primary_bt = profile.primary_behavior or (behavior_type[0] if behavior_type else "OTHER")
            tag_filters = TagFilterDto(
                age_range=age_range_str,
                behavior_type=primary_bt,
                emotion_level=emotion_level,
            )
        else:
            patient_profile = None
            tag_filters = _build_default_tag_filters(behavior_type, emotion_level)
    else:
        patient_profile = None
        tag_filters = _build_default_tag_filters(behavior_type, emotion_level)

    _logger.info(
        "consultation_started",
        extra={
            "request_id": request_id,
            "session_id": session_id,
            "user_id": user_id,
            "profile_id": profile_id,
            "has_profile": profile_id is not None,
        },
    )

    # ------------------------------------------------------------------
    # 步骤 2：RAG 语义检索
    # ------------------------------------------------------------------
    search_input = SemanticSearchInput(
        query_text=behavior_description,
        tag_filters=tag_filters,
        top_k=10,
        request_id=request_id,
    )
    search_result: SemanticSearchResult = await search_cases(search_input, db)

    # ------------------------------------------------------------------
    # 步骤 3：危机分级判定
    # ------------------------------------------------------------------
    crisis_result = await _run_crisis_judgment(
        behavior_description=behavior_description,
        behavior_type=behavior_type,
        patient_profile=patient_profile,
    )

    plan_input = EmergencyPlanInput(
        crisis_result=crisis_result,
        search_result=search_result,
        profile_summary=profile_summary,
        behavior_description=behavior_description,
        request_id=request_id,
    )

    # ------------------------------------------------------------------
    # 步骤 4：Prompt 构建
    # ------------------------------------------------------------------
    builder = PromptBuilder()
    messages, ctx = builder.build(plan_input)

    # ------------------------------------------------------------------
    # 步骤 5：流式生成器 + SSE 注册
    # ------------------------------------------------------------------
    generator = stream_generate(
        input_data=plan_input,
        messages=messages,
        prenumbered_slices=ctx.prenumbered_slices,
    )

    streaming_service = SseStreamingService()
    streaming_service.register_generator(session_id, generator)

    # 存储生成元数据供 SSE DoneEvent 使用
    streaming_service.store_generation_meta(
        session_id=session_id,
        prenumbered_slices={
            num: sid for num, sid in ctx.prenumbered_slices
        },
        crisis_level=crisis_result.final_level.value,
        block_deep_response=crisis_result.block_deep_response,
        behavior_description=behavior_description,
        request_id=request_id,
        search_result=search_result,
        plan_input=plan_input,
    )

    _logger.info(
        "consultation_generator_registered",
        extra={
            "request_id": request_id,
            "session_id": session_id,
        },
    )

    return session_id


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _build_default_tag_filters(
    behavior_type: list[str] | None,
    emotion_level: str | None,
) -> TagFilterDto:
    """构建默认标签过滤条件（无档案时）。"""
    primary_behavior = behavior_type[0] if behavior_type else "OTHER"
    return TagFilterDto(
        age_range="未知年龄段",
        behavior_type=primary_behavior,
        emotion_level=emotion_level,
    )


def _map_age_to_range(birth_date: Any) -> str:
    """根据出生日期映射为年龄段字符串（简化版）。"""
    if not birth_date:
        return "未知年龄段"
    from datetime import date

    age = (date.today() - birth_date).days // 365
    if age < 3:
        return "婴幼儿(0-2岁)"
    elif age < 6:
        return "学龄前(3-5岁)"
    elif age < 13:
        return "学龄儿童(6-12岁)"
    elif age < 18:
        return "青少年(13-17岁)"
    else:
        return "成年(18岁+)"


def _extract_behavior_tags(profile: Any) -> list[str]:
    """从 Profile ORM 对象提取历史行为标签列表。"""
    tags: list[str] = []
    if hasattr(profile, "primary_behavior") and profile.primary_behavior:
        tags.append(profile.primary_behavior)
    if hasattr(profile, "sensory_features") and profile.sensory_features:
        for sf in profile.sensory_features:
            if isinstance(sf, str):
                tags.append(sf)
    return tags


async def _inject_event_history(
    db: Any,
    profile_id: str,
    behavior_type: str | None,
    profile_summary: str,
) -> str:
    """查询患者近期事件日志，追加到档案摘要末尾。

    Args:
        db: 数据库会话。
        profile_id: 档案 UUID 字符串。
        behavior_type: 当前咨询的行为类型（可选，用于筛选同类事件）。
        profile_summary: 当前已构建的档案摘要 Markdown。

    Returns:
        追加了事件历史的档案摘要字符串。
    """
    import uuid as _uuid
    from py_db.repositories.event_repository import EventRepository

    try:
        pid = _uuid.UUID(profile_id)
    except (ValueError, TypeError):
        return profile_summary

    event_repo = EventRepository()
    events = await event_repo.list_recent_by_profile(
        session=db,
        profile_id=pid,
        limit=5,
        behavior_type=behavior_type,
        days=30,
    )

    if not events:
        return profile_summary

    lines: list[str] = ["\n## 近期相关事件"]
    for i, evt in enumerate(events, 1):
        date_str = evt.event_time.strftime("%Y-%m-%d") if evt.event_time else "未知日期"
        setting = evt.setting or "未知场景"
        manifest = (evt.manifestation or "")[:80]
        intervention = (evt.intervention_tried or "")[:80]
        result = (evt.intervention_result or "")[:60]
        prof_mark = "（老师评估）" if evt.is_professional else "（家属记录）"

        lines.append(
            f"{i}. [{date_str} {setting}] {manifest}。"
            f"尝试：{intervention}。结果：{result}。{prof_mark}"
        )

    return profile_summary + "\n" + "\n".join(lines)


async def _run_crisis_judgment(
    behavior_description: str,
    behavior_type: list[str] | None,
    patient_profile: PatientProfileSnapshot | None,
) -> CrisisJudgmentResult:
    """执行危机分级判定，失败时 fallback 到 mild。"""
    try:
        from app.services.crisis_judgment import judge_crisis

        behavior_type_selection: list[BehaviorTypeCategory] = []
        if behavior_type:
            for bt in behavior_type:
                try:
                    behavior_type_selection.append(BehaviorTypeCategory(bt))
                except ValueError:
                    _logger.warning("invalid_behavior_type", extra={"value": bt})

        if not behavior_type_selection:
            behavior_type_selection = [BehaviorTypeCategory.OTHER]

        crisis_request = CrisisJudgmentRequest(
            patient_profile=patient_profile,
            behavior_type_selection=behavior_type_selection,
            behavior_description=behavior_description,
        )
        return await judge_crisis(crisis_request)
    except Exception:
        _logger.exception("crisis_judgment_failed_fallback_to_mild")
        return CrisisJudgmentResult(
            final_level=CrisisLevel.MILD,
            block_deep_response=False,
            judgment_sources=[
                JudgmentLayerResult(
                    layer_name="Fallback",
                    level=CrisisLevel.MILD,
                )
            ],
            degradation_note="crisis_judgment_failed",
        )


__all__ = ["search_cases", "start_consultation"]
