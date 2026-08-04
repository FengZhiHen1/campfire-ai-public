"""api-server 认证模块 — 准入审核服务。

机制事实源：docs/技术设计/机制/认证与访问.md §3.2（账号状态机）。
- admin：待审列表 / 通过 / 驳回（含原因）
- 用户自服务：驳回后补交材料重提（rejected → pending_review）

状态机守卫：仅 pending_review 可审核，仅 rejected 可重提；
refresh 以 DB 最新 status 签发，审核结果随下一次续期自然生效。
"""

from __future__ import annotations

import uuid
from typing import Any

from py_logger import logger
from py_schemas.auth import (
    ReviewApproveResponse,
    ReviewListItem,
    ReviewListResponse,
    UserRole,
)
from py_schemas.enums import AccountStatus

from app.modules.auth.exceptions import (
    ReviewNotFoundError,
    ReviewStateError,
)

# 准入审核覆盖的角色（teacher/expert 注册进入审核流）
_REVIEW_ROLES: tuple[UserRole, UserRole] = (UserRole.TEACHER, UserRole.EXPERT)


def _to_review_item(user: Any) -> ReviewListItem:
    """ORM → DTO 映射（管理员视角，手机号完整可见——NFR 字段级权限）。"""
    return ReviewListItem(
        user_id=str(user.id),
        phone=user.phone,
        real_name=user.real_name,
        role=user.role,
        status=user.status,
        reject_reason=user.reject_reason,
        created_at=user.created_at.isoformat(),
    )


class ReviewService:
    """准入审核服务。

    依赖注入：UserRepository（py_db）。
    事务边界：本服务内方法显式 commit/rollback。
    """

    def __init__(self, user_repo: Any) -> None:
        self._user_repo = user_repo

    async def list_pending(self, session: Any) -> ReviewListResponse:
        """待审列表（pending_review 的 teacher/expert，按注册时间升序）。"""
        users = await self._user_repo.list_by_status_and_roles(
            session,
            statuses=[AccountStatus.PENDING_REVIEW],
            roles=list(_REVIEW_ROLES),
        )
        items = [_to_review_item(u) for u in users]
        return ReviewListResponse(items=items, total=len(items))

    async def approve(self, user_id: str, admin_user_id: str, session: Any) -> ReviewApproveResponse:
        """审核通过：pending_review → active。"""
        user = await self._load_review_target(session, user_id)
        if user.status != AccountStatus.PENDING_REVIEW:
            raise ReviewStateError("仅审核中账号可执行通过操作")

        user.status = AccountStatus.ACTIVE
        user.reject_reason = None
        await session.commit()

        logger.critical(
            service="api-server",
            message="准入审核通过",
            op_type="REVIEW_APPROVE",
            extra={"user_id": user_id, "admin_user_id": admin_user_id},
        )
        return ReviewApproveResponse(user_id=user_id)

    async def reject(self, user_id: str, reason: str, admin_user_id: str, session: Any) -> ReviewApproveResponse:
        """审核驳回：pending_review → rejected（含面向用户的驳回原因）。"""
        user = await self._load_review_target(session, user_id)
        if user.status != AccountStatus.PENDING_REVIEW:
            raise ReviewStateError("仅审核中账号可执行驳回操作")

        user.status = AccountStatus.REJECTED
        user.reject_reason = reason
        await session.commit()

        logger.critical(
            service="api-server",
            message="准入审核驳回",
            op_type="REVIEW_REJECT",
            extra={"user_id": user_id, "admin_user_id": admin_user_id},
        )
        return ReviewApproveResponse(
            user_id=user_id,
            status=AccountStatus.REJECTED,
            message="已驳回",
        )

    async def resubmit(self, user_id: str, real_name: str | None, session: Any) -> ReviewApproveResponse:
        """补交材料重提（用户自服务）：rejected → pending_review。

        可选更正 real_name；驳回原因清空，等待管理员重新审核。
        """
        user = await self._load_review_target(session, user_id)
        if user.status != AccountStatus.REJECTED:
            raise ReviewStateError("仅已驳回账号可补交材料重提")

        if real_name:
            user.real_name = real_name
        user.status = AccountStatus.PENDING_REVIEW
        user.reject_reason = None
        await session.commit()

        logger.critical(
            service="api-server",
            message="准入材料补交重提",
            op_type="REVIEW_RESUBMIT",
            extra={"user_id": user_id},
        )
        return ReviewApproveResponse(
            user_id=user_id,
            status=AccountStatus.PENDING_REVIEW,
            message="已重新提交，等待管理员审核",
        )

    async def _load_review_target(self, session: Any, user_id: str) -> Any:
        """加载审核目标用户（teacher/expert）。"""
        try:
            uid = uuid.UUID(user_id)
        except (ValueError, AttributeError) as exc:
            raise ReviewNotFoundError() from exc
        user = await self._user_repo.find_by_id(session, uid)
        if user is None or user.role not in _REVIEW_ROLES:
            raise ReviewNotFoundError()
        return user


__all__ = ["ReviewService"]
