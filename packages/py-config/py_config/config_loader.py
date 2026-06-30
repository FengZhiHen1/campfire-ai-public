"""DEPLOY-05 环境配置管理 — AppSettingsLoader（实现 BaseConfigLoader 契约）。

将 __init__.py 中原有的加载/校验/错误处理逻辑提取到此模块，
通过 BaseConfigLoader 模板方法保证校验流程不可绕过。
"""

from __future__ import annotations

import functools
import logging
import sys
from typing import TYPE_CHECKING

from pydantic import ValidationError

from py_config.config import AppSettings
from py_config.config_contract import BaseConfigLoader
from py_config.types import ConfigFieldName

if TYPE_CHECKING:
    pass

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


def _extract_expected_format(error_type: str) -> str:
    """根据 Pydantic 错误类型生成人类可读的格式描述。"""
    if error_type in _EXPECTED_FORMAT_MAP:
        return _EXPECTED_FORMAT_MAP[error_type]
    return f"合法的 {error_type} 类型值"


def _emit_readable_stderr(
    missing_fields: list[ConfigFieldName],
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


class AppSettingsLoader(BaseConfigLoader[AppSettings]):
    """AppSettings 加载器 —— 实现 BaseConfigLoader 契约。

    从环境变量和 .env 文件加载全部 18 项配置字段。
    校验失败时以 sys.exit(1) 终止进程（fail-fast 策略）。
    """

    def _do_load(self) -> AppSettings:
        """通过 pydantic-settings BaseSettings 构造加载并校验配置。

        pydantic-settings 在 BaseSettings.__init__ 中自动执行：
        - 读取 .env 文件
        - 读取环境变量
        - 按字段类型校验值格式
        - 缺失必填字段或格式不合法 → ValidationError

        Returns:
            AppSettings: 校验通过的全局配置实例。

        Raises:
            pydantic.ValidationError: 校验失败时由 pydantic-settings 抛出，
                由 load() 模板方法的外层错误处理捕获。
        """
        return AppSettings.model_validate({})

    def _handle_validation_error(self, exc: ValidationError) -> None:
        """处理配置校验失败：解析错误 → 结构化日志 → stderr 输出 → sys.exit(1)。

        Args:
            exc: pydantic-settings 抛出的校验错误。
        """
        errors = exc.errors()
        missing_fields: list[ConfigFieldName] = []
        format_error_dicts: list[dict[str, str]] = []

        for error in errors:
            error_type = error.get("type", "")
            loc = error.get("loc", ())
            field_name = ".".join(str(part) for part in loc)

            if error_type == "missing":
                missing_fields.append(ConfigFieldName(field_name))
            else:
                received = error.get("input", "")
                received_str = str(received) if received else ""
                expected = _extract_expected_format(error_type)
                format_error_dicts.append(
                    {
                        "field": field_name,
                        "received": received_str,
                        "expected": expected,
                    }
                )

        # 结构化日志
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

        # 人类可读 stderr 输出
        _emit_readable_stderr(
            missing_fields=missing_fields,
            format_errors=format_error_dicts,
        )

        sys.exit(1)


# === 全局配置单例 ===


@functools.lru_cache()
def get_settings() -> AppSettings:
    """获取全局配置单例。

    首次调用时从环境变量和 .env 文件加载并校验全部配置字段，
    后续调用返回缓存实例。校验失败时进程以 sys.exit(1) 终止。

    Returns:
        AppSettings: 经 pydantic-settings 校验通过的全局配置单例。

    Side Effects:
        - 首次调用: 读取 .env 文件（若存在）和环境变量
        - 首次调用: 生产环境下若密钥来自本地文件，通过 warnings.warn() 输出 ConfigWarning
        - 校验失败: 调用 sys.exit(1) 终止进程
    """
    loader = AppSettingsLoader()
    try:
        return loader.load()
    except ValidationError as exc:
        loader._handle_validation_error(exc)
        # handle_validation_error 内部调用 sys.exit(1)，
        # 此处 return 仅为类型检查器
        raise
