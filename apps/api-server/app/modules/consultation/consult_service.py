"""CSLT-02/08 应急咨询编排 — consult_service。

模块: app.modules.consultation.consult_service
职责: 应急咨询编排实现。ConsultationOrchestratorImpl 继承 BaseConsultationOrchestrator ABC，
      @final 公共入口 start_consultation/search_cases 强制执行前置→执行→后置三步流程。
      模块级便捷函数委托给单例实例，保持 routes.py 的导入兼容。
数据来源:
  - py_rag.hybrid_search: MUST — RAG 语义检索引擎
  - app.modules.crisis: MUST — 危机分级判定
  - app.core.streaming.SseStreamingService: MUST — SSE 流式推送
边界:
  - 依赖: py_rag, py_logger, py_schemas, app.modules.crisis, app.core.streaming
  - 被依赖: routes.py
禁止行为:
  - 禁止在 _do_ 钩子中调用 super()
  - 禁止绕过 @final 方法直接调用 _do_ 钩子
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from py_logger import logger
from py_rag.retrieval import hybrid_search
from py_schemas.consult import (
    SemanticSearchInput,
    SemanticSearchResult,
    TagFilterDto,
)

from app.modules.crisis.enums import CrisisLevel, BehaviorTypeCategory
from app.modules.crisis.models import (
    CrisisJudgmentResult,
    CrisisJudgmentRequest,
    JudgmentLayerResult,
    PatientProfileSnapshot,
)
from app.modules.consultation.plan_generation.models import (
    EmergencyPlanInput,
)
from app.modules.consultation.plan_generation.prompt_builder import PromptBuilder
from app.modules.consultation.plan_generation.streaming import stream_generate
from app.core.streaming.sse_service import SseStreamingService

from .consultation_contract import BaseConsultationOrchestrator
from .types import BehaviorDescription, ProfileSummary, RequestId, SessionId


# ============================================================================
# ConsultationOrchestratorImpl — 实现 BaseConsultationOrchestrator ABC
# ============================================================================


class ConsultationOrchestratorImpl(BaseConsultationOrchestrator):
    """应急咨询编排实现。继承 BaseConsultationOrchestrator ABC，仅覆写 _do_ 钩子。"""

    # ========================================================================
    # _do_ 钩子
    # ========================================================================

    def _do_load_profile(
        self,
        profile_id: str | None,
        db: AsyncSession,
    ) -> ProfileSummary:
        if not profile_id:
            return ProfileSummary("（未关联档案）")
        # TODO: 档案关联逻辑待调试通过后恢复
        return ProfileSummary("（未关联档案）")

    async def _do_search_cases(
        self,
        query_text: str,
        behavior_type: list[str] | None,
        emotion_level: str | None,
        request_id: RequestId,
        db: AsyncSession,
    ) -> Any:
        tag_filters = _build_default_tag_filters(behavior_type, emotion_level)

        search_input = SemanticSearchInput(
            query_text=query_text,
            tag_filters=tag_filters,
            top_k=10,
            request_id=str(request_id),
        )

        logger.info(
            service="api-server",
            message="search_cases_started",
            op_type=None,
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
            message="search_cases_done",
            op_type=None,
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
    ) -> Any:
        try:
            from app.modules.crisis import judge_crisis

            behavior_type_selection: list[BehaviorTypeCategory] = []
            if behavior_type:
                for bt in behavior_type:
                    try:
                        behavior_type_selection.append(BehaviorTypeCategory(bt))
                    except ValueError:
                        logger.warning("invalid_behavior_type", extra={"value": bt})

            if not behavior_type_selection:
                behavior_type_selection = [BehaviorTypeCategory.OTHER]

            crisis_request = CrisisJudgmentRequest(
                patient_profile=None,
                behavior_type_selection=behavior_type_selection,
                behavior_description=behavior_description,
            )
            return await judge_crisis(crisis_request)
        except Exception:
            logger.exception("crisis_judgment_failed_fallback_to_mild")
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

    def _do_generate_stream(self, plan_input: Any) -> Any:
        builder = PromptBuilder()
        messages, ctx = builder.build(plan_input)
        return stream_generate(
            input_data=plan_input,
            messages=messages,
            prenumbered_slices=ctx.prenumbered_slices,
        )

    def _do_register_sse(
        self,
        session_id: SessionId,
        generator: Any,
        plan_input: Any,
        search_result: Any,
        crisis_result: Any,
        behavior_description: str,
        request_id: RequestId,
    ) -> None:
        builder = PromptBuilder()
        _messages, ctx = builder.build(plan_input)

        streaming_service = SseStreamingService()
        streaming_service.register_generator(str(session_id), generator)
        streaming_service.store_generation_meta(
            session_id=str(session_id),
            prenumbered_slices={num: sid for num, sid in ctx.prenumbered_slices},
            crisis_level=crisis_result.final_level.value,
            block_deep_response=crisis_result.block_deep_response,
            behavior_description=behavior_description,
            request_id=str(request_id),
            search_result=search_result,
            plan_input=plan_input,
        )

    async def _do_execute_search(self, request: Any, db: AsyncSession) -> Any:
        logger.info(
            service="api-server",
            message="search_cases_started",
            op_type=None,
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
            message="search_cases_done",
            op_type=None,
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
    result = _orchestrator.start_consultation(
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


# ============================================================================
# 内部辅助
# ============================================================================


def _build_default_tag_filters(
    behavior_type: list[str] | None,
    emotion_level: str | None,
) -> TagFilterDto:
    primary_behavior = behavior_type[0] if behavior_type else "OTHER"
    return TagFilterDto(
        age_range="未知年龄段",
        behavior_type=primary_behavior,
        emotion_level=emotion_level,
    )


__all__ = [
    "ConsultationOrchestratorImpl",
    "search_cases",
    "start_consultation",
]
