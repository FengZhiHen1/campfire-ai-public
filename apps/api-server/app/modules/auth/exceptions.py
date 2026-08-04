"""api-server 认证模块 — 业务异常层次（ADR-013 目标态）。

模块: app.modules.auth.exceptions
职责: 定义认证服务层的业务异常，与 HTTP 传输层解耦。
      路由层负责将业务异常映射为 HTTPException。

边界:
  - 依赖: Python stdlib typing
  - 被依赖: auth_contract.py, auth_service.py, invite_codes_service.py, review_service.py

禁止行为:
  - 禁止在异常类中引用 FastAPI HTTPException（保持与传输层解耦）
  - 禁止异常类包含循环导入（不 import 任何项目内部模块）
"""

from __future__ import annotations

from typing import Any


class AuthServiceError(Exception):
    """认证服务统一异常基类。

    诊断字段:
      - message: 人类可读的错误描述
      - code: 机器可读的错误码（用于 HTTP 状态码映射）
      - detail: 可选的错误详情字典
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "AUTH_ERROR",
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.message: str = message
        self.code: str = code
        self.detail: dict[str, Any] | None = detail
        super().__init__(self.message)


# ============================================================================
# 注册相关异常
# ============================================================================


class PasswordComplexityError(AuthServiceError):
    """密码复杂度不足。映射: HTTP 422。"""

    def __init__(self, message: str = "密码必须同时包含大写字母、小写字母和数字") -> None:
        super().__init__(
            message,
            code="PASSWORD_COMPLEXITY",
            detail={
                "errors": [
                    {
                        "field": "password",
                        "reason": message,
                        "constraint": "password_complexity",
                    }
                ]
            },
        )


class RealNameRequiredError(AuthServiceError):
    """老师/专家角色缺少真实姓名（准入审核依据）。映射: HTTP 422。"""

    def __init__(self) -> None:
        super().__init__(
            "老师/专家角色必须填写真实姓名",
            code="REAL_NAME_REQUIRED",
            detail={
                "errors": [
                    {
                        "field": "real_name",
                        "reason": "老师/专家角色必须填写真实姓名",
                        "constraint": "required_for_review_roles",
                    }
                ]
            },
        )


class DuplicateUserError(AuthServiceError):
    """手机号已注册。映射: HTTP 409。"""

    def __init__(self, code: str = "DUPLICATE_PHONE", message: str = "该手机号已被注册") -> None:
        super().__init__(message, code=code)


class InvalidInviteCodeError(AuthServiceError):
    """邀请码无效（不存在/已停用/已过期/已用完）。映射: HTTP 422。

    安全约束：不区分具体失效原因——避免邀请码枚举探测。
    """

    def __init__(self) -> None:
        super().__init__(
            "邀请码无效或已用完",
            code="INVALID_INVITE_CODE",
            detail={
                "errors": [
                    {
                        "field": "invite_code",
                        "reason": "邀请码无效或已用完",
                        "constraint": "invite_code_valid",
                    }
                ]
            },
        )


class InviteChannelMismatchError(AuthServiceError):
    """邀请码渠道与注册角色不匹配（认证与访问 §4.1 channel 约束）。映射: HTTP 422。"""

    def __init__(self) -> None:
        super().__init__(
            "该邀请码不支持注册所选角色",
            code="INVITE_CHANNEL_MISMATCH",
            detail={
                "errors": [
                    {
                        "field": "role",
                        "reason": "该邀请码不支持注册所选角色",
                        "constraint": "invite_channel_roles",
                    }
                ]
            },
        )


# ============================================================================
# 登录相关异常
# ============================================================================


class InvalidCredentialsError(AuthServiceError):
    """登录凭证无效。

    安全约束: 不区分「用户不存在」和「密码错误」（防手机号枚举攻击）。
    映射: HTTP 401
    """

    def __init__(self) -> None:
        super().__init__(
            "手机号或密码错误",
            code="INVALID_CREDENTIALS",
        )


class AccountDisabledError(AuthServiceError):
    """账号已被禁用（凭证校验通过后拒绝签发）。映射: HTTP 403。"""

    def __init__(self) -> None:
        super().__init__(
            "账号已被禁用，请联系管理员",
            code="ACCOUNT_DISABLED",
        )


# ============================================================================
# 续期相关异常
# ============================================================================


class TokenInvalidError(AuthServiceError):
    """Token 无效/过期/复用/家族已吊销。映射: HTTP 401。"""

    def __init__(self, reason: str = "token_invalid") -> None:
        messages: dict[str, str] = {
            "token_invalid": "Token 无效或已过期",
            "token_reused": "Token 已被使用，可能存在安全风险",
            "token_expired": "Token 已过期，请重新登录",
            "family_revoked": "会话已失效，请重新登录",
        }
        super().__init__(
            messages.get(reason, "Token 无效"),
            code="TOKEN_INVALID",
            detail={"reason": reason},
        )


# ============================================================================
# 准入审核相关异常
# ============================================================================


class ReviewNotFoundError(AuthServiceError):
    """审核目标用户不存在。映射: HTTP 404。"""

    def __init__(self) -> None:
        super().__init__("审核目标用户不存在", code="REVIEW_NOT_FOUND")


class ReviewStateError(AuthServiceError):
    """准入状态机非法流转（如对 active 账号执行审核）。映射: HTTP 409。"""

    def __init__(self, message: str = "当前账号状态不允许该操作") -> None:
        super().__init__(message, code="REVIEW_STATE_INVALID")


# ============================================================================
# 邀请码管理相关异常
# ============================================================================


class InviteCodeNotFoundError(AuthServiceError):
    """邀请码不存在（管理端停用操作）。映射: HTTP 404。"""

    def __init__(self) -> None:
        super().__init__("邀请码不存在", code="INVITE_CODE_NOT_FOUND")


# ============================================================================
# 内部错误
# ============================================================================


class AuthInternalError(AuthServiceError):
    """认证服务内部错误。映射: HTTP 500。"""

    def __init__(self, message: str = "系统繁忙，请稍后重试") -> None:
        super().__init__(message, code="INTERNAL_ERROR")


__all__ = [
    "AuthServiceError",
    "PasswordComplexityError",
    "RealNameRequiredError",
    "DuplicateUserError",
    "InvalidInviteCodeError",
    "InviteChannelMismatchError",
    "InvalidCredentialsError",
    "AccountDisabledError",
    "TokenInvalidError",
    "ReviewNotFoundError",
    "ReviewStateError",
    "InviteCodeNotFoundError",
    "AuthInternalError",
]
