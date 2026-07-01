"""py-db 迁移服务契约 — ABC 模板方法定义。

模块: py_db.migration_contract
职责: 定义数据库迁移服务的 ABC 契约骨架。实现者只能覆写 _do_ 前缀的钩子方法，
      @final 公共入口强制执行 前置校验 → 执行 → 后置处理 三阶段流程。
数据来源:
  - Alembic: MUST — 迁移引擎，所有 DDL 操作通过 alembic.command 执行
  - SQLAlchemy Engine: MUST — 同步引擎（psycopg2），连接验证和版本查询
  - DATABASE_URL 环境变量: MUST — 数据库连接串（可被参数覆盖）
  - py_logger.logger: MUST — 结构化日志全局单例，记录所有迁移操作事件
边界:
  - 依赖: py_db.types, py_db.exceptions, py_logger, alembic, sqlalchemy
  - 被依赖: 部署流水线（CI/CD）、api-server 启动脚本
禁止行为:
  - 禁止在 @final 方法之外暴露迁移入口——所有调用必须经过前置校验
  - 禁止在实现类中覆写 @final 方法
  - 禁止使用异步驱动（asyncpg）——DDL 操作强制同步 psycopg2
  - 禁止在 _do_ 钩子中重复做参数校验——上游已处理
  - 禁止直接写 stderr/stdout 做结构化输出——日志统一走 py_logger
"""

from __future__ import annotations

import os
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import final

import alembic.command
import alembic.config
from py_logger import logger
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError

from py_db.exceptions import (
    MigrationConnectionError,
    MigrationGenerationError,
    MigrationScriptNotFoundError,
)
from py_db.types import DatabaseUrl, MigrationMessage, MigrationTarget

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_CONNECTION_RETRY_MAX: int = 3  # 共 3 次尝试（1 主 + 2 重试）
_CONNECTION_RETRY_INTERVAL_SECONDS: float = 5.0
_CONNECTION_TIMEOUT_SECONDS: int = 5


# ============================================================================
# MigrationService — 迁移服务契约 ABC
# ============================================================================


