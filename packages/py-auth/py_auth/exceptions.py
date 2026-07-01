# @contract
"""py-auth 认证安全 — 异常层次。

统一基类 AuthError，所有认证域异常继承自此，方便上层统一捕获。

异常层次:
- AuthError(Exception): 认证域统一基类
  - HashingError(AuthError): bcrypt 哈希计算或校验失败
  - TokenCreationError(AuthError): JWT 签发失败
  - TokenDecodeError(AuthError): JWT 格式无效或校验失败
  - PermissionDeniedError(AuthError): RBAC 权限不足
  - BlacklistError(AuthError): Token 黑名单操作失败
"""

from __future__ import annotations

from typing import Any


class AuthError(Exception):
    """认证域统一异常基类。

    触发条件: 任何认证流程中的可恢复异常。
    诊断字段:
      - message: 人类可读的错误描述
      - detail: 可选的机器可读错误详情字典

    上层代码可通过 ``except AuthError`` 统一捕获所有 py-auth 异常。
    """

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        self.message: str = message
        self.detail: dict[str, Any] | None = detail
        super().__init__(self.message)


class HashingError(AuthError):
    """bcrypt 哈希计算或校验失败。

    触发条件:
      - passlib / bcrypt 库内部抛出异常
      - 加密引擎不可用（如系统缺少 /dev/urandom）
      - 哈希串格式损坏无法解析

    诊断字段（继承自 AuthError）:
      - message: 原始异常信息
      - detail: {"operation": "hash"|"verify", "error_type": 原始异常类名}
    """

    def __init__(self, message: str, operation: str = "", detail: dict[str, Any] | None = None) -> None:
        merged = detail or {}
        if operation:
            merged["operation"] = operation
        super().__init__(message, merged)


class TokenCreationError(AuthError):
    """JWT Token 签发失败。

    触发条件:
      - python-jose jwt.encode() 抛出 JWTError
      - 密钥长度不足导致 HMAC 失败
      - 数据序列化为 JSON 时失败

    诊断字段（继承自 AuthError）:
      - message: 原始异常信息
      - detail: {"token_type": "access"|"refresh", "error_type": 原始异常类名}
    """

    def __init__(self, message: str, token_type: str = "", detail: dict[str, Any] | None = None) -> None:
        merged = detail or {}
        if token_type:
            merged["token_type"] = token_type
        super().__init__(message, merged)


class TokenDecodeError(AuthError):
    """JWT Token 格式无效或校验失败。

    触发条件:
      - python-jose jwt.get_unverified_headers() 无法解析 token
      - Token 字符串不包含三段 Base64 编码（非 JWT 格式）
      - Token header 格式损坏

    诊断字段（继承自 AuthError）:
      - message: 原始异常信息
      - detail: {"kid": 从 header 提取的 kid（如有）, "error_type": 原始异常类名}
    """

    def __init__(self, message: str, kid: str = "", detail: dict[str, Any] | None = None) -> None:
        merged = detail or {}
        if kid:
            merged["kid"] = kid
        super().__init__(message, merged)


class PermissionDeniedError(AuthError):
    """RBAC 权限不足或认证缺失。

    触发条件:
      - 用户对象为 None 或缺少 roles 属性
      - 用户角色列表为空
      - 用户角色层级低于 min_level
      - 用户角色不在 exact_roles 白名单中

    诊断字段:
      - message: 人类可读的错误描述
      - reason: 机器可读的原因码 ("user_missing" | "no_roles" | "permission_denied")
      - detail: {"user_roles": [...], "required": ...}

    调用方可根据 reason 码将异常映射为恰当的 HTTP 状态码：
      - user_missing / no_roles → 401
      - permission_denied → 403
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str = "permission_denied",
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.reason: str = reason
        merged = detail or {}
        merged["reason"] = reason
        super().__init__(message, merged)


class BlacklistError(AuthError):
    """Token 黑名单操作失败。

    触发条件:
      - Redis 连接不可用且调用方不允许降级
      - 黑名单 Key 写入冲突

    诊断字段（继承自 AuthError）:
      - message: 错误描述
      - detail: {"jti": ..., "operation": "add"|"check", "strategy": "fail_open"|"fail_closed"}
    """

    def __init__(
        self,
        message: str,
        jti: str = "",
        operation: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        merged = detail or {}
        if jti:
            merged["jti"] = jti
        if operation:
            merged["operation"] = operation
        super().__init__(message, merged)


__all__ = [
    "AuthError",
    "HashingError",
    "TokenCreationError",
    "TokenDecodeError",
    "PermissionDeniedError",
    "BlacklistError",
]
