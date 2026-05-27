"""py-auth — 认证安全共享包。

FastAPI OAuth2 Bearer Token 认证 + bcrypt 密码哈希 + 五级 RBAC 鉴权。

薄封装层，核心依赖：
- python-jose: JWT 签发/校验
- passlib[bcrypt]: 密码哈希
- FastAPI OAuth2PasswordBearer: Bearer Token 提取（自动 OpenAPI 文档）
- Redis: Token 黑名单 + Refresh Token 单次使用
"""

from py_auth.blacklist import (
    add_to_blacklist,
    is_blacklisted,
    is_refresh_used,
    mark_refresh_used,
)
from py_auth.dependencies import get_current_user, oauth2_scheme
from py_auth.exceptions import HashingError, TokenCreationError, TokenDecodeError
from py_auth.hashing import hash_password, verify_password
from py_auth.jwt_utils import (
    TokenType,
    create_access_token,
    create_refresh_token,
    verify_access_token,
    verify_refresh_token,
    verify_token,
)
from py_auth.rbac import PrivacyGuard, get_masked_phone, require_role
from py_schemas.auth import UserRole

__all__ = [
    # Token
    "TokenType",
    "create_access_token",
    "create_refresh_token",
    "verify_token",
    "verify_access_token",
    "verify_refresh_token",
    # Password
    "hash_password",
    "verify_password",
    # Dependencies
    "oauth2_scheme",
    "get_current_user",
    # RBAC
    "require_role",
    "get_masked_phone",
    "PrivacyGuard",
    "UserRole",
    # Blacklist
    "add_to_blacklist",
    "is_blacklisted",
    "mark_refresh_used",
    "is_refresh_used",
    # Exceptions
    "HashingError",
    "TokenCreationError",
    "TokenDecodeError",
]
