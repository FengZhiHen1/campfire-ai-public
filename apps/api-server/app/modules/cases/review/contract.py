"""CASE-03 案例审核工作流 — 行为契约（ABC 模板方法）。

定义专家审核流程的契约骨架：
- submit_review: 专家终审 — 10 步审核流水线
- list_review_queue: 查看待审核队列

所有 @final 公共方法强制执行 前置校验 → 调用钩子 → 后置校验 的三明治结构。
实现者只能覆写 _do_ 前缀的钩子方法。

数据来源:
  - CaseRepository (py_db): MUST — 案例查询 + CAS 状态更新
  - ReviewRepository (py_db): MUST — 审核记录读写
  - ReviewAuditLogRepository (py_db): MUST — 审计日志写入
  - run_ai_pre_review (本模块): MUST — AI 预审规则引擎
边界:
  - 依赖: py_db, py_schemas, 本模块 ai_pre_review
  - 被依赖: review_routes.py（路由层委托）
  - 不负责: 索引入队的实际执行（仅触发异步任务）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, final

from py_db.repositories.case_repository import CaseRepository
from py_db.repositories.narrative_repository import NarrativeRepository
from py_db.repositories.review_repository import (
    ReviewAuditLogRepository,
    ReviewRepository,
)
from py_schemas.cases import (
    AiReviewSummary,
    CaseReviewResponse,
    CheckItem,
    PaginatedResponse,
    ReviewQueueItem,
    ReviewRequest,
)
from py_schemas.enums.case_enums import CaseStatus
from sqlalchemy.ext.asyncio import AsyncSession

from .ai_pre_review import case_data_from_orm, run_ai_pre_review

from ..exceptions import (
    CaseNotFoundError,
    CaseStatusError,
    PiiHardBlockError,
    RejectCommentTooShortError,
    SelfReviewForbiddenError,
)


class ReviewWorkflowContract(ABC):
    """案例审核服务契约。实现者只能覆写 _do_ 前缀的钩子方法。

    异常策略: 契约基类校验器抛出域异常（exceptions.py 中定义），
    这些异常携带诊断字段供上层处理。Service 实现可按需包装为 HTTPException。
    契约层（框架无关）与服务层（FastAPI 适配）的异常体系是有意分离的。
    """

    # ---------------------------------------------------------------------------
    # 常量
    # ---------------------------------------------------------------------------

    REJECT_COMMENT_MIN_LENGTH: int = 10
    """驳回意见最小字数。"""

    WORKING_DAYS_DEADLINE: int = 2
    """审核截止工作日数。"""

    # ---------------------------------------------------------------------------
    # @final 公共入口
    # ---------------------------------------------------------------------------

    @final
    async def submit_review(
        self,
        case_id: str,
        review_request: ReviewRequest,
        current_user: dict[str, Any],
        session: AsyncSession,
        case_repo: CaseRepository,
        review_repo: ReviewRepository,
        audit_repo: ReviewAuditLogRepository,
        narrative_repo: NarrativeRepository,
    ) -> CaseReviewResponse:
        """专家终审 — 提交审核裁决。

        执行完整的 10 步审核流水线：
        1. 参数校验（case_id 非空）
        2. 查询案例 → 存在性校验
        3. 状态校验 → 必须为 pending_review
        4. 审核人校验 → 不能是案例作者
        5. AI 预审（规则引擎）
        6. PII 硬门槛检查
        7. 驳回意见长度校验
        8. CAS 更新案例状态
        9. 写入审核记录 + 审计日志
        10. 审核通过则异步入队

        前置:
          - case_id 非空
          - 案例存在且 status=pending_review
          - 审核人 ≠ 作者
          - 若驳回，review_comment >= 10 字
        后置:
          - 案例状态已变更为 approved 或 rejected
          - 审核记录已写入 case_reviews 表
          - 审计日志已写入 review_audit_logs 表
        异常:
          - CaseNotFoundError: 案例不存在
          - CaseStatusError: 状态不是 pending_review
          - SelfReviewForbiddenError: 审核人是案例作者
          - PiiHardBlockError: PII 硬门槛未通过
          - RejectCommentTooShortError: 驳回意见长度不足
        Side Effects:
          - 写入 cases 表（状态变更）
          - 写入 case_reviews 表（审核记录）
          - 写入 review_audit_logs 表（审计日志）
          - 审核通过时触发 Redis 索引入队
        """
        # 步骤 1-4：前置校验
        self._validate_review_preconditions(case_id, review_request, current_user)
        case = await self._load_case_for_review(case_id, session, narrative_repo)
        reviewer_id = current_user.get("sub", "")
        self._validate_case_reviewable(case, reviewer_id)

        # 步骤 5-6：AI 预审 + PII 硬门槛
        ai_review = self._run_ai_pre_review_for_case(case)
        self._validate_pii_hard_gate(ai_review, case_id)

        # 步骤 7：驳回意见校验
        self._validate_review_decision(review_request)

        # 步骤 8-10：执行审核
        result = await self._do_submit_review(
            case_id, review_request, current_user, session,
            narrative_repo, review_repo, audit_repo, case, ai_review,
        )

        self._validate_review_result(result, case_id)
        return result

    @final
    async def list_review_queue(
        self,
        status_filter: str | None,
        page: int,
        page_size: int,
        session: AsyncSession,
        case_repo: CaseRepository,
        review_repo: ReviewRepository,
        narrative_repo: NarrativeRepository,
    ) -> PaginatedResponse[ReviewQueueItem]:
        """查看待审核队列。

        前置:
          - page >= 1, page_size 在 1-100 之间
        后置:
          - 返回分页的待审核案例列表，含超时状态
        """
        self._validate_queue_params(page, page_size)
        result = await self._do_list_review_queue(
            status_filter, page, page_size, session, case_repo, review_repo, narrative_repo,
        )
        if result is None:
            raise RuntimeError("ReviewWorkflowContract.list_review_queue 返回了 None")
        return result

    # ---------------------------------------------------------------------------
    # @abstractmethod 钩子（实现者必填）
    # ---------------------------------------------------------------------------

    @abstractmethod
    async def _do_submit_review(
        self,
        case_id: str,
        review_request: ReviewRequest,
        current_user: dict[str, Any],
        session: AsyncSession,
        narrative_repo: NarrativeRepository,
        review_repo: ReviewRepository,
        audit_repo: ReviewAuditLogRepository,
        narrative: Any,
        ai_review: AiReviewSummary,
    ) -> CaseReviewResponse:
        """执行审核裁决的核心逻辑。

        实现者在此: CAS 状态更新 → 审核记录写入 → 审计日志写入 →
                    异步入队 → 事务提交。
        """
        ...

    @abstractmethod
    async def _do_list_review_queue(
        self,
        status_filter: str | None,
        page: int,
        page_size: int,
        session: AsyncSession,
        case_repo: CaseRepository,
        review_repo: ReviewRepository,
        narrative_repo: NarrativeRepository,
    ) -> PaginatedResponse[ReviewQueueItem]:
        """查看待审核队列的核心逻辑。

        不需要关心: 分页参数校验（上游已处理）。
        实现者在此: 查询 pending_review 案例 → 计算超时状态 → 分页组装。
        """
        ...

    # ---------------------------------------------------------------------------
    # 校验器 + 辅助方法（模板提供基线实现）
    # ---------------------------------------------------------------------------

    def _validate_review_preconditions(
        self,
        case_id: str,
        review_request: ReviewRequest,
        current_user: dict[str, Any],
    ) -> None:
        """基线审核前置校验：参数非空。"""
        if not case_id:
            raise ValueError("case_id 不能为空")
        if review_request is None:
            raise ValueError("review_request 不能为空")

    async def _load_case_for_review(
        self,
        case_id: str,
        session: AsyncSession,
        narrative_repo: NarrativeRepository,
    ) -> Any:
        """加载叙事并校验存在性。"""
        narrative = await narrative_repo.find_by_narrative_id(session, case_id)
        if narrative is None:
            raise CaseNotFoundError(case_id)
        return narrative

    def _validate_case_reviewable(self, case: Any, reviewer_id: str) -> None:
        """校验叙事可审核性：状态 + 非自审。"""
        # 状态校验
        if case.status != CaseStatus.PENDING_REVIEW:
            current = case.status.value if hasattr(case.status, "value") else str(case.status)
            raise CaseStatusError(
                str(case.narrative_id), current, "pending_review"
            )

        # 禁止自审（author_id 为 UUID，reviewer_id 为字符串，统一转换为字符串比较）
        if str(case.author_id) == reviewer_id:
            raise SelfReviewForbiddenError(
                str(case.narrative_id), reviewer_id, str(case.author_id)
            )

    def _run_ai_pre_review_for_case(self, case: Any) -> AiReviewSummary:
        """执行 AI 预审（模板提供基线实现，子类可覆写以注入 mock）。

        默认调用本模块的 run_ai_pre_review 规则引擎。
        MVP 阶段若案例未携带 ai_review，返回全 pass 占位结果。
        """
        if hasattr(case, "ai_review") and case.ai_review:
            raw = case.ai_review
            if isinstance(raw, dict):
                return AiReviewSummary(
                    overall=raw.get("overall", "pass"),
                    format_check=CheckItem(**raw.get("format_check", {"status": "pass", "is_hard_gate": True})),
                    required_fields_check=CheckItem(**raw.get("required_fields_check", {"status": "pass", "is_hard_gate": False})),
                    ebp_consistency_check=CheckItem(**raw.get("ebp_consistency_check", {"status": "pass", "is_hard_gate": False})),
                    pii_check=CheckItem(**raw.get("pii_check", {"status": "pass", "is_hard_gate": True})),
                )
            elif isinstance(raw, AiReviewSummary):
                return raw

        # 执行完整的规则引擎预审
        case_data = case_data_from_orm(case)
        return run_ai_pre_review(case_data)

    def _validate_pii_hard_gate(
        self, ai_review: AiReviewSummary, case_id: str
    ) -> None:
        """PII 硬门槛校验。"""
        if (
            ai_review.pii_check.is_hard_gate
            and ai_review.pii_check.status == "fail"
        ):
            raise PiiHardBlockError(case_id, ai_review.pii_check.details or [])

    def _validate_review_decision(self, review_request: ReviewRequest) -> None:
        """驳回意见长度校验。"""
        if review_request.decision == "rejected":
            comment = review_request.review_comment or ""
            if len(comment.strip()) < self.REJECT_COMMENT_MIN_LENGTH:
                raise RejectCommentTooShortError(
                    len(comment), self.REJECT_COMMENT_MIN_LENGTH
                )

    def _validate_review_result(
        self, result: CaseReviewResponse, case_id: str
    ) -> None:
        """基线审核后置校验。"""
        if result is None:
            raise RuntimeError(
                f"ReviewWorkflowContract.submit_review({case_id}) 返回了 None"
            )

    def _validate_queue_params(self, page: int, page_size: int) -> None:
        """基线队列查询参数校验。"""
        if page < 1:
            raise ValueError("page 必须 >= 1")
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size 必须在 1-100 之间")
