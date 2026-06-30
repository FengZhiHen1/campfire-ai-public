# @contract
"""api-server 认证服务行为契约 — ABC 模板方法骨架。

模块: app.modules.auth.auth_contract
职责: 定义认证服务的业务编排契约。覆盖 AUTH-01（注册）、AUTH-02（登录）、
      AUTH-03（续期）和登出四个核心流程。每个 @final 公共入口强制执行
      前置校验 → _do_ 钩子 → 后置校验三步流程，实现者只能覆写 _do_ 钩子。

数据来源:
  - py_auth.auth_contract.PasswordHasher: MUST — 密码哈希与校验，不可绕过 bcrypt
  - py_auth.auth_contract.TokenManager: MUST — JWT 签发与校验，不可绕过 HS256
  - py_auth.auth_contract.TokenBlacklist: MUST — Token 失效管理，不可绕过 Redis 黑名单
  - py_db.repositories.user_repository.UserRepository: MUST — 用户持久化查询
  - py_schemas.auth (RegisterRequest, LoginRequest, TokenResponse, RefreshRequest): MUST — 数据契约
  - py_logger: SHOULD — 结构化审计日志

边界:
  - 依赖: py_auth, py_db, py_schemas, py_logger, sqlalchemy (AsyncSession)
  - 被依赖: app.modules.auth.routes (FastAPI 路由层)

禁止行为:
  - 禁止在 @final 方法中直接调用 py_auth 便捷函数（必须走注入的契约实例）
  - 禁止在 _do_ 钩子中直接操作 FastAPI HTTPException（由 @final 方法统一转换异常）
  - 禁止在 Service 层直接访问 HTTP 请求对象（Request 对象只存在于路由层）
  - 禁止实现者覆写 @final 方法
  - 禁止在 register 流程中同步等待审计日志写入（必须使用 asyncio.create_task 异步投递）
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, final

from py_schemas.auth import UserRole

from app.modules.auth.exceptions import (
    AuthInternalError,
    DuplicateUserError,
    InvalidCredentialsError,
    PasswordComplexityError,
    RealNameRequiredError,
    TokenInvalidError,
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
r"""密码复杂度正则：至少包含一个小写字母、一个大写字母、一个数字，且至少 8 位。"""


# ============================================================================
# AuthService — 认证服务契约
# ============================================================================


class AuthService(ABC):
    """认证服务契约 — 业务编排层 ABC。

    实现者只能覆写 _do_ 前缀的钩子。
    外部调用者通过 @final 方法进入，无法绕过前置校验和后置处理。

    依赖注入（通过 __init__ 传入）:
      - password_hasher: PasswordHasher 契约实现（py_auth）
      - token_manager: TokenManager 契约实现（py_auth）
      - token_blacklist: TokenBlacklist 契约实现（py_auth）
      - user_repo: UserRepository 实例（py_db）
    """

    def __init__(
        self,
        password_hasher: "PasswordHasherContract",
        token_manager: "TokenManagerContract",
        token_blacklist: "TokenBlacklistContract",
        user_repo: "UserRepository",
    ) -> None:
        self._password_hasher = password_hasher
        self._token_manager = token_manager
        self._token_blacklist = token_blacklist
        self._user_repo = user_repo

    # ======================================================================
    # AUTH-01 用户注册
    # ======================================================================

    @final
    async def register(self, request: "RegisterRequest", session: Any) -> "RegisterResponse":
        """用户注册 — 7 步校验流程编排。

        前置:
          - request 已通过 Pydantic Field 级校验（路由层 Depends 完成）
          - session 是活跃的 AsyncSession（请求级依赖注入）
          - request.role 仅允许 family/teacher/expert
        后置:
          - 成功: 用户持久化到 users 表，审计日志异步投递
          - 失败: 抛出 AuthServiceError 子类异常
        输入约束:
          - request: RegisterRequest Pydantic 模型实例
          - session: sqlalchemy.ext.asyncio.AsyncSession
        输出约束:
          - RegisterResponse: result="success", user_id=UUIDv4 字符串
        异常:
          - PasswordComplexityError: 密码复杂度不足
          - RealNameRequiredError: 专家角色缺少 real_name
          - DuplicateUserError: 用户名或手机号重复
          - AuthInternalError: 密码哈希失败或数据库操作失败
        Side Effects:
          - 写入 users 表（同步等待）
          - 异步投递审计日志（不阻塞响应）
        """
        # 步骤 1: 密码复杂度校验（Pydantic Field 校验由路由层完成）
        self._validate_password_complexity(request.password)
        # 步骤 2: 专家角色 real_name 必填校验
        self._validate_expert_real_name(request.role, request.real_name)
        # 步骤 3: 用户名 + 手机号唯一性校验
        await self._validate_uniqueness(request.username, request.phone, session)
        # 步骤 4: 密码哈希
        hashed = self._do_hash_password(request.password)
        # 步骤 5: 数据写入
        result = await self._do_register(request, hashed, session)
        # 后置: 结果校验 + 审计日志异步投递
        self._validate_register_result(result)
        self._audit_log_async(result.user_id, request.username, request.role)
        return result

    # ======================================================================
    # AUTH-02 用户登录
    # ======================================================================

    @final
    async def login(self, request: "LoginRequest", session: Any) -> "TokenResponse":
        """用户登录 — 凭证校验 + JWT 签发。

        前置:
          - request 已通过 Pydantic 校验
          - session 是活跃的 AsyncSession
        后置:
          - 成功: 返回 access_token + refresh_token + expires_in
          - 失败: 抛出 InvalidCredentialsError
        输入约束:
          - request: LoginRequest Pydantic 模型实例
          - session: AsyncSession
        输出约束:
          - TokenResponse: access_token, refresh_token, token_type="Bearer"
        异常:
          - InvalidCredentialsError: 用户名不存在或密码错误（不区分具体原因）
          - AuthInternalError: JWT 签发失败
        Side Effects:
          - 无持久化写入（Token 本身不存储）
        """
        # 前置: 查询用户
        user = await self._fetch_user(request.username, session)
        # 前置: 用户存在性校验（不区分"不存在"和"密码错"——防枚举攻击）
        self._validate_user_exists(user)
        assert user is not None  # _validate_user_exists 保证非 None
        # 前置: 密码校验
        self._validate_password_match(request.password, user.password_hash)
        # 后置: JWT 签发
        result = self._do_login(user)
        self._validate_login_result(result)
        return result

    # ======================================================================
    # AUTH-03 Token 续期
    # ======================================================================

    @final
    async def refresh_token(self, request: "RefreshRequest", session: Any) -> "TokenResponse":
        """Token 续期 — 校验 refresh token + 轮换。

        前置:
          - request.refresh_token 为非空 JWT 字符串
          - session 是活跃的 AsyncSession
        后置:
          - 旧 refresh token 标记为已使用（防重放攻击）
          - 返回新的 TokenResponse
        输入约束:
          - request: RefreshRequest Pydantic 模型实例
          - session: AsyncSession
        输出约束:
          - TokenResponse: 新的 access_token + refresh_token
        异常:
          - TokenInvalidError: refresh token 无效、过期或已被使用
          - AuthInternalError: JWT 签发失败
        Side Effects:
          - 旧 refresh token 的 jti 标记为已使用（Redis 写入）
        """
        # 前置: 校验 refresh token 签名和类型
        payload = self._validate_refresh_token(request.refresh_token)
        # 前置: 防重放检测
        await self._validate_refresh_not_used(payload["jti"])
        # 执行: 标记旧 token → 签发新 token 对
        result = await self._do_refresh(payload, request.refresh_token)
        # 后置: 校验新 token 对非空
        self._validate_refresh_output(result)
        return result

    # ======================================================================
    # 登出
    # ======================================================================

    @final
    async def logout(self, access_token: str, refresh_token: str) -> None:
        """登出 — Token 失效。

        前置:
          - access_token 和 refresh_token 为非空 JWT 字符串
        后置:
          - access token 的 jti 加入黑名单（TTL=900s）
          - refresh token 的 jti 标记为已使用（TTL=7d）
        输入约束:
          - access_token: JWT access token
          - refresh_token: JWT refresh token
        异常:
          - 不抛异常——黑名单写入失败采用 fail-open 降级策略
        Side Effects:
          - Redis 写入（黑名单 + refresh 标记）
        """
        access_jti = self._extract_jti_unsafe(access_token)
        refresh_jti = self._extract_jti_unsafe(refresh_token)
        await self._do_logout(access_jti, refresh_jti)

    # ======================================================================
    # @abstractmethod 钩子 — 实现者填以下方法
    # ======================================================================

    @abstractmethod
    def _do_hash_password(self, plain_password: str) -> str:
        """执行 bcrypt 密码哈希。

        实现者在此调用注入的 self._password_hasher.hash_password()。
        不需要关心密码复杂度——@final register 已通过 _validate_password_complexity 处理。
        不需要关心密码长度——PasswordHasher 契约内置长度校验。

        输入约束:
          - plain_password 已通过复杂度正则和 Pydantic min_length=8 校验
        输出约束:
          - bcrypt 哈希字符串 ($2b$ 或 $2a$ 开头)
        异常:
          - HashingError: bcrypt 引擎内部错误（由 @final 转换为 AuthInternalError）
        """
        ...

    @abstractmethod
    async def _do_register(self, request: "RegisterRequest", hashed_password: str, session: Any) -> "RegisterResponse":
        """执行用户数据持久化。

        实现者在此构造 User ORM 对象并调用 self._user_repo.create()。
        不需要关心密码复杂度、唯一性校验、专家角色校验——@final register 已全部处理。

        输入约束:
          - request 所有字段已通过校验
          - hashed_password 是合法的 bcrypt 哈希串
        输出约束:
          - RegisterResponse 实例
        异常:
          - IntegrityError 由实现者在 try/except 中捕获并转换为 DuplicateUserError
        """
        ...

    async def _fetch_user(self, username: str, session: Any) -> Any | None:
        """查询用户——大小写不敏感用户名匹配。

        调用注入的 self._user_repo.find_by_username_lower()。
        子类可覆写以自定义查询逻辑。

        输入约束:
          - username 已通过 Pydantic 校验
        输出约束:
          - User ORM 实例或 None
        """
        return await self._user_repo.find_by_username_lower(session, username)

    @abstractmethod
    def _do_login(self, user: Any) -> "TokenResponse":
        """执行 JWT Token 对签发。

        实现者在此调用:
        1. self._token_manager.create_access_token(data)
        2. self._token_manager.create_refresh_token(data)

        不需要关心用户存在性和密码正确性——@final login 已校验。

        输入约束:
          - user 是已通过认证的 User ORM 实例（id, username, role 均非空）
        输出约束:
          - TokenResponse 实例
        异常:
          - TokenCreationError 由 @final 转换为 AuthInternalError
        """
        ...

    @abstractmethod
    async def _do_refresh(self, payload: dict[str, Any], old_refresh_token: str) -> "TokenResponse":
        """执行 Token 轮换——标记旧 token + 签发新 token 对。

        实现者在此:
        1. 调用 self._token_blacklist.mark_refresh_used(payload["jti"])
        2. 调用 self._token_manager.create_access_token() 和 create_refresh_token()

        不需要关心 refresh token 有效性校验——@final refresh_token 已处理。
        不需要关心重放检测——@final refresh_token 已处理。

        输入约束:
          - payload 是通过校验的 refresh token payload（含 sub, roles, jti）
        输出约束:
          - TokenResponse 实例
        """
        ...

    @abstractmethod
    async def _do_logout(self, access_jti: str | None, refresh_jti: str | None) -> None:
        """执行 Token 失效操作。

        实现者在此:
        1. 若 access_jti 非空 → 调用 self._token_blacklist.add_to_blacklist(access_jti)
        2. 若 refresh_jti 非空 → 调用 self._token_blacklist.mark_refresh_used(refresh_jti)

        不需要关心 fail-open 降级——TokenBlacklist 契约内置降级策略。

        输入约束:
          - access_jti 和 refresh_jti 可能为 None（token 格式损坏无法提取 jti 时）
        """
        ...

    # ======================================================================
    # 校验器 — 子类可通过 super() 叠加业务级校验
    # ======================================================================

    def _validate_password_complexity(self, password: str) -> None:
        """密码复杂度校验——必须同时包含大小写字母和数字，至少 8 位。

        Raises:
            PasswordComplexityError: 复杂度不足。
        """
        if not _PASSWORD_COMPLEXITY_REGEX.match(password):
            raise PasswordComplexityError()

    def _validate_expert_real_name(self, role: UserRole, real_name: str | None) -> None:
        """专家角色 real_name 必填校验。

        Raises:
            RealNameRequiredError: 专家角色缺少 real_name。
        """
        if role == UserRole.EXPERT and not real_name:
            raise RealNameRequiredError()

    async def _validate_uniqueness(self, username: str, phone: str, session: Any) -> None:
        """用户名和手机号唯一性校验。

        分别查询用户名和手机号是否存在，精确区分冲突类型。

        Raises:
            DuplicateUserError: 用户名或手机号重复，code 精确区分。
        """
        existing_user = await self._user_repo.find_by_username_lower(session, username)
        if existing_user is not None:
            raise DuplicateUserError(
                code="DUPLICATE_USERNAME",
                message="该用户名已被注册",
            )
        existing_phone = await self._user_repo.find_by_phone(session, phone)
        if existing_phone is not None:
            raise DuplicateUserError(
                code="DUPLICATE_PHONE",
                message="该手机号已被注册",
            )

    def _validate_user_exists(self, user: Any | None) -> None:
        """用户存在性校验——login 流程前置。

        不区分"用户不存在"和"密码错误"——统一抛出 InvalidCredentialsError，
        防止攻击者通过错误消息差异枚举有效用户名。

        Raises:
            InvalidCredentialsError: 用户名或密码错误。
        """
        if user is None:
            raise InvalidCredentialsError()

    def _validate_password_match(self, plain_password: str, hashed_password: str) -> None:
        """密码匹配校验——login 流程前置。

        通过注入的 password_hasher 执行 bcrypt 比对。
        密码不匹配时抛出与"用户不存在"完全相同的异常。

        Raises:
            InvalidCredentialsError: 密码不匹配。
        """
        if not self._password_hasher.verify_password(plain_password, hashed_password):
            raise InvalidCredentialsError()

    def _validate_refresh_token(self, token: str) -> dict[str, Any]:
        """Refresh token 有效性校验——续期流程前置。

        校验签名 + 有效期 + type == "refresh"。

        Raises:
            TokenInvalidError: token 无效、过期或类型不是 refresh。

        Returns:
            dict: 校验通过后的 token payload。
        """
        payload: dict[str, Any] | None = self._token_manager.verify_refresh_token(token)
        if payload is None:
            raise TokenInvalidError(reason="token_invalid")
        return payload

    async def _validate_refresh_not_used(self, jti: str) -> None:
        """Refresh token 重放检测——续期流程前置。

        查询 Redis 黑名单中该 jti 是否已被标记为使用过。
        若已使用 → 可能的 token 盗窃事件，拒绝续期。

        Raises:
            TokenInvalidError: refresh token 已被使用（reason=token_reused）。
        """
        was_used = await self._token_blacklist.is_refresh_used(jti)
        if was_used:
            raise TokenInvalidError(reason="token_reused")

    def _validate_login_result(self, result: Any) -> None:
        """后置校验——确保登录返回的 TokenResponse 非空且含 access_token。

        Raises:
            AuthInternalError: 登录返回结果异常。
        """
        if result is None or not result.access_token:
            raise AuthInternalError("登录返回结果异常")

    def _validate_register_result(self, result: Any) -> None:
        """后置校验——确保注册结果包含非空 user_id。

        Raises:
            AuthInternalError: 注册返回结果缺少 user_id。
        """
        if result is None or not result.user_id:
            raise AuthInternalError("注册返回结果异常")

    def _validate_refresh_output(self, result: Any) -> None:
        """后置校验——确保续期返回的 TokenResponse 非空。

        Raises:
            AuthInternalError: Token 续期返回空结果。
        """
        if result is None:
            raise AuthInternalError("Token 续期返回异常")

    # ======================================================================
    # 辅助方法
    # ======================================================================

    @staticmethod
    def _extract_jti_unsafe(token: str) -> str | None:
        """不验证签名地从 token 中提取 jti claim。

        用于登出流程——即使 token 已过期也需要提取 jti 以写入黑名单。
        通过 base64 解码 payload 段实现，不调用签名校验。

        Args:
            token: JWT 字符串（可能已过期或签名无效）。

        Returns:
            jti 字符串（提取成功）或 None（token 格式损坏）。
        """
        import base64
        import json

        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            # 解码 payload 段（不校验签名）
            payload_bytes = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
            payload: dict[str, Any] = json.loads(payload_bytes)
            return payload.get("jti")
        except Exception:
            return None

    def _audit_log_async(self, user_id: str, username: str, role: UserRole) -> None:
        """异步投递审计日志——不阻塞注册响应。

        基类默认实现为空操作。子类可覆写以注入实际的 audit_logger 实例。
        注意：不是 _do_ 前缀——这不是抽象钩子，是可选的覆写点。

        实现者应使用 asyncio.create_task + asyncio.to_thread 投递日志，
        失败时静默记录 warning，不中断用户响应。
        """
        pass


__all__ = ["AuthService"]
