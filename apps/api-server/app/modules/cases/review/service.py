"""CASE-03 案例审核工作流 — 核心业务编排。

提供两大核心功能：
1. submit_review: 专家终审——提交审核裁决（approve/reject）
2. list_review_queue: 查看待审核队列（所有 status=pending_review 的案例）

审核流程：
1. AI 预审（规则引擎，<5ms）→ 4 项检查
2. 专家终审裁决 → 写入审核记录 + 审计日志
3. 审核通过 → 异步触发 CASE-04 索引入队

本模块提供 ReviewWorkflowService 类（继承 ReviewWorkflowContract 契约 ABC）。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from py_config import get_settings
from py_logger import logger
from py_db.models.review_models import CaseReview
from py_db.repositories.case_repository import CaseRepository
from py_db.repositories.narrative_repository import NarrativeRepository
from py_db.repositories.review_repository import (
    ReviewAuditLogRepository,
    ReviewRepository,
)
from py_schemas.cases import (
    AiReviewSummary,
    CaseReviewResponse,
    PaginatedResponse,
    ReviewQueueItem,
    ReviewRequest,
)
from py_schemas.enums.case_enums import CaseStatus
from sqlalchemy.ext.asyncio import AsyncSession

from .contract import ReviewWorkflowContract

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_REJECT_COMMENT_MIN_LENGTH: int = 10
"""驳回意见最小字数。"""

_REVIEW_QUEUE_PAGE_SIZE_DEFAULT: int = 15
"""审核队列默认每页条数。"""

_WORKING_DAYS_DEADLINE: int = 2
"""审核截止工作日数（AI 预审完成 + 2 工作日）。"""

_OVERDUE_WARNING_DAYS: int = 2
"""超时警告阈值（deadline 超过 2 天 → overdue）。"""

# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _calculate_deadline(from_time: datetime) -> datetime:
    """计算审核截止时间（AI 预审完成 + 2 工作日，简化版仅跳过周末）。

    MVP 简化实现：仅跳过周六日，不考虑中国法定假日。
    若需要精确的中国法定假日计算，可替换为 chinese_calendar 库。

    Args:
        from_time: AI 预审完成时间。

    Returns:
        截止时间（datetime，timezone-aware）。
    """
    current: datetime = from_time
    remaining_days: int = _WORKING_DAYS_DEADLINE

    while remaining_days > 0:
        current += timedelta(days=1)
        # 跳过周六(5)和周日(6)
        if current.weekday() < 5:
            remaining_days -= 1

    return current


def _get_timeout_status(deadline: datetime) -> str:
    """根据截止时间计算超时状态。

    Args:
        deadline: 审核截止时间。

    Returns:
        "overdue"（已超期）/ "warning"（接近超期）/ "normal"。
    """
    now: datetime = datetime.now(timezone.utc)

    if now > deadline + timedelta(days=_OVERDUE_WARNING_DAYS):
        return "overdue"
    if now > deadline:
        return "warning"
    return "normal"


def _compute_pii_blocked(ai_review: AiReviewSummary) -> bool:
    """判断 AI 预审 PII 硬门槛是否阻断。

    Args:
        ai_review: AI 预审结果。

    Returns:
        True 表示 PII 硬门槛不通过（不可被专家覆盖）。
    """
    return (
        ai_review.pii_check.is_hard_gate
        and ai_review.pii_check.status == "fail"
    )


async def _enqueue_index_async(case_id: str) -> None:
    """异步触发 CASE-04 索引入队（MVP 简化版：直接投递 Redis 队列）。

    使用 Redis LPUSH 将 case_id 投递到 campfire:case_index 队列，
    由 Worker 消费后执行切片 + 向量化 + 入库。

    Args:
        case_id: 案例唯一标识。
    """
    try:
        settings = get_settings()
        redis_client = aioredis.from_url(str(settings.REDIS_URL), decode_responses=True)
        payload = json.dumps({"task": "index_case", "case_id": case_id})
        await redis_client.lpush("index:queue:case_chunks", payload)  # type: ignore[misc]  # redis.asyncio 类型桩返回 int|Awaitable[int] 的已知误报
        await redis_client.close()
        logger.info(
            "index_enqueue_success",
            extra={"case_id": case_id, "queue": "index:queue:case_chunks"},
        )
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as exc:
        logger.error(
            "index_enqueue_failed",
            extra={"case_id": case_id, "error": str(exc)},
        )


# ---------------------------------------------------------------------------
# ReviewWorkflowService — 契约实现
# ---------------------------------------------------------------------------


class ReviewWorkflowService(ReviewWorkflowContract):
    """案例审核服务 — ReviewWorkflowContract 契约实现。

    继承契约 ABC 中的 @final 公共入口（submit_review / list_review_queue），
    仅实现 _do_ 钩子方法。
    """

    # ---------------------------------------------------------------------------
    # _do_ 钩子实现
    # ---------------------------------------------------------------------------

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
        reviewer_id: str = current_user.get("sub", "")

        # ---- CAS 更新叙事状态 ----
        new_status: CaseStatus = (
            CaseStatus.APPROVED
            if review_request.decision == "approved"
            else CaseStatus.REJECTED
        )

        try:
            updated_narrative = await narrative_repo.update_status(
                session,
                case_id,
                new_status,
                expected_status=CaseStatus.PENDING_REVIEW,
                review_comment=review_request.review_comment,
            )
        except ValueError as exc:
            raise RuntimeError(f"CAS 更新叙事状态失败：{exc}") from exc

        # ---- 写入审核记录 ----
        latest_review: CaseReview | None = await review_repo.get_latest_review(
            session, case_id
        )
        next_round: int = (latest_review.review_round + 1) if latest_review else 1

        is_override: bool = review_request.override_reason is not None and len(review_request.override_reason.strip()) > 0

        review_record = CaseReview(
            case_id=case_id,
            review_round=next_round,
            ai_review_report=ai_review.model_dump(),
            decision=review_request.decision,
            review_comment=review_request.review_comment,
            reviewer_id=reviewer_id,
            reviewed_at=datetime.now(timezone.utc),
            is_override=is_override,
            override_reason=review_request.override_reason if is_override else None,
        )
        await review_repo.create_review_record(session, review_record)

        # ---- 写入审计日志 ----
        audit_action: str = (
            "approved" if review_request.decision == "approved" else "rejected"
        )
        await audit_repo.insert_audit_log(
            session=session,
            case_id=case_id,
            action=audit_action,
            operator_id=reviewer_id,
            operator_role="expert",
            details={
                "decision": review_request.decision,
                "review_round": next_round,
                "ai_review_overall": ai_review.overall,
                "is_override": is_override,
            },
        )

        if is_override:
            await audit_repo.insert_audit_log(
                session=session,
                case_id=case_id,
                action="expert_override",
                operator_id=reviewer_id,
                operator_role="expert",
                details={
                    "override_reason": review_request.override_reason,
                    "review_round": next_round,
                },
            )

        # ---- 提交事务 ----
        try:
            await session.commit()
            await session.refresh(updated_narrative)
        except Exception as exc:
            await session.rollback()
            logger.error(
                "review_commit_failed",
                extra={"case_id": case_id, "error": str(exc)},
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="服务暂时不可用，请稍后重试",
            ) from exc

        # ---- 审核通过时异步触发索引入队 ----
        if review_request.decision == "approved":
            asyncio.create_task(_enqueue_index_async(case_id))

        # ---- 日志 ----
        logger.info(
            "review_completed",
            extra={
                "case_id": case_id,
                "decision": review_request.decision,
                "reviewer_id": reviewer_id,
                "review_round": next_round,
                "ai_review_overall": ai_review.overall,
            },
        )

        return CaseReviewResponse(
            case_id=case_id,
            new_status=review_request.decision,  # type: ignore[arg-type]
            ai_review_summary=ai_review,
            expert_decision=f"专家{'通过' if review_request.decision == 'approved' else '驳回'}审核",
            review_comment=review_request.review_comment,
            reviewer_id=reviewer_id,
            reviewed_at=review_record.reviewed_at,
        )

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

        契约前置已处理: 分页参数校验。
        实现者在此: 查询 pending_review 叙事 → 计算超时状态 → 分页组装。
        """
        # 查询所有 pending_review 状态的叙事（不限制 author_id）
        narratives, total_count = await narrative_repo.find_by_filters(
            session,
            status=CaseStatus.PENDING_REVIEW,
            author_id=None,
            page=page,
            page_size=page_size,
        )

        now: datetime = datetime.now(timezone.utc)
        items: list[ReviewQueueItem] = []

        for narrative in narratives:
            # MVP 跳过 AI 预审
            ai_review_overall = "pass"

            # 提交时间取 created_at
            submitted_at: datetime = narrative.created_at

            # 计算截止时间和超时状态
            deadline: datetime = _calculate_deadline(submitted_at)
            timeout_status: str = _get_timeout_status(deadline)

            items.append(ReviewQueueItem(
                narrative_id=str(narrative.narrative_id),
                title=narrative.title,
                author_name=narrative.author_id,
                behavior_type="",  # L1 叙事层不包含行为类型，待提取后由 L2 卡片填充
                submitted_at=submitted_at,
                ai_review_overall=ai_review_overall,
                deadline=deadline,
                timeout_status=timeout_status,  # type: ignore[arg-type]
            ))

        total_pages: int = (total_count + page_size - 1) // page_size if total_count > 0 else 0

        return PaginatedResponse[ReviewQueueItem](  # type:ignore[valid-type]
            items=items,
            total=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


__all__ = [
    "ReviewWorkflowService",
]
