"""consultation — 智能应急咨询：咨询编排、应急方案生成、流式推送、置信度校验、历史归档。

提供 5 大能力：
1. 咨询编排（CSLT-08）：端到端应急咨询流程编排——档案加载→RAG检索→危机判定→方案生成→SSE推送
2. 语义检索（CSLT-02）：基于行为描述的 RAG 语义检索 + 档案标签精确过滤
3. 应急方案生成（CSLT-03）：LLM 流式生成四段式应急方案 + 阻断场景安全提示
4. 置信度后校验（CSLT-05）：关键词安检 + LLM自评估 + 规则校验 两阶段流水线
5. 咨询历史管理（CSLT-06）：归档写入（幂等）+ 分页列表 + 详情查询

核心类：
  - ConsultationOrchestratorImpl: 实现 BaseConsultationOrchestrator 契约，咨询编排
  - PlanGeneratorImpl: 实现 BasePlanGenerator 契约，应急方案生成
  - ConfidenceValidatorImpl: 实现 BaseConfidenceValidator 契约，置信度后校验
  - HistoryManagerImpl: 实现 BaseHistoryManager 契约，历史管理

外部接口：
  - start_consultation(behavior_description, profile_id, behavior_type, emotion_level, user_id, db) -> SessionId
  - search_cases(request, db) -> SemanticSearchResult
  - generate_emergency_plan(input_data, config) -> GenerationResult
  - validate_confidence(input, background_tasks) -> ConfidenceValidationOutput
  - archive_consultation(data, current_user, db) -> ConsultationHistoryDetail
  - list_history(page, page_size, current_user, db) -> PaginatedResponse
  - get_detail(consultation_id, current_user, db) -> ConsultationHistoryDetail

Usage:
    from app.modules.consultation import start_consultation, search_cases
    from app.modules.consultation.plan_generation import generate_emergency_plan
    from app.modules.consultation.consult import validate_confidence
    from app.modules.consultation.history import archive_consultation, list_history, get_detail
"""

from __future__ import annotations

# 实现类
from .consult_service import (
    ConsultationOrchestratorImpl,
    search_cases,
    start_consultation,
)

# 契约（供聚合脚本自动发现）
from .consultation_contract import BaseConsultationOrchestrator
from .exceptions import (
    ConsultationArchiveError,
    ConsultationError,
    ConsultationGenerationError,
    ConsultationInputError,
    ConsultationNotFoundError,
    ConsultationSearchError,
    ConsultationStreamError,
)
from .history_routes import router as consultations_router
from .routes import router as consult_router
from .stream_routes import router as stream_router
from .types import (
    BehaviorDescription,
    ConfidenceScore,
    ElapsedMs,
    PlanText,
    ProfileSummary,
    RequestId,
    SessionId,
)

__all__ = [
    # 契约
    "BaseConsultationOrchestrator",
    # 语义类型
    "SessionId",
    "RequestId",
    "BehaviorDescription",
    "PlanText",
    "ProfileSummary",
    "ConfidenceScore",
    "ElapsedMs",
    # 异常
    "ConsultationError",
    "ConsultationInputError",
    "ConsultationSearchError",
    "ConsultationGenerationError",
    "ConsultationArchiveError",
    "ConsultationNotFoundError",
    "ConsultationStreamError",
    # 实现接口
    "ConsultationOrchestratorImpl",
    "search_cases",
    "start_consultation",
    "consult_router",
    "stream_router",
    "consultations_router",
]
