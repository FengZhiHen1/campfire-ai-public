"""py-auth 五级 RBAC 鉴权 — DefaultRBACGuard 实现。

实现 RBACGuard 契约，提供路由级权限校验、字段级脱敏和档案隐私控制。

核心类:
  - DefaultRBACGuard: 实现 RBACGuard 契约，五级角色权限判定

工具函数:
  - require_role: FastAPI Depends 工厂函数（路由级权限）
  - get_masked_phone: 手机号字段级脱敏

Usage:
    from py_auth.rbac import DefaultRBACGuard, require_role, get_guard
    guard = get_guard()
    guard.authorize(user, min_level=UserRole.ADMIN)
"""

from __future__ import annotations

import re
import traceback
from typing import TYPE_CHECKING, Any, Callable, Sequence, cast

if TYPE_CHECKING:
    from py_schemas.profiles import AccessDecision

from fastapi import HTTPException, Request
from py_logger import logger
from py_schemas.auth import UserRole

from py_auth.auth_contract import RBACGuard
from py_auth.exceptions import PermissionDeniedError
from py_auth.types import HasRoles

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_PERMISSION_DENIED_DETAIL: str = "当前角色无权执行此操作，如需权限请联系管理员"
_AUTH_MISSING_DETAIL: str = "未登录或角色信息缺失，请重新登录"

_PHONE_PATTERN: re.Pattern[str] = re.compile(r"^1[3-9]\d{9}$")
_FALLBACK_MASK: str = "****"

# ---------------------------------------------------------------------------
# RBACGuard 实现
# ---------------------------------------------------------------------------


class DefaultRBACGuard(RBACGuard):
    """五级 RBAC 权限判定，继承 RBACGuard 契约。

    前置校验（用户存在性、角色非空、参数互斥）由 @final authorize 处理，
    实现者只需关心角色层级比较逻辑。
    """

    def _do_authorize(
        self,
        user: HasRoles,
        min_level: Any | None,
        exact_roles: list[Any] | None,
    ) -> bool:
        """判定用户角色是否满足权限要求。

        Returns:
            True 表示应拒绝（权限不足），False 表示放行。
        """
        user_roles: list[UserRole] = list(getattr(user, "roles", []))

        # 防御：虽然 _validate_authorize_input 已校验 roles 非空，
        # 但这里仍做一次防御，避免非正常调用路径触发 max([]) 崩溃
        if not user_roles:
            return True  # 拒绝——无角色不可访问

        if min_level is not None:
            max_level = max(role.level for role in user_roles)
            if max_level < min_level.level:
                return True  # 拒绝
        elif exact_roles is not None:
            allowed_set = set(exact_roles)
            if not any(role in allowed_set for role in user_roles):
                return True  # 拒绝
        # 两者均为 None → 默认放行

        return False  # 放行


# ============================================================================
# 惰性初始化（避免 import 时触发配置读取）
# ============================================================================

_guard_instance: DefaultRBACGuard | None = None


def get_guard() -> DefaultRBACGuard:
    """获取 DefaultRBACGuard 模块级单例（惰性初始化）。

    首次调用时创建实例，后续调用返回同一实例。
    避免在模块 import 阶段触发配置读取（get_security_config）。
    """
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = DefaultRBACGuard()
    return _guard_instance


# ============================================================================
# FastAPI Depends 工厂
# ============================================================================


def require_role(
    min_level: UserRole | None = None,
    exact_roles: Sequence[UserRole] | None = None,
) -> Callable[[Request], Any]:
    """路由级权限校验 FastAPI Depends 工厂。

    通过调用 DefaultRBACGuard.authorize() 进入契约路径：
    前置校验（用户存在性、角色非空）→ _do_authorize 判定 → 后置日志。

    在路由中使用:
        @router.get("/admin")
        async def admin_route(_: None = Depends(require_role(min_level=UserRole.ADMIN))):
            ...

    Args:
        min_level: 层级累加模式——用户最高角色层级 >= 此值时放行。
        exact_roles: 精确模式——用户任一角色在此白名单内时放行。

    Raises:
        ValueError: 两个参数同时非空（互斥）。
    """
    if min_level is not None and exact_roles is not None:
        raise ValueError("min_level 和 exact_roles 参数不能同时使用")

    async def _require_role(request: Request) -> None:
        if not hasattr(request, "state"):
            raise HTTPException(status_code=401, detail=_AUTH_MISSING_DETAIL)

        user = getattr(request.state, "user", None)

        # 通过契约公共入口 authorize 进行判定
        # authorize 的 _validate_authorize_input 会处理 user=None → PermissionDeniedError
        guard = get_guard()
        try:
            guard.authorize(
                cast(HasRoles, user),
                min_level=min_level,
                exact_roles=list(exact_roles) if exact_roles else None,
            )
        except PermissionDeniedError as e:
            if e.reason in ("user_missing", "no_roles"):
                raise HTTPException(
                    status_code=401,
                    detail=_AUTH_MISSING_DETAIL,
                ) from e
            raise HTTPException(
                status_code=403,
                detail=_PERMISSION_DENIED_DETAIL,
            ) from e

        return None

    return _require_role


# ============================================================================
# 工具函数
# ============================================================================


def get_masked_phone(phone: str | None, user_roles: Sequence[UserRole]) -> str:
    """手机号字段级脱敏判定。

    admin(level>=4) / maintainer(5) 返回完整号码，其他角色返回脱敏格式。
    任何意外异常降级为 "****" 并记录 warning 日志。

    Args:
        phone: 原始手机号字符串（可为 None）。
        user_roles: 查看者的角色列表。

    Returns:
        完整号码或脱敏格式（如 138****1234）。
    """
    try:
        if phone is None:
            return _FALLBACK_MASK

        if not user_roles:
            max_level = 0
        else:
            max_level = max(role.level if isinstance(role, UserRole) else 0 for role in user_roles)

        if max_level >= 4:
            return str(phone).strip()

        cleaned = str(phone).strip()
        if len(cleaned) != 11 or not _PHONE_PATTERN.match(cleaned):
            logger.warning(
                "py-auth",
                "手机号格式异常，无法脱敏",
                op_type="权限拒绝",
                extra={
                    "length": len(cleaned),
                    "pattern_matched": bool(_PHONE_PATTERN.match(cleaned)),
                },
            )
            return _FALLBACK_MASK

        return cleaned[:3] + "****" + cleaned[-4:]
    except Exception:
        logger.warning(
            "py-auth",
            "手机号脱敏过程发生意外异常",
            op_type="权限拒绝",
            extra={"stacktrace": traceback.format_exc()},
        )
        return _FALLBACK_MASK


# ============================================================================
# PrivacyGuard — MVP 绕过版（临时）
# ============================================================================


class PrivacyGuard:
    """档案隐私控制守卫（MVP 绕过版）。

    所有访问请求直接放行，返回 allowed=True。
    正式上线后替换为基于 RBAC 的真实实现。

    # TODO: 正式版替换为 call RBAC guard 的真实实现（deadline: 上线前）
    """

    @staticmethod
    async def check_access(request: Any, db_session: Any) -> AccessDecision:
        from py_schemas.profiles import AccessDecision, VisibleScope

        return AccessDecision(
            allowed=True,
            visible_scope=VisibleScope.ALL_FIELDS,
        )


__all__ = [
    "DefaultRBACGuard",
    "get_guard",
    "require_role",
    "get_masked_phone",
    "PrivacyGuard",
]
