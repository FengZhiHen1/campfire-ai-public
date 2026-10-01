"""引用索引表：让输出里的每条引用都能回指到业务条目。

职责：声明 `campfire_citation` 的表形状，让 Alembic 建表；供装配处的端口实现
（`surfaces/consult/citations.py`）读写。
边界：只声明存储形状；不 import `agent/*`（见下方归属说明），不提供用例接口。
参考：docs/技术设计/technical-details/通用基座.md 第 4 节；docs/项目结构设计.md 第 10 节。

为什么这张表归 `core/db`（而不是 `agent/` 或某个 `modules/*`）：

- 端口 `CitationIndex` 与记录形状 `CitationRecord` 属基座（`agent/context/citations.py`），
  但 `agent/*` 只允许依赖 `core/config`——基座不持有连接池、也不建表（该模块的
  docstring 明写「持久化实现由装配处提供」）。
- `core/*` 不得依赖 `agent/*`，因此本模块不 import `CitationRecord`，只声明列。
  「行 ↔ 记录」的转换由装配处的实现做（先例：`core/db/sdk_session.py` 声明 SDK 的表，
  映射由读它的模块做）。
- 表没有单一业务模块所有者：引用的回指对象可以是资料、案例、档案条目或记忆条目，
  四个模块都可能被引用。表归属的默认规则（与模块同名）在这里无解，故按
  `sdk_session.py` 的同一判据落在 `core/db`。
- 迁移白名单的判据是「在 `core/db.metadata` 里才管理」（`migrations/env.py` 的
  `include_object`）。不注册进这份元数据，迁移就建不出这张表。

表名用 `campfire_` 前缀（`core/db` 的约定），避免与 SuperTokens core 自建表撞名。
`data_` 前缀保留给 LlamaIndex，本项目自己的模型不得使用。
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from sqlalchemy import BigInteger, DateTime, Identity, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from campfire.core.db import Base

#: 表名。装配处的实现与迁移都按它引用，写成常量避免两处字面量漂移。
CITATION_TABLE_NAME: Final = "campfire_citation"

#: `citation_id` 的列宽。默认标识工厂产出 `uuid4().hex`（32 字符），留一倍余量以容纳
#: 将来换用带连字符或带前缀的标识，而不必为此改一次表。
MAX_CITATION_ID_LENGTH: Final = 64

#: `run_id` 的列宽。与 `random.Random` 无关：运行标识目前是 `uuid4().hex`（32 字符），
#: 同样留一倍余量。它同时是 `list_for_run` 的查询键。
MAX_RUN_ID_LENGTH: Final = 64

#: `source` 的列宽。来源是「哪个数据通道」一类的短标识（例如 `knowledge`、`profile`），
#: 不是自由文本，因此给一个有界宽度而不是 `Text`——无界列会让一次笔误把整段正文写进来。
MAX_SOURCE_LENGTH: Final = 128


class Citation(Base):
    """一条引用记录：来源、时间与指向的业务标识。

    第 4 节的不变量「没有索引记录的注入消息不得成为可引用依据」由写入路径保证
    （`CitationRecorder` 先写索引再发凭据），本表是那个写入的落点。

    写入顺序必须可复原（端口契约：`list_for_run` 按写入顺序返回），因此除主键外
    另有一列自增序号 `seq`——不靠 `recorded_at` 排序：时钟可由装配处注入，
    同一微秒内的两条记录用时间戳无法定序。序号由数据库生成（`Identity`），
    应用侧不赋值，因此并发写入不会拿到同一个序号。
    """

    __tablename__ = CITATION_TABLE_NAME

    #: 引用标识（面向使用者的稳定回指键），同时是超时重试的幂等键：端口契约要求
    #: 「要么让写入按 `citation_id` 幂等，要么在超时后按该标识核实」，实现选用前者，
    #: 因此这里是主键（重复写入被 `ON CONFLICT DO NOTHING` 吸收）。
    citation_id: Mapped[str] = mapped_column(String(MAX_CITATION_ID_LENGTH), primary_key=True)
    #: 写入序号，唯一且由数据库自增。`list_for_run` 按它排序即为写入顺序。
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    #: 产生这条引用的运行。`run_finished` 的引用清单按它取用。
    run_id: Mapped[str] = mapped_column(String(MAX_RUN_ID_LENGTH), nullable=False)
    #: 来源标识（例如某个数据通道或存储的名字）。
    source: Mapped[str] = mapped_column(String(MAX_SOURCE_LENGTH), nullable=False)
    #: 指向的业务标识，权威在业务条目本身。用 `Text` 而不是定长：它可能是复合键
    #: （库别 + 条目 id + 块序号），形状由业务侧拥有，本表只存值不问形状。
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    #: 记录时间（带时区）。取记录方给的时刻而不是 `now()`：记录方可能注入时钟，
    #: 用库时间会让同一批记录的时间来源有两个。
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: 一句话摘要，供面展示；不影响回指。
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # `list_for_run` 的唯一查询形状：按运行取全部记录并按写入顺序排。
        # 复合索引而不是两个单列索引：查询恒带 `run_id`，且排序键紧随其后，
        # 这样排序不需要额外的一次 sort。
        Index("ix_campfire_citation_run_seq", "run_id", "seq"),
        {"comment": "引用索引：注入项的可回指凭据（不是对话的第二份真源）"},
    )


__all__ = [
    "CITATION_TABLE_NAME",
    "MAX_CITATION_ID_LENGTH",
    "MAX_RUN_ID_LENGTH",
    "MAX_SOURCE_LENGTH",
    "Citation",
]
