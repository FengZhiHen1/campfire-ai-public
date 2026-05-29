"""py-config — 全局配置管理共享包。

提供 get_settings() 工厂函数作为全局配置单例获取入口。
首次调用时从环境变量和 .env 文件加载并校验全部配置字段，
校验失败时进程以 sys.exit(1) 终止。

架构：
- config_contract.py: BaseConfigLoader ABC（契约骨架）
- config_loader.py: AppSettingsLoader（实现契约）
- config.py: AppSettings（pydantic-settings 模型，语法契约）
- security.py: SecurityConfig + RateLimitConfig + SecurityConfigLoader
- exceptions.py: 配置域异常层次
- types.py: 语义类型（EnvName, ConfigFieldName）
"""

from __future__ import annotations

from py_config.config import AppSettings
from py_config.config_contract import BaseConfigLoader
from py_config.config_loader import AppSettingsLoader, get_settings
from py_config.exceptions import (
    ConfigError,
    ConfigFormatError,
    ConfigWarning,
    ForbiddenAccess,
    MissingRequiredFieldError,
    ProfileConflictError,
    ProfileLimitExceededError,
)
from py_config.security import (
    RateLimitConfig,
    SecurityConfig,
    get_security_config,
)
from py_config.types import ConfigFieldName, EnvName

__all__ = [
    # 工厂函数
    "get_settings",
    "get_security_config",
    # 配置模型
    "AppSettings",
    "SecurityConfig",
    "RateLimitConfig",
    # 契约
    "BaseConfigLoader",
    "AppSettingsLoader",
    # 语义类型
    "EnvName",
    "ConfigFieldName",
    # 异常
    "ConfigError",
    "MissingRequiredFieldError",
    "ConfigFormatError",
    "ConfigWarning",
    "ForbiddenAccess",
    "ProfileLimitExceededError",
    "ProfileConflictError",
]
