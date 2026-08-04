"""profiles 域共享用户工具。

模块: app.modules.profiles._user_utils
职责: 从已认证用户对象中统一提取用户 UUID，消除 3 个路由文件中的重复代码。

ADR-013：匿名演示轨废除，入参从匿名 dict 改为 CurrentUser。
数据级授权（档案关联/协作照护）在 S4 档案重构时落地，本期仅做角色收敛。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status

from app.core.dependencies.auth_dependencies import CurrentUser


class InvalidUserIdentityError(HTTPException):
    """无法从已认证用户中提取有效用户标识。"""

    def __init__(self, reason: str) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=reason,
        )


def extract_user_id(current_user: CurrentUser) -> UUID:
    """从已认证用户中提取用户 UUID。

    Args:
        current_user: get_current_user / require_roles 依赖注入的已认证用户。

    Returns:
        UUID: 提取到的用户标识。

    Raises:
        InvalidUserIdentityError: 无法解析用户标识。
    """
    try:
        return UUID(current_user.user_id)
    except (ValueError, AttributeError):
        raise InvalidUserIdentityError("用户标识格式无效") from None


__all__ = ["extract_user_id", "InvalidUserIdentityError"]
