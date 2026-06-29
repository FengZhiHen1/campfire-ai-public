"""Alembic 运行时环境配置 — DEPLOY-04 数据库迁移。

配置 target_metadata、连接引擎、事务模式，供 alembic.command.* 调用。

关键约束：
- 同步驱动强制：DDL 操作使用 psycopg2，禁止使用 asyncpg
- transaction_per_migration = True：每份迁移脚本在独立事务中执行
- 连接串从 DATABASE_URL 环境变量读取（支持 asyncpg/psycopg2 双协议自动转换）
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Alembic Config 对象，提供 .ini 文件中的配置值
config = context.config

# 配置日志（读取 alembic.ini 中的 [loggers] 等章节）
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# target_metadata — 指向所有 ORM 模型的声明式基类
# ---------------------------------------------------------------------------
# 导入 Base，Alembic autogenerate 通过比对 Base.metadata 与数据库实际结构
# 差异来生成迁移脚本。
#
# 当前指向空 Base（models 尚未定义具体表）。
# 待 models/ 下各模块定义具体表后，Base.metadata 自动包含全部表结构。
from py_db.models.base import Base  # noqa: E402

target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# 数据库连接串解析
# ---------------------------------------------------------------------------


def _resolve_db_url() -> str:
    """从环境变量或 alembic.ini 解析数据库连接串。

    优先级：
    1. 环境变量 DATABASE_URL
    2. alembic.ini [alembic] sqlalchemy.url

    若连接串使用 asyncpg 协议（postgresql+asyncgp://），自动转换为
    psycopg2 协议（postgresql+psycopg2://），因为 Alembic DDL 操作
    必须通过同步驱动执行。

    Returns:
        psycopg2 格式的连接串。

    Raises:
        RuntimeError: 未配置 DATABASE_URL 且 alembic.ini 中无 sqlalchemy.url。
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not configured. "
            "Set the DATABASE_URL environment variable or "
            "configure sqlalchemy.url in alembic.ini."
        )

    # 若连接串使用 asyncpg 驱动，转换为 psycopg2 同步驱动
    if "asyncpg" in url:
        url = url.replace("+asyncpg", "+psycopg2")
    return url


# ---------------------------------------------------------------------------
# 事务模式 — 每份迁移脚本独立事务
# ---------------------------------------------------------------------------
# 不通过 get_section 传递此配置，直接在 run_migrations_online 中硬编码以确保
# transaction_per_migration 在所有环境下均强制执行。
_TRANSACTION_PER_MIGRATION: bool = True


def _include_object(object, name, type_, reflected, compare_to):
    """过滤不应由 Alembic autogenerate 管理的对象。

    pgvector 的 vector 类型列和 HNSW 索引不在 ORM 模型中映射，
    若参与比较会被误判为需要删除。此处显式排除。
    """
    if type_ == "column" and name == "embedding" and getattr(object, "table", None) is not None and object.table.name == "case_chunks":
        return False
    if type_ == "index" and name == "ix_case_chunks_embedding_hnsw":
        return False
    return True


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本而不连接数据库。

    在此模式下，Alembic 输出纯 SQL 文本而非实际执行 DDL。
    用于生成可审查的 SQL 预览或在不联网环境中产出 DDL 脚本。
    """
    url = _resolve_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transaction_per_migration=_TRANSACTION_PER_MIGRATION,
        include_object=_include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库并执行 DDL 操作。

    通过 engine_from_config 创建同步引擎（psycopg2），
    每份迁移脚本在独立 PostgreSQL 事务中执行。
    """
    db_url = _resolve_db_url()

    # 构建引擎配置 — 仅使用必要的连接参数
    engine_config = config.get_section(config.config_ini_section, {})
    engine_config["sqlalchemy.url"] = db_url

    connectable = engine_from_config(
        engine_config,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transaction_per_migration=_TRANSACTION_PER_MIGRATION,
            include_object=_include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Alembic 入口 — 根据 --sql 标记选择在线/离线模式
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
