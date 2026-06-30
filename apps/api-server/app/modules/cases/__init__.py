"""cases — 案例库管理模块。

当前提供两大业务能力：

1. 案例审核工作流 (CASE-03): AI 预审、专家终审、审计日志、审核队列
2. L1 叙事 + L2 卡片管理: 叙事 CRUD、卡片 CRUD、卡片审核与索引触发
3. case_extraction/: LLM 提取服务（L1 叙事 → L2 结构化卡片）

核心类：
  - ReviewWorkflowService: 实现 ReviewWorkflowContract 契约，审核工作流
  - NarrativeManagementService: 实现 NarrativeManagementContract 契约，叙事+卡片管理
  - ExtractionService: 实现 ExtractionServiceContract 契约，LLM 提取

外部接口：
  - submit_review(case_id, review_request, user, session, repos...) -> CaseReviewResponse
  - list_review_queue(status, page, page_size, session, repos...) -> PaginatedResponse
  - create_narrative(title, narrative, source_type, user, session) -> CaseNarrative
  - get_narrative(narrative_id, user, session) -> CaseNarrative
  - extract_cards_from_narrative(narrative_text, narrative_id, db) -> list[CaseCard]
  - run_ai_pre_review(case_data) -> AiReviewSummary
  - check_ebp_consistency(evidence_level, ebp_labels) -> str | None

Usage:
    from app.modules.cases import reviews_router, narratives_router, card_router
    app.include_router(reviews_router)
    app.include_router(narratives_router)
    app.include_router(card_router)
"""

from .narrative.card_routes import router as card_router
from .narrative.routes import router as narratives_router
from .review.routes import router as reviews_router

__all__ = [
    # 路由
    "card_router",
    "reviews_router",
    "narratives_router",
]
