"""py-auth 显式角色→能力 RBAC（ADR-013 目标态）。

六角色显式能力矩阵（认证与访问 §六）——矩阵即文档，越权用例可直接
对照验收；数值层级继承（min_level）已废除，守卫统一为显式集合匹配。

核心内容:
  - Capability: 能力域枚举（应急咨询/档案/案例/工单/平台管理/系统运维）
  - ROLE_CAPABILITIES: 角色→能力显式映射矩阵
  - DefaultRBACGuard: 实现 RBACGuard 契约，显式集合匹配判定
  - require_roles: FastAPI Depends 工厂（路由级显式角色守卫）
  - has_capability: 能力判定纯函数
  - get_masked_phone: 手机号字段级脱敏（NFR：仅 admin 可见完整手机号）

Usage:
    from py_auth.rbac import require_roles, has_capability, Capability
    @router.get("/admin")
    async def admin_route(_: None = Depends(require_roles(UserRole.ADMIN))): ...
"""

from __future__ import annotations

import re
import traceback
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Callable, Sequence, cast

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


# ===========================================================================
# 能力域枚举与角色→能力矩阵（认证与访问 §六 的代码直译）
# ===========================================================================


class Capability(StrEnum):
    """能力域枚举——全站能力的最小授权单位。

    与认证与访问 §六 矩阵的「能力域」列一一对应；
    数据级授权（档案关联、案例可见性分级等）归各模块机制文档，不在此枚举。
    """

    EMERGENCY_CONSULT = "emergency_consult"  # 应急咨询 / 科普
    PROFILE_OWN = "profile_own"  # 档案（自有家庭全权）
    PROFILE_COLLAB = "profile_collab"  # 档案（受邀受限/受邀共建）
    CASE_CREATE = "case_create"  # 案例录入
    CASE_REVIEW = "case_review"  # 案例审核 / 下架
    CASE_FORCE_UNLIST = "case_force_unlist"  # 案例强制下架（admin）
    TICKET_FAMILY = "ticket_family"  # 工单家属侧
    TICKET_TEACHER = "ticket_teacher"  # 工单普通/紧急接单
    TICKET_EXPERT = "ticket_expert"  # 工单专家侧（特急仅专家）
    TICKET_DISPATCH = "ticket_dispatch"  # 工单转派
    PLATFORM_ADMIN = "platform_admin"  # 平台管理（用户/准入审核/邀请码）
    SYSTEM_OPS = "system_ops"  # 系统运维（健康/监控/维护）


ROLE_CAPABILITIES: dict[UserRole, frozenset[Capability]] = {
    UserRole.FAMILY: frozenset(
        {
            Capability.EMERGENCY_CONSULT,
            Capability.PROFILE_OWN,
            Capability.TICKET_FAMILY,
        }
    ),
    UserRole.VOLUNTEER: frozenset(
        {
            Capability.EMERGENCY_CONSULT,
            Capability.PROFILE_COLLAB,
        }
    ),
    UserRole.TEACHER: frozenset(
        {
            Capability.PROFILE_COLLAB,
            Capability.CASE_CREATE,
            Capability.TICKET_TEACHER,
        }
    ),
    UserRole.EXPERT: frozenset(
        {
            Capability.PROFILE_COLLAB,
            Capability.CASE_CREATE,
            Capability.CASE_REVIEW,
            Capability.TICKET_EXPERT,
        }
    ),
    UserRole.ADMIN: frozenset(
        {
            Capability.CASE_FORCE_UNLIST,
            Capability.TICKET_DISPATCH,
            Capability.PLATFORM_ADMIN,
        }
    ),
    UserRole.MAINTAINER: frozenset(
        {
            Capability.SYSTEM_OPS,
        }
    ),
}
"""六角色 → 能力显式映射矩阵。变更属设计变更，需同步更新认证与访问 §六。"""


def has_capability(role: UserRole, capability: Capability) -> bool:
    """判定角色是否拥有指定能力（显式映射，无隐式继承）。"""
    return capability in ROLE_CAPABILITIES.get(role, frozenset())


# ---------------------------------------------------------------------------
# RBACGuard 实现（显式集合匹配）
# ---------------------------------------------------------------------------


class DefaultRBACGuard(RBACGuard):
    """显式角色集合匹配守卫，继承 RBACGuard 契约。

    前置校验（用户存在性、角色非空）由 @final authorize 处理，
    本类只关心显式集合匹配逻辑。
    """

    def _do_authorize(
        self,
        user: HasRoles,
        exact_roles: list[Any] | None,
    ) -> bool:
        """判定用户角色是否满足显式集合要求。

        Returns:
            True 表示应拒绝（权限不足），False 表示放行。
        """
        user_roles: list[UserRole] = list(getattr(user, "roles", []))

        # 防御：虽然 _validate_authorize_input 已校验 roles 非空，
        # 但这里仍做一次防御，避免非正常调用路径触发异常
        if not user_roles:
            return True  # 拒绝——无角色不可访问

        if exact_roles is not None:
            allowed_set = set(exact_roles)
            if not any(role in allowed_set for role in user_roles):
                return True  # 拒绝

        return False  # 放行


# ============================================================================
# 惰性初始化（避免 import 时触发配置读取）
# ============================================================================

_guard_instance: DefaultRBACGuard | None = None


def get_guard() -> DefaultRBACGuard:
    """获取 DefaultRBACGuard 模块级单例（惰性初始化）。"""
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = DefaultRBACGuard()
    return _guard_instance


# ============================================================================
# FastAPI Depends 工厂
# ============================================================================


def require_roles(*roles: UserRole) -> Callable[[Request], Any]:
    """路由级权限校验 FastAPI Depends 工厂（显式集合匹配）。

    从 request.state.user 读取已认证用户（由 get_current_user 依赖注入），
    通过 DefaultRBACGuard.authorize() 进入契约路径判定。

    在路由中使用:
        @router.get("/admin")
        async def admin_route(_: None = Depends(require_roles(UserRole.ADMIN))):
            ...

    Args:
        *roles: 放行的角色集合（显式枚举，至少一个）。

    Raises:
        ValueError: 未传入任何角色（编程错误，禁止空调用）。
    """
    if not roles:
        raise ValueError("require_roles 必须显式声明至少一个角色")

    required = list(roles)

    async def _require_roles(request: Request) -> None:
        if not hasattr(request, "state"):
            raise HTTPException(status_code=401, detail=_AUTH_MISSING_DETAIL)

        user = getattr(request.state, "user", None)

        guard = get_guard()
        try:
            guard.authorize(cast(HasRoles, user), exact_roles=required)
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

    return _require_roles


# ============================================================================
# 工具函数
# ============================================================================


def get_masked_phone(phone: str | None, user_roles: Sequence[UserRole]) -> str:
    """手机号字段级脱敏判定（NFR：手机号仅管理员可见）。

    仅 admin 返回完整号码，其他角色（含 maintainer——无业务数据权限）
    返回脱敏格式。任何意外异常降级为 "****" 并记录 warning 日志。

    Args:
        phone: 原始手机号字符串（可为 None）。
        user_roles: 查看者的角色列表。

    Returns:
        完整号码或脱敏格式（如 138****1234）。
    """
    try:
        if phone is None:
            return _FALLBACK_MASK

        if UserRole.ADMIN in user_roles:
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


__all__ = [
    "Capability",
    "ROLE_CAPABILITIES",
    "has_capability",
    "DefaultRBACGuard",
    "get_guard",
    "require_roles",
    "get_masked_phone",
]
