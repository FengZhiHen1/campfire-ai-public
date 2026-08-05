"""api-server 认证模块 — FastAPI 依赖注入工厂（ADR-013 目标态）。

提供：
- 数据库会话与各 Repository 的请求级依赖
- py_auth 契约实例的组装工厂（PasswordHasher/TokenManager/TokenBlacklist）
- AuthService / InviteCodeService / ReviewService 的组装工厂
- CurrentUser 语义类型与全站认证守卫：
  - get_current_user: JWT 验签 + jti 黑名单 + 家族吊销检查（无状态，不查 DB）
  - require_roles(*roles): 显式角色集合守卫（组合 get_current_user + RBACGuard）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncGenerator

from fastapi import Depends, HTTPException, Request
from py_auth.auth_contract import PasswordHasher as BasePasswordHasher
from py_auth.blacklist import RedisBlacklist
from py_auth.exceptions import PermissionDeniedError
from py_auth.hashing import hash_password, verify_password
from py_auth.jwt_utils import JoseTokenManager
from py_auth.rbac import get_guard
from py_config import get_settings
from py_db.repositories.credential_repository import CredentialRepository
from py_db.repositories.invite_code_repository import InviteCodeRepository
from py_db.repositories.narrative_repository import NarrativeRepository
from py_db.repositories.profile_repository import (
    EventLogRepository,
    ProfessionalNoteRepository,
    ProfileAccessRepository,
    ProfileRepository,
)
from py_db.repositories.review_repository import (
    ReviewAuditLogRepository,
    ReviewRepository,
)
from py_db.repositories.user_repository import UserRepository
from py_logger import logger
from py_schemas.auth import UserRole
from py_schemas.enums import AccountStatus
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from app.modules.auth.auth_contract import AuthService
    from app.modules.auth.invite_codes_service import InviteCodeService
    from app.modules.auth.review_service import ReviewService


# ---------------------------------------------------------------------------
# 数据库引擎与会话工厂（模块级惰性初始化）
# ---------------------------------------------------------------------------

_engine = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取或创建异步会话工厂（惰性初始化）。"""
    global _engine, _async_session_factory
    if _async_session_factory is None:
        settings = get_settings()
        database_url = str(settings.DATABASE_URL)
        _engine = create_async_engine(database_url, echo=False)
        _async_session_factory = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：为每个请求提供独立的异步数据库会话。"""
    factory = _get_session_factory()
    async with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# CurrentUser — 已认证用户语义类型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CurrentUser:
    """当前已认证用户（access token 验签后的可信声明）。

    roles 属性满足 py_auth.types.HasRoles 协议（单角色互斥后仍保持
    协议形态，供 RBACGuard 复用）。
    """

    user_id: str
    role: UserRole
    status: AccountStatus
    family_id: str
    jti: str

    @property
    def id(self) -> str:
        return self.user_id

    @property
    def roles(self) -> list[UserRole]:
        return [self.role]

    def to_legacy_dict(self) -> dict[str, str]:
        """转为旧 service 层期望的 dict 契约（sub/user_id/role）。

        兼容桥接：consultation/cases/profiles 各 service 在 S3/S4 模块重写前
        仍消费 dict 形态入参；模块重写时改收 CurrentUser 并删除本方法。
        """
        return {"sub": self.user_id, "user_id": self.user_id, "role": self.role.value}


# ---------------------------------------------------------------------------
# PasswordHasher 适配器
# ---------------------------------------------------------------------------


class PasswordHasher(BasePasswordHasher):
    """bcrypt 密码哈希适配器（封装 py_auth.hashing 调用）。"""

    def _do_hash(self, plain_password: str) -> str:
        return hash_password(plain_password)

    def _do_verify(self, plain_password: str, hashed_password: str) -> bool:
        return verify_password(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# AuditLogger 适配器
# ---------------------------------------------------------------------------


class AuditLogger:
    """审计日志适配器（认证与访问 §七 审计事件，统一 py_logger 结构化日志）。"""

    def log_user_register(self, user_id: str, phone: str, role: str) -> None:
        """用户注册成功审计（手机号脱敏记录——日志不落地完整 PII）。"""
        logger.critical(
            service="api-server",
            message="用户注册成功",
            op_type="USER_REGISTER",
            extra={
                "user_id": user_id,
                "phone_masked": phone[:3] + "****" + phone[-4:] if len(phone) == 11 else "****",
                "role": role,
            },
        )


# ---------------------------------------------------------------------------
# 全站认证守卫
# ---------------------------------------------------------------------------

_AUTH_MISSING_DETAIL = "未登录或凭证无效，请重新登录"
_PERMISSION_DENIED_DETAIL = "当前角色无权执行此操作，如需权限请联系管理员"

_token_manager: JoseTokenManager | None = None
_token_blacklist: RedisBlacklist | None = None


def _get_token_manager() -> JoseTokenManager:
    global _token_manager
    if _token_manager is None:
        _token_manager = JoseTokenManager()
    return _token_manager


def _get_token_blacklist() -> RedisBlacklist:
    global _token_blacklist
    if _token_blacklist is None:
        _token_blacklist = RedisBlacklist()
    return _token_blacklist


async def get_current_user(request: Request) -> CurrentUser:
    """全站认证守卫——解析并校验 access token。

    校验链（无状态，不查 DB——机制 §5.1「校验无状态，吊销状态存 Redis」）：
      1. Authorization Bearer token 提取
      2. JWT 验签 + 有效期 + type=access
      3. jti 黑名单检查（logout 后的 access 即拒）
      4. family_id 吊销检查（登出/复用检测/角色状态变更后的家族即拒）

    disabled 账号语义：存活 access ≤15min 自然到期收敛（机制 §3.2），
    刷新路径由 AuthService 以 DB 最新 status 拒签。

    Raises:
        HTTPException 401: 未携带凭证 / 验签失败 / 已吊销。
    """
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail=_AUTH_MISSING_DETAIL)

    token = authorization.removeprefix("Bearer ").strip()
    payload = _get_token_manager().verify_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail=_AUTH_MISSING_DETAIL)

    blacklist = _get_token_blacklist()
    jti = str(payload.get("jti", ""))
    if jti and await blacklist.is_blacklisted(jti):
        raise HTTPException(status_code=401, detail=_AUTH_MISSING_DETAIL)

    family_id = str(payload.get("family_id", ""))
    if family_id and await blacklist.is_family_revoked(family_id):
        raise HTTPException(status_code=401, detail=_AUTH_MISSING_DETAIL)

    try:
        user = CurrentUser(
            user_id=str(payload["sub"]),
            role=UserRole(str(payload["role"])),
            status=AccountStatus(str(payload["status"])),
            family_id=family_id,
            jti=jti,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail=_AUTH_MISSING_DETAIL) from exc

    # 写入 request.state 供 py_auth.rbac.require_roles 等下游守卫复用
    request.state.user = user
    return user


def require_roles(*roles: UserRole):
    """显式角色集合守卫工厂（认证与访问 §六）。

    组合 get_current_user + RBACGuard 显式集合匹配，
    返回 CurrentUser 供路由处理函数使用。

    Usage:
        @router.get("/admin")
        async def admin_route(user: CurrentUser = Depends(require_roles(UserRole.ADMIN))): ...
    """
    if not roles:
        raise ValueError("require_roles 必须显式声明至少一个角色")

    required = list(roles)

    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        try:
            get_guard().authorize(user, exact_roles=required)
        except PermissionDeniedError as exc:
            raise HTTPException(status_code=403, detail=_PERMISSION_DENIED_DETAIL) from exc
        return user

    return _dep


# ---------------------------------------------------------------------------
# FastAPI Depends 工厂函数
# ---------------------------------------------------------------------------


def get_user_repository() -> UserRepository:
    """FastAPI Depends 工厂：构造 UserRepository 实例。"""
    return UserRepository(session_factory=_get_session_factory())


def get_credential_repository() -> CredentialRepository:
    """FastAPI Depends 工厂：构造 CredentialRepository 实例。"""
    return CredentialRepository(session_factory=_get_session_factory())


def get_invite_code_repository() -> InviteCodeRepository:
    """FastAPI Depends 工厂：构造 InviteCodeRepository 实例。"""
    return InviteCodeRepository(session_factory=_get_session_factory())


def get_narrative_repository() -> NarrativeRepository:
    """FastAPI Depends 工厂：构造 NarrativeRepository 实例。"""
    return NarrativeRepository(session_factory=_get_session_factory())


def get_password_hasher() -> PasswordHasher:
    """FastAPI Depends 工厂：构造 PasswordHasher 适配器实例。"""
    return PasswordHasher()


def get_audit_logger() -> AuditLogger:
    """FastAPI Depends 工厂：构造 AuditLogger 适配器实例。"""
    return AuditLogger()


def get_token_manager() -> JoseTokenManager:
    """FastAPI Depends 工厂：构造 JoseTokenManager 实例。"""
    return JoseTokenManager()


def get_token_blacklist() -> RedisBlacklist:
    """FastAPI Depends 工厂：构造 RedisBlacklist 实例。"""
    return RedisBlacklist()


def get_auth_service() -> "AuthService":
    """FastAPI Depends 工厂：组装 AuthServiceImpl 并注入所有依赖。"""
    from app.modules.auth.auth_service import AuthServiceImpl

    return AuthServiceImpl(
        password_hasher=PasswordHasher(),
        token_manager=JoseTokenManager(),
        token_blacklist=RedisBlacklist(),
        user_repo=UserRepository(session_factory=_get_session_factory()),
        credential_repo=CredentialRepository(session_factory=_get_session_factory()),
        invite_code_repo=InviteCodeRepository(session_factory=_get_session_factory()),
        audit_logger=AuditLogger(),
    )


def get_invite_code_service() -> "InviteCodeService":
    """FastAPI Depends 工厂：组装 InviteCodeService。"""
    from app.modules.auth.invite_codes_service import InviteCodeService

    return InviteCodeService(
        invite_code_repo=InviteCodeRepository(session_factory=_get_session_factory()),
    )


def get_review_service() -> "ReviewService":
    """FastAPI Depends 工厂：组装 ReviewService。"""
    from app.modules.auth.review_service import ReviewService

    return ReviewService(
        user_repo=UserRepository(session_factory=_get_session_factory()),
    )


def get_review_repository() -> ReviewRepository:
    """FastAPI Depends 工厂：构造 ReviewRepository 实例。"""
    return ReviewRepository(session_factory=_get_session_factory())


def get_review_audit_log_repository() -> ReviewAuditLogRepository:
    """FastAPI Depends 工厂：构造 ReviewAuditLogRepository 实例。"""
    return ReviewAuditLogRepository(session_factory=_get_session_factory())


def get_event_repository() -> EventLogRepository:
    """FastAPI Depends 工厂：构造 EventLogRepository 实例。"""
    return EventLogRepository(session_factory=_get_session_factory())


def get_profile_repository() -> ProfileRepository:
    """FastAPI Depends 工厂：构造 ProfileRepository 实例。"""
    return ProfileRepository(session_factory=_get_session_factory())


def get_profile_access_repository() -> ProfileAccessRepository:
    """FastAPI Depends 工厂：构造 ProfileAccessRepository 实例。"""
    return ProfileAccessRepository(session_factory=_get_session_factory())


def get_professional_note_repository() -> ProfessionalNoteRepository:
    """FastAPI Depends 工厂：构造 ProfessionalNoteRepository 实例。"""
    return ProfessionalNoteRepository(session_factory=_get_session_factory())


__all__ = [
    "CurrentUser",
    "get_current_user",
    "require_roles",
    "get_db_session",
    "get_user_repository",
    "get_credential_repository",
    "get_invite_code_repository",
    "get_review_repository",
    "get_review_audit_log_repository",
    "get_event_repository",
    "get_profile_access_repository",
    "get_professional_note_repository",
    "get_profile_repository",
    "get_password_hasher",
    "get_audit_logger",
    "get_token_manager",
    "get_token_blacklist",
    "get_auth_service",
    "get_invite_code_service",
    "get_review_service",
    "PasswordHasher",
    "AuditLogger",
]
