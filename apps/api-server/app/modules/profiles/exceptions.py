"""profiles 模块——业务异常。"""

from __future__ import annotations


class ProfileError(Exception):
    """档案域统一异常基类。"""

    def __init__(self, message: str, *, code: str = "PROFILE_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class ProfileNotFoundError(ProfileError):
    """档案不存在或无访问权限（存在性隐藏，防探测）。映射 404。"""

    def __init__(self) -> None:
        super().__init__("档案不存在或无权访问", code="PROFILE_NOT_FOUND")


class ProfileForbiddenError(ProfileError):
    """有档案访问权但无该操作权限（如 volunteer 尝试删除事件）。映射 403。"""

    def __init__(self, message: str = "当前角色无权执行此操作") -> None:
        super().__init__(message, code="PROFILE_FORBIDDEN")


class EventNotFoundError(ProfileError):
    """事件不存在。映射 404。"""

    def __init__(self) -> None:
        super().__init__("事件不存在", code="EVENT_NOT_FOUND")


class AccessNotFoundError(ProfileError):
    """关联不存在。映射 404。"""

    def __init__(self) -> None:
        super().__init__("关联不存在", code="ACCESS_NOT_FOUND")


class InviteeNotFoundError(ProfileError):
    """被邀请人未注册或角色不符。映射 422。"""

    def __init__(self) -> None:
        super().__init__("被邀请人未注册或角色不符", code="INVITEE_INVALID")


class DuplicateAccessError(ProfileError):
    """重复关联。映射 409。"""

    def __init__(self) -> None:
        super().__init__("该用户已关联此档案", code="ACCESS_DUPLICATE")


__all__ = [
    "ProfileError",
    "ProfileNotFoundError",
    "ProfileForbiddenError",
    "EventNotFoundError",
    "AccessNotFoundError",
    "InviteeNotFoundError",
    "DuplicateAccessError",
]
