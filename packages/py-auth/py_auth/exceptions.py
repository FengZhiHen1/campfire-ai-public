"""SEC-01 认证安全 — 自定义异常层次。

三级异常：
- HashingError: bcrypt 密码哈希/校验引擎内部错误
- TokenCreationError: JWT 签发失败
- TokenDecodeError: JWT 格式无效（非 JWT 格式字符串）
"""

from __future__ import annotations


class HashingError(Exception):
    """bcrypt 哈希计算或校验失败。

    触发场景：passlib CryptContext.hash() 或 .verify() 抛出内部异常
    （如 bcrypt 库不可用、OOM 等）。
    """

    def __init__(self, message: str) -> None:
        self.message: str = message
        super().__init__(self.message)


class TokenCreationError(Exception):
    """JWT Token 签发失败。

    触发场景：python-jose jwt.encode() 抛出 JWTError
    （如密钥长度不足、jose 库内部错误等）。
    """

    def __init__(self, message: str) -> None:
        self.message: str = message
        super().__init__(self.message)


class TokenDecodeError(Exception):
    """JWT Token 格式无效（非 JWT 格式字符串）。

    触发场景：python-jose jose.jwt.get_unverified_headers() 无法解析 token
    （如字符串不包含三段 Base64 编码）。
    """

    def __init__(self, message: str) -> None:
        self.message: str = message
        super().__init__(self.message)


__all__ = [
    "HashingError",
    "TokenCreationError",
    "TokenDecodeError",
]
