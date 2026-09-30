"""会话：对话的唯一真源，落在我们自己的 PostgreSQL。

依据 docs/技术设计/technical-details/通用基座.md 第 2 节的真源划分（事实 → 真源）：

- 对话（用户消息、助手消息、工具调用与结果、注入的消息） → SDK 的会话存储（本地，落在我们的 PostgreSQL）

唯一，不另存副本。所以本模块只做一件事：把 SDK 提供的会话实现按我们的配置装配起来，
不包一层自己的对话表——另存副本正是第 2 节要避免的。

两处边界：

- 引擎由装配处注入。`agent/*` 只允许依赖 `core/config`（docs/项目结构设计.md 第 7 节），
  连接池的所有权在 `core/db`；基座自己建引擎会多出一个连接池，且绕过 `core/db` 的所有权。
- 建表由 Alembic 负责。`create_tables=False` 是默认值：表结构属于迁移文件
  （`❌ 禁止：手动修改生产数据库 schema 而不通过迁移文件`）。置 `True` 只用于本地一次性
  试验，且不会带上中文迁移注释与审阅。
"""

from __future__ import annotations

from collections.abc import Callable

from agents.extensions.memory.sqlalchemy_session import SQLAlchemySession
from agents.memory.session import Session
from sqlalchemy.ext.asyncio import AsyncEngine

from .errors import SessionConfigurationError

SessionFactory = Callable[[str], Session]
"""按会话标识造会话；由装配处提供（例如 `functools.partial(build_sqlalchemy_session, engine=engine)`）。"""


def build_sqlalchemy_session(
    session_id: str,
    *,
    engine: AsyncEngine,
    create_tables: bool = False,
) -> Session:
    """按会话标识造一个 SDK 会话。

    `create_tables=True` 会让 SDK 建它自己的两张表（`agent_sessions` /
    `agent_messages`）。这两张表目前没有登记在任何设计文档与迁移里，而
    docs/项目结构设计.md 第 187 行要求表归属与模块同名——因此默认关闭，只在本地开发与
    测试里显式打开；生产路径必须由 Alembic 迁移建表（技术栈设计第 1 节），并先为这两张表
    定下归属与命名。登记于 docs/TODO.md。

    Raises:
        SessionConfigurationError: `session_id` 为空或只有空白——没有标识就无法保证两次
            运行落在同一条对话上，那会让「对话是唯一真源」失去意义；纯空白同样不能定位
            （实测 `"   "` 会被单纯的真值判断放过）。
    """
    if not session_id.strip():
        raise SessionConfigurationError("会话标识不能为空：对话真源必须能被稳定定位")
    return SQLAlchemySession(session_id, engine=engine, create_tables=create_tables)