class MigrationService(ABC):
    """数据库迁移服务契约。

    实现者只能覆写 _do_ 前缀的钩子方法。
    @final 公共入口强制执行 参数校验 → 连接验证 → 执行迁移 流程。
    """

    # ------------------------------------------------------------------
    # @final 公共入口 1：migrate_up
    # ------------------------------------------------------------------

    @final
    def migrate_up(
        self,
        target: MigrationTarget = MigrationTarget("head"),
        database_url: DatabaseUrl | None = None,
    ) -> int:
        """执行数据库正向迁移，将数据库版本升级到目标版本。

        前置: 无（参数校验在方法内部执行）
        后置: 数据库版本已升级到 target，或无可执行脚本时返回 0
        输入约束:
          - target: "head" 或 YYYYMMDD_HHMMSS 格式的有效 revision hash
          - database_url: postgresql:// 或 postgresql+driver:// 格式，None 时从环境变量读取
        输出约束:
          - 返回 int 退出码：0 = 成功，非 0 = 失败
        异常:
          - MigrationExecutionError: upgrade() 执行失败
          - MigrationConnectionError: 数据库连接不可用
          - MigrationScriptNotFoundError: target revision 不存在
        Side Effects:
          - 通过 py_logger 记录结构化日志（migration_up_started / migration_up_completed）
          - 修改数据库 Schema（DDL 操作）
          - 更新 alembic_version 表
        """
        self._validate_target_format(target, allow_relative=False)
        resolved_url = self._resolve_database_url(database_url)
        self._validate_database_url_format(resolved_url)
        self._validate_connection(resolved_url)

        logger.info(
            "migration",
            "migration_up_started",
            extra={"target": target},
            op_type="migrate_up",
        )

        result = self._do_migrate_up(target, resolved_url)
        self._validate_migration_result(result, "upgrade", target)
        return result

    # ------------------------------------------------------------------
    # @final 公共入口 2：migrate_down
    # ------------------------------------------------------------------

    @final
    def migrate_down(
        self,
        target: MigrationTarget = MigrationTarget("-1"),
        database_url: DatabaseUrl | None = None,
    ) -> int:
        """执行数据库回滚迁移，将数据库版本回退到目标版本。

        前置: 无（参数校验在方法内部执行）
        后置: 数据库版本已回退到 target，或无已应用迁移时返回 0
        输入约束:
          - target: "head" / YYYYMMDD_HHMMSS / 相对标记 "-N"
          - database_url: postgresql:// 或 postgresql+driver:// 格式，None 时从环境变量读取
        输出约束:
          - 返回 int 退出码：0 = 成功，非 0 = 失败
        异常:
          - MigrationRollbackError: 回滚失败（downgrade 不存在或执行错误）
          - MigrationConnectionError: 数据库连接不可用
          - MigrationScriptNotFoundError: target revision 不存在
        Side Effects:
          - 通过 py_logger 记录结构化日志（migration_down_started / migration_down_completed）
          - 修改数据库 Schema（DDL 回滚操作）
          - 更新 alembic_version 表
        """
        self._validate_target_format(target, allow_relative=True)
        resolved_url = self._resolve_database_url(database_url)
        self._validate_database_url_format(resolved_url)
        self._validate_connection(resolved_url)

        logger.info(
            "migration",
            "migration_down_started",
            extra={"target": target},
            op_type="migrate_down",
        )

        result = self._do_migrate_down(target, resolved_url)
        self._validate_migration_result(result, "downgrade", target)
        return result

    # ------------------------------------------------------------------
    # @final 公共入口 3：generate_migration
    # ------------------------------------------------------------------

    @final
    def generate_migration(
        self,
        message: MigrationMessage,
        autogenerate: bool = True,
    ) -> str:
        """自动生成新的迁移脚本。

        前置: 无（参数校验在方法内部执行）
        后置: versions/ 目录下新增一个 .py 迁移脚本文件
        输入约束:
          - message: 1-128 字符的非空迁移描述
          - autogenerate: 是否启用自动检测模式
        输出约束:
          - 返回新生成的迁移脚本文件绝对路径
        异常:
          - MigrationGenerationError: 迁移脚本生成失败
          - ValueError: message 为空或过长
        Side Effects:
          - 通过 py_logger 记录结构化日志
          - 在 versions/ 目录下创建新 .py 文件（文件系统写操作）
        """
        self._validate_generate_message(message, autogenerate)

        logger.info(
            "migration",
            "migration_generation_started",
            extra={"message": message, "autogenerate": autogenerate},
            op_type="generate_migration",
        )

        result = self._do_generate_migration(message, autogenerate)
        self._validate_generated_path(result)
        return result

    # ------------------------------------------------------------------
    # @final 公共入口 4：verify_migration
    # ------------------------------------------------------------------

    @final
    def verify_migration(
        self,
        database_url: DatabaseUrl,
    ) -> tuple[int, str]:
        """在目标数据库上执行全面迁移验证。

        前置: 无（参数校验在方法内部执行）
        后置: 完成三项检查（alembic check / upgrade head / AST downgrade 检查）
        输入约束:
          - database_url: postgresql:// 或 postgresql+driver:// 格式的有效连接串
        输出约束:
          - 返回 (exit_code, summary)：
            0 = 全部验证通过
            1 = 迁移脚本不可执行
            2 = 缺少 downgrade() 函数
            3 = alembic check 检测到未记录的 Schema 变更
        异常:
          - MigrationConnectionError: 数据库连接失败
          - MigrationVerificationError: 验证过程中发生非预期错误
        Side Effects:
          - 通过 py_logger 记录结构化日志
          - 对数据库执行 DDL 操作（upgrade head）
        """
        self._validate_database_url_format(database_url)
        self._validate_connection(database_url)

        logger.info(
            "migration",
            "migration_verification_started",
            op_type="verify_migration",
        )

        result = self._do_verify_migration(database_url)
        self._validate_verify_result(result)
        return result

    # ==================================================================
    # @abstractmethod 钩子 — 实现者必填
    # ==================================================================

    @abstractmethod
    def _do_migrate_up(
        self,
        target: MigrationTarget,
        database_url: DatabaseUrl,
    ) -> int:
        """执行正向迁移的核心逻辑。

        实现者在此填写 Alembic upgrade 的实际调用流程。
        不需要关心参数格式校验和连接验证——@final migrate_up 已处理。

        输入约束:
          - target 已通过 _validate_target_format 校验
          - database_url 已通过 _validate_database_url_format 校验
          - 数据库连接已验证可用
        输出约束:
          - 返回 0 表示成功（含无可执行脚本），非 0 表示失败
        异常:
          - MigrationExecutionError: upgrade() 执行失败
        """
        ...

    @abstractmethod
    def _do_migrate_down(
        self,
        target: MigrationTarget,
        database_url: DatabaseUrl,
    ) -> int:
        """执行回滚迁移的核心逻辑。

        实现者在此填写 Alembic downgrade 的实际调用流程。
        不需要关心参数格式校验和连接验证——@final migrate_down 已处理。

        输入约束:
          - target 已通过 _validate_target_format 校验（含相对标记）
          - database_url 已通过 _validate_database_url_format 校验
          - 数据库连接已验证可用
        输出约束:
          - 返回 0 表示成功（含无可回滚迁移），非 0 表示失败
        异常:
          - MigrationRollbackError: downgrade 不存在或执行失败
        """
        ...

    @abstractmethod
    def _do_generate_migration(
        self,
        message: MigrationMessage,
        autogenerate: bool,
    ) -> str:
        """生成迁移脚本的核心逻辑。

        实现者在此填写 alembic.command.revision 的实际调用流程。
        不需要关心 message 参数校验——@final generate_migration 已处理。

        输入约束:
          - message 已通过非空和长度校验
          - autogenerate 已通过类型校验
        输出约束:
          - 返回新生成的迁移脚本文件绝对路径
        异常:
          - MigrationGenerationError: 生成失败
        """
        ...

    @abstractmethod
    def _do_verify_migration(
        self,
        database_url: DatabaseUrl,
    ) -> tuple[int, str]:
        """执行迁移验证的核心逻辑。

        实现者在此填写三项检查的实际执行流程：
        alembic check → upgrade head → AST downgrade 检查。
        不需要关心 database_url 格式校验和连接验证——@final verify_migration 已处理。

        输入约束:
          - database_url 已通过 _validate_database_url_format 校验
          - 数据库连接已验证可用
        输出约束:
          - 返回 (exit_code, summary)
        异常:
          - MigrationVerificationError: 验证过程非预期错误
        """
        ...

    # ==================================================================
    # 校验器 — 模板提供基线校验，子类通过 super() 叠加
    # ==================================================================

    def _validate_target_format(
        self,
        target: MigrationTarget,
        allow_relative: bool = False,
    ) -> None:
        """验证 target 格式是否符合契约约束。

        基线校验：拒绝空字符串，验证格式匹配规则。
        allow_relative=True 时额外接受 "-N" 相对标记。

        异常:
          - MigrationScriptNotFoundError: 格式不符合要求。
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
                    f"Invalid target format: '{target}'. Expected 'head' or revision hash (YYYYMMDD_HHMMSS).",
                    target=target,
                )

    def _validate_database_url_format(
        self,
        database_url: DatabaseUrl,
    ) -> None:
        """验证 database_url 是否为合法的 PostgreSQL 连接串格式。

        基线校验：检查 postgresql:// 或 postgresql+driver:// 前缀。

        异常:
          - MigrationConnectionError: URL 为空或格式不正确。
        """
        if not database_url or not re.match(r"^postgresql(\+[a-z][a-z0-9]*)?://", database_url):
            raise MigrationConnectionError(
                f"Invalid database URL format: '{database_url}'. "
                "Expected postgresql:// or postgresql+driver:// prefix.",
                retries_attempted=0,
            )

    def _validate_generate_message(
        self,
        message: MigrationMessage,
        autogenerate: bool,
    ) -> None:
        """验证 generate_migration 的输入参数。

        基线校验：message 非空且不超过 128 字符，autogenerate 为 bool。

        异常:
          - ValueError: message 为空或过长。
          - MigrationGenerationError: autogenerate 不是 bool。
        """
        if not message or not message.strip():
            raise ValueError("message must be a non-empty string")
        if len(message) > 128:
            raise ValueError("message must not exceed 128 characters")
        if not isinstance(autogenerate, bool):
            raise MigrationGenerationError(f"autogenerate must be a boolean, got {type(autogenerate).__name__}.")

    def _validate_migration_result(
        self,
        result: int,
        direction: str,
        target: MigrationTarget,
    ) -> None:
        """后置校验：确认迁移结果符合预期。

        检查返回值类型并记录结果日志。
        子类可通过 super() 叠加更多后置条件。

        异常:
          - RuntimeError: 返回值类型不正确。
        """
        if not isinstance(result, int):
            raise RuntimeError(f"Migration {direction} returned non-int result: {type(result).__name__}")

        logger.info(
            "migration",
            f"migration_{direction}_completed",
            extra={"target": target, "exit_code": result},
            op_type=f"migrate_{direction}",
        )

    def _validate_generated_path(self, path: str) -> None:
        """后置校验：确认生成的迁移脚本路径有效。

        异常:
          - RuntimeError: 路径为空或不是 .py 文件。
        """
        if not path:
            raise RuntimeError("Generated migration path is empty")
        if not path.endswith(".py"):
            raise RuntimeError(f"Generated migration path is not a .py file: {path}")

    def _validate_verify_result(self, result: tuple[int, str]) -> None:
        """后置校验：确认 verify_migration 返回合法结果。

        检查返回值为 (exit_code, summary) 且 exit_code 在 0-3 范围。

        异常:
          - RuntimeError: 返回值结构不正确。
        """
        if not isinstance(result, tuple) or len(result) != 2:
            raise RuntimeError(f"verify_migration returned invalid result: {type(result).__name__}")
        exit_code, summary = result
        if not isinstance(exit_code, int) or exit_code not in (0, 1, 2, 3):
            raise RuntimeError(f"verify_migration returned invalid exit_code: {exit_code}")
        if not isinstance(summary, str):
            raise RuntimeError(f"verify_migration returned non-str summary: {type(summary).__name__}")

    def _validate_connection(
        self,
        database_url: DatabaseUrl,
    ) -> None:
        """验证数据库连接可用性（带重试）。

        基线校验：psycopg2 同步连接 + SELECT 1 测试，最大 3 次重试。
        认证失败不重试，直接抛出。

        异常:
          - MigrationConnectionError: 连接失败且重试耗尽，或认证失败。
        """
        last_error: Exception | None = None
        psycopg2_url = self._convert_url_to_psycopg2(database_url)

        for attempt in range(1, _CONNECTION_RETRY_MAX + 1):
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
                logger.info(
                    "migration",
                    "database_connection_verified",
                    extra={"attempt": attempt},
                    op_type="validate_connection",
                )
                return
            except (OperationalError, ProgrammingError) as exc:
                last_error = exc
                error_msg = str(exc)

                if self._is_auth_failure(error_msg):
                    raise MigrationConnectionError(
                        f"Database authentication failed: {error_msg}",
                        retries_attempted=attempt,
                    ) from exc

                logger.warning(
                    "migration",
                    "database_connection_failure",
                    extra={
                        "attempt": attempt,
                        "max_retries": _CONNECTION_RETRY_MAX,
                        "error": error_msg,
                    },
                    op_type="validate_connection",
                )

                if attempt < _CONNECTION_RETRY_MAX:
                    time.sleep(_CONNECTION_RETRY_INTERVAL_SECONDS)

        raise MigrationConnectionError(
            f"Database unreachable after {_CONNECTION_RETRY_MAX} retries: {last_error}",
            retries_attempted=_CONNECTION_RETRY_MAX,
        )

    # ==================================================================
    # 内部辅助：数据库连接解析
    # ==================================================================

    def _resolve_database_url(
        self,
        database_url: DatabaseUrl | None,
    ) -> DatabaseUrl:
        """解析数据库连接串（参数优先，否则读环境变量）。

        异常:
          - MigrationConnectionError: 参数和环境变量均为空。
        """
        url = database_url
        if not url:
            env_url = os.environ.get("DATABASE_URL")
            if env_url:
                url = DatabaseUrl(env_url)
        if not url:
            raise MigrationConnectionError(
                "DATABASE_URL not configured. "
                "Provide database_url parameter or set the DATABASE_URL environment variable.",
                retries_attempted=0,
            )
        return self._convert_url_to_psycopg2(url)

    def _convert_url_to_psycopg2(self, url: DatabaseUrl) -> DatabaseUrl:
        """将 asyncpg 连接串转换为 psycopg2 格式。

        Alembic DDL 操作必须通过 psycopg2 同步驱动执行。
        """
        if "asyncpg" in url:
            return DatabaseUrl(url.replace("+asyncpg", "+psycopg2"))
        return url

    # ==================================================================
    # 内部辅助：认证失败检测
    # ==================================================================

    @staticmethod
    def _is_auth_failure(error_msg: str) -> bool:
        """检测是否为认证失败（不应重试）。"""
        auth_keywords = (
            "password authentication failed",
            "no password supplied",
            "role",
            "authentication failed",
            "Ident authentication failed",
        )
        error_lower = error_msg.lower()
        return any(keyword.lower() in error_lower for keyword in auth_keywords)

    # ==================================================================
    # 内部辅助：Alembic Config 构建（供实现者使用）
    # ==================================================================

    @staticmethod
    def _build_alembic_config(
        database_url: DatabaseUrl | None = None,
    ) -> alembic.config.Config:
        """构建 Alembic Config 对象，注入数据库连接串和绝对路径。

        供 _do_ 钩子实现中调用。
        """
        # 定位 alembic.ini（packages/py-db/ 根目录）
        module_dir = Path(__file__).resolve().parent  # py_db/
        package_dir = module_dir.parent  # packages/py-db/
        ini_path = str(package_dir / "alembic.ini")

        resolved_url = database_url or DatabaseUrl(os.environ.get("DATABASE_URL", ""))

        cfg = alembic.config.Config(ini_path)
        if resolved_url:
            cfg.set_main_option("sqlalchemy.url", resolved_url)

        script_location = os.path.join(os.path.dirname(ini_path), "migrations")
        cfg.set_main_option("script_location", script_location)

        return cfg
