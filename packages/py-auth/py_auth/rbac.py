"""AUTH-04 五级RBAC鉴权 — 实现版。

提供路由级权限校验、字段级脱敏和档案隐私控制。
"""

from __future__ import annotations

import logging
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

_logger = logging.getLogger("py_auth.rbac")


def require_role(
    min_level: UserRole | None = None,
    exact_roles: Sequence[UserRole] | None = None,
) -> Callable[[Request], Any]:
    """路由级权限校验 FastAPI Depends 工厂。

    Args:
        min_level: 层级累加模式——用户最高角色层级 >= 此值时放行。
        exact_roles: 精确模式——用户任一角色在此白名单内时放行。

    Raises:
        ValueError: 两个参数同时非空（互斥）。
    """
    if min_level is not None and exact_roles is not None:
        raise ValueError("min_level 和 exact_roles 参数不能同时使用")

    async def _require_role(request: Request) -> None:
        # --- 前置依赖检查 ---
        if not hasattr(request, "state"):
            raise HTTPException(status_code=401, detail=_AUTH_MISSING_DETAIL)

        user = getattr(request.state, "user", None)
        if user is None:
            raise HTTPException(status_code=401, detail=_AUTH_MISSING_DETAIL)

        roles = getattr(user, "roles", None)
        if roles is None or len(roles) == 0:
            raise HTTPException(status_code=401, detail=_AUTH_MISSING_DETAIL)

        # --- 权限判定 ---
        user_roles: list[UserRole] = list(roles)
        denied = False

        if min_level is not None:
            max_level = max(role.level for role in user_roles)
            if max_level < min_level.level:
                denied = True
        elif exact_roles is not None:
            allowed_set = set(exact_roles)
            if not any(role in allowed_set for role in user_roles):
                denied = True
        else:
            # 两者均为 None → 默认 FAMILY 层级，任何已认证用户放行
            pass

        if denied:
            try:
                _logger.warning(
                    "permission_denied",
                    extra={
                        "event": "permission_denied",
                        "user_id": getattr(user, "id", None),
                        "target_route": request.url.path,
                        "required": str(min_level) if min_level else [str(r) for r in exact_roles] if exact_roles else None,
                        "actual_roles": [str(r) for r in user_roles],
                    },
                )
            except Exception:
                pass  # 日志失败不影响 403 抛出

            raise HTTPException(
                status_code=403,
                detail=_PERMISSION_DENIED_DETAIL,
            )

        return None

    return _require_role


def get_masked_phone(phone: str, user_roles: Sequence[UserRole]) -> str:
    """手机号字段级脱敏判定。

    Args:
        phone: 原始手机号字符串。
        user_roles: 查看者的角色列表。

    Returns:
        admin/maintainer(level>=4) 返回完整号码，其他角色返回脱敏格式。
        异常格式号码降级为 "****"，永不抛异常。
    """
    try:
        # 处理 None 输入
        if phone is None:
            return _FALLBACK_MASK

        # 计算最高角色层级（空列表默认 0）
        if not user_roles:
            max_level = 0
        else:
            max_level = max(
                role.level if isinstance(role, UserRole) else 0
                for role in user_roles
            )

        # admin(4) / maintainer(5) 可见完整号码
        if max_level >= 4:
            return str(phone).strip()

        # 脱敏处理
        cleaned = str(phone).strip()
        if len(cleaned) != 11 or not _PHONE_PATTERN.match(cleaned):
            _logger.warning(
                "Invalid phone format for masking: length=%d, pattern_matched=%s",
                len(cleaned),
                bool(_PHONE_PATTERN.match(cleaned)),
            )
            return _FALLBACK_MASK

        return cleaned[:3] + "****" + cleaned[-4:]
    except Exception:
        return _FALLBACK_MASK


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
