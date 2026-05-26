"""AUTH-04 五级RBAC鉴权 — 核心实现。

提供路由级权限校验和字段级脱敏判定：

- require_role(): FastAPI Depends 工厂，基于当前用户角色执行路由级鉴权。
  支持层级累加模式（>= min_level）和精确模式（角色在 exact_roles 集合内），
  两种模式互斥。

- get_masked_phone(): 手机号字段级脱敏判定纯函数。
  管理员（admin/maintainer）返回完整手机号，其他角色返回脱敏格式。

契约引用：
- require_role: docs/contracts/AUTH-04/require_role.json
- get_masked_phone: docs/contracts/AUTH-04/get_masked_phone.json
- UserRole: docs/contracts/AUTH-04/UserRole.json
- PermissionDeniedResponse: docs/contracts/AUTH-04/PermissionDeniedResponse.json
"""

from __future__ import annotations

import re
from typing import Any, Callable, Sequence

from fastapi import HTTPException, Request
from fastapi.datastructures import State

from py_logger import logger
from py_schemas.auth import UserRole

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_PERMISSION_DENIED_DETAIL: str = (
    "当前角色无权执行此操作，如需权限请联系管理员"
)
"""权限拒绝固定文案（信息最小化约束）。

禁止在任何环境下（包括 debug 模式）返回权限规则细节。"""

_AUTH_MISSING_DETAIL: str = "未登录或角色信息缺失，请重新登录"
"""身份/角色信息缺失固定文案。"""

_PHONE_PATTERN: re.Pattern[str] = re.compile(r"^1[3-9]\d{9}$")
"""中国大陆手机号正则（11 位，1 开头，第二位 3-9）。"""

_FALLBACK_MASK: str = "****"
"""手机号格式异常时的降级掩码。"""


# ===========================================================================
# 公开接口
# ===========================================================================


