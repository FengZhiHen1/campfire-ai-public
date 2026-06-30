"""PROF-05 专家关联管理 — API 路由。

端点（挂载于 /api/v1/profiles 前缀下）:
- GET    /{profile_id}/experts             — 获取关联专家列表
- DELETE /{profile_id}/experts/{link_id}   — 解除专家关联
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from py_db.repositories.profile_repository import ProfileRepository
from py_db.repositories.teacher_link_repository import TeacherLinkRepository
from py_db.repositories.user_repository import UserRepository
from py_schemas.profiles import ExpertInfo
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.anonymous_user import get_anonymous_user
from app.core.dependencies.auth_dependencies import (
    get_db_session,
    get_profile_repository,
    get_teacher_link_repository,
    get_user_repository,
)
from app.modules.profiles._exception_mapping import map_domain_error
from app.modules.profiles._user_utils import extract_user_id
from app.modules.profiles.exceptions import ProfileDomainError
from app.modules.profiles.expert_service import ExpertServiceImpl

router = APIRouter(prefix="/api/v1/profiles", tags=["experts"])


def _get_expert_service(
    link_repo: TeacherLinkRepository = Depends(get_teacher_link_repository),
    profile_repo: ProfileRepository = Depends(get_profile_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> ExpertServiceImpl:
    """依赖注入：构造 ExpertServiceImpl 实例。"""
    return ExpertServiceImpl(
        link_repository=link_repo,
        profile_repository=profile_repo,
        user_repository=user_repo,
    )


# ===========================================================================
# GET /{profile_id}/experts — 关联专家列表
# ===========================================================================


@router.get(
    "/{profile_id}/experts",
    status_code=status.HTTP_200_OK,
    summary="获取关联专家列表",
    response_model=list[ExpertInfo],
    responses={
        200: {"description": "返回关联专家列表"},
        404: {"description": "档案不存在"},
    },
)
async def list_experts_endpoint(
    profile_id: UUID,
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
    expert_service: ExpertServiceImpl = Depends(_get_expert_service),
) -> list[ExpertInfo]:
    caregiver_id = extract_user_id(anonymous_user)
    try:
        return await expert_service.list_experts(
            profile_id=profile_id,
            caregiver_id=caregiver_id,
            session=session,
        )
    except ProfileDomainError as exc:
        raise map_domain_error(exc)


# ===========================================================================
# DELETE /{profile_id}/experts/{link_id} — 解除专家关联
# ===========================================================================


@router.delete(
    "/{profile_id}/experts/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="解除专家关联",
    responses={
        204: {"description": "解除成功"},
        404: {"description": "档案或关联不存在"},
        409: {"description": "乐观锁冲突，请刷新后重试"},
    },
)
async def unlink_expert_endpoint(
    profile_id: UUID,
    link_id: UUID,
    anonymous_user: dict = Depends(get_anonymous_user),
    session: AsyncSession = Depends(get_db_session),
    expert_service: ExpertServiceImpl = Depends(_get_expert_service),
) -> None:
    caregiver_id = extract_user_id(anonymous_user)
    try:
        await expert_service.unlink_expert(
            profile_id=profile_id,
            link_id=link_id,
            caregiver_id=caregiver_id,
            session=session,
        )
    except ProfileDomainError as exc:
        raise map_domain_error(exc)


__all__ = ["router"]
