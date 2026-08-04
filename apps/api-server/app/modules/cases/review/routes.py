"""CASE-03 案例审核工作流 — 路由。

案例审核能力域：expert 审核 / admin 强制下架（认证与访问 §六）。
审核通过后自动投递 Redis 队列触发 Worker 索引。
路由层仅做依赖注入和委托——所有业务逻辑在 ReviewWorkflowService 中。

两个端点：
- POST /api/v1/cases/{case_id}/review — 提交审核裁决（approve/reject）
- GET /api/v1/cases/review-queue — 查看待审核队列
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from py_db.repositories.narrative_repository import NarrativeRepository
from py_db.repositories.review_repository import (
    ReviewAuditLogRepository,
    ReviewRepository,
)
from py_schemas.auth import UserRole
from py_schemas.cases import (
    CaseReviewResponse,
    PaginatedResponse,
    ReviewQueueItem,
    ReviewRequest,
)
from py_schemas.security.validation_schemas import ValidationErrorResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.auth_dependencies import (
    CurrentUser,
    get_db_session,
    get_narrative_repository,
    get_review_audit_log_repository,
    get_review_repository,
    require_roles,
)

from ..exceptions import SelfReviewForbiddenError
from .service import ReviewWorkflowService

router = APIRouter(prefix="/api/v1/cases", tags=["reviews"])

# 案例审核能力域角色集合：expert 审核 / admin 强制下架（认证与访问 §六）
_CASE_REVIEW_ROLES = (UserRole.EXPERT, UserRole.ADMIN)

_review_service = ReviewWorkflowService()


@router.post(
    "/{case_id}/review",
    response_model=CaseReviewResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "审核裁决提交成功"},
        404: {"description": "案例不存在"},
        409: {"description": "状态不是 pending_review"},
        422: {
            "description": "驳回意见不满足长度要求",
            "model": ValidationErrorResponse,
        },
    },
    summary="提交审核裁决",
    description=(
        "对处于 pending_review 状态的案例执行审核（expert/admin）。\n\n审核通过后自动触发 Worker 索引入队。"
    ),
)
async def submit_review_endpoint(
    case_id: str,
    review_request: ReviewRequest,
    current_user: CurrentUser = Depends(require_roles(*_CASE_REVIEW_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    review_repo: ReviewRepository = Depends(get_review_repository),
    audit_repo: ReviewAuditLogRepository = Depends(get_review_audit_log_repository),
    narrative_repo: NarrativeRepository = Depends(get_narrative_repository),
) -> CaseReviewResponse:
    """提交审核裁决端点。"""
    try:
        return await _review_service.submit_review(
            case_id=case_id,
            review_request=review_request,
            current_user=current_user.to_legacy_dict(),
            session=session,
            review_repo=review_repo,
            audit_repo=audit_repo,
            narrative_repo=narrative_repo,
        )
    except SelfReviewForbiddenError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "SELF_REVIEW_FORBIDDEN", "message": str(exc)},
        ) from exc


@router.get(
    "/review-queue",
    response_model=PaginatedResponse[ReviewQueueItem],
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "返回待审核队列（分页）"},
    },
    summary="查看待审核队列",
    description="查看所有待审核（status=pending_review）案例的队列。",
)
async def list_review_queue_endpoint(
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="状态筛选（默认 pending_review）",
    ),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=15, ge=1, le=100, description="每页条数"),
    _current_user: CurrentUser = Depends(require_roles(*_CASE_REVIEW_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    review_repo: ReviewRepository = Depends(get_review_repository),
    narrative_repo: NarrativeRepository = Depends(get_narrative_repository),
) -> PaginatedResponse[ReviewQueueItem]:
    """查看待审核队列端点。"""
    return await _review_service.list_review_queue(
        status_filter=status_filter,
        page=page,
        page_size=page_size,
        session=session,
        review_repo=review_repo,
        narrative_repo=narrative_repo,
    )


__all__ = ["router"]
