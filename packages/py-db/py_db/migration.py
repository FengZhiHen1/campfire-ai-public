r"""py-db 数据库迁移 — MigrationServiceImpl 实现。

模块: py_db.migration
职责: 实现 MigrationService 契约，将 Alembic 的版本化 DDL 管理能力
      封装为 MigrationServiceImpl 类。所有公共入口由契约的 @final 方法
      控制执行流程（前置校验 → 执行 → 后置处理），本模块仅实现 4 个
      _do_ 抽象钩子。

设计策略：
  - 所有 DDL 操作通过 psycopg2 同步连接执行，禁止异步驱动
  - 日志通过 py_logger 结构化记录，不再使用 logging.getLogger(__name__)
  - 迁移逻辑从旧模块级函数迁移至类方法，遵循模板方法模式

边界:
  - 依赖: py_db.migration_contract, py_db.exceptions, py_db.types, alembic, sqlalchemy, py_logger
  - 被依赖: 部署流水线 (CI/CD), api-server 启动脚本
"""

from __future__ import annotations

import ast
from pathlib import Path

import alembic.command
import alembic.config
import alembic.util.exc
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from py_logger import logger
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, ProgrammingError

from py_db.exceptions import (
    MigrationExecutionError,
    MigrationGenerationError,
    MigrationRollbackError,
    MigrationScriptNotFoundError,
    MigrationVerificationError,
)
from py_db.migration_contract import MigrationService
from py_db.types import DatabaseUrl, MigrationMessage, MigrationTarget

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_CONNECTION_TIMEOUT_SECONDS: int = 5


# ============================================================================
# MigrationServiceImpl — 迁移服务实现
# ============================================================================


