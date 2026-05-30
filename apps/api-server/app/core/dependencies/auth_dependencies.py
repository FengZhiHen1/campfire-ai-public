"""AUTH-01 用户注册 — FastAPI 依赖注入工厂。

提供 UserRepository、PasswordHasher、AuditLogger 的依赖注入工厂函数，
以及数据库异步会话的请求级依赖。
所有工厂函数均可在 FastAPI Depends() 中直接使用。
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from py_auth.hashing import hash_password
from py_config import get_settings
from py_db.repositories.case_repository import CaseRepository
from py_db.repositories.event_repository import EventRepository
from py_db.repositories.profile_repository import ProfileRepository
from py_db.repositories.review_repository import (
    ReviewAuditLogRepository,
    ReviewRepository,
)
from py_db.repositories.teacher_link_repository import TeacherLinkRepository
from py_db.repositories.user_repository import UserRepository
from py_logger import logger


# ---------------------------------------------------------------------------
# 数据库引擎与会话工厂（模块级惰性初始化）
# ---------------------------------------------------------------------------

_engine = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取或创建异步会话工厂（惰性初始化）。

    首次调用时从 AppSettings.DATABASE_URL 创建 asyncpg 引擎，
    后续调用返回缓存的会话工厂。

    Returns:
        async_sessionmaker[AsyncSession]: 已配置的异步会话工厂。
    """
    global _engine, _async_session_factory
    if _async_session_factory is None:
        settings = get_settings()
        # PostgresDsn 的字符串形式即为完整连接串
        database_url = str(settings.DATABASE_URL)
        _engine = create_async_engine(database_url, echo=False)
        _async_session_factory = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：为每个请求提供独立的异步数据库会话。

    会话在请求结束时自动关闭，确保连接归还连接池。

    Yields:
        AsyncSession: 当前请求的数据库异步会话。
    """
    factory = _get_session_factory()
    async with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# PasswordHasher 适配器
# ---------------------------------------------------------------------------


class PasswordHasher:
    """bcrypt 密码哈希适配器。

    封装 py_auth.hashing.hash_password() 调用，
    提供干净的依赖注入边界，便于 Service 层单元测试时 mock。

    Usage:
        hasher = PasswordHasher()
        hashed = hasher.hash("Abc12345")
    """

    def hash(self, plain_password: str) -> str:
        """对明文密码执行 bcrypt 不可逆哈希。

        Args:
            plain_password: 明文密码原文。

        Returns:
            bcrypt 哈希字符串，格式 $2b$12$...。

        Raises:
            HashingError: bcrypt 引擎内部错误（passlib 不可用、OOM 等）。
        """
        return hash_password(plain_password)


# ---------------------------------------------------------------------------
# AuditLogger 适配器
# ---------------------------------------------------------------------------


class AuditLogger:
    """审计日志适配器。

    封装 py_logger.logger.critical() 调用（op_type 必填），
    提供干净的依赖注入边界，便于 Service 层单元测试时 mock。

    Usage:
        audit = AuditLogger()
        audit.log_user_register(user_id="...", username="...", role="family")
    """

    def log_user_register(
        self,
        user_id: str,
        username: str,
        role: str,
    ) -> None:
        """写入用户注册成功审计日志。

        调用 logger.critical() 强制要求 op_type="USER_REGISTER"，
        确保注册事件不可绕过审计追踪。

        Args:
            user_id: 新注册用户的 UUID 字符串。
            username: 注册用户名。
            role: 用户角色值（family/teacher/expert）。
        """
        logger.critical(
            service="api-server",
            message=f"用户注册成功: {username}",
            op_type="USER_REGISTER",
            extra={
                "user_id": user_id,
                "username": username,
                "role": role,
            },
        )


# ---------------------------------------------------------------------------
# FastAPI Depends 工厂函数
# ---------------------------------------------------------------------------


def get_user_repository() -> UserRepository:
    """FastAPI Depends 工厂：构造 UserRepository 实例。

    注入 async_session_factory 供 Repository 内部使用。
    每次请求调用时返回新实例（无状态，创建成本可忽略）。

    Returns:
        UserRepository: 已配置会话工厂的 Repository 实例。
    """
    return UserRepository(session_factory=_get_session_factory())


def get_case_repository() -> CaseRepository:
    """FastAPI Depends 工厂：构造 CaseRepository 实例。

    注入 async_session_factory 供 Repository 内部使用。
    每次请求调用时返回新实例。

    Returns:
        CaseRepository: 已配置会话工厂的 Repository 实例。
    """
    return CaseRepository(session_factory=_get_session_factory())


def get_password_hasher() -> PasswordHasher:
    """FastAPI Depends 工厂：构造 PasswordHasher 适配器实例。

    Returns:
        PasswordHasher: 封装 hash_password() 的适配器。
    """
    return PasswordHasher()


def get_audit_logger() -> AuditLogger:
    """FastAPI Depends 工厂：构造 AuditLogger 适配器实例。

    Returns:
        AuditLogger: 封装 logger.critical() 的适配器。
    """
    return AuditLogger()


def get_review_repository() -> ReviewRepository:
    """FastAPI Depends 工厂：构造 ReviewRepository 实例。

    注入 async_session_factory 供 Repository 内部使用。
    每次请求调用时返回新实例（无状态，创建成本可忽略）。

    Returns:
        ReviewRepository: 已配置会话工厂的 Repository 实例。
    """
    return ReviewRepository(session_factory=_get_session_factory())


def get_review_audit_log_repository() -> ReviewAuditLogRepository:
    """FastAPI Depends 工厂：构造 ReviewAuditLogRepository 实例。

    注入 async_session_factory 供 Repository 内部使用（虽然 AuditLogRepository
    不使用会话工厂——它直接接收已开启的 session 作为参数）。

    Returns:
        ReviewAuditLogRepository: 已配置的审计日志 Repository 实例。
    """
    return ReviewAuditLogRepository(session_factory=_get_session_factory())


def get_event_repository() -> EventRepository:
    """FastAPI Depends 工厂：构造 EventRepository 实例。"""
    return EventRepository(session_factory=_get_session_factory())


def get_profile_repository() -> ProfileRepository:
    """FastAPI Depends 工厂：构造 ProfileRepository 实例。"""
    return ProfileRepository(session_factory=_get_session_factory())


def get_teacher_link_repository() -> TeacherLinkRepository:
    """FastAPI Depends 工厂：构造 TeacherLinkRepository 实例。"""
    return TeacherLinkRepository(session_factory=_get_session_factory())


__all__ = [
    "get_db_session",
    "get_user_repository",
    "get_case_repository",
    "get_review_repository",
    "get_review_audit_log_repository",
    "get_event_repository",
    "get_profile_repository",
    "get_teacher_link_repository",
    "get_password_hasher",
    "get_audit_logger",
    "PasswordHasher",
    "AuditLogger",
]
