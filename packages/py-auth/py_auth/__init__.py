"""py-auth — 认证安全共享包。

提供 4 大能力：
1. 密码哈希: BcryptHasher 实现 PasswordHasher 契约，bcrypt 不可逆哈希
2. JWT 管理: JoseTokenManager 实现 TokenManager 契约，HS256 签发与校验
3. Token 黑名单: RedisBlacklist 实现 TokenBlacklist 契约，两层防护 + fail-open
4. RBAC 鉴权: DefaultRBACGuard 实现 RBACGuard 契约，五级角色权限判定

核心类：
  - BcryptHasher: 实现 PasswordHasher 契约，bcrypt 密码哈希
  - JoseTokenManager: 实现 TokenManager 契约，JWT 签发/校验
  - RedisBlacklist: 实现 TokenBlacklist 契约，Redis 黑名单
  - DefaultRBACGuard: 实现 RBACGuard 契约，五级角色判定

外部接口（便捷函数）：
  - hash_password(plain) -> str
  - verify_password(plain, hashed) -> bool
  - create_access_token(data) -> str
  - create_refresh_token(data) -> str
  - verify_token(token) -> dict | None
  - verify_access_token(token) -> dict | None
  - verify_refresh_token(token) -> dict | None
  - add_to_blacklist(jti) -> None
  - is_blacklisted(jti) -> bool
  - mark_refresh_used(jti) -> None
  - is_refresh_used(jti) -> bool
  - require_role(min_level, exact_roles) -> FastAPI Depends
  - get_masked_phone(phone, roles) -> str

注：MVP 阶段的匿名用户身份由 api-server 的
    app.core.dependencies.anonymous_user.get_anonymous_user 维护，
    不在 py-auth 中提供。

Usage:
    from py_auth import BcryptHasher, JoseTokenManager
    hasher = BcryptHasher()
    hashed = hasher.hash_password("mypassword")
"""

# ── 契约 ────────────────────────────────────────────────────────────────────
from py_schemas.auth import UserRole

from py_auth.auth_contract import (
    PasswordHasher,
    RBACGuard,
    TokenBlacklist,
    TokenManager,
)

# ── 实现 ────────────────────────────────────────────────────────────────────
from py_auth.blacklist import (
    RedisBlacklist,
    add_to_blacklist,
    is_blacklisted,
    is_refresh_used,
    mark_refresh_used,
)

# ── 异常 ────────────────────────────────────────────────────────────────────
from py_auth.exceptions import (
    AuthError,
    BlacklistError,
    HashingError,
    PermissionDeniedError,
    TokenCreationError,
    TokenDecodeError,
)
from py_auth.hashing import BcryptHasher, hash_password, verify_password
from py_auth.jwt_utils import (
    JoseTokenManager,
    TokenType,
    create_access_token,
    create_refresh_token,
    verify_access_token,
    verify_refresh_token,
    verify_token,
)
from py_auth.rbac import (
    DefaultRBACGuard,
    PrivacyGuard,
    get_guard,
    get_masked_phone,
    require_role,
)

# ── 语法契约（语义类型）─────────────────────────────────────────────────────
from py_auth.types import DeviceID, HasRoles, JtiToken, PlainPassword, TokenHash, UserID

__all__ = [
    # ── 契约 ──
    "PasswordHasher",
    "TokenManager",
    "TokenBlacklist",
    "RBACGuard",
    # ── 语义类型 ──
    "UserID",
    "PlainPassword",
    "TokenHash",
    "JtiToken",
    "DeviceID",
    "HasRoles",
    # ── 异常 ──
    "AuthError",
    "HashingError",
    "TokenCreationError",
    "TokenDecodeError",
    "PermissionDeniedError",
    "BlacklistError",
    # ── 实现 ──
    "BcryptHasher",
    "JoseTokenManager",
    "RedisBlacklist",
    "DefaultRBACGuard",
    # ── 工具 ──
    "TokenType",
    "UserRole",
    # ── 便捷函数 ──
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "verify_token",
    "verify_access_token",
    "verify_refresh_token",
    "add_to_blacklist",
    "is_blacklisted",
    "mark_refresh_used",
    "is_refresh_used",
    "require_role",
    "get_guard",
    "get_masked_phone",
    "PrivacyGuard",
]