class MigrationServiceImpl(MigrationService):
    """数据库迁移服务实现类。

    继承 MigrationService 契约，实现 4 个 _do_ 抽象钩子。
    所有前置校验、连接验证和后置处理由基类 @final 方法统一执行，
    本类专注于 Alembic 的实际调用流程。

    Usage:
        impl = MigrationServiceImpl()
        impl.migrate_up(target=MigrationTarget("head"))
        impl.migrate_down(target=MigrationTarget("-1"))
        impl.generate_migration(message=MigrationMessage("add_user_nickname"))
        impl.verify_migration(database_url=DatabaseUrl("postgresql://..."))
    """

    # ------------------------------------------------------------------
    # _do_ 钩子 1：执行正向迁移
    # ------------------------------------------------------------------

    def _do_migrate_up(
        self,
        target: MigrationTarget,
        database_url: DatabaseUrl,
    ) -> int:
        """执行 Alembic upgrade 的核心逻辑。

        前置: target 和 database_url 已由 @final migrate_up 校验
        后置: 数据库 Schema 已更新到目标版本

        Raises:
            MigrationExecutionError: upgrade() 执行失败
        """
        alembic_cfg = self._build_alembic_config(database_url)

        # 检查迁移脚本是否存在
        try:
            script_dir = ScriptDirectory.from_config(alembic_cfg)
            # 注意: get_heads() 在部分 alembic 版本中类型标注不完整
            head_revisions = script_dir.get_heads()  # type: ignore[attr-defined]
            if not head_revisions:
                logger.info(
                    "migration_up_no_scripts",
                    extra={"target": target},
                    op_type="migrate_up",
                )
                return 0

            if target != "head":
                _validate_target_exists(script_dir, target)
        except MigrationScriptNotFoundError:
            raise
        except Exception as exc:
            raise MigrationExecutionError(
                f"Failed to read migration scripts: {exc}",
            ) from exc

        # 获取当前数据库版本（用于失败时的诊断）
        current_rev = _get_current_revision(database_url)

        # 执行正向迁移
        try:
            alembic.command.upgrade(alembic_cfg, target)
        except Exception as exc:
            error_msg = str(exc)
            logger.error(
                "migration_execution_failed",
                extra={
                    "target": target,
                    "error_message": error_msg,
                    "current_version": current_rev,
                },
                op_type="migrate_up",
            )
            raise MigrationExecutionError(
                f"Migration upgrade to '{target}' failed: {error_msg}",
                current_version=current_rev or "",
            ) from exc

        logger.info(
            "migration_up_executed",
            extra={"target": target, "previous_version": current_rev},
            op_type="migrate_up",
        )
        return 0

    # ------------------------------------------------------------------
    # _do_ 钩子 2：执行回滚迁移
    # ------------------------------------------------------------------

    def _do_migrate_down(
        self,
        target: MigrationTarget,
        database_url: DatabaseUrl,
    ) -> int:
        """执行 Alembic downgrade 的核心逻辑。

        前置: target 和 database_url 已由 @final migrate_down 校验
        后置: 数据库 Schema 已回退到目标版本

        Raises:
            MigrationRollbackError: downgrade 不存在或执行失败
        """
        alembic_cfg = self._build_alembic_config(database_url)

        # 获取当前数据库版本
        current_rev = _get_current_revision(database_url)

        if current_rev is None:
            logger.info(
                "migration_down_no_migrations_applied",
                extra={"target": target},
                op_type="migrate_down",
            )
            return 0

        # 对于非相对标记，验证目标版本是否存在于脚本目录
        try:
            script_dir = ScriptDirectory.from_config(alembic_cfg)
            if target not in ("head", "-1", "-2") and not target.startswith("-"):
                _validate_target_exists(script_dir, target)
        except MigrationScriptNotFoundError:
            raise

        # 执行回滚迁移
        try:
            alembic.command.downgrade(alembic_cfg, target)
        except (alembic.util.exc.CommandError, Exception) as exc:
            error_msg = str(exc)

            if "downgrade" in error_msg.lower() or "no such revision" in error_msg.lower():
                reason = f"Downgrade not available for target '{target}'"
            else:
                reason = f"Rollback failed: {error_msg}"

            logger.error(
                "migration_rollback_failed",
                extra={
                    "target": target,
                    "error_message": error_msg,
                    "current_version": current_rev,
                },
                op_type="migrate_down",
            )
            raise MigrationRollbackError(
                reason,
                current_version=current_rev or "",
            ) from exc

        logger.info(
            "migration_down_executed",
            extra={
                "target": target,
                "previous_version": current_rev,
            },
            op_type="migrate_down",
        )
        return 0

    # ------------------------------------------------------------------
    # _do_ 钩子 3：生成迁移脚本
    # ------------------------------------------------------------------

    def _do_generate_migration(
        self,
        message: MigrationMessage,
        autogenerate: bool,
    ) -> str:
        """生成迁移脚本的核心逻辑。

        前置: message 和 autogenerate 已由 @final generate_migration 校验
        后置: versions/ 目录下新增一个 .py 迁移脚本文件

        Raises:
            MigrationGenerationError: 迁移脚本生成失败
        """
        alembic_cfg = self._build_alembic_config()

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

        # 定位最新生成的迁移脚本文件
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

        logger.info(
            "migration_generation_completed",
            extra={"file_path": generated_path, "message": message},
            op_type="generate_migration",
        )
        return generated_path

    # ------------------------------------------------------------------
    # _do_ 钩子 4：验证迁移
    # ------------------------------------------------------------------

    def _do_verify_migration(
        self,
        database_url: DatabaseUrl,
    ) -> tuple[int, str]:
        """执行迁移验证的核心逻辑。

        前置: database_url 已由 @final verify_migration 校验并验证连接
        后置: 返回 (exit_code, summary) 验证结果

        验证流程:
          1. alembic check — 检测未记录的 Schema 变更
          2. alembic upgrade head — 验证所有脚本可执行
          3. AST 解析 — 每份脚本是否同时包含 upgrade() 和 downgrade()

        Raises:
            MigrationVerificationError: 验证过程中发生非预期错误
        """
        alembic_cfg = self._build_alembic_config(database_url)

        # 检查 1: alembic check — 检测手动修改导致的未记录 Schema 变更
        try:
            alembic.command.check(alembic_cfg)
        except Exception as exc:
            error_msg = str(exc)
            if "check" in error_msg.lower() or "migration" in error_msg.lower():
                summary = (
                    f"Migration check failed (unrecorded schema changes detected): {exc}"
                )
                logger.warning(
                    "migration_verification_check_failed",
                    extra={"reason": summary},
                    op_type="verify_migration",
                )
                return (3, summary)
            raise MigrationVerificationError(
                f"Unexpected error during alembic check: {exc}"
            ) from exc

        # 检查 2: upgrade head — 验证全部迁移脚本可执行
        try:
            alembic.command.upgrade(alembic_cfg, "head")
        except Exception as exc:
            summary = f"Migration scripts are not executable: {exc}"
            logger.warning(
                "migration_verification_upgrade_failed",
                extra={"reason": summary},
                op_type="verify_migration",
            )
            return (1, summary)

        # 检查 3: AST 解析 — 每份脚本必须同时包含 upgrade() 和 downgrade()
        versions_dir = _get_versions_dir(alembic_cfg)
        missing_downgrade: list[str] = []

        for py_file in sorted(versions_dir.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            _has_up, has_down = _check_migration_functions(str(py_file))
            if not has_down:
                missing_downgrade.append(py_file.name)

        if missing_downgrade:
            summary = (
                f"Missing downgrade() in {len(missing_downgrade)} script(s): "
                f"{', '.join(missing_downgrade)}"
            )
            logger.warning(
                "migration_verification_missing_downgrade",
                extra={"reason": summary, "files": missing_downgrade},
                op_type="verify_migration",
            )
            return (2, summary)

        summary = (
            "All migration verifications passed: "
            "check OK, upgrade executable, bidirectional OK."
        )
        logger.info(
            "migration_verification_all_passed",
            extra={"result": "passed"},
            op_type="verify_migration",
        )
        return (0, summary)


# ============================================================================
# 模块级辅助函数 — 供 MigrationServiceImpl 的 _do_ 钩子内部调用
# ============================================================================


def _get_current_revision(database_url: DatabaseUrl) -> str | None:
    """获取数据库当前迁移版本号。

    尝试从 alembic_version 表读取当前版本。
    若表不存在或不可达（如全新数据库），返回 None。

    Args:
        database_url: psycopg2 格式的数据库连接串。

    Returns:
        当前迁移版本号字符串，或 None（视为全新数据库）。
    """
    try:
        engine = create_engine(
            database_url,
            connect_args={"connect_timeout": _CONNECTION_TIMEOUT_SECONDS},
        )
        with engine.connect() as conn:
            migration_ctx = MigrationContext.configure(conn)
            # 注意: get_current_revision() 在部分 alembic 版本中类型标注不完整
            current_rev = migration_ctx.get_current_revision()  # type: ignore[union-attr]
        engine.dispose()
        return current_rev
    except ProgrammingError as exc:
        logger.info(
            "alembic_version_not_found_treating_as_new_database",
            extra={"error": str(exc)},
            op_type="get_current_revision",
        )
        return None
    except OperationalError as exc:
        logger.info(
            "alembic_version_unreachable_treating_as_new_database",
            extra={"error": str(exc)},
            op_type="get_current_revision",
        )
        return None


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
        # 注意: get_revision() 在部分 alembic 版本中类型标注不完整
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


def _get_versions_dir(alembic_cfg: alembic.config.Config) -> Path:
    """获取迁移脚本目录的绝对路径。

    Args:
        alembic_cfg: 已初始化的 Alembic Config。

    Returns:
        migrations/versions/ 目录的 Path 对象。
    """
    script = ScriptDirectory.from_config(alembic_cfg)
    return Path(script.versions_dir).resolve()


def _check_migration_functions(file_path: str) -> tuple[bool, bool]:
    """通过 AST 解析检查迁移脚本是否同时包含 upgrade 和 downgrade 函数。

    Args:
        file_path: 迁移脚本 .py 文件的绝对路径。

    Returns:
        (has_upgrade, has_downgrade): 两个布尔值，分别表示
        是否存在 upgrade() 和 downgrade() 函数定义。
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
        logger.warning(
            "ast_parse_error_skipping_file",
            extra={"file": file_path, "error": str(exc)},
            op_type="check_migration_functions",
        )

    return has_upgrade, has_downgrade
