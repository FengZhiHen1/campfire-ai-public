"""cases — 案例库管理模块。

提供三大业务能力和一个辅助子模块：

1. 案例录入管理 (CASE-01): 案例 CRUD、状态转换、PII 检测、EBP 一致性校验
2. 案例审核工作流 (CASE-03): AI 预审、专家终审、审计日志、审核队列
3. L1 叙事 + L2 卡片管理: 叙事 CRUD、卡片 CRUD、卡片审核与索引触发
4. case_extraction/: LLM 提取服务（L1 叙事 → L2 结构化卡片）

核心类：
  - CaseManagementService: 实现 CaseManagementContract 契约，案例 CRUD
  - ReviewWorkflowService: 实现 ReviewWorkflowContract 契约，审核工作流
  - NarrativeManagementService: 实现 NarrativeManagementContract 契约，叙事+卡片管理
  - ExtractionService: 实现 ExtractionServiceContract 契约，LLM 提取

外部接口：
  - create_case(request, user, session, repo) -> CaseResponse
  - update_case(case_id, update, user, session, repo) -> CaseResponse
  - submit_case(case_id, user, session, repo, pii_confirmed) -> CaseResponse
  - get_case(case_id, user, session, repo) -> CaseResponse
  - list_cases(filters..., user, session, repo) -> PaginatedResponse
  - submit_review(case_id, review_request, user, session, repos...) -> CaseReviewResponse
  - list_review_queue(status, page, page_size, session, repos...) -> PaginatedResponse
  - create_narrative(title, narrative, source_type, user, session) -> CaseNarrative
  - get_narrative(narrative_id, user, session) -> CaseNarrative
  - extract_cards_from_narrative(narrative_text, narrative_id, db) -> list[CaseCard]
  - run_ai_pre_review(case_data) -> AiReviewSummary
  - check_ebp_consistency(evidence_level, ebp_labels) -> str | None

Usage:
    from app.modules.cases import cases_router, reviews_router, narratives_router
    app.include_router(cases_router)
    app.include_router(reviews_router)
    app.include_router(narratives_router)
"""

from .routes import router as cases_router
from .review_routes import router as reviews_router
from .narrative_routes import router as narratives_router

__all__ = [
    # 路由
    "cases_router",
    "reviews_router",
    "narratives_router",
]
