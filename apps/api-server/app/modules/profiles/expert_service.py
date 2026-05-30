"""PROF-05 专家关联管理 — Service 层。

提供专家关联的查询与解除业务逻辑。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.repositories.profile_repository import ProfileRepository
from py_db.repositories.teacher_link_repository import TeacherLinkRepository
from py_db.repositories.user_repository import UserRepository
from py_schemas.profiles import ExpertInfo


async def list_experts(
    profile_id: UUID,
    caregiver_id: UUID,
    session: AsyncSession,
    link_repo: TeacherLinkRepository,
    profile_repo: ProfileRepository,
    user_repo: UserRepository,
) -> list[ExpertInfo]:
    """查询指定档案的关联专家列表。

    Args:
        profile_id: 目标档案 UUID。
        caregiver_id: 当前用户 UUID（用于档案权限校验）。
        session: 活动数据库会话。
        link_repo: TeacherLinkRepository 实例。
        profile_repo: ProfileRepository 实例。
        user_repo: UserRepository 实例。

    Returns:
        list[ExpertInfo]: 关联专家列表。

    Raises:
        HTTPException(404): 档案不存在。
    """
    profile = await profile_repo.get_by_id(session, profile_id, caregiver_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="档案不存在",
        )

    links = await link_repo.find_links_by_profile(session, profile_id)
    experts: list[ExpertInfo] = []

    for link in links:
        user = await user_repo.find_by_id(session, link.teacher_id)
        if user is None:
            continue
        name = user.real_name or user.username
        experts.append(
            ExpertInfo(
                expert_id=str(link.teacher_id),
                link_id=str(link.link_id),
                name=name,
                role=link.role,
                created_at=link.created_at,
            )
        )

    return experts


async def unlink_expert(
    profile_id: UUID,
    link_id: UUID,
    caregiver_id: UUID,
    session: AsyncSession,
    link_repo: TeacherLinkRepository,
    profile_repo: ProfileRepository,
) -> None:
    """解除指定档案与专家的关联。

    Args:
        profile_id: 目标档案 UUID。
        link_id: 关联记录 UUID。
        caregiver_id: 当前用户 UUID（用于档案权限校验）。
        session: 活动数据库会话。
        link_repo: TeacherLinkRepository 实例。
        profile_repo: ProfileRepository 实例。

    Raises:
        HTTPException(404): 档案不存在或关联不存在。
    """
    profile = await profile_repo.get_by_id(session, profile_id, caregiver_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="档案不存在",
        )

    links = await link_repo.find_links_by_profile(session, profile_id)
    target_link = next((lnk for lnk in links if lnk.link_id == link_id), None)
    if target_link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="关联不存在",
        )

    from py_db.repositories.teacher_link_repository import StaleDataError

    try:
        await link_repo.unlink_teacher(session, link_id, expected_version=target_link.version)
    except StaleDataError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="关联已被其他操作修改，请刷新后重试",
        )


__all__ = ["list_experts", "unlink_expert"]
