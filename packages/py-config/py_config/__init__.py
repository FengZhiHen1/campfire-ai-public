"""py-config — 全局配置管理共享包。

提供 get_settings() 工厂函数作为全局配置单例获取入口。
首次调用时从环境变量和 .env 文件加载并校验全部配置字段，
校验失败时进程以 sys.exit(1) 终止。

同时提供 SEC-01 安全配置 SecurityConfig 和 RateLimitConfig。
"""

from __future__ import annotations

import functools
import logging
import sys
from typing import TYPE_CHECKING

from pydantic import ValidationError

from py_config.config import AppSettings
from py_config.exceptions import (
    ConfigError,
    ConfigFormatError,
    ConfigWarning,
    ForbiddenAccess,
    MissingRequiredFieldError,
)
from py_config.security import (
    RateLimitConfig,
    SecurityConfig,
    get_security_config,
)

if TYPE_CHECKING:
    pass

__all__ = [
    "get_settings",
    "get_security_config",
    "AppSettings",
    "SecurityConfig",
    "RateLimitConfig",
    "ConfigError",
    "MissingRequiredFieldError",
    "ConfigFormatError",
    "ConfigWarning",
    "ForbiddenAccess",
]

_logger = logging.getLogger("py_config")


# === 格式期望映射表 ===
# 将 Pydantic 错误类型映射为人类可读的格式描述
_EXPECTED_FORMAT_MAP: dict[str, str] = {
    "PostgresDsn": "合法的 PostgreSQL 连接串 (postgresql+asyncpg://user:pass@host:port/db)",
    "RedisDsn": "合法的 Redis 连接串 (redis://host:port/db)",
    "AnyHttpUrl": "合法的 HTTPS URL",
    "string_too_short": "长度不少于规定字符数的字符串",
    "greater_than_equal": "不小于最小值的整数",
    "enum": "枚举允许值之一",
    "url_parsing": "合法的 URL 格式",
    "secret_str": "有效的密钥字符串",
}


def _extract_expected_format(field_type: str, error_type: str) -> str:
    """根据字段类型和错误类型生成人类可读的格式描述。"""
    if error_type in _EXPECTED_FORMAT_MAP:
        return _EXPECTED_FORMAT_MAP[error_type]
    if field_type in _EXPECTED_FORMAT_MAP:
        return _EXPECTED_FORMAT_MAP[field_type]
    return f"合法的 {field_type} 类型值"


def _emit_readable_stderr(
    missing_fields: list[str],
    format_errors: list[dict[str, str]],
) -> None:
    """向 stderr 输出人类可读的中文错误信息。

    Args:
        missing_fields: 缺失的必填配置项字段名列表。
        format_errors: 格式错误的配置项列表，每项包含 field, received, expected。
    """
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("[配置加载失败] 服务启动阻断")
    lines.append("=" * 60)

    if missing_fields:
        lines.append("")
        lines.append("[缺少必填配置项]")
        lines.append("-" * 40)
        fields_str = "、".join(missing_fields)
        lines.append(f"  缺失字段: {fields_str}")
        lines.append(f"  共 {len(missing_fields)} 项未设置。")
        lines.append("  操作建议:")
        lines.append("    1. 检查项目根目录下是否存在 .env 文件")
        lines.append("    2. 确认 .env 文件中已设置上述字段的值")
        lines.append("    3. 生产环境请确认 KMS 注入的环境变量已生效")

    if format_errors:
        lines.append("")
        lines.append("[配置项格式错误]")
        lines.append("-" * 40)
        for err in format_errors:
            received_display = err.get("received", "N/A")
            lines.append(f"  字段: {err['field']}")
            lines.append(f"    当前值: {received_display}")
            lines.append(f"    期望格式: {err['expected']}")
        lines.append("  操作建议:")
        lines.append("    1. 根据上述期望格式修正对应配置项的值")
        lines.append("    2. 修改后重启服务")

    lines.append("")
    lines.append("服务即将退出（exit code = 1）。请修正以上配置后重新启动。")
    lines.append("=" * 60)

    message = "\n".join(lines)
    print(message, file=sys.stderr)


@functools.lru_cache()
def get_settings() -> AppSettings:
    """获取全局配置单例。

    首次调用时从环境变量和 .env 文件加载并校验全部 18 项配置字段，
    后续调用返回缓存实例。校验失败时进程以 sys.exit(1) 终止。

    Returns:
        AppSettings: 经 pydantic-settings 校验通过的全局配置单例。

    Side Effects:
        - 首次调用: 读取 .env 文件（若存在）和环境变量
        - 首次调用: 生产环境下若密钥来自本地文件，通过 warnings.warn() 输出 ConfigWarning
        - 校验失败: 调用 sys.exit(1) 终止进程

    Raises:
        本函数不向调用方抛出异常 —— 校验失败直接以 sys.exit(1) 终止进程。
        仅在首次调用时产生副作用，后续调用为纯函数返回缓存实例。
    """
    try:
        settings = AppSettings()
    except ValidationError as exc:
        errors = exc.errors()
        missing_fields: list[str] = []
        format_error_dicts: list[dict[str, str]] = []

        for error in errors:
            error_type = error.get("type", "")
            loc = error.get("loc", ())
            field_name = ".".join(str(part) for part in loc)

            if error_type == "missing":
                missing_fields.append(field_name)
            else:
                # 获取实际值（脱敏处理）
                received = error.get("input", "")
                # SecretStr 类型的值在 error dict 中已经是脱敏后的
                received_str = str(received) if received else ""

                # 从字段类型映射期望格式
                expected = _extract_expected_format(
                    field_type="", error_type=error_type
                )

                format_error_dicts.append(
                    {
                        "field": field_name,
                        "received": received_str,
                        "expected": expected,
                    }
                )

        # === 构建异常实例（用于日志，不抛出） ===

        missing_error: MissingRequiredFieldError | None = None
        if missing_fields:
            missing_msg = (
                f"缺少必填配置项: {'、'.join(missing_fields)}。"
                f"请检查 .env 文件或 KMS 注入"
            )
            missing_error = MissingRequiredFieldError(
                message=missing_msg,
                missing_fields=missing_fields,
            )

        format_errors_list: list[ConfigFormatError] = []
        for fe in format_error_dicts:
            format_errors_list.append(
                ConfigFormatError(
                    message=(
                        f"配置项格式错误: {fe['field']}={fe['received']}，"
                        f"期望格式: {fe['expected']}"
                    ),
                    field_name=fe["field"],
                    expected_format=fe["expected"],
                    received_value=fe["received"] or None,
                )
            )

        # === 结构化日志（尝试 py-logger，不可用时降级为标准 logging） ===
        try:
            _logger.critical(
                "config_load_failed",
                extra={
                    "event": "config_load_failed",
                    "missing": missing_fields,
                    "format_errors": format_error_dicts,
                },
            )
        except Exception:
            # py-logger 不可用时的降级方案
            if missing_fields:
                _logger.critical(
                    "config_load_failed (missing_required): fields=%s",
                    missing_fields,
                )
            if format_error_dicts:
                _logger.critical(
                    "config_load_failed (format_error): errors=%s",
                    format_error_dicts,
                )

        # === 人类可读 stderr 输出 ===
        _emit_readable_stderr(
            missing_fields=missing_fields,
            format_errors=format_error_dicts,
        )

        sys.exit(1)

    return settings
