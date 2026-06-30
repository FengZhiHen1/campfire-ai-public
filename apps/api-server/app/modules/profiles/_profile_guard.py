"""profiles 域档案存在性校验 — 共享守卫。

模块: app.modules.profiles._profile_guard
职责: 提供 `ensure_profile_exists` 函数，供 BaseEventService 和 BaseExpertService
      共享使用，消除 `_ensure_profile_exists` 方法在两者间的重复。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.profiles.exceptions import ProfileNotFoundError

if TYPE_CHECKING:
    from uuid import UUID

    from py_db.repositories.profile_repository import ProfileRepository


async def ensure_profile_exists(
    profile_repo: "ProfileRepository",
    profile_id: "UUID",
    caregiver_id: "UUID",
    session: AsyncSession,
) -> None:
    """确保档案存在且归属指定用户。

    Raises:
        ProfileNotFoundError: 档案不存在。
    """
    profile = await profile_repo.get_by_id(session, profile_id, caregiver_id)
    if profile is None:
        raise ProfileNotFoundError(str(profile_id))


__all__ = ["ensure_profile_exists"]
