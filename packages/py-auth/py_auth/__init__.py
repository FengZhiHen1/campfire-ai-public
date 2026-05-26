"""py-auth — 认证安全共享包。

提供 JWT Token 签发/校验、bcrypt 密码哈希/校验、RBAC 权限检查。
"""

from py_auth.hashing import hash_password, verify_password
from py_auth.jwt_utils import create_access_token, verify_token
from py_auth.exceptions import (
    HashingError,
    TokenCreationError,
    TokenDecodeError,
)

__all__ = [
    # 密码哈希
    "hash_password",
    "verify_password",
    # JWT
    "create_access_token",
    "verify_token",
    # 异常
    "HashingError",
    "TokenCreationError",
    "TokenDecodeError",
]
