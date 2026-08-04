"""api-server 认证服务 — AuthServiceImpl 实现（ADR-013 目标态）。

本模块是 AuthService 契约的唯一实现，注入 py_auth 契约实例
（PasswordHasher, TokenManager, TokenBlacklist）和 py_db Repository
（User / Credential / InviteCode），通过覆写 _do_ 钩子完成
注册/登录/续期/登出/me 的核心执行步骤。

每个 _do_ 钩子只包含具体执行逻辑——前置校验、后置校验和异常映射
由 @final 父类方法统一负责。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

from py_auth.exceptions import HashingError, TokenCreationError
from py_db.models.auth import Credential, User
from py_logger import logger
from py_schemas.auth import RegisterResponse, TokenResponse, UserRole
from py_schemas.enums import AccountStatus, CredentialType
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.modules.auth.auth_contract import AuthService
from app.modules.auth.exceptions import (
    AuthInternalError,
    DuplicateUserError,
    InvalidInviteCodeError,
)

if TYPE_CHECKING:
    from py_auth.auth_contract import (
        PasswordHasher as PasswordHasherContract,
    )
    from py_auth.auth_contract import (
        TokenBlacklist as TokenBlacklistContract,
    )
    from py_auth.auth_contract import (
        TokenManager as TokenManagerContract,
    )
    from py_db.models.auth import InviteCode
    from py_db.repositories.credential_repository import CredentialRepository
    from py_db.repositories.invite_code_repository import InviteCodeRepository
    from py_db.repositories.user_repository import UserRepository
    from py_schemas.auth import RegisterRequest

    from app.core.dependencies.auth_dependencies import AuditLogger

# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _parse_integrity_error(exc: IntegrityError) -> tuple[str, str]:
    """解析 IntegrityError 的 PostgreSQL 约束名，映射为精确错误码。

    仅处理 pgcode == "23505"（唯一约束违反）。
    """
    orig = exc.orig
    if orig is not None and getattr(orig, "pgcode", None) == "23505":
        constraint_name = getattr(getattr(orig, "diag", None), "constraint_name", "") or ""
        if "phone" in constraint_name:
            return ("DUPLICATE_PHONE", "该手机号已被注册")
        if "credentials" in constraint_name:
            return ("DUPLICATE_CREDENTIAL", "该凭证已存在")
    return ("DUPLICATE_FIELD", "手机号或凭证已被注册")


def _audit_log_task(
    user_id: str,
    phone: str,
    role: str,
    audit_logger: "AuditLogger",
) -> None:
    """异步审计日志写入任务（注册事件）。失败不阻塞主流程。"""
    try:
        audit_logger.log_user_register(user_id=user_id, phone=phone, role=role)
    except Exception:
        logger.warning(
            service="api-server",
            message="audit_log_write_failed",
            extra={"user_id": user_id, "role": role},
        )


# ============================================================================
# AuthServiceImpl — AuthService 契约实现
# ============================================================================


class AuthServiceImpl(AuthService):
    """认证服务实现（ADR-013 目标态）。

    继承 AuthService 契约骨架，注入 py_auth 契约实例与 py_db Repository，
    通过覆写 _do_ 钩子完成注册/登录/续期/登出/me 的核心执行步骤。
    """

    def __init__(
        self,
        password_hasher: "PasswordHasherContract",
        token_manager: "TokenManagerContract",
        token_blacklist: "TokenBlacklistContract",
        user_repo: "UserRepository",
        credential_repo: "CredentialRepository",
        invite_code_repo: "InviteCodeRepository",
        audit_logger: "AuditLogger | None" = None,
    ) -> None:
        super().__init__(
            password_hasher,
            token_manager,
            token_blacklist,
            user_repo,
            credential_repo,
            invite_code_repo,
        )
        self._audit_logger: AuditLogger | None = audit_logger

    # ==================================================================
    # 注册 _do_ 钩子
    # ==================================================================

    def _do_hash_password(self, plain_password: str) -> str:
        """执行 bcrypt 密码哈希。"""
        try:
            return self._password_hasher.hash_password(plain_password)
        except HashingError as exc:
            logger.error(
                service="api-server",
                message="hash_password_failed",
                extra={"error": str(exc)},
            )
            raise AuthInternalError("密码哈希失败") from exc

    async def _do_register(
        self,
        request: "RegisterRequest",
        hashed_password: str,
        invite_code: "InviteCode",
        session: Any,
    ) -> RegisterResponse:
        """执行注册落库原子事务。

        步骤：原子消费邀请码 → 创建 User（准入落态）→ 创建 password Credential
        → commit。任一步骤失败回滚，邀请码消费随之回滚不产生脏扣减。
        """
        # 1. 原子消费邀请码（条件自增，并发下仅一个请求成功）
        consumed = await self._invite_code_repo.consume_if_valid(session, request.invite_code)
        if consumed is None:
            raise InvalidInviteCodeError()

        # 2. 创建 User（teacher/expert 置 pending_review，其余 active）
        status = (
            AccountStatus.PENDING_REVIEW if request.role in (UserRole.TEACHER, UserRole.EXPERT) else AccountStatus.ACTIVE
        )
        user = User(
            phone=request.phone,
            real_name=request.real_name,
            role=request.role,
            status=status,
        )

        try:
            created_user = await self._user_repo.create(session, user)

            # 3. 创建 password Credential（identifier=phone，secret=bcrypt 哈希）
            credential = Credential(
                user_id=created_user.id,
                type=CredentialType.PASSWORD,
                identifier=request.phone,
                secret=hashed_password,
            )
            await self._credential_repo.create(session, credential)

            # 4. 提交事务（邀请码消费 + User + Credential 原子落库）
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            code, message = _parse_integrity_error(exc)
            raise DuplicateUserError(code=code, message=message) from exc
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.critical(
                service="api-server",
                message="database_insert_failed",
                op_type="database_error",
                extra={"error": str(exc)},
            )
            raise AuthInternalError("数据库写入失败") from exc

        return RegisterResponse(
            result="success",
            user_id=str(created_user.id),
            status=status,
            message="注册成功" if status == AccountStatus.ACTIVE else "注册成功，等待管理员审核",
        )

    # ==================================================================
    # 查询 _do_ 钩子
    # ==================================================================

    async def _do_fetch_credential(self, phone: str, session: Any) -> Credential | None:
        """按手机号查询 password 渠道凭证。"""
        return await self._credential_repo.find_by_type_and_identifier(
            session, CredentialType.PASSWORD, phone
        )

    async def _do_fetch_user_by_id(self, user_id: str, session: Any) -> User | None:
        """按 UUID 查询用户。"""
        try:
            uid = uuid.UUID(user_id)
        except (ValueError, AttributeError):
            return None
        return await self._user_repo.find_by_id(session, uid)

    # ==================================================================
    # 登录/续期 _do_ 钩子 — Token 签发
    # ==================================================================

    def _build_token_data(self, user: User, family_id: str) -> dict[str, Any]:
        """构建 Token 签发数据（role/status 以 DB 最新值为准）。"""
        return {
            "sub": str(user.id),
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "status": user.status.value if hasattr(user.status, "value") else str(user.status),
            "family_id": family_id,
        }

    def _do_login(self, user: User) -> TokenResponse:
        """执行新 Token 家族签发（每次登录创建新家族）。"""
        data = self._build_token_data(user, family_id=str(uuid.uuid4()))
        try:
            access_token = self._token_manager.create_access_token(data)
            refresh_token = self._token_manager.create_refresh_token(data)
        except TokenCreationError as exc:
            logger.error(
                service="api-server",
                message="token_creation_failed",
                extra={"user_id": data["sub"], "error": str(exc)},
            )
            raise AuthInternalError("Token 签发失败") from exc
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    async def _do_refresh(self, payload: dict[str, Any], user: User) -> TokenResponse:
        """执行 Token 轮换——标记旧 jti + 同家族内签发新对。"""
        # 标记旧 token 已使用（防重放）
        await self._token_blacklist.mark_refresh_used(payload["jti"])

        # 同一家族内延续，role/status 以 DB 最新值为准
        data = self._build_token_data(user, family_id=payload["family_id"])
        try:
            access_token = self._token_manager.create_access_token(data)
            refresh_token = self._token_manager.create_refresh_token(data)
        except TokenCreationError as exc:
            logger.error(
                service="api-server",
                message="token_refresh_failed",
                extra={"sub": data["sub"][:8] + "...", "error": str(exc)},
            )
            raise AuthInternalError("Token 续期失败") from exc
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    # ==================================================================
    # 登出 _do_ 钩子
    # ==================================================================

    async def _do_logout(self, access_jti: str | None, family_id: str | None) -> None:
        """执行 Token 失效——access jti 入黑名单 + 家族吊销（fail-open）。"""
        if access_jti:
            await self._token_blacklist.add_to_blacklist(access_jti)
        if family_id:
            await self._token_blacklist.revoke_family(family_id)

    # ==================================================================
    # 审计日志覆写
    # ==================================================================

    def _audit_log_async(self, user_id: str, phone: str, role: UserRole) -> None:
        """异步投递注册审计日志——不阻塞注册响应。"""
        if self._audit_logger is None:
            return
        role_str = role.value if hasattr(role, "value") else str(role)
        asyncio.create_task(
            asyncio.to_thread(
                _audit_log_task,
                user_id,
                phone,
                role_str,
                self._audit_logger,
            )
        )

    def _audit_token_reuse(self, family_id: str) -> None:
        """令牌复用检测安全审计事件（认证与访问 §七）。"""
        logger.critical(
            service="api-server",
            message="检测到 Refresh Token 复用，已吊销整个 Token 家族",
            op_type="TOKEN_REUSE_DETECTED",
            extra={"family_id": family_id[:8] + "..."},
        )


__all__ = ["AuthServiceImpl"]
