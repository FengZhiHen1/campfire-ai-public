# @contract
"""api-server 认证服务行为契约 — ABC 模板方法骨架（ADR-013 目标态）。

模块: app.modules.auth.auth_contract
职责: 定义认证服务的业务编排契约。覆盖注册（邀请码原子消费 + 准入落态）、
      登录（手机号 + 状态机放行）、续期（轮换 + 家族吊销 + 复用检测）、
      登出（家族吊销）与 me 五个核心流程。每个 @final 公共入口强制执行
      前置校验 → _do_ 钩子 → 后置校验三步流程，实现者只能覆写 _do_ 钩子。

数据来源:
  - py_auth.auth_contract.PasswordHasher: MUST — 密码哈希与校验
  - py_auth.auth_contract.TokenManager: MUST — JWT 签发与校验（family_id 家族语义）
  - py_auth.auth_contract.TokenBlacklist: MUST — 黑名单/refresh 单次使用/家族吊销
  - py_db UserRepository / CredentialRepository / InviteCodeRepository: MUST — 持久化
  - py_schemas.auth: MUST — 数据契约（事实源：机制/认证与访问）

边界:
  - 依赖: py_auth, py_db, py_schemas, sqlalchemy (AsyncSession)
  - 被依赖: app.modules.auth.routes（FastAPI 路由层）

禁止行为:
  - 禁止在 @final 方法中直接调用 py_auth 便捷函数（必须走注入的契约实例）
  - 禁止在 _do_ 钩子中直接操作 FastAPI HTTPException
  - 禁止在 Service 层直接访问 HTTP 请求对象
  - 禁止实现者覆写 @final 方法
  - 禁止绕过邀请码原子消费（consume_if_valid 条件自增）直接 used_count+1
"""

from __future__ import annotations

import base64
import json
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, final

from py_schemas.auth import (
    CHANNEL_ALLOWED_ROLES,
    REVIEW_REQUIRED_ROLES,
    MeResponse,
    UserRole,
)
from py_schemas.enums import AccountStatus, InviteCodeStatus

from app.modules.auth.exceptions import (
    AccountDisabledError,
    AuthInternalError,
    DuplicateUserError,
    InvalidCredentialsError,
    InvalidInviteCodeError,
    InviteChannelMismatchError,
    PasswordComplexityError,
    RealNameRequiredError,
    TokenInvalidError,
)

if TYPE_CHECKING:
    from datetime import datetime

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
    from py_schemas.auth import (
        LoginRequest,
        RefreshRequest,
        RegisterRequest,
        RegisterResponse,
        TokenResponse,
    )

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_PASSWORD_COMPLEXITY_REGEX: re.Pattern[str] = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")
r"""密码复杂度正则：至少包含一个小写字母、一个大写字母、一个数字，且至少 8 位（维持现状规则）。"""


# ============================================================================
# AuthService — 认证服务契约
# ============================================================================