def require_role(
    min_level: UserRole | None = None,
    exact_roles: Sequence[UserRole] | None = None,
) -> Callable[[Request], Any]:
    """路由级权限校验 FastAPI Depends 工厂。

    返回一个 async 依赖可调用对象，供 FastAPI Depends() 注入使用。
    该依赖在请求入口处校验当前用户的角色是否满足目标路由的要求。

    两种模式（互斥）：
    - **层级累加模式**（min_level）：用户最高角色层级 >= min_level 时放行。
      适用于通用业务接口。多角色用户取最高层级判定。
    - **精确模式**（exact_roles）：用户角色必须在 exact_roles 集合内才放行。
      适用于运维操作（案例强制下架、用户角色变更等），
      仅管理员/维护人员可执行。

    若 min_level 和 exact_roles 均为 None，默认使用 min_level=UserRole.FAMILY。

    Args:
        min_level: 层级累加模式的最小角色要求。与 exact_roles 互斥。
        exact_roles: 精确模式的角色白名单。与 min_level 互斥。

    Returns:
        一个 async callable(request: Request) -> None，供 FastAPI Depends 注入。
        校验通过时正常返回 None，控制流进入路由处理函数。

    Raises:
        ValueError: min_level 和 exact_roles 同时非空（立即抛出，
                    在路由注册阶段即可发现错误）。
        HTTPException(401): request.state.user 不存在或 roles 为空。
        HTTPException(403): 权限校验未通过（响应体为 PermissionDeniedResponse）。

    Side Effects:
        - 权限拒绝时通过 py-logger 记录结构化日志（op_type="权限拒绝"）
        - 身份信息缺失时记录 warning 日志

    Prerequisites:
        - 必须在 AUTH-02 get_current_user Depends 之后执行
        - 路由 Depends 声明顺序: Depends(get_current_user) -> Depends(require_role(...))

    Usage:
        @router.get("/some-protected-path")
        async def handler(
            _: None = Depends(require_role(min_level=UserRole.TEACHER)),
        ):
            ...
    """
    # ---- 步骤 1: 互斥校验（工厂阶段立即执行） ----
    if min_level is not None and exact_roles is not None:
        raise ValueError(
            "min_level 和 exact_roles 参数不能同时使用"
        )

    # ---- 步骤 2: 默认值处理（两者均为 None → FAMILY 层级累加） ----
    if min_level is None and exact_roles is None:
        min_level = UserRole.FAMILY

    # 捕获到闭包中（避免循环引用）
    _min_level: UserRole | None = min_level
    _exact_roles_set: frozenset[UserRole] | None = (
        frozenset(exact_roles) if exact_roles is not None else None
    )

    # ---- 步骤 3: 构造并返回 async Depends 可调用对象 ----
    async def _require_role(request: Request) -> None:
        """FastAPI Depends 注入的实际校验逻辑。

        Args:
            request: FastAPI/Starlette Request 对象（框架自动注入）。
        """
        # ---- 前置检查：用户身份信息就绪 ----
        user_state: State = getattr(request, "state", None)
        if user_state is None:
            _log_and_raise_401(request, reason="request.state 不存在")

        user_obj: object | None = getattr(user_state, "user", None)
        if user_obj is None:
            _log_and_raise_401(request, reason="request.state.user 为 None")

        raw_roles: list[Any] | None = getattr(user_obj, "roles", None)
        if raw_roles is None or (isinstance(raw_roles, list) and len(raw_roles) == 0):
            _log_and_raise_401(
                request, reason="roles 为空或 None", user_obj=user_obj
            )

        # ---- 解析角色为 UserRole 枚举 ----
        user_roles: list[UserRole] = _parse_roles(raw_roles)
        if not user_roles:
            _log_and_raise_401(
                request, reason="roles 中无可识别的有效角色", user_obj=user_obj
            )

        # ---- 根据模式执行权限校验 ----
        if _min_level is not None:
            # 层级累加模式：用户最高层级 >= 目标层级
            max_level: int = max(role.level for role in user_roles)
            if max_level < _min_level.level:
                _log_and_raise_403(
                    request,
                    mode="hierarchical",
                    user_roles=user_roles,
                    required=f"min_level={_min_level.value}(L{_min_level.level})",
                )
        else:
            # 精确模式：用户角色必须命中白名单
            assert _exact_roles_set is not None  # 互斥保证
            user_role_set: set[UserRole] = set(user_roles)
            if not (user_role_set & _exact_roles_set):
                required_str: str = ",".join(
                    sorted(r.value for r in _exact_roles_set)
                )
                _log_and_raise_403(
                    request,
                    mode="exact",
                    user_roles=user_roles,
                    required=f"exact_roles=[{required_str}]",
                )

        # 校验通过 → 返回 None，控制流进入路由处理函数
        return None

    return _require_role


def get_masked_phone(
    phone: str,
    user_roles: Sequence[UserRole],
) -> str:
    """手机号字段级脱敏判定纯函数。

    根据用户角色判定手机号的可见性并执行脱敏。
    由 SEC-01 响应脱敏中间件在序列化阶段调用。

    判定规则：
    - 管理员角色（admin/maintainer, level >= 4）：返回原始完整手机号
    - 其他角色（family/teacher/expert, level < 4）：返回脱敏格式
    - phone 格式异常（非 11 位/非标准手机号）：返回 "****"

    脱敏格式：保留前 3 位和后 4 位，中间替换为 "****"
    例如："13812345678" → "138****5678"

    Args:
        phone: 原始手机号字符串（11 位数字）。
        user_roles: 当前用户的角色列表。
                   多角色用户取最高层级判定（与累加原则一致）。

    Returns:
        str: 管理员角色返回原始手机号；其他角色返回脱敏格式。

    Raises:
        无异常抛出。所有异常路径均降级返回安全值。

    Side Effects:
        - phone 格式异常时记录 warning 日志
    """
    # ---- 步骤 1: 提取用户最高角色层级 ----
    if not user_roles:
        # 无角色信息 → 按非管理员处理（脱敏）
        max_level: int = 0
    else:
        max_level = max(role.level for role in user_roles)

    # ---- 步骤 2: 管理员角色 → 返回完整手机号 ----
    if max_level >= 4:
        # admin(L4) 或 maintainer(L5) 可见完整手机号
        return phone

    # ---- 步骤 3: 非管理员角色 → 脱敏 ----
    phone_stripped: str = phone.strip()
    if len(phone_stripped) != 11 or not _PHONE_PATTERN.match(phone_stripped):
        logger.warning(
            "py-auth",
            "手机号格式异常，降级返回全掩码",
            extra={
                "phone_length": len(phone_stripped),
                "is_match": bool(_PHONE_PATTERN.match(phone_stripped)),
            },
        )
        return _FALLBACK_MASK

    return f"{phone_stripped[:3]}****{phone_stripped[-4:]}"


