"""api-server 认证服务 — AuthServiceImpl 实现。

本模块是 AuthService 契约的唯一实现，注入 py_auth 契约实例
（PasswordHasher, TokenManager, TokenBlacklist）和 UserRepository，
通过覆写 _do_ 钩子完成 AUTH-01~03 及登出的核心执行步骤。

每个 _do_ 钩子只包含具体执行逻辑——前置校验、后置校验和异常映射
由 @final 父类方法统一负责。
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from py_auth.exceptions import HashingError, TokenCreationError
from py_db.models.auth import User
from py_schemas.auth import RegisterRequest, RegisterResponse, TokenResponse, UserRole

from app.modules.auth.auth_contract import AuthService
from app.modules.auth.exceptions import (
    AuthInternalError,
    DuplicateUserError,
)

if TYPE_CHECKING:
    from py_auth.auth_contract import (
        PasswordHasher as PasswordHasherContract,
        TokenBlacklist as TokenBlacklistContract,
        TokenManager as TokenManagerContract,
    )
    from py_db.repositories.user_repository import UserRepository

    from app.core.dependencies.auth_dependencies import AuditLogger

# ---------------------------------------------------------------------------
# 模块级 logger
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _parse_integrity_error(exc: IntegrityError) -> tuple[str, str]:
    """解析 IntegrityError 的 PostgreSQL 约束名，映射为精确错误码。

    仅处理 pgcode == "23505"（唯一约束违反），其他 pgcode 返回通用错误码。
    提取 diag.constraint_name 区分 unique_username 和 unique_phone。

    Args:
        exc: SQLAlchemy IntegrityError 异常。

    Returns:
        (code, message) 元组：
        - ("DUPLICATE_USERNAME", "该用户名已被注册")
        - ("DUPLICATE_PHONE", "该手机号已被注册")
        - ("DUPLICATE_FIELD", "用户名或手机号已被注册")  # 回退
    """
    orig = exc.orig
    if orig is not None and getattr(orig, "pgcode", None) == "23505":
        constraint_name = getattr(getattr(orig, "diag", None), "constraint_name", "")
        if "username" in constraint_name:
            return ("DUPLICATE_USERNAME", "该用户名已被注册")
        if "phone" in constraint_name:
            return ("DUPLICATE_PHONE", "该手机号已被注册")
    return ("DUPLICATE_FIELD", "用户名或手机号已被注册")


def _audit_log_task(
    user_id: str,
    username: str,
    role: str,
    audit_logger: "AuditLogger",
) -> None:
    """异步审计日志写入任务。

    由 asyncio.create_task() 投递到事件循环执行。
    日志写入失败不阻塞注册流程，但会在回调中记录 warning。

    Args:
        user_id: 新创建用户的 UUID 字符串。
        username: 注册用户名。
        role: 注册角色值。
        audit_logger: AuditLogger 适配器实例。
    """
    try:
        audit_logger.log_user_register(
            user_id=user_id,
            username=username,
            role=role,
        )
    except Exception:
        _logger.warning(
            "audit_log_write_failed",
            extra={
                "user_id": user_id,
                "username": username,
                "role": role,
            },
        )


# ============================================================================
# AuthServiceImpl — AuthService 契约实现
# ============================================================================


class AuthServiceImpl(AuthService):
    """认证服务实现。

    继承 AuthService 契约骨架，注入 py_auth 的 PasswordHasher / TokenManager /
    TokenBlacklist 契约实例和 py_db 的 UserRepository，通过覆写 _do_ 钩子
    完成 AUTH-01~03 和登出流程的核心执行步骤。

    依赖注入（通过 __init__ 传入）:
      - password_hasher: PasswordHasher 契约实现
      - token_manager: TokenManager 契约实现
      - token_blacklist: TokenBlacklist 契约实现
      - user_repo: UserRepository 实例
      - audit_logger: 可选的 AuditLogger 适配器实例
    """

    def __init__(
        self,
        password_hasher: "PasswordHasherContract",
        token_manager: "TokenManagerContract",
        token_blacklist: "TokenBlacklistContract",
        user_repo: "UserRepository",
        audit_logger: "AuditLogger | None" = None,
    ) -> None:
        super().__init__(password_hasher, token_manager, token_blacklist, user_repo)
        self._audit_logger: AuditLogger | None = audit_logger

    # ======================================================================
    # AUTH-01 _do_ 钩子 — 密码哈希 + 数据持久化
    # ======================================================================

    def _do_hash_password(self, plain_password: str) -> str:
        """执行 bcrypt 密码哈希。

        调用注入的 self._password_hasher.hash_password()，
        捕获 HashingError 转换为 AuthInternalError。

        Args:
            plain_password: 已通过复杂度校验的明文密码。

        Returns:
            bcrypt 哈希字符串。

        Raises:
            AuthInternalError: bcrypt 引擎内部错误。
        """
        try:
            hashed: str = self._password_hasher.hash_password(plain_password)
            return hashed
        except HashingError as exc:
            _logger.error(
                "hash_password_failed",
                extra={"error": str(exc)},
            )
            raise AuthInternalError("密码哈希失败") from exc

    async def _do_register(
        self,
        request: RegisterRequest,
        hashed_password: str,
        session: Any,
    ) -> RegisterResponse:
        """执行用户数据持久化。

        构造 User ORM 对象，调用 self._user_repo.create() 写入数据库。
        捕获 IntegrityError 并解析约束名，精确区分 DUPLICATE_USERNAME /
        DUPLICATE_PHONE。

        Args:
            request: 已通过全部校验的注册请求。
            hashed_password: bcrypt 哈希后的密码串。
            session: 活动数据库异步会话。

        Returns:
            RegisterResponse: 注册成功响应。

        Raises:
            DuplicateUserError: 用户名或手机号重复（code 精确区分）。
            AuthInternalError: 数据库写入异常。
        """
        user = User(
            username=request.username,
            password_hash=hashed_password,
            role=request.role,
            phone=request.phone,
            real_name=request.real_name,
        )

        try:
            created_user = await self._user_repo.create(session, user)
        except IntegrityError as exc:
            code, message = _parse_integrity_error(exc)
            raise DuplicateUserError(code=code, message=message) from exc
        except SQLAlchemyError as exc:
            _logger.critical(
                "database_insert_failed",
                extra={
                    "username": request.username,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            raise AuthInternalError("数据库写入失败") from exc

        return RegisterResponse(
            result="success",
            user_id=str(created_user.id),
            message="注册成功",
        )

    # ======================================================================
    # AUTH-02 _do_ 钩子 — JWT 签发
    # ======================================================================

    def _do_login(self, user: Any) -> TokenResponse:
        """执行 JWT Token 对签发。

        从已认证的 User ORM 实例提取 id(转 str)、role.value，
        构造包含 sub 和 roles 的 JWT payload，调用 token_manager
        签发 access_token 和 refresh_token。

        不需要关心用户存在性和密码正确性——@final login 已校验。

        Args:
            user: 已通过认证的 User ORM 实例（id, role 均非空）。

        Returns:
            TokenResponse: 包含 access_token 和 refresh_token。

        Raises:
            AuthInternalError: JWT 签发失败。
        """
        user_id_str = str(user.id)
        role_value = user.role.value if hasattr(user.role, "value") else str(user.role)
        payload: dict[str, Any] = {
            "sub": user_id_str,
            "roles": [role_value],
        }

        try:
            access_token = self._token_manager.create_access_token(payload)
            refresh_token = self._token_manager.create_refresh_token(payload)
        except TokenCreationError as exc:
            _logger.error(
                "token_creation_failed",
                extra={"user_id": user_id_str, "error": str(exc)},
            )
            raise AuthInternalError("Token 签发失败") from exc

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    # ======================================================================
    # AUTH-03 _do_ 钩子 — Token 轮换
    # ======================================================================

    async def _do_refresh(
        self,
        payload: dict[str, Any],
        old_refresh_token: str,
    ) -> TokenResponse:
        """执行 Token 轮换——标记旧 token + 签发新 token 对。

        1. 调用 self._token_blacklist.mark_refresh_used() 标记旧 jti 已使用
        2. 构造新 payload（sub + roles），签发新的 access_token + refresh_token

        不需要关心 refresh token 有效性校验和重放检测——@final refresh_token 已处理。

        Args:
            payload: 已通过校验的旧 refresh token payload（含 sub, roles, jti）。
            old_refresh_token: 旧 refresh token 字符串（未使用，保留参数一致性）。

        Returns:
            TokenResponse: 新的 access_token + refresh_token。

        Raises:
            AuthInternalError: JWT 签发失败。
        """
        # 标记旧 token 已使用（防重放攻击）
        await self._token_blacklist.mark_refresh_used(payload["jti"])

        # 构造新 payload，签发新 token 对
        new_payload: dict[str, Any] = {
            "sub": payload["sub"],
            "roles": payload["roles"],
        }

        try:
            access_token = self._token_manager.create_access_token(new_payload)
            refresh_token = self._token_manager.create_refresh_token(new_payload)
        except TokenCreationError as exc:
            _logger.error(
                "token_refresh_failed",
                extra={
                    "sub": str(payload.get("sub", ""))[:8] + "...",
                    "error": str(exc),
                },
            )
            raise AuthInternalError("Token 续期失败") from exc

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    # ======================================================================
    # 登出 _do_ 钩子 — Token 失效
    # ======================================================================

    async def _do_logout(
        self,
        access_jti: str | None,
        refresh_jti: str | None,
    ) -> None:
        """执行 Token 失效操作。

        - 若 access_jti 非空 → 调用 self._token_blacklist.add_to_blacklist()
        - 若 refresh_jti 非空 → 调用 self._token_blacklist.mark_refresh_used()

        契约内置 fail-open 降级策略，写入失败不抛异常。

        Args:
            access_jti: access token 的 jti claim（可能为 None）。
            refresh_jti: refresh token 的 jti claim（可能为 None）。
        """
        if access_jti:
            await self._token_blacklist.add_to_blacklist(access_jti)
        if refresh_jti:
            await self._token_blacklist.mark_refresh_used(refresh_jti)

    # ======================================================================
    # 覆写审计日志钩子 — 异步投递不阻塞注册响应
    # ======================================================================

    def _audit_log_async(
        self,
        user_id: str,
        username: str,
        role: UserRole,
    ) -> None:
        """异步投递审计日志——不阻塞注册响应。

        覆写基类的空操作实现。使用 asyncio.create_task + asyncio.to_thread
        将日志写入投递到事件循环。若 audit_logger 未注入则静默跳过。
        失败时由 _audit_log_task 内部记录 warning，不影响用户响应。

        Args:
            user_id: 新注册用户 UUID 字符串。
            username: 注册用户名。
            role: 注册角色枚举值。
        """
        if self._audit_logger is None:
            return
        role_str = role.value if hasattr(role, "value") else str(role)
        asyncio.create_task(
            asyncio.to_thread(
                _audit_log_task,
                user_id,
                username,
                role_str,
                self._audit_logger,
            )
        )


__all__ = [
    "AuthServiceImpl",
    "_parse_integrity_error",
]
