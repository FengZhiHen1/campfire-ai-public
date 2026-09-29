"""Alembic 运行环境。

设计要点（见 docs/项目结构设计.md 第 10 节与 docs/TODO.md 第五节）：

- **连接串唯一来源是 ``core/config``**，不在 ``alembic.ini`` 里写 URL——避免配置
  出现第二真相。
- **元数据唯一来源是 ``core/db.metadata``**；各模块的模型经
  ``campfire.modules.library.models`` 注册进去，迁移与运行期共用同一份。
- **禁用 ``--autogenerate`` 对 Supervisor 之外对象的删除**：SuperTokens core 在
  自己的库内建表（技术栈设计第 4 节），SDK 也会建 ``agent_sessions``/
  ``agent_messages``。这些表不归本项目迁移管理，必须从 autogenerate 的比较中
  排除，否则一次自动生成就会产出删表迁移——这是 AGENTS.md 明文禁止的。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from campfire.core.config import get_settings
from campfire.core.db import metadata

# 导入模型以注册进 metadata：不导入则 autogenerate 认为「表全都该删」。
from campfire.modules.library import models  # noqa: F401  —— 仅为注册副作用
from campfire.modules.memory import models as memory_models  # noqa: F401  —— 仅为注册副作用

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata

# 不归本项目迁移管理的表：SuperTokens core 自建表、SDK 自建会话表。
# 它们由各自的组件创建与维护；autogenerate 必须忽略，否则会生成删表迁移。
EXTERNAL_TABLE_PREFIXES = (
    "supertokens_",  # SuperTokens core 在自己的库里建的表
    "agent_sessions",  # OpenAI Agents SDK 的 SQLAlchemySession 自建表
    "agent_messages",
    "alembic_version",  # Alembic 自己的版本表
)


def include_object(_object: object, name: str | None, type_: str, _reflected: bool, _compare_to: object) -> bool:
    """autogenerate 的比较过滤器：排除外部组件的表。"""
    if type_ == "table" and name is not None:
        return not any(name == prefix or name.startswith(prefix) for prefix in EXTERNAL_TABLE_PREFIXES)
    return True


def _database_url() -> str:
    """从 ``core/config`` 取连接串（``postgresql+asyncpg://``）。

    迁移与运行期用同一个 asyncpg 驱动，不引入第二套同步驱动依赖。
    """
    url = get_settings().database_url
    if not url:
        raise RuntimeError("未配置 DATABASE_URL，无法执行迁移")
    return url


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连库。"""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在给定连接上执行迁移（异步引擎经 ``run_sync`` 调用到此）。"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """用 asyncpg 建连并执行迁移；不复用应用侧连接池（迁移是单次命令行）。"""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()

    connectable = async_engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式：连库执行迁移。"""
    import asyncio

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
