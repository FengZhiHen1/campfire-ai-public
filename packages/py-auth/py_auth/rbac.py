"""AUTH-04 五级RBAC鉴权 — MVP 完全绕过版。

MVP 阶段：所有角色校验直接放行，不执行任何权限检查。
原有函数签名和返回值保持不变，确保路由层无需修改。
"""

from __future__ import annotations

import re
from typing import Any, Callable, Sequence

from fastapi import HTTPException, Request

from py_schemas.auth import UserRole


_PERMISSION_DENIED_DETAIL: str = (
    "当前角色无权执行此操作，如需权限请联系管理员"
)

_AUTH_MISSING_DETAIL: str = "未登录或角色信息缺失，请重新登录"

_PHONE_PATTERN: re.Pattern[str] = re.compile(r"^1[3-9]\d{9}$")

_FALLBACK_MASK: str = "****"


def require_role(
    min_level: UserRole | None = None,
    exact_roles: Sequence[UserRole] | None = None,
) -> Callable[[Request], Any]:
    """路由级权限校验 FastAPI Depends 工厂（MVP 绕过版）。

    无论传入什么参数，均直接返回 None（放行）。
    保持原有函数签名，路由层 Depends 无需任何修改。
    """

    async def _require_role(request: Request) -> None:
        """直接放行，不执行任何权限检查。"""
        return None

    return _require_role


def get_masked_phone(phone: str, viewer_role: UserRole) -> str:
    """手机号字段级脱敏判定（MVP 简化版：始终返回完整号码）。"""
    return phone


class PrivacyGuard:
    """档案隐私控制守卫（MVP 绕过版）。

    所有访问请求直接放行，返回 allowed=True。
    """

    @staticmethod
    async def check_access(request, db_session) -> "AccessDecision":
        from py_schemas.profiles import AccessDecision, VisibleScope
        return AccessDecision(
            allowed=True,
            visible_scope=VisibleScope.ALL_FIELDS,
        )


__all__ = [
    "require_role",
    "get_masked_phone",
    "PrivacyGuard",
]
