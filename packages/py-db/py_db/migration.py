"""DEPLOY-04 数据库迁移 — 核心实现。

基于 Alembic 对 PostgreSQL 数据库 Schema 实施版本化增量管理。
封装 migrate_up、migrate_down、generate_migration、verify_migration 四个核心接口。

设计策略：薄封装 Alembic 原生能力，仅在部署流水线集成和错误报告格式上
增加结构化输出层。

同步驱动强制：所有 DDL 操作通过 psycopg2 同步连接执行，
禁止使用 asyncpg 或任何异步驱动。
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import alembic.command
import alembic.config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError

from py_db.exceptions import (
    MigrationConnectionError,
    MigrationExecutionError,
    MigrationGenerationError,
    MigrationRollbackError,
    MigrationScriptNotFoundError,
    MigrationVerificationError,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_CONNECTION_RETRY_MAX: int = 3
_CONNECTION_RETRY_INTERVAL_SECONDS: float = 5.0
_CONNECTION_TIMEOUT_SECONDS: int = 5
_MIGRATION_TIMEOUT_SECONDS: int = 300

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 内部辅助：路径解析
# ---------------------------------------------------------------------------


def _get_alembic_ini_path() -> str:
    """定位 alembic.ini 文件的绝对路径。

    alembic.ini 位于 packages/py-db/ 根目录，与本模块的 py_db 包目录
    同级。从当前模块文件路径向上两级即可找到。

    Returns:
        alembic.ini 的绝对路径。
    """
    # packages/py-db/py_db/migration.py → 向上两级 → packages/py-db/
    module_dir = Path(__file__).resolve().parent  # py_db/
    package_dir = module_dir.parent  # packages/py-db/
    ini_path = package_dir / "alembic.ini"
    return str(ini_path)


def _get_versions_dir(alembic_cfg: alembic.config.Config) -> Path:
    """获取迁移脚本目录的绝对路径。

    Args:
        alembic_cfg: 已初始化的 Alembic Config。

    Returns:
        migrations/versions/ 目录的路径。
    """
    script = ScriptDirectory.from_config(alembic_cfg)
    return Path(script.versions_dir).resolve()


# ---------------------------------------------------------------------------
# 内部辅助：数据库连接串处理
# ---------------------------------------------------------------------------


def _convert_url_to_psycopg2(url: str) -> str:
    """将 asyncpg 连接串转换为 psycopg2 格式。

    Alembic DDL 操作必须通过 psycopg2 同步驱动执行。
    将 DATABASE_URL 中的 +asyncpg 替换为 +psycopg2。

    Args:
        url: 原始数据库连接串（可能使用 asyncpg 前缀）。

    Returns:
        psycopg2 格式的连接串。
    """
    if "asyncpg" in url:
        return url.replace("+asyncpg", "+psycopg2")
    return url


def _resolve_database_url(database_url: str | None) -> str:
    """解析数据库连接串。

    优先级：
    1. 函数参数 database_url
    2. 环境变量 DATABASE_URL
    3. 均为 None → 抛出异常

    Args:
        database_url: 显式传入的连接串（可为 None）。

    Returns:
        psycopg2 格式的数据库连接串。

    Raises:
        MigrationConnectionError: 未配置 DATABASE_URL。
    """
    url = database_url
    if not url:
        url = os.environ.get("DATABASE_URL")
    if not url:
        raise MigrationConnectionError(
            "DATABASE_URL not configured. "
            "Provide database_url parameter or set the DATABASE_URL environment variable.",
            retries_attempted=0,
        )
    return _convert_url_to_psycopg2(url)


# ---------------------------------------------------------------------------
# 内部辅助：Alembic Config 构建
# ---------------------------------------------------------------------------


def _build_alembic_config(database_url: str | None = None) -> alembic.config.Config:
    """构建 Alembic Config 对象。

    从 alembic.ini 创建配置，注入数据库连接串，
    确保 script_location 使用绝对路径。

    Args:
        database_url: 数据库连接串（可为 None，从环境变量读取）。

    Returns:
        已配置的 Alembic Config 对象。
    """
    ini_path = _get_alembic_ini_path()
    resolved_url = _resolve_database_url(database_url)

    cfg = alembic.config.Config(ini_path)
    cfg.set_main_option("sqlalchemy.url", resolved_url)

    # 确保 script_location 为绝对路径，避免 cwd 依赖
    script_location = os.path.join(os.path.dirname(ini_path), "migrations")
    cfg.set_main_option("script_location", script_location)

    return cfg


# ---------------------------------------------------------------------------
# 内部辅助：连接验证
# ---------------------------------------------------------------------------


def _validate_connection(
    database_url: str,
    retry_max: int = _CONNECTION_RETRY_MAX,
    retry_interval: float = _CONNECTION_RETRY_INTERVAL_SECONDS,
) -> None:
    """验证数据库连接可用性（带重试）。

    通过 psycopg2 创建测试连接并执行 SELECT 1，
    连接超时 5 秒。连接失败时重试（固定间隔），认证失败不重试。

    Args:
        database_url: psycopg2 格式的连接串。
        retry_max: 最大重试次数（默认 3）。
        retry_interval: 重试间隔秒数（默认 5.0）。

    Raises:
        MigrationConnectionError: 连接失败且重试耗尽，或认证失败。
    """
    last_error: Exception | None = None
    psycopg2_url = _convert_url_to_psycopg2(database_url)

    for attempt in range(1, retry_max + 1):
        try:
            engine = create_engine(
                psycopg2_url,
                connect_args={
                    "connect_timeout": _CONNECTION_TIMEOUT_SECONDS,
                },
            )
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                conn.commit()
            engine.dispose()
            _logger.info(
                "database_connection_verified",
                extra={"attempt": attempt},
            )
            return
        except (OperationalError, ProgrammingError) as exc:
            last_error = exc
            error_msg = str(exc)

            # 认证失败：不重试
            if _is_auth_failure(error_msg):
                raise MigrationConnectionError(
                    f"Database authentication failed: {error_msg}",
                    retries_attempted=attempt,
                ) from exc

            _logger.warning(
                "database_connection_failure",
                extra={
                    "attempt": attempt,
                    "max_retries": retry_max,
                    "error": error_msg,
                },
            )

            if attempt < retry_max:
                time.sleep(retry_interval)

    raise MigrationConnectionError(
        f"Database unreachable after {retry_max} retries: {last_error}",
        retries_attempted=retry_max,
    )


def _is_auth_failure(error_msg: str) -> bool:
    """检测是否为认证失败（不应重试）。

    PostgreSQL 认证失败的典型错误消息包含特定关键词。

    Args:
        error_msg: 异常消息字符串。

    Returns:
        True 表示认证失败。
    """
    auth_keywords = (
        "password authentication failed",
        "no password supplied",
        "role",
        "authentication failed",
        "Ident authentication failed",
    )
    error_lower = error_msg.lower()
    return any(keyword.lower() in error_lower for keyword in auth_keywords)


# ---------------------------------------------------------------------------
# 内部辅助：输入参数格式验证
# ---------------------------------------------------------------------------


def _validate_database_url_format(database_url: str) -> None:
    """验证 database_url 是否为合法的 PostgreSQL 连接串格式。

    必须在任何数据库操作之前调用，确保 URL 格式符合 PostgreSQL 连接串
    的预期结构，防止无效 URL 透传到底层库导致非契约异常。

    Args:
        database_url: 待验证的数据库连接串（必须为非空字符串）。

    Raises:
        MigrationConnectionError: URL 为空或格式不符合 PostgreSQL 连接串前缀。
    """
    if not database_url or not re.match(r"^postgresql(\+[a-z][a-z0-9]*)?://", database_url):
        raise MigrationConnectionError(
            f"Invalid database URL format: '{database_url}'. "
            "Expected postgresql:// or postgresql+driver:// prefix.",
            retries_attempted=0,
        )


def _validate_target_format(target: str, allow_relative: bool = False) -> None:
    """验证 target 参数格式是否符合契约约束。

    在任何数据库操作之前调用，确保 target 参数格式有效，防止空字符串
    或无效格式传递到底层 alembic 导致非预期行为。

    - migrate_up 场景（allow_relative=False）：
        target 必须匹配 'head' 或 'YYYYMMDD_HHMMSS' 格式。
    - migrate_down 场景（allow_relative=True）：
        target 可额外接受相对标记 '-N'（如 '-1', '-2'）。

    Args:
        target: 待验证的目标版本标识。
        allow_relative: 是否允许相对标记格式（默认 False）。

    Raises:
        MigrationScriptNotFoundError: target 格式不符合要求。
    """
    if allow_relative:
        if not re.match(r"^(head|\d{8}_\d{6}|-\d+)$", target):
            raise MigrationScriptNotFoundError(
                f"Invalid target format: '{target}'. "
                "Expected 'head', revision hash (YYYYMMDD_HHMMSS), or relative marker (-N).",
                target=target,
            )
    else:
        if not re.match(r"^(head|\d{8}_\d{6})$", target):
            raise MigrationScriptNotFoundError(
                f"Invalid target format: '{target}'. "
                "Expected 'head' or revision hash (YYYYMMDD_HHMMSS).",
                target=target,
            )


# ---------------------------------------------------------------------------
# 内部辅助：结构化错误输出
# ---------------------------------------------------------------------------


def _write_structured_error(
    error_type: str,
    error_message: str,
    script_name: str = "",
    revision_id: str = "",
    current_version: str = "",
) -> None:
    """将结构化错误信息以 JSON 格式写入 stderr。

    Args:
        error_type: 错误码（如 MIG-ERR-001）。
        error_message: 可读错误描述。
        script_name: 失败的脚本文件名。
        revision_id: 失败的 revision hash。
        current_version: 失败时的数据库版本。
    """
    error_payload: dict[str, Any] = {
        "error_type": error_type,
        "error_message": error_message,
    }
    if script_name:
        error_payload["script_name"] = script_name
    if revision_id:
        error_payload["revision_id"] = revision_id
    if current_version:
        error_payload["current_version"] = current_version

    json.dump(error_payload, sys.stderr, ensure_ascii=False)
    sys.stderr.write("\n")
    sys.stderr.flush()


def _write_structured_log(
    event: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """将结构化日志以 JSON 格式写入 stdout。

    Args:
        event: 事件名称（如 migration_completed）。
        extra: 附加字段。
    """
    log_payload: dict[str, Any] = {"event": event}
    if extra:
        log_payload.update(extra)
    json.dump(log_payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# 公共接口 1：migrate_up
# ---------------------------------------------------------------------------


def migrate_up(
    target: str = "head",
    database_url: str | None = None,
) -> int:
    """执行数据库正向迁移，将数据库版本升级到目标版本。

    执行流程（遵循落地规范 §1.5）：
        步骤 1: 解析数据库连接串
        步骤 2: 验证数据库连接可用（3 次重试，5s 间隔）
        步骤 3: 获取当前数据库版本状态
        步骤 4: 执行正向迁移
        步骤 5: 失败处理

    Args:
        target: 目标迁移版本标识，默认 "head"（最新版本）。
                可指定具体 revision hash（如 "20260526_143021"）。
        database_url: 目标数据库连接串。若为 None，从环境变量
                      DATABASE_URL 读取。

    Returns:
        int: 退出码。0 = 成功（无待执行迁移或全部执行成功）；非 0 = 失败。

    Raises:
        MigrationExecutionError: 任一迁移脚本的 upgrade() 执行失败。
        MigrationConnectionError: 数据库连接不可用。
        MigrationScriptNotFoundError: 指定 target revision 不存在。
    """
    # 步骤 0: 验证参数格式（在任何数据库操作之前）
    _validate_target_format(target, allow_relative=False)

    # 步骤 1: 解析数据库连接
    resolved_url = _resolve_database_url(database_url)
    _validate_database_url_format(resolved_url)
    psycopg2_url = _convert_url_to_psycopg2(resolved_url)

    _write_structured_log("migration_up_started", {"target": target})

    # 步骤 2: 验证数据库连接可用
    try:
        _validate_connection(resolved_url)
    except MigrationConnectionError:
        _write_structured_error(
            error_type="MIG-ERR-003",
            error_message=f"Database unreachable after {_CONNECTION_RETRY_MAX} retries",
            current_version="unknown",
        )
        raise

    # 构建 Alembic 配置
    alembic_cfg = _build_alembic_config(database_url)

    # 步骤 3: 获取当前数据库版本状态
    try:
        script_dir = ScriptDirectory.from_config(alembic_cfg)
        head_revisions = script_dir.get_heads()  # type: ignore[attr-defined]
        if not head_revisions:
            _write_structured_log("migration_up_no_scripts")
            return 0

        head_revision = head_revisions[0]  # type: ignore[index]

        # 验证 target 是否存在于脚本目录中
        if target != "head":
            _validate_target_exists(script_dir, target)
    except MigrationScriptNotFoundError:
        raise
    except Exception as exc:
        _write_structured_error(
            error_type="MIG-ERR-001",
            error_message=f"Failed to read migration scripts: {exc}",
        )
        raise MigrationExecutionError(
            f"Failed to read migration scripts: {exc}",
        ) from exc

    # 步骤 4: 执行正向迁移
    try:
        with _create_engine(psycopg2_url).connect() as conn:
            migration_ctx = MigrationContext.configure(conn)
            current_rev = (
                migration_ctx.get_current_revision()  # type: ignore[union-attr]
            )
    except Exception as exc:
        # alembic_version 表不存在 → 视为全新数据库
        _logger.info(
            "alembic_version_not_found_treating_as_new_database",
            extra={"error": str(exc)},
        )
        current_rev = None

    try:
        alembic.command.upgrade(alembic_cfg, target)
    except Exception as exc:
        error_msg = str(exc)
        _write_structured_error(
            error_type="MIG-ERR-001",
            error_message=error_msg,
            current_version=current_rev or "unknown",
        )
        _logger.error(
            "migration_execution_failed",
            extra={
                "target": target,
                "error_message": error_msg,
                "current_version": current_rev,
            },
        )
        raise MigrationExecutionError(
            f"Migration upgrade to '{target}' failed: {error_msg}",
            current_version=current_rev or "",
        ) from exc

    _write_structured_log(
        "migration_up_completed",
        {"target": target},
    )
    return 0


# ---------------------------------------------------------------------------
# 公共接口 2：migrate_down
# ---------------------------------------------------------------------------


def migrate_down(
    target: str = "-1",
    database_url: str | None = None,
) -> int:
    """执行数据库回滚迁移，将数据库版本回退到目标版本。

    执行流程：
        步骤 1: 解析数据库连接串
        步骤 2: 验证数据库连接可用
        步骤 3: 获取当前版本
        步骤 4: 执行回滚迁移
        步骤 5: 失败处理

    Args:
        target: 目标回滚版本标识，默认 "-1"（回滚一个版本）。
                可指定具体 revision hash 或相对标记（如 "-2"）。
        database_url: 目标数据库连接串。若为 None，从环境变量
                      DATABASE_URL 读取。

    Returns:
        int: 退出码。0 = 回滚成功；非 0 = 回滚失败。

    Raises:
        MigrationRollbackError: 回滚操作失败（downgrade 不存在或执行错误）。
        MigrationConnectionError: 数据库连接不可用。
        MigrationScriptNotFoundError: 指定 target revision 不存在。
    """
    # 步骤 0: 验证参数格式（在任何数据库操作之前）
    _validate_target_format(target, allow_relative=True)

    resolved_url = _resolve_database_url(database_url)
    _validate_database_url_format(resolved_url)
    psycopg2_url = _convert_url_to_psycopg2(resolved_url)

    _write_structured_log("migration_down_started", {"target": target})

    # 步骤 2: 验证数据库连接可用
    try:
        _validate_connection(resolved_url)
    except MigrationConnectionError:
        _write_structured_error(
            error_type="MIG-ERR-003",
            error_message=f"Database unreachable after {_CONNECTION_RETRY_MAX} retries",
            current_version="unknown",
        )
        raise

    # 构建 Alembic 配置
    alembic_cfg = _build_alembic_config(database_url)

    # 步骤 3: 获取当前版本
    try:
        with _create_engine(psycopg2_url).connect() as conn:
            migration_ctx = MigrationContext.configure(conn)
            current_rev = (
                migration_ctx.get_current_revision()  # type: ignore[union-attr]
            )
    except Exception as exc:
        _logger.warning(
            "failed_to_get_current_revision",
            extra={"error": str(exc)},
        )
        current_rev = None

    if current_rev is None:
        _write_structured_log("migration_down_no_migrations_applied")
        return 0

    # 检查目标是否存在
    try:
        script_dir = ScriptDirectory.from_config(alembic_cfg)
        if target not in ("head", "-1", "-2") and not target.startswith("-"):
            _validate_target_exists(script_dir, target)
    except MigrationScriptNotFoundError:
        raise

    # 步骤 4: 执行回滚迁移
    try:
        alembic.command.downgrade(alembic_cfg, target)
    except (alembic.util.exc.CommandError, Exception) as exc:
        error_msg = str(exc)

        # 检查是否因为缺少 downgrade 函数
        if "downgrade" in error_msg.lower() or "no such revision" in error_msg.lower():
            reason = f"Downgrade not available for target '{target}'"
        else:
            reason = f"Rollback failed: {error_msg}"

        _write_structured_error(
            error_type="MIG-ERR-002",
            error_message=reason,
            current_version=current_rev or "unknown",
        )
        _logger.error(
            "migration_rollback_failed",
            extra={
                "target": target,
                "error_message": error_msg,
                "current_version": current_rev,
            },
        )
        raise MigrationRollbackError(
            reason,
            current_version=current_rev or "",
        ) from exc

    _write_structured_log(
        "migration_down_completed",
        {"target": target, "previous_version": current_rev},
    )
    return 0


# ---------------------------------------------------------------------------
# 公共接口 3：generate_migration
# ---------------------------------------------------------------------------


def generate_migration(
    message: str,
    autogenerate: bool = True,
) -> str:
    """自动生成新的迁移脚本。

    调用 alembic.command.revision 在 versions/ 目录下创建新的 .py 文件。
    autogenerate=True 时比对 target_metadata 与数据库实际结构差异自动生成
    迁移内容；False 时生成空模板供手工填写。

    Args:
        message: 迁移脚本的语义化描述，将作为文件名的一部分。
                 例如 "add_user_nickname"。长度限制 1-128 字符。
        autogenerate: 是否启用自动检测模式。默认 True。

    Returns:
        str: 新生成的迁移脚本文件绝对路径。

    Raises:
        MigrationGenerationError: 迁移脚本生成失败。
        ValueError: message 为空或过长。
    """
    if not message or not message.strip():
        raise ValueError("message must be a non-empty string")
    if len(message) > 128:
        raise ValueError("message must not exceed 128 characters")
    if not isinstance(autogenerate, bool):
        raise MigrationGenerationError(
            f"autogenerate must be a boolean, got {type(autogenerate).__name__}."
        )

    _write_structured_log(
        "migration_generation_started",
        {"message": message, "autogenerate": autogenerate},
    )

    alembic_cfg = _build_alembic_config()

    try:
        alembic.command.revision(
            alembic_cfg,
            message=message,
            autogenerate=autogenerate,
        )
    except Exception as exc:
        raise MigrationGenerationError(
            f"Failed to generate migration script '{message}': {exc}"
        ) from exc

    # 查找最新生成的迁移脚本文件
    versions_dir = _get_versions_dir(alembic_cfg)
    try:
        py_files = sorted(
            versions_dir.glob("*.py"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not py_files:
            raise MigrationGenerationError(
                "Migration script was not created. Check Alembic configuration."
            )
        generated_path = str(py_files[0].resolve())
    except Exception as exc:
        raise MigrationGenerationError(
            f"Failed to locate generated migration file: {exc}"
        ) from exc

    _write_structured_log(
        "migration_generation_completed",
        {"file_path": generated_path},
    )
    return generated_path


# ---------------------------------------------------------------------------
# 公共接口 4：verify_migration
# ---------------------------------------------------------------------------


def verify_migration(
    database_url: str,
) -> tuple[int, str]:
    """在目标空数据库上执行全面迁移验证。

    执行以下检查：
    1. alembic check：检测数据库状态与迁移脚本是否一致
    2. alembic upgrade head：在空数据库上执行全部迁移脚本
    3. AST 解析检查：每份迁移脚本是否同时包含 upgrade() 和 downgrade()

    此接口主要用于 CI 流水线中的自动化验证。

    Args:
        database_url: 目标空数据库连接串。

    Returns:
        tuple[int, str]: (退出码, 验证结果摘要)。
                         退出码 0 = 全部验证通过；
                         退出码 1 = 迁移脚本不可执行；
                         退出码 2 = 缺少 downgrade() 函数；
                         退出码 3 = alembic check 检测到未记录的 Schema 变更。

    Raises:
        MigrationConnectionError: 数据库连接失败。
        MigrationVerificationError: 验证过程中发生非预期错误。
    """
    _write_structured_log("migration_verification_started")

    # 步骤 0: 验证参数格式（在任何数据库操作之前）
    _validate_database_url_format(database_url)

    # 验证连接
    try:
        _validate_connection(database_url)
    except MigrationConnectionError:
        _write_structured_error(
            error_type="MIG-ERR-003",
            error_message="Database unreachable during verification",
        )
        raise

    alembic_cfg = _build_alembic_config(database_url)

    # 步骤 1: alembic check — 检测手动修改
    try:
        alembic.command.check(alembic_cfg)
    except Exception as exc:
        error_msg = str(exc)
        if "check" in error_msg.lower() or "migration" in error_msg.lower():
            summary = f"Migration check failed (unrecorded schema changes detected): {exc}"
            _write_structured_log("migration_verification_failed", {"reason": summary})
            return (3, summary)
        raise MigrationVerificationError(
            f"Unexpected error during alembic check: {exc}"
        ) from exc

    # 步骤 2: alembic upgrade head — 验证全部脚本可执行性
    try:
        alembic.command.upgrade(alembic_cfg, "head")
    except Exception as exc:
        summary = f"Migration scripts are not executable: {exc}"
        _write_structured_log("migration_verification_failed", {"reason": summary})
        return (1, summary)

    # 步骤 3: AST 解析检查 — 每份脚本必须包含 upgrade 和 downgrade
    versions_dir = _get_versions_dir(alembic_cfg)
    missing_downgrade: list[str] = []

    for py_file in sorted(versions_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        has_up, has_down = _check_migration_functions(str(py_file))
        if not has_down:
            missing_downgrade.append(py_file.name)

    if missing_downgrade:
        summary = (
            f"Missing downgrade() in {len(missing_downgrade)} script(s): "
            f"{', '.join(missing_downgrade)}"
        )
        _write_structured_log("migration_verification_failed", {"reason": summary})
        return (2, summary)

    summary = "All migration verifications passed: check OK, upgrade executable, bidirectional OK."
    _write_structured_log(
        "migration_verification_completed",
        {"result": "passed"},
    )
    return (0, summary)


# ---------------------------------------------------------------------------
# 内部辅助：AST 检查
# ---------------------------------------------------------------------------


def _check_migration_functions(file_path: str) -> tuple[bool, bool]:
    """通过 AST 解析检查迁移脚本是否包含 upgrade 和 downgrade 函数。

    Args:
        file_path: 迁移脚本文件路径。

    Returns:
        (has_upgrade, has_downgrade): 两个布尔值。
    """
    has_upgrade = False
    has_downgrade = False

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if node.name == "upgrade":
                    has_upgrade = True
                elif node.name == "downgrade":
                    has_downgrade = True

    except SyntaxError as exc:
        _logger.warning(
            "ast_parse_error_skipping_file",
            extra={"file": file_path, "error": str(exc)},
        )

    return has_upgrade, has_downgrade


# ---------------------------------------------------------------------------
# 内部辅助：引擎创建
# ---------------------------------------------------------------------------


def _create_engine(database_url: str):
    """创建 SQLAlchemy 同步引擎（psycopg2）。

    Args:
        database_url: psycopg2 格式的连接串。

    Returns:
        SQLAlchemy Engine 实例。
    """
    return create_engine(
        database_url,
        connect_args={
            "connect_timeout": _CONNECTION_TIMEOUT_SECONDS,
        },
    )


# ---------------------------------------------------------------------------
# 内部辅助：验证 target 存在
# ---------------------------------------------------------------------------


def _validate_target_exists(
    script_dir: ScriptDirectory,
    target: str,
) -> None:
    """验证 target revision 是否存在于脚本目录中。

    Args:
        script_dir: Alembic ScriptDirectory 实例。
        target: 待验证的 revision hash。

    Raises:
        MigrationScriptNotFoundError: target revision 不存在。
    """
    try:
        script = script_dir.get_revision(target)  # type: ignore[attr-defined]
        if script is None:
            raise MigrationScriptNotFoundError(
                f"Revision '{target}' not found in migration scripts.",
                target=target,
            )
    except (alembic.util.exc.CommandError, Exception) as exc:
        if "No such revision" in str(exc) or "not found" in str(exc).lower():
            raise MigrationScriptNotFoundError(
                f"Revision '{target}' not found in migration scripts: {exc}",
                target=target,
            ) from exc
        raise
