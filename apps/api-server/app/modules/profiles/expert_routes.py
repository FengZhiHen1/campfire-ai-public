"""PROF-05 专家关联管理 — API 路由。

提供专家关联的查询与解除端点，挂载于 /api/v1/profiles 前缀下。

端点：
- GET    /{profile_id}/experts           — 获取关联专家列表
- DELETE /{profile_id}/experts/{link_id} — 解除专家关联
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies.anonymous_user import get_anonymous_user
from app.core.dependencies.auth_dependencies import (
    get_db_session,
    get_profile_repository,
    get_teacher_link_repository,
    get_user_repository,
)
from app.modules.profiles.expert_service import list_experts, unlink_expert
from py_db.repositories.profile_repository import ProfileRepository
from py_db.repositories.teacher_link_repository import TeacherLinkRepository
from py_db.repositories.user_repository import UserRepository
from py_schemas.profiles import ExpertInfo

router = APIRouter(prefix="/api/v1/profiles", tags=["experts"])


def _extract_user_id(anonymous_user: dict) -> UUID:
    """从匿名用户字典中提取用户 UUID。"""
    user_id_str: str = anonymous_user.get("sub", anonymous_user.get("user_id", ""))
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无法解析用户标识",
        )
    try:
        return UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户标识格式无效",
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
    link_repo: TeacherLinkRepository = Depends(get_teacher_link_repository),
    profile_repo: ProfileRepository = Depends(get_profile_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> list[ExpertInfo]:
    """关联专家列表端点。"""
    caregiver_id = _extract_user_id(anonymous_user)
    return await list_experts(
        profile_id=profile_id,
        caregiver_id=caregiver_id,
        session=session,
        link_repo=link_repo,
        profile_repo=profile_repo,
        user_repo=user_repo,
    )


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
    link_repo: TeacherLinkRepository = Depends(get_teacher_link_repository),
    profile_repo: ProfileRepository = Depends(get_profile_repository),
) -> None:
    """解除专家关联端点。"""
    caregiver_id = _extract_user_id(anonymous_user)
    await unlink_expert(
        profile_id=profile_id,
        link_id=link_id,
        caregiver_id=caregiver_id,
        session=session,
        link_repo=link_repo,
        profile_repo=profile_repo,
    )


__all__ = ["router"]
