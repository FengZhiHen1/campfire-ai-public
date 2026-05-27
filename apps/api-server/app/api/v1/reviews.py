"""CASE-03 案例审核工作流 — FastAPI 路由注册。

两个端点：
- POST /api/v1/cases/{case_id}/review — 提交审核裁决（approve/reject）
- GET /api/v1/cases/review-queue — 查看待审核队列

所有端点通过 Depends 链进行角色准入校验（需 EXPERT 及以上角色）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth_dependencies import (
    get_case_repository,
    get_db_session,
    get_review_audit_log_repository,
    get_review_repository,
)
from app.services.review_service import list_review_queue, submit_review
from py_auth.dependencies import get_current_user
from py_auth.rbac import require_role
from py_db.repositories.case_repository import CaseRepository
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

router = APIRouter(prefix="/api/v1/cases", tags=["reviews"])


@router.post(
    "/{case_id}/review",
    response_model=CaseReviewResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "审核裁决提交成功"},
        403: {"description": "角色权限不足 或 审核人等于提交者"},
        404: {"description": "案例不存在"},
        409: {"description": "状态不是 pending_review 或 PII 硬门槛拦截"},
        422: {
            "description": "驳回意见不满足长度要求",
            "model": ValidationErrorResponse,
        },
    },
    summary="提交审核裁决",
    description=(
        "对处于 pending_review 状态的案例执行专家终审。\n\n"
        "审核流程：AI 预审（规则引擎 4 项检查）→ 专家裁决 → 状态更新 → 审计日志。\n"
        "审核通过后异步触发 CASE-04 索引入队。\n"
        "PII 硬门槛不可被专家覆盖。"
    ),
)
async def submit_review_endpoint(
    case_id: str,
    review_request: ReviewRequest = Depends(),
    current_user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_role(min_level=UserRole.EXPERT)),
    session: AsyncSession = Depends(get_db_session),
    case_repo: CaseRepository = Depends(get_case_repository),
    review_repo: ReviewRepository = Depends(get_review_repository),
    audit_repo: ReviewAuditLogRepository = Depends(get_review_audit_log_repository),
) -> CaseReviewResponse:
    """提交审核裁决端点。

    依赖注入链：
    1. ReviewRequest — Pydantic 校验
    2. get_current_user — JWT 解析
    3. require_role — 角色校验（专家及以上）
    4. get_db_session — 数据库会话
    5. get_case_repository — CaseRepository 实例
    6. get_review_repository — ReviewRepository 实例
    7. get_review_audit_log_repository — ReviewAuditLogRepository 实例
    """
    return await submit_review(
        case_id=case_id,
        review_request=review_request,
        current_user=current_user,
        session=session,
        case_repo=case_repo,
        review_repo=review_repo,
        audit_repo=audit_repo,
    )


@router.get(
    "/review-queue",
    response_model=PaginatedResponse[ReviewQueueItem],
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "返回待审核队列（分页）"},
        403: {"description": "角色权限不足"},
    },
    summary="查看待审核队列",
    description=(
        "查看所有待审核（status=pending_review）案例的队列。\n"
        "返回案例摘要信息和审核队列特有字段（AI 预审结论、截止时间、超时状态）。"
    ),
)
async def list_review_queue_endpoint(
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="状态筛选（默认 pending_review）",
    ),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=15, ge=1, le=100, description="每页条数"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    _: None = Depends(require_role(min_level=UserRole.EXPERT)),
    session: AsyncSession = Depends(get_db_session),
    case_repo: CaseRepository = Depends(get_case_repository),
    review_repo: ReviewRepository = Depends(get_review_repository),
) -> PaginatedResponse[ReviewQueueItem]:
    """查看待审核队列端点。"""
    return await list_review_queue(
        status_filter=status_filter,
        page=page,
        page_size=page_size,
        session=session,
        case_repo=case_repo,
        review_repo=review_repo,
    )


__all__ = ["router"]
