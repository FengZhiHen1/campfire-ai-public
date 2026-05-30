"""profiles 域共享用户工具。

模块: app.modules.profiles._user_utils
职责: 从匿名用户字典中统一提取用户 UUID，消除 3 个路由文件中的重复代码。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status


class InvalidUserIdentityError(HTTPException):
    """无法从匿名用户字典中提取有效用户标识。"""

    def __init__(self, reason: str) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=reason,
        )


def extract_user_id(anonymous_user: dict) -> UUID:
    """从匿名用户字典中提取用户 UUID。

    从 dict 中按优先级提取 sub → user_id 字段，
    校验非空、有效 UUID 格式后返回。

    Args:
        anonymous_user: get_anonymous_user 依赖注入的 dict。

    Returns:
        UUID: 提取到的用户标识。

    Raises:
        InvalidUserIdentityError: 无法解析用户标识。
    """
    user_id_str: str = anonymous_user.get("sub", anonymous_user.get("user_id", ""))
    if not user_id_str:
        raise InvalidUserIdentityError("无法解析用户标识")
    try:
        return UUID(user_id_str)
    except ValueError:
        raise InvalidUserIdentityError("用户标识格式无效")


__all__ = ["extract_user_id", "InvalidUserIdentityError"]
