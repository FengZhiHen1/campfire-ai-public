"""DEPLOY-05 环境配置管理的自定义异常层次 + PROF-05 ForbiddenAccess。

异常层次（配置相关）：
- ConfigError: 配置异常基类
- MissingRequiredFieldError: 必填配置项缺失
- ConfigFormatError: 配置项格式错误
- ConfigWarning: 生产环境安全告警（非阻断）

异常层次（鉴权相关）：
- ForbiddenAccess: 档案级访问权限拒绝异常（HTTP 403）
"""

from typing import Optional


class ConfigError(Exception):
    """配置异常基类。

    所有与配置加载、校验、分发相关的异常均继承自此基类。
    供下游模块通过 ``except ConfigError`` 统一捕获。
    """

    def __init__(self, message: str) -> None:
        self.message: str = message
        super().__init__(self.message)


class MissingRequiredFieldError(ConfigError):
    """必填配置字段缺失异常。

    系统启动时环境变量未设置或值为空时触发。
    一次性收集全部缺失字段名称并输出，触发后立即阻断服务启动（fail-fast）。
    """

    def __init__(self, message: str, missing_fields: list[str]) -> None:
        super().__init__(message)
        self.missing_fields: list[str] = missing_fields


class ConfigFormatError(ConfigError):
    """配置项格式错误异常。

    配置项已设置但值格式不合法时触发（如数据库连接串缺少端口、过期时间不是正整数等）。
    """

    def __init__(
        self,
        message: str,
        field_name: str,
        expected_format: str,
        received_value: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.field_name: str = field_name
        self.expected_format: str = expected_format
        self.received_value: Optional[str] = received_value


# ===========================================================================
# PROF-05 档案隐私控制 — ForbiddenAccess 异常
# ===========================================================================


class ForbiddenAccess(Exception):
    """档案级访问权限拒绝异常。

    当 PrivacyGuard.check_access() 返回 AccessDecision(allowed=False) 时，
    由 profile_service 抛出此异常。全局异常处理器捕获后返回 HTTP 403，
    响应体为 {"detail": "数据不存在"}。

    异常设计遵循静默拒绝策略——detail 使用泛化消息"数据不存在"，
    避免泄露档案存在性或权限结构信息。

    Attributes:
        status_code: HTTP 状态码，固定为 403。
        detail: 拒绝说明文案，固定为"数据不存在"。
    """

    def __init__(
        self,
        detail: str = "数据不存在",
    ) -> None:
        self.status_code: int = 403
        self.detail: str = detail
        super().__init__(self.detail)


class ProfileLimitExceededError(Exception):
    """档案数量超限异常。

    当家属账号下 active 状态的档案数量已达到上限（默认 5 个）时，
    创建新档案的请求抛出此异常。
    全局异常处理器捕获后返回 HTTP 409 Conflict。

    Attributes:
        status_code: HTTP 状态码，固定为 409。
        error_code: 机器可读的错误码，固定为 "PROFILE_LIMIT_EXCEEDED"。
        detail: 错误提示信息，包含已达上限说明和引导文案。
        current_count: 当前账号下的档案数量。
        max_allowed: 允许的档案数量上限。
    """

    def __init__(
        self,
        detail: str = (
            "您已达到单个账号最多 5 个档案的上限。"
            "如需为新的患者建档，可先删除一个不再需要的旧档案"
            "（删除操作不可恢复），或使用另一个家属账号创建。"
        ),
        current_count: int = 5,
        max_allowed: int = 5,
    ) -> None:
        self.status_code: int = 409
        self.error_code: str = "PROFILE_LIMIT_EXCEEDED"
        self.detail: str = detail
        self.current_count: int = current_count
        self.max_allowed: int = max_allowed
        super().__init__(self.detail)


class ProfileConflictError(Exception):
    """档案并发冲突异常。

    当乐观锁检测到 updated_at 时间戳不匹配时（即另一设备在当前请求
    读取后修改了同一档案），更新或删除操作抛出此异常。
    全局异常处理器捕获后返回 HTTP 409 Conflict。

    Attributes:
        status_code: HTTP 状态码，固定为 409。
        error_code: 机器可读的错误码，固定为 "PROFILE_CONFLICT"。
        detail: 错误提示信息，引导用户刷新后重试。
    """

    def __init__(
        self,
        detail: str = "档案数据已被其他设备修改，请刷新页面后重新操作。",
    ) -> None:
        self.status_code: int = 409
        self.error_code: str = "PROFILE_CONFLICT"
        self.detail: str = detail
        super().__init__(self.detail)


class ConfigWarning(UserWarning):
    """生产环境安全告警。

    在生产环境中检测到密钥类配置项来源于本地 .env 文件而非 KMS 注入时触发。
    使用 warnings.warn() 机制输出，不阻断启动。
    """

    def __init__(
        self,
        message: str,
        affected_fields: Optional[list[str]] = None,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.affected_fields: Optional[list[str]] = affected_fields
