"""api-server 认证模块 — 业务异常层次。

模块: app.modules.auth.exceptions
职责: 定义认证服务层的业务异常，与 HTTP 传输层解耦。
      @final AuthService 方法负责将业务异常映射为 HTTPException。

数据来源:
  - 无外部数据依赖（纯异常定义）

边界:
  - 依赖: Python stdlib typing
  - 被依赖: auth_contract.py, auth_service.py（实现层）

禁止行为:
  - 禁止在异常类中引用 FastAPI HTTPException（保持与传输层解耦）
  - 禁止异常类包含循环导入（不 import 任何项目内部模块）
"""

from __future__ import annotations

from typing import Any


class AuthServiceError(Exception):
    """认证服务统一异常基类。

    触发条件: 认证流程中任何可恢复的业务异常。
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
# AUTH-01 注册相关异常
# ============================================================================


class PasswordComplexityError(AuthServiceError):
    """密码复杂度不足。

    触发条件: 密码不满足大写字母+小写字母+数字+至少8位的要求。
    映射: HTTP 422 Unprocessable Entity
    """

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
    """专家角色缺少真实姓名。

    触发条件: 注册角色为 expert 但 real_name 为 None 或空字符串。
    映射: HTTP 422 Unprocessable Entity
    """

    def __init__(self) -> None:
        super().__init__(
            "专家角色必须填写真实姓名",
            code="REAL_NAME_REQUIRED",
            detail={
                "errors": [
                    {
                        "field": "real_name",
                        "reason": "专家角色必须填写真实姓名",
                        "constraint": "required_for_expert",
                    }
                ]
            },
        )


class DuplicateUserError(AuthServiceError):
    """用户名或手机号重复。

    触发条件: 数据库唯一约束冲突（unique_username 或 unique_phone）。
    映射: HTTP 409 Conflict
    """

    def __init__(self, code: str = "DUPLICATE_FIELD", message: str = "用户名或手机号已被注册") -> None:
        super().__init__(message, code=code)


# ============================================================================
# AUTH-02 登录相关异常
# ============================================================================


class InvalidCredentialsError(AuthServiceError):
    """登录凭证无效。

    触发条件: 用户名不存在或密码不匹配。
    安全约束: 不区分具体原因（防用户名枚举攻击）。
    映射: HTTP 401 Unauthorized
    """

    def __init__(self) -> None:
        super().__init__(
            "用户名或密码错误",
            code="INVALID_CREDENTIALS",
        )


# ============================================================================
# AUTH-03 续期相关异常
# ============================================================================


class TokenInvalidError(AuthServiceError):
    """Token 无效或过期。

    触发条件: refresh token 签名无效、exp 已过期或 type != "refresh"。
    映射: HTTP 401 Unauthorized
    """

    def __init__(self, reason: str = "token_invalid") -> None:
        messages: dict[str, str] = {
            "token_invalid": "Token 无效或已过期",
            "token_reused": "Token 已被使用，可能存在安全风险",
            "token_expired": "Token 已过期，请重新登录",
        }
        super().__init__(
            messages.get(reason, "Token 无效"),
            code="TOKEN_INVALID",
            detail={"reason": reason},
        )


# ============================================================================
# 内部错误
# ============================================================================


class AuthInternalError(AuthServiceError):
    """认证服务内部错误。

    触发条件: 密码哈希失败、数据库操作失败、JWT 签发失败等不可预期错误。
    映射: HTTP 500 Internal Server Error
    """

    def __init__(self, message: str = "系统繁忙，请稍后重试") -> None:
        super().__init__(message, code="INTERNAL_ERROR")


__all__ = [
    "AuthServiceError",
    "PasswordComplexityError",
    "RealNameRequiredError",
    "DuplicateUserError",
    "InvalidCredentialsError",
    "TokenInvalidError",
    "AuthInternalError",
]