# ===========================================================================
# 私有辅助函数
# ===========================================================================


def _parse_roles(raw_roles: list[Any]) -> list[UserRole]:
    """将原始角色列表转换为 UserRole 枚举列表。

    支持 str 和 UserRole 两种输入格式（兼容 JWT payload 的 str 值
    和代码中直接传入的 UserRole 枚举值）。无法识别的角色值被静默跳过。

    Args:
        raw_roles: 原始角色列表，元素为 str 或 UserRole。

    Returns:
        已识别的 UserRole 枚举列表。元素顺序保持与输入一致。
    """
    result: list[UserRole] = []
    for role in raw_roles:
        if isinstance(role, UserRole):
            result.append(role)
        elif isinstance(role, str):
            try:
                result.append(UserRole(role))
            except ValueError:
                # 无效角色值 → 跳过并记录警告
                logger.warning(
                    "py-auth",
                    "无法识别的角色值，已跳过",
                    extra={"role_value": role},
                )
        # 其他类型静默跳过
    return result


def _get_user_id(user_obj: object) -> str:
    """从用户对象中提取用户 ID。

    尝试常见的属性名：id、sub、user_id。
    若均不存在则返回 "unknown"。

    Args:
        user_obj: request.state.user 对象。

    Returns:
        用户 ID 字符串。
    """
    for attr in ("id", "sub", "user_id"):
        value = getattr(user_obj, attr, None)
        if value is not None:
            return str(value)
    return "unknown"


def _log_and_raise_401(
    request: Request,
    *,
    reason: str,
    user_obj: object | None = None,
) -> None:
    """记录 auth_context_missing 日志并抛出 HTTP 401。

    Args:
        request: FastAPI Request 对象。
        reason: 缺失原因（用于日志）。
        user_obj: request.state.user 对象（可为 None）。

    Raises:
        HTTPException(401): 始终抛出。
    """
    extra_payload: dict[str, object] = {
        "target_route": request.url.path,
        "reason": reason,
    }
    logger.warning(
        "py-auth",
        "auth_context_missing",
        extra=extra_payload,
    )
    raise HTTPException(status_code=401, detail=_AUTH_MISSING_DETAIL)


def _log_and_raise_403(
    request: Request,
    *,
    mode: str,
    user_roles: list[UserRole],
    required: str,
) -> None:
    """记录 permission_denied 审计日志并抛出 HTTP 403。

    日志中包含完整的权限上下文（用户、路由、所需角色、实际角色），
    但 HTTP 403 响应体中仅包含固定文案（信息最小化约束）。

    Args:
        request: FastAPI Request 对象。
        mode: 校验模式（"hierarchical" 或 "exact"）。
        user_roles: 当前用户的角色列表。
        required: 目标资源要求的权限描述（仅用于日志，不返回给客户端）。

    Raises:
        HTTPException(403): 始终抛出。
    """
    user_id: str = "unknown"
    user_obj = getattr(getattr(request, "state", None), "user", None)
    if user_obj is not None:
        user_id = _get_user_id(user_obj)

    extra_payload: dict[str, object] = {
        "user_id": user_id,
        "target_route": request.url.path,
        "mode": mode,
        "required": required,
        "actual_roles": [role.value for role in user_roles],
        "actual_levels": [role.level for role in user_roles],
    }

    # 审计日志使用 warning 级别 + op_type="权限拒绝"
    # 确保异常安全：日志记录失败不阻断主路径
    try:
        logger.warning(
            "py-auth",
            "permission_denied",
            op_type="权限拒绝",
            extra=extra_payload,
        )
    except Exception:
        # 日志记录失败不影响主路径（异常抛出示意不变）
        pass

    raise HTTPException(
        status_code=403,
        detail=_PERMISSION_DENIED_DETAIL,
    )


__all__ = [
    "require_role",
    "get_masked_phone",
    "UserRole",
]
