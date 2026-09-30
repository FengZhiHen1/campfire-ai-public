"""Alembic 运行环境。

设计要点（见 docs/项目结构设计.md 第 10 节与 docs/TODO.md 第五节）：

- **连接串唯一来源是 ``core/config``**，不在 ``alembic.ini`` 里写 URL——避免配置
  出现第二真相。
- **元数据唯一来源是 ``core/db.metadata``**；各模块的模型经
  ``campfire.modules.library.models`` 注册进去，迁移与运行期共用同一份。
- **禁用 ``--autogenerate`` 删除不归本项目管理的表**：SuperTokens core 在自己的库内
  建表（技术栈设计第 4 节），SDK 也会建 ``agent_sessions``/``agent_messages``。这些表
  与 Alembic 自己的 ``alembic_version`` 都必须排除在比较之外，否则一次自动生成就会
  产出删表迁移——这是 AGENTS.md 明文禁止的。
  **实测更正（2026-09-29）**：这些表**没有前缀**，按前缀排除的实现在本库完全失效
  （实测 56 张无前缀表会被判为「该删掉」）。过滤器因此改为白名单，判据与理由见
  ``include_object``。若将来接入第二个外部组件，**不要**给它加前缀名单——白名单已覆盖。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# 导入模型以注册进 metadata：不导入则 autogenerate 认为「表全都该删」。
from campfire.core import pending_write as pending_write_models  # noqa: F401  —— 仅为注册副作用
from campfire.core.auth import tombstone as auth_tombstone_models  # noqa: F401  —— 仅为注册副作用
from campfire.core.config import get_settings
from campfire.core.db import metadata
from campfire.modules.accounts import models as accounts_models  # noqa: F401  —— 仅为注册副作用
from campfire.modules.library import models  # noqa: F401  —— 仅为注册副作用
from campfire.modules.memory import models as memory_models  # noqa: F401  —— 仅为注册副作用
from campfire.modules.profile import models as profile_models  # noqa: F401  —— 仅为注册副作用

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def include_object(_object: object, name: str | None, type_: str, reflected: bool, _compare_to: object) -> bool:
    """autogenerate 的比较过滤器：**只管理本项目自己的表**（白名单）。

    ## 为什么是白名单，而不是「排除外部表名前缀」

    原实现按前缀排除（``supertokens_``、``agent_sessions``…）。**2026-09-29 实测该实现
    完全失效**：SuperTokens core 建的表**没有前缀**——实测本库有 56 张无前缀表
    （``session_info``、``emailpassword_users``、``tenants``、``apps``、
    ``all_auth_recipe_users``、``webauthn_users``…），前缀一个都没命中。因此
    ``--autogenerate`` 会产出 **56 条 remove_table + 106 条 remove_index** 的删表迁移，
    正好是 AGENTS.md 与 [项目结构设计] 第 10 节明文禁止的事（一次自动生成即摧毁全部
    身份与会话数据）。

    前缀法还有个结构性缺陷：它要求我们**穷举**外部组件的表名，而外部组件的表集随版本
    增长（本次实测的 56 张里含 webauthn/saml/oauth/totp 等本项目**根本不用**的 recipe）。
    每升级一次 core 就可能多出一批新表要补进名单，漏一个就是一次删表迁移。

    改为白名单后，判据反转为**「在 ``core/db.metadata`` 里才管理」**：任何不在我方
    元数据里的表（外部组件的、Alembic 自己的、将来第三方加的）一律不碰。判据从
    「我知道哪些不是我的」变成「我只动我声明过的」，与模块边界同一种思路。

    **取舍（显式写入）**：删表不再由 ``--autogenerate`` 提出——从模型里去掉一张表后，
    autogenerate 不会生成 ``drop_table``，**删除迁移必须手写**。这是**有意**的代价：
    本项目历史上没有任何一次「由 autogenerate 删表」是安全的，而漏一次删表只是多一次
    人工动作。新增与改列不受影响（那是 metadata 侧的表）。

    Args:
        _object: 被比较的对象（表/索引/列）。
        name: 对象名。
        type_: 对象类型（``table`` / ``index`` / ``column`` …）。
        reflected: True 表示该对象来自**数据库反射**（而非我方元数据）。
        _compare_to: 比较对象，本过滤器不关心。

    Returns:
        True 表示纳入 autogenerate 的比较范围。
    """
    if type_ == "table" and reflected:
        # 只放行我方元数据里声明过的表；其余（SuperTokens 的 56 张、SDK 自建表、
        # alembic_version）全部排除在比较之外。
        return name in target_metadata.tables
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
