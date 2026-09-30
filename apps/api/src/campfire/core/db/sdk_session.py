"""SDK 会话存储的两张表：登记进 `core/db.metadata`，使其进入迁移白名单。

职责：声明 `agent_sessions` / `agent_messages` 的表形状与表名常量，让 Alembic 建表、
运行期不建表；供需要只读这些表的模块（`modules/accounts` 的会话列表与水合）引用表名。
边界：只声明存储形状与只读表名常量；对话读写仍归 SDK 的 `SQLAlchemySession`，
本模块不提供任何增删改接口。
参考：docs/项目结构设计.md 第 10 节；docs/TODO.md「SDK 自建表未登记」条；
docs/技术设计/technical-details/通用基座.md 第 2 节。

为什么这两张表归 `core/db`（而不是 `modules/*` 或 `agent/*`）：

表归属的默认规则是「与模块同名」（项目结构设计第 10 节），但这两张表没有业务模块
所有者——它们是 SDK 的会话存储，由框架定义形状。三条硬约束叠加后只剩这一个落点：

- 迁移白名单的判据是「在 `core/db.metadata` 里才管理」（`migrations/env.py` 的
  `include_object`）。不把模型注册进这份元数据，迁移就建不出这两张表，
  而运行期保持 `create_tables=False`——结果是两边各建一套或都不建
  （TODO「SDK 自建表未登记」条明写了这个后果）。
- `modules/accounts` 的水合与列表要按 `session_id` 只读它们，而 `modules` 层的
  白名单只有 `campfire.core`（项目结构设计第 7 节）——表名常量必须能从 `core` 取到。
- `agent/*` 只允许依赖 `core/config`，且 `core/*` 不得依赖 `agent/*`；把模型放
  `agent/` 会让迁移反向依赖基座，放 `modules/` 则 `accounts` 之外无处置身，
  且会让一个业务模块「拥有」框架表。

表形状必须与 SDK 的实现逐列一致，否则 `--autogenerate` 会产出改列迁移，而改
SDK 的表正是决策记录否决过的做法（会话归属单立表归 accounts 的「被否决项」）。
一致性由 `apps/api/tests/test_accounts_sessions_integration.py` 机械核对：
它把 SDK 自己建的表反射出来，与本模块声明的列/索引逐项比对。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from campfire.core.db import Base

#: SDK 会话表的表名。SDK 的 `SQLAlchemySession` 以这两个名字为默认值
#: （构造参数 `sessions_table` / `messages_table`），装配处不得改名——
#: 改名会让迁移建的表与 SDK 读写的表不是同一张。
SDK_SESSIONS_TABLE_NAME = "agent_sessions"

#: SDK 消息表的表名。
SDK_MESSAGES_TABLE_NAME = "agent_messages"

#: SDK 消息表上那条复合索引的名字。逐个字符对上 SDK 的实现：索引名是 autogenerate
#: 会比较的对象，写错一个字就会产出一条「改索引」迁移。
SDK_MESSAGES_INDEX_NAME = "idx_agent_messages_session_time"


class AgentSession(Base):
    """SDK 的会话行：一条对话的登记与活动时间。

    它不含 `account_id`——这正是 `campfire_session` 必须单独存在的原因
    （决策记录：没有任何真源能判定一个会话属于哪个账号）。因此本表不是归属真源，
    `modules/accounts` 只读它取活动时间。

    时间戳是 `timestamp without time zone`（SDK 如此声明，且默认值取
    `CURRENT_TIMESTAMP`）。照抄类型而不是「修正」为带时区：改列类型会让
    `--autogenerate` 提议一条改列迁移，而改 SDK 的表等于制造未登记的分叉。
    """

    __tablename__ = SDK_SESSIONS_TABLE_NAME

    #: 会话标识，主键。SDK 声明为无界 `String`。
    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    #: 本行创建时间（SDK 在首次写入条目时插入本行）。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )
    #: 最近一次写入条目的时间。SDK 的 `add_items` 每次写入都刷新它，
    #: 因此它是「该会话最近有活动」的权威时间——会话列表取它当 `updated_at`，
    #: 而不是在 `campfire_session` 里再造一列（派生值不落库）。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=sql_text("CURRENT_TIMESTAMP"),
        onupdate=sql_text("CURRENT_TIMESTAMP"),
    )

    __table_args__ = ({"comment": "SDK 会话存储：对话真源，由 Alembic 建表、运行期只读写不改形状"},)


class AgentMessage(Base):
    """SDK 的消息行：一条持久化的对话条目（JSON 文本）。

    `message_data` 是 SDK 序列化后的输入项，形状随条目类型变化
    （使用者消息、助手消息、思考项、工具调用与结果、注入消息），因此不在存储层
    解析——那会让表形状随 SDK 的条目联合类型漂移。解析归读取方
    （`modules/accounts` 的会话列表与水合）。

    没有 `role` 列：角色在 JSON 里。加一列等于把 SDK 的序列化格式复制进我们的
    schema，SDK 升级就会让两处不一致。
    """

    __tablename__ = SDK_MESSAGES_TABLE_NAME

    #: 自增主键。同一秒内写入多条时，它是唯一的顺序依据（`created_at` 的
    #: 精度只到秒），因此读取一律按 `(created_at, id)` 排序。
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: 所属会话。级联删除由数据库执行：删会话即删它的全部消息。
    session_id: Mapped[str] = mapped_column(
        String,
        ForeignKey(f"{SDK_SESSIONS_TABLE_NAME}.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    #: 序列化后的条目（JSON 文本）。SDK 用 `json.dumps` 写入，读取方负责解析。
    message_data: Mapped[str] = mapped_column(Text, nullable=False)
    #: 写入时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        # 按会话取消息的时间序走它；名字必须是 SDK 用的那一个（见上方常量说明）。
        Index(SDK_MESSAGES_INDEX_NAME, "session_id", "created_at"),
        {"comment": "SDK 会话存储：每条对话条目的序列化文本，由 Alembic 建表"},
    )


__all__ = [
    # 表名（读取方按它只读这两张表）
    "SDK_MESSAGES_INDEX_NAME",
    "SDK_MESSAGES_TABLE_NAME",
    "SDK_SESSIONS_TABLE_NAME",
    # 模型（注册进 core/db.metadata，供迁移建表）
    "AgentMessage",
    "AgentSession",
]