class AuthService(ABC):
    """认证服务契约 — 业务编排层 ABC（ADR-013 目标态）。

    实现者只能覆写 _do_ 前缀的钩子。
    外部调用者通过 @final 方法进入，无法绕过前置校验和后置处理。

    依赖注入（通过 __init__ 传入）:
      - password_hasher / token_manager / token_blacklist: py_auth 契约实例
      - user_repo / credential_repo / invite_code_repo: py_db Repository
    """

    def __init__(
        self,
        password_hasher: "PasswordHasherContract",
        token_manager: "TokenManagerContract",
        token_blacklist: "TokenBlacklistContract",
        user_repo: "UserRepository",
        credential_repo: "CredentialRepository",
        invite_code_repo: "InviteCodeRepository",
    ) -> None:
        self._password_hasher = password_hasher
        self._token_manager = token_manager
        self._token_blacklist = token_blacklist
        self._user_repo = user_repo
        self._credential_repo = credential_repo
        self._invite_code_repo = invite_code_repo

    # ==================================================================
    # 注册（邀请码 + 准入落态）
    # ==================================================================

    @final
    async def register(self, request: "RegisterRequest", session: Any) -> "RegisterResponse":
        """用户注册 — 邀请码校验 + 原子消费 + 身份-凭证落库（认证与访问 §4.2）。

        流程编排:
          1. 密码复杂度校验
          2. teacher/expert real_name 必填校验
          3. 邀请码预检（存在/active/未过期/有余量）+ channel 约束角色
          4. 手机号唯一性校验
          5. 密码哈希
          6. _do_register：原子消费邀请码 + 创建 User + Credential + commit
          7. 审计日志异步投递

        异常:
          - PasswordComplexityError / RealNameRequiredError: 输入校验失败
          - InvalidInviteCodeError: 邀请码无效或并发消费失败
          - InviteChannelMismatchError: 邀请码渠道不允许该角色
          - DuplicateUserError: 手机号已注册
          - AuthInternalError: 内部错误
        """
        self._validate_password_complexity(request.password)
        self._validate_review_role_real_name(request.role, request.real_name)
        invite_code = await self._validate_invite_code(request.invite_code, request.role, session)
        await self._validate_phone_uniqueness(request.phone, session)
        hashed = self._do_hash_password(request.password)
        result = await self._do_register(request, hashed, invite_code, session)
        self._validate_register_result(result)
        self._audit_log_async(result.user_id, request.phone, request.role)
        return result

    # ==================================================================
    # 登录（手机号 + 状态机放行）
    # ==================================================================

    @final
    async def login(self, request: "LoginRequest", session: Any) -> "TokenResponse":
        """用户登录 — 凭证校验 + 状态机放行 + 新 Token 家族签发（§4.3 / §5.2）。

        流程编排:
          1. 查询 password 凭证（identifier=phone）
          2. 凭证存在性校验（防枚举统一 401）
          3. 密码校验（同上统一 401）
          4. 查询用户并按 status 放行（disabled 拒签）
          5. _do_login：创建新家族（family_id）并签发 Token 对

        异常:
          - InvalidCredentialsError: 凭证不存在或密码错误（不区分）
          - AccountDisabledError: 账号已禁用
          - AuthInternalError: JWT 签发失败
        """
        credential = await self._do_fetch_credential(request.phone, session)
        self._validate_credential_exists(credential)
        assert credential is not None
        self._validate_password_match(request.password, credential.secret)
        user = await self._do_fetch_user_by_id(str(credential.user_id), session)
        self._validate_user_exists(user)
        assert user is not None
        self._validate_user_status(user)
        result = self._do_login(user)
        self._validate_token_pair(result)
        return result

    # ==================================================================
    # 续期（轮换 + 家族吊销 + 复用检测）
    # ==================================================================

    @final
    async def refresh_token(self, request: "RefreshRequest", session: Any) -> "TokenResponse":
        """Token 续期 — 轮换 + 家族语义（§5.1 / §5.2）。

        流程编排:
          1. 校验 refresh token 签名与类型
          2. 家族吊销检查（logout/禁用/角色变更后旧家族即拒）
          3. 复用检测：旧 refresh 再次出示 → 吊销全家族并拒绝
          4. 查询用户并校验状态（disabled 拒签）
          5. _do_refresh：标记旧 jti 已用 + 以最新 role/status 在同一家族内签发新对

        异常:
          - TokenInvalidError: token_invalid / family_revoked / token_reused
          - AccountDisabledError: 账号已禁用
        """
        payload = self._validate_refresh_token(request.refresh_token)
        await self._validate_family_not_revoked(payload["family_id"])
        await self._validate_refresh_not_used(payload["jti"], payload["family_id"])
        user = await self._do_fetch_user_by_id(payload["sub"], session)
        self._validate_user_exists(user)
        assert user is not None
        self._validate_user_status(user)
        result = await self._do_refresh(payload, user)
        self._validate_token_pair(result)
        return result

    # ==================================================================
    # 登出（access 黑名单 + 家族吊销）
    # ==================================================================

    @final
    async def logout(self, access_token: str, refresh_token: str) -> None:
        """登出 — access jti 入黑名单 + refresh 家族吊销（§5.2）。

        Redis 故障 fail-open 返回正常（维持现状语义）。
        不抛异常。
        """
        access_jti = self._extract_claim_unsafe(access_token, "jti")
        family_id = self._extract_claim_unsafe(refresh_token, "family_id")
        await self._do_logout(access_jti, family_id)

    # ==================================================================
    # me — 当前用户信息
    # ==================================================================

    @final
    async def get_me(self, user_id: str, session: Any) -> MeResponse:
        """获取当前用户信息。

        异常:
          - InvalidCredentialsError: 用户不存在（token 失效后的正常清理路径）
        """
        user = await self._do_fetch_user_by_id(user_id, session)
        self._validate_user_exists(user)
        assert user is not None
        return MeResponse(
            user_id=str(user.id),
            phone=user.phone,
            real_name=user.real_name,
            role=user.role,
            status=user.status,
        )

    # ==================================================================
    # @abstractmethod 钩子
    # ==================================================================

    @abstractmethod
    def _do_hash_password(self, plain_password: str) -> str:
        """执行 bcrypt 密码哈希（调用注入的 password_hasher）。"""
        ...

    @abstractmethod
    async def _do_register(
        self,
        request: "RegisterRequest",
        hashed_password: str,
        invite_code: "InviteCode",
        session: Any,
    ) -> "RegisterResponse":
        """执行注册落库原子事务。

        实现者职责:
          1. consume_if_valid 原子消费邀请码（失败 → InvalidInviteCodeError）
          2. 创建 User（teacher/expert 置 pending_review，其余 active）
          3. 创建 password Credential（identifier=phone, secret=哈希）
          4. session.commit() 提交事务

        输入约束:
          - request 已通过全部前置校验；invite_code 已通过预检
        输出约束:
          - RegisterResponse（status 反映准入落态）
        """
        ...

    @abstractmethod
    async def _do_fetch_credential(self, phone: str, session: Any) -> Any | None:
        """按手机号查询 password 渠道凭证。"""
        ...

    @abstractmethod
    async def _do_fetch_user_by_id(self, user_id: str, session: Any) -> Any | None:
        """按 UUID 查询用户。"""
        ...

    @abstractmethod
    def _do_login(self, user: Any) -> "TokenResponse":
        """执行新 Token 家族签发（family_id=新 UUID）。"""
        ...

    @abstractmethod
    async def _do_refresh(self, payload: dict[str, Any], user: Any) -> "TokenResponse":
        """执行 Token 轮换——标记旧 jti + 同家族内签发新对（以 DB 最新 role/status）。"""
        ...

    @abstractmethod
    async def _do_logout(self, access_jti: str | None, family_id: str | None) -> None:
        """执行 Token 失效——access jti 入黑名单 + 家族吊销。"""
        ...

    # ==================================================================
    # 校验器
    # ==================================================================

    def _validate_password_complexity(self, password: str) -> None:
        """密码复杂度校验——大小写字母 + 数字，至少 8 位。"""
        if not _PASSWORD_COMPLEXITY_REGEX.match(password):
            raise PasswordComplexityError()

    def _validate_review_role_real_name(self, role: UserRole, real_name: str | None) -> None:
        """teacher/expert real_name 必填校验（准入审核依据）。"""
        if role in REVIEW_REQUIRED_ROLES and not real_name:
            raise RealNameRequiredError()

    async def _validate_invite_code(self, code: str, role: UserRole, session: Any) -> "InviteCode":
        """邀请码预检——存在性/状态/过期/余量 + channel 约束角色。

        注意：此为预检，最终一致性由 _do_register 的原子消费保证
        （条件自增，并发下仅一个请求成功）。

        Raises:
            InvalidInviteCodeError: 码不存在/已停用/已过期/已用完（不区分原因，防枚举）。
            InviteChannelMismatchError: 码渠道不允许注册该角色。
        """
        invite_code = await self._invite_code_repo.find_by_code(session, code)
        if invite_code is None:
            raise InvalidInviteCodeError()
        if invite_code.status != InviteCodeStatus.ACTIVE:
            raise InvalidInviteCodeError()
        if self._is_expired(invite_code.expires_at):
            raise InvalidInviteCodeError()
        if invite_code.used_count >= invite_code.max_uses:
            raise InvalidInviteCodeError()
        if role not in CHANNEL_ALLOWED_ROLES[invite_code.channel]:
            raise InviteChannelMismatchError()
        return invite_code

    @staticmethod
    def _is_expired(expires_at: "datetime") -> bool:
        """过期判定（兼容 naive/aware 时间戳）。"""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        if expires_at.tzinfo is None:
            return expires_at < now.replace(tzinfo=None)
        return expires_at < now

    async def _validate_phone_uniqueness(self, phone: str, session: Any) -> None:
        """手机号唯一性校验。"""
        existing = await self._user_repo.find_by_phone(session, phone)
        if existing is not None:
            raise DuplicateUserError()

    def _validate_credential_exists(self, credential: Any | None) -> None:
        """凭证存在性校验——与密码错误统一 401（防枚举）。"""
        if credential is None:
            raise InvalidCredentialsError()

    def _validate_password_match(self, plain_password: str, hashed_password: str | None) -> None:
        """密码匹配校验——与凭证不存在统一 401。"""
        if not hashed_password:
            raise InvalidCredentialsError()
        if not self._password_hasher.verify_password(plain_password, hashed_password):
            raise InvalidCredentialsError()

    def _validate_user_exists(self, user: Any | None) -> None:
        """用户存在性校验。"""
        if user is None:
            raise InvalidCredentialsError()

    def _validate_user_status(self, user: Any) -> None:
        """账号状态放行校验——disabled 即签即拒（§3.2 / §4.3）。

        pending_review/rejected 放行（可登录见状态页，能力由 RBAC 守卫收敛）。
        """
        if user.status == AccountStatus.DISABLED:
            raise AccountDisabledError()

    def _validate_refresh_token(self, token: str) -> dict[str, Any]:
        """Refresh token 有效性校验（签名 + 有效期 + type）。"""
        payload: dict[str, Any] | None = self._token_manager.verify_refresh_token(token)
        if payload is None:
            raise TokenInvalidError(reason="token_invalid")
        return payload

    async def _validate_family_not_revoked(self, family_id: str) -> None:
        """家族吊销检查——logout/禁用/角色变更后旧家族即拒。"""
        if await self._token_blacklist.is_family_revoked(family_id):
            raise TokenInvalidError(reason="family_revoked")

    async def _validate_refresh_not_used(self, jti: str, family_id: str) -> None:
        """Refresh 复用检测——旧 token 再次出示判定泄露，吊销全家族（§5.2）。"""
        if await self._token_blacklist.is_refresh_used(jti):
            await self._token_blacklist.revoke_family(family_id)
            self._audit_token_reuse(family_id)
            raise TokenInvalidError(reason="token_reused")

    def _validate_register_result(self, result: Any) -> None:
        """后置校验——注册结果含非空 user_id。"""
        if result is None or not result.user_id:
            raise AuthInternalError("注册返回结果异常")

    def _validate_token_pair(self, result: Any) -> None:
        """后置校验——Token 对非空。"""
        if result is None or not result.access_token or not result.refresh_token:
            raise AuthInternalError("Token 签发返回异常")

    # ==================================================================
    # 辅助方法
    # ==================================================================

    @staticmethod
    def _extract_claim_unsafe(token: str, claim: str) -> str | None:
        """不验证签名地从 token 中提取指定 claim（登出流程，token 可能已过期）。"""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            payload_bytes = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
            payload: dict[str, Any] = json.loads(payload_bytes)
            value = payload.get(claim)
            return str(value) if value is not None else None
        except Exception:
            return None

    def _audit_log_async(self, user_id: str, phone: str, role: UserRole) -> None:
        """异步投递注册审计日志——基类默认空操作，子类可覆写注入 audit_logger。"""
        pass

    def _audit_token_reuse(self, family_id: str) -> None:
        """令牌复用检测安全审计事件——基类默认空操作，子类可覆写。"""
        pass


__all__ = ["AuthService"]
