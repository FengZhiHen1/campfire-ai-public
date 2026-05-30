# @contract
"""py-auth 行为契约 — ABC 模板方法骨架。

定义认证域的四个核心契约，实现者只能覆写 _do_ 前缀的钩子:

1. PasswordHasher: 密码哈希与校验（前置: 长度校验 → _do_hash/_do_verify → 后置: 格式校验）
2. TokenManager: JWT 签发与校验（前置: 必填字段校验 → _do_create/_do_verify → 后置: 输出校验）
3. TokenBlacklist: Token 失效管理（降级策略: fail-open，Redis 不可用时放行）
4. RBACGuard: 角色权限判定（前置: 用户存在性校验 → _do_authorize → 后置: 审计日志）

契约即代码骨架——@final 公共入口不可覆写，实现者填 _do_ 钩子。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, final

from py_auth.types import HasRoles
from py_logger import logger


# ============================================================================
# PasswordHasher — 密码哈希契约
# ============================================================================


class PasswordHasher(ABC):
    """密码哈希与校验契约。

    实现者只能覆写 _do_ 前缀的钩子。
    外部调用者通过 @final hash_password / verify_password 进入，
    无法绕过长度校验和格式校验。
    """

    # === 常量 ===

    _MIN_PASSWORD_LENGTH: int = 8
    _MAX_PASSWORD_LENGTH: int = 64

    # === @final 公共方法 ===

    @final
    def hash_password(self, plain_password: str) -> str:
        """对明文密码执行不可逆哈希。

        前置校验 → _do_hash → 后置校验。
        此方法不可覆写（@final）。

        前置:
          - plain_password 非空字符串
          - 长度在 [8, 64] 范围内
        后置:
          - 返回以 $2b$ 或 $2a$ 开头的 bcrypt 哈希串
          - 每次调用产生不同哈希值（随机 salt）
        输入约束:
          - plain_password: 明文密码原文
        输出约束:
          - str: bcrypt 哈希字符串
        异常:
          - ValueError: 密码长度超出范围
          - HashingError: bcrypt 引擎内部错误
        Side Effects:
          - 无。纯函数，无 I/O 操作。
        """
        self._validate_password_length(plain_password)
        hashed = self._do_hash(plain_password)
        self._validate_hash_output(hashed)
        return hashed

    @final
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """验证明文密码是否匹配已存储的哈希值。

        前置校验 → _do_verify → 返回结果。

        前置:
          - plain_password 长度在 [8, 64]
          - hashed_password 以 $2b$ 或 $2a$ 开头
        后置:
          - 返回 bool 类型
        输入约束:
          - plain_password: 待验证的明文密码
          - hashed_password: 已存储的 bcrypt 哈希值
        输出约束:
          - bool: True 匹配，False 不匹配
        异常:
          - ValueError: 输入格式不合法
          - HashingError: bcrypt 引擎内部错误
        Side Effects:
          - 无。纯函数，无 I/O 操作。
        """
        self._validate_password_length(plain_password)
        self._validate_hash_format(hashed_password)
        return self._do_verify(plain_password, hashed_password)

    # === @abstractmethod 钩子 ===

    @abstractmethod
    def _do_hash(self, plain_password: str) -> str:
        """执行 bcrypt 哈希计算。

        实现者在此填写实际的哈希逻辑。
        前置校验（长度/非空）已由 @final hash_password 处理，实现者无需关心。

        输入约束:
          - plain_password 已通过 _validate_password_length 校验
        输出约束:
          - 返回格式为 $2b$<rounds>$<salt><hash> 的字符串
        异常:
          - HashingError: bcrypt 计算失败
        """
        ...

    @abstractmethod
    def _do_verify(self, plain_password: str, hashed_password: str) -> bool:
        """执行密码比对校验。

        前置校验（长度/格式）已由 @final verify_password 处理，实现者无需关心。

        输入约束:
          - plain_password 和 hashed_password 已通过前置校验
        输出约束:
          - bool: True 表示匹配
        异常:
          - HashingError: bcrypt 校验过程出错
        """
        ...

    # === 校验器 ===

    def _validate_password_length(self, plain_password: str) -> None:
        """基线密码长度校验。

        Raises:
            ValueError: 密码长度不在 [8, 64] 范围内。
        """
        if not isinstance(plain_password, str):
            raise ValueError(
                f"密码必须是 str 类型，实际为 {type(plain_password).__name__}"
            )
        length = len(plain_password)
        if length < self._MIN_PASSWORD_LENGTH or length > self._MAX_PASSWORD_LENGTH:
            raise ValueError(
                f"密码长度必须在 {self._MIN_PASSWORD_LENGTH}-{self._MAX_PASSWORD_LENGTH} "
                f"之间，当前长度为 {length}"
            )

    def _validate_hash_format(self, hashed_password: str) -> None:
        """基线哈希格式校验。

        Raises:
            ValueError: 哈希串不是以 $2b$ 或 $2a$ 开头的合法 bcrypt 格式。
        """
        if not isinstance(hashed_password, str):
            raise ValueError(
                f"hashed_password 必须是 str 类型，实际为 {type(hashed_password).__name__}"
            )
        if not hashed_password.startswith("$2b$") and not hashed_password.startswith(
            "$2a$"
        ):
            raise ValueError(
                "hashed_password 格式不合法，必须以 $2b$ 或 $2a$ 开头"
            )

    def _validate_hash_output(self, hashed: str) -> None:
        """基线后置校验——确保 _do_hash 返回值格式正确。

        Raises:
            RuntimeError: 哈希输出格式不合法（内部逻辑错误）。
        """
        if not hashed or not isinstance(hashed, str):
            raise RuntimeError(f"{self.__class__.__name__}._do_hash 返回了无效结果")
        if not hashed.startswith("$2b$") and not hashed.startswith("$2a$"):
            raise RuntimeError(
                f"{self.__class__.__name__}._do_hash 输出格式不合法: "
                f"必须以 $2b$ 或 $2a$ 开头"
            )


# ============================================================================
# TokenManager — JWT Token 契约
# ============================================================================


class TokenManager(ABC):
    """JWT Token 签发与校验契约。

    实现者只能覆写 _do_ 前缀的钩子。
    外部调用者通过 @final create_access_token / verify_token 等方法进入，
    无法绕过必填字段校验和 Token 类型检查。
    """

    # === @final 公共方法 ===

    @final
    def create_access_token(self, data: dict[str, Any]) -> str:
        """签发访问令牌（15 分钟有效，type=access）。

        前置校验 → _do_create_token → 后置校验。

        前置:
          - data 必须包含 "sub" (用户ID) 和 "roles" (角色列表)
        后置:
          - 返回有效的 JWT 字符串（三段 Base64 编码）
        输入约束:
          - data["sub"]: str 类型，用户唯一标识
          - data["roles"]: list 类型，角色枚举值列表
        输出约束:
          - str: JWT access token
        异常:
          - ValueError: data 缺少必填字段
          - TokenCreationError: JWT 签发失败
        Side Effects:
          - 无。token 本身不持久化（由调用方决定存储策略）。
        """
        self._validate_token_data(data)
        token = self._do_create_token(data, "access", self._ACCESS_TTL_SECONDS)
        self._validate_token_output(token)
        logger.debug(
            "py-auth",
            "access_token_created",
            op_type="认证",
            extra={"sub": str(data.get("sub", ""))[:8] + "..."},
        )
        return token

    @final
    def create_refresh_token(self, data: dict[str, Any]) -> str:
        """签发续期令牌（7 天有效，type=refresh）。

        前置校验 → _do_create_token → 后置校验。

        前置:
          - data 必须包含 "sub" 和 "roles"
        后置:
          - 返回有效的 JWT 字符串
        输入约束:
          - 与 create_access_token 相同
        输出约束:
          - str: JWT refresh token
        异常:
          - ValueError: data 缺少必填字段
          - TokenCreationError: JWT 签发失败
        Side Effects:
          - 无。
        """
        self._validate_token_data(data)
        token = self._do_create_token(data, "refresh", self._REFRESH_TTL_SECONDS)
        self._validate_token_output(token)
        logger.debug(
            "py-auth",
            "refresh_token_created",
            op_type="认证",
            extra={"sub": str(data.get("sub", ""))[:8] + "..."},
        )
        return token

    @final
    def verify_token(self, token: str) -> dict[str, Any] | None:
        """校验 Token 签名和有效期（不检查 type）。

        校验流程:
        1. 解码 header 提取 kid
        2. 根据 kid 选择对应版本密钥
        3. 签名校验 + exp 过期检查

        前置:
          - token 为非空字符串
        后置:
          - 签名有效 → 返回 payload dict
          - 签名无效/过期 → 返回 None
        输入约束:
          - token: JWT 字符串
        输出约束:
          - dict | None: 解码后的 payload，校验失败返回 None
        异常:
          - TokenDecodeError: Token 格式无效（非 JWT 格式）
        Side Effects:
          - 无。
        """
        if not token or not isinstance(token, str):
            return None
        return self._do_verify_token(token)

    @final
    def verify_access_token(self, token: str) -> dict[str, Any] | None:
        """校验访问令牌：签名 + 有效期 + type == access。

        在 verify_token 基础上叠加 type 检查。
        """
        payload = self.verify_token(token)
        if payload is None:
            return None
        if payload.get("type") != "access":
            return None
        return payload

    @final
    def verify_refresh_token(self, token: str) -> dict[str, Any] | None:
        """校验续期令牌：签名 + 有效期 + type == refresh。"""
        payload = self.verify_token(token)
        if payload is None:
            return None
        if payload.get("type") != "refresh":
            return None
        return payload

    # === @abstractmethod 钩子 ===

    @abstractmethod
    def _do_create_token(
        self, data: dict[str, Any], token_type: str, ttl_seconds: int
    ) -> str:
        """执行 JWT Token 签发。

        实现者在此填写实际的 JWT 编码逻辑。
        必填字段校验已由 @final 创建方法处理，实现者无需关心。

        输入约束:
          - data 已通过 _validate_token_data 校验
          - token_type: "access" 或 "refresh"
          - ttl_seconds: Token 有效期（秒）
        输出约束:
          - str: 编码后的 JWT 字符串
        异常:
          - TokenCreationError: JWT 签发失败
        """
        ...

    @abstractmethod
    def _do_verify_token(self, token: str) -> dict[str, Any] | None:
        """执行 JWT 签名校验和过期检查。

        实现者在此填写实际的 JWT 解码逻辑。
        格式校验已由 @final verify_token 处理。

        输入约束:
          - token 是非空字符串
        输出约束:
          - dict | None: 校验通过返回 payload，失败返回 None
        异常:
          - TokenDecodeError: Token header 格式损坏
        """
        ...

    # === 校验器 ===

    _ACCESS_TTL_SECONDS: int = 15 * 60  # 15 分钟
    _REFRESH_TTL_SECONDS: int = 7 * 24 * 3600  # 7 天

    def _validate_token_data(self, data: dict[str, Any]) -> None:
        """基线 Token 数据校验——确保必填字段存在。

        Raises:
            ValueError: data 缺少 "sub" 或 "roles" 字段。
        """
        if "sub" not in data:
            raise ValueError("data 必须包含 sub 字段")
        if "roles" not in data:
            raise ValueError("data 必须包含 roles 字段")

    def _validate_token_output(self, token: str) -> None:
        """基线后置校验——确保 _do_create_token 返回非空字符串。

        Raises:
            RuntimeError: Token 签发返回空值。
        """
        if not token:
            raise RuntimeError(
                f"{self.__class__.__name__}._do_create_token 返回了空 Token"
            )


# ============================================================================
# TokenBlacklist — Token 失效管理契约
# ============================================================================


class TokenBlacklist(ABC):
    """Token 失效管理契约。

    两层防护:
    1. 角色变更撤销: add_to_blacklist / is_blacklisted（TTL=900s）
    2. Refresh Token 单次使用: mark_refresh_used / is_refresh_used（TTL=7d）

    降级策略 (fail-open): 存储不可用时放行，记录 warning 日志。
    实现者只能覆写 _do_ 前缀的钩子。
    """

    # === 常量 ===

    _BLACKLIST_TTL: int = 900  # Access Token 有效期 15 分钟
    _REFRESH_USED_TTL: int = 7 * 24 * 3600  # Refresh Token 有效期 7 天

    # === @final 公共方法 ===

    @final
    async def add_to_blacklist(self, jti: str) -> None:
        """将被撤销 Token 的 jti 加入黑名单。

        在角色变更时调用，使旧 Token 立即失效。

        前置:
          - jti 为非空字符串
        后置:
          - 存储不可用时静默降级（fail-open），记录 warning 日志
        输入约束:
          - jti: JWT Token 的 jti claim，UUID v4 格式
        输出约束:
          - None
        异常:
          - 不抛异常——降级策略为 fail-open
        Side Effects:
          - 向持久化存储执行写入操作
        """
        if not jti:
            logger.warning(
                "py-auth",
                "黑名单写入跳过：jti 为空",
                op_type="权限拒绝",
            )
            return
        try:
            await self._do_add_blacklist(jti)
        except Exception as exc:
            logger.warning(
                "py-auth",
                "黑名单写入失败（fail-open）",
                op_type="权限拒绝",
                extra={"jti": jti[:20] + "...", "strategy": "fail_open", "error": str(exc)},
            )

    @final
    async def is_blacklisted(self, jti: str) -> bool:
        """查询 jti 是否在黑名单中。

        若命中 → 返回 True（应拒绝请求）。
        存储不可用时 → 返回 False（fail-open 放行）。

        输入约束:
          - jti: 非空字符串
        输出约束:
          - bool: True 在黑名单中，False 不在或存储不可用
        Side Effects:
          - 向持久化存储执行只读查询
        """
        if not jti:
            return False
        try:
            return await self._do_check_blacklist(jti)
        except Exception as exc:
            logger.warning(
                "py-auth",
                "黑名单查询降级（fail-open）",
                op_type="权限拒绝",
                extra={"jti": jti[:20] + "...", "strategy": "fail_open", "error": str(exc)},
            )
            return False

    @final
    async def mark_refresh_used(self, jti: str) -> None:
        """将续期令牌标记为已使用（防止重放攻击）。

        前置:
          - jti 为非空字符串
        后置:
          - 存储不可用时静默降级
        Side Effects:
          - 向持久化存储写入标记
        """
        if not jti:
            return
        try:
            await self._do_mark_refresh(jti)
        except Exception as exc:
            logger.warning(
                "py-auth",
                "Refresh 标记写入失败（fail-open）",
                op_type="认证",
                extra={"jti": jti[:20] + "...", "strategy": "fail_open", "error": str(exc)},
            )

    @final
    async def is_refresh_used(self, jti: str) -> bool:
        """查询续期令牌是否已被使用过。

        存储不可用时返回 False（fail-open）。
        """
        if not jti:
            return False
        try:
            return await self._do_check_refresh(jti)
        except Exception as exc:
            logger.warning(
                "py-auth",
                "Refresh 查询降级（fail-open）",
                op_type="认证",
                extra={"jti": jti[:20] + "...", "strategy": "fail_open", "error": str(exc)},
            )
            return False

    # === @abstractmethod 钩子 ===

    @abstractmethod
    async def _do_add_blacklist(self, jti: str) -> None:
        """执行黑名单写入到持久化存储。

        实现者在此填写实际的存储写入逻辑。
        jti 非空校验和 fail-open 降级已由 @final 方法处理。

        Side Effects:
          - 写入 Key: token_blacklist:{jti}，TTL=900s
        """
        ...

    @abstractmethod
    async def _do_check_blacklist(self, jti: str) -> bool:
        """查询持久化存储中的黑名单记录。

        实现者在此填写实际的存储查询逻辑。
        """
        ...

    @abstractmethod
    async def _do_mark_refresh(self, jti: str) -> None:
        """标记 Refresh Token 已使用。

        Side Effects:
          - 写入 Key: refresh_used:{jti}，TTL=7d
        """
        ...

    @abstractmethod
    async def _do_check_refresh(self, jti: str) -> bool:
        """查询 Refresh Token 是否已被使用。"""
        ...


# ============================================================================
# RBACGuard — 角色权限判定契约
# ============================================================================


class RBACGuard(ABC):
    """基于角色的权限判定契约。

    实现者只能覆写 _do_authorize 钩子。
    外部调用者通过 @final authorize 进入，无法绕过用户存在性校验。

    权限判定模式（互斥）:
    - min_level: 层级累加模式，用户最高角色层级 >= 此值时放行
    - exact_roles: 精确模式，用户任一角色在此白名单内时放行
    - 两者均为 None: 默认放行（任何已认证用户）
    """

    _LOG_PERMISSION_DENIED_EVENT: str = "permission_denied"

    @final
    def authorize(
        self,
        user: HasRoles,
        min_level: Any | None = None,
        exact_roles: list[Any] | None = None,
    ) -> None:
        """校验用户是否有权限执行操作。

        前置校验 → _do_authorize → 后置处理。

        前置:
          - user 对象存在且包含 roles 属性
          - min_level 和 exact_roles 互斥（不同时非空）
        后置:
          - 权限不足时抛出 PermissionDeniedError
          - 通过时静默返回
        输入约束:
          - user: 含 roles 属性的用户对象
          - min_level: 最低角色层级（与 exact_roles 互斥）
          - exact_roles: 角色白名单（与 min_level 互斥）
        异常:
          - PermissionDeniedError: 用户不存在、无角色或权限不足
          - ValueError: min_level 和 exact_roles 同时非空
        Side Effects:
          - 权限拒绝时记录结构化 warning 日志
        """
        self._validate_authorize_input(user, min_level, exact_roles)
        denied = self._do_authorize(user, min_level, exact_roles)

        if denied:
            self._log_denial(user, min_level, exact_roles)
            raise PermissionDeniedError(
                "当前角色无权执行此操作，如需权限请联系管理员",
                detail={
                    "user_roles": [str(r) for r in getattr(user, "roles", [])],
                    "required": (
                        str(min_level)
                        if min_level is not None
                        else [str(r) for r in exact_roles]
                        if exact_roles is not None
                        else None
                    ),
                },
            )

    # === @abstractmethod 钩子 ===

    @abstractmethod
    def _do_authorize(
        self,
        user: HasRoles,
        min_level: Any | None,
        exact_roles: list[Any] | None,
    ) -> bool:
        """执行权限判定逻辑。

        实现者在此填写实际的权限判断。
        用户存在性和互斥校验已由 @final authorize 处理。

        输入约束:
          - user 已通过 _validate_authorize_input 校验
          - min_level 和 exact_roles 不同时非空
        输出约束:
          - bool: True 表示应拒绝（权限不足），False 表示放行
        """
        ...

    # === 校验器 ===

    def _validate_authorize_input(
        self,
        user: HasRoles,
        min_level: Any | None,
        exact_roles: list[Any] | None,
    ) -> None:
        """基线授权输入校验。

        Raises:
            PermissionDeniedError: user 为 None、无 roles 属性或 roles 为空。
            ValueError: min_level 和 exact_roles 同时非空。
        """
        if user is None:
            raise PermissionDeniedError(
                "未登录或用户信息缺失",
                reason="user_missing",
            )
        roles = getattr(user, "roles", None)
        if roles is None or len(roles) == 0:
            raise PermissionDeniedError(
                "角色信息缺失",
                reason="no_roles",
            )
        if min_level is not None and exact_roles is not None:
            raise ValueError("min_level 和 exact_roles 参数不能同时使用")

    # === 内部 ===

    def _log_denial(
        self,
        user: HasRoles,
        min_level: Any | None,
        exact_roles: list[Any] | None,
    ) -> None:
        """记录权限拒绝日志。"""
        try:
            logger.warning(
                "py-auth",
                self._LOG_PERMISSION_DENIED_EVENT,
                op_type="权限拒绝",
                extra={
                    "user_id": getattr(user, "id", None),
                    "user_roles": [str(r) for r in getattr(user, "roles", [])],
                    "required": (
                        str(min_level)
                        if min_level is not None
                        else [str(r) for r in exact_roles]
                        if exact_roles is not None
                        else None
                    ),
                },
            )
        except Exception:
            pass  # 日志失败不影响权限拒绝


# ============================================================================
# 异常映射（避免循环导入）
# ============================================================================

from py_auth.exceptions import PermissionDeniedError  # noqa: E402

__all__ = [
    "PasswordHasher",
    "TokenManager",
    "TokenBlacklist",
    "RBACGuard",
]
