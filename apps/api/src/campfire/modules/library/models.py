"""专业资料与案例的表结构：条目（事实真源）与检索节点（投影）。

职责：声明条目表与检索节点表的映射、索引与约束，供迁移与检索链使用。
边界：不定义检索行为；节点表结构必须与 `PGVectorStore` 期望的逐列一致。
参考：docs/项目结构设计.md 第 6 节；docs/技术设计/technical-details/RAG策略.md 第 2 节；docs/技术设计/decisions/检索链归入library模块.md；细节见 `KnowledgeItem` 与 `RetrievedNode` 的 docstring。
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from campfire.core.config import EMBEDDING_DIM
from campfire.core.db import Base, Vector, new_uuid

#: 嵌入维度常量由 :mod:`campfire.core.config` 拥有（它与嵌入模型名同处唯一配置点，
#: 因为检索链与记忆侧必须共用同一维度，而 `modules/*` 之间不得互相 import）；
#: 此处只转出，供迁移与调用方从本模块取用。
__all__ = [
    "EMBEDDING_DIM",
    "LIBRARY_CASE",
    "LIBRARY_KNOWLEDGE",
    "KnowledgeItem",
    "RetrievedNode",
]

#: 库别：资料库与案例库是两个独立集合，不合并成一张表加类型标签（`RQ-KB-01`）。
LIBRARY_KNOWLEDGE = "knowledge"
LIBRARY_CASE = "case"


class KnowledgeItem(Base):
    """专业资料条目（研究、指南、机构材料）。

    字段依据：`docs/技术设计/technical-details/资料与案例检索.md` 第 1 节
    「每个条目必须有：来源、适用范围、状态、版本与撤下标记」（`RQ-KB-02`），
    以及 RAG 策略第 1.4 节（`keywords`/`aliases` 供字面路使用）。

    归属（见 docs/项目结构设计.md 第 6 节与
    docs/技术设计/decisions/检索链归入library模块.md）：条目表与检索链同属本模块。
    """

    __tablename__ = "campfire_knowledge_item"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    #: 出处：机构、年份、链接或文件引用。缺来源的条目不进入检索（不变量）。
    source: Mapped[str] = mapped_column(Text, nullable=False)
    #: 适用人群与情境；同时是 `search_knowledge` 的 `scope` 过滤维度。
    applicable_scope: Mapped[str] = mapped_column(Text, nullable=False)
    #: 版本与撤下标记（`RQ-KB-02`、`RQ-KB-04`）。
    version: Mapped[str] = mapped_column(String(100), nullable=False, server_default=sql_text("'1'"))
    withdrawn: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("false"))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 状态固定为 `published`（资料侧无授权维度）；保留列以便与案例侧同形。
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=sql_text("'published'"))
    #: 字面路字段。用文本列而不是数组：`pg_trgm` 的 `gin_trgm_ops` 操作符类
    #: 不接受 `text[]`（实测报 "operator class gin_trgm_ops does not accept data type
    #: text[]"），而 `array_to_string` 表达式索引又不被允许（非 IMMUTABLE）。
    #: 约定以空格分隔多值；字面路用 `LIKE '%词%'` 匹配。
    keywords: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    aliases: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    #: 摄取来源文件与批次，供撤下时回溯（RAG 策略第 7 节纪律 3）。
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )

    __table_args__ = (
        # 字面路的三个 GIN trigram 索引（RAG 策略第 3.1 节）。中文约束已实测：
        # 需 ≥3 个连续汉字才产生三元组，且必须用 LIKE/ILIKE 才走索引。
        Index(
            "ix_campfire_knowledge_item_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_campfire_knowledge_item_keywords_trgm",
            "keywords",
            postgresql_using="gin",
            postgresql_ops={"keywords": "gin_trgm_ops"},
        ),
        Index(
            "ix_campfire_knowledge_item_aliases_trgm",
            "aliases",
            postgresql_using="gin",
            postgresql_ops={"aliases": "gin_trgm_ops"},
        ),
        # 检索按状态与撤下过滤（不变量：过滤在 SQL 内完成）。
        Index("ix_campfire_knowledge_item_withdrawn_status", "withdrawn", "status"),
        # 摄取幂等：同一文件同一 hash 不重复入库（RAG 策略第 7 节）。
        UniqueConstraint("source_path", "doc_hash", name="uq_campfire_knowledge_item_source_doc"),
        # 表注释必须与迁移 113a04901d24 建表时写的一致：ORM 未声明时
        # `--autogenerate` 会产出 drop_table_comment（见 RetrievedNode 的同类说明）。
        {"comment": "专业资料条目：事实真源（内容与来源字段的权威）"},
    )


class RetrievedNode(Base):
    """检索节点表：条目表的投影，结构必须与 `PGVectorStore` 期望的一致。

    ⚠️ 本表由迁移建出后，`PGVectorStore` 以 `perform_setup=False` 使用它。
    列名与类型不可随意改（`id`/`text`/`metadata_`/`node_id`/`embedding`），
    因为框架按这些名字读写；改动必须同步框架版本并重跑集成测试。

    表名 `data_campfire_node` → 框架渲染为 `data_` 前缀的约定见 RAG 策略第 2 节。

    两张表的关系（RAG 策略第 2 节）：条目表是事实真源——状态、撤下、来源、
    适用范围、`keywords`/`aliases` 都由它拥有；节点表是它的投影，供向量检索使用。
    投影不是第二真源，但需要在 SQL 层过滤的字段必须同时写进节点 metadata，
    否则过滤会掉到应用层，违反「过滤在 SQL 内完成」的不变量。

    节点表为什么不用 ORM 声明：它由 LlamaIndex 的 `PGVectorStore` 自带表结构
    （表名 `data_<table_name>`、`id bigint` + sequence 自增、`metadata_ jsonb`、
    `embedding vector(N)`），已实测（TECH-19，2026-09-29）。我们用 Alembic 建出
    与之逐列一致的结构并令 `perform_setup=False`，因此该表在这里只导出
    供迁移使用的 SQLAlchemy 表对象，不注册进 `Base.metadata` 之外的 ORM 映射——
    避免两处定义漂移。
    """

    __tablename__ = "data_campfire_node"

    #: 框架期望 bigint + sequence 自增；缺 sequence 会写入失败（TECH-19 实测）。
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    #: 节点正文（分块后的文本）。用 varchar 而非 text：框架建出的是
    #: `character varying`，此处保持一致，否则 `--autogenerate` 会反复生成改列类型的迁移。
    text: Mapped[str] = mapped_column(String, nullable=False)
    #: 框架的 metadata JSONB 列，名字带尾下划线（框架固定）。
    metadata_: Mapped[dict | None] = mapped_column("metadata_", JSONB, nullable=True)
    #: 框架写入的节点标识。
    node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    #: 向量列；一期不建向量索引（几万节点内精确检索保证召回 100%）。
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    __table_args__ = (
        # 框架自建时只建 metadata_->>'ref_doc_id' 的表达式索引；我们保持一致，
        # 并补上检索真正需要的过滤维度（条目归属、库别、撤下）。
        # 说明：不对 `node_id` 建唯一约束——框架自己不建，擅自加会让重复写入
        # 由「覆盖」变成「报错」；这里用普通索引支撑按 node_id 查找。
        Index("ix_data_campfire_node_ref_doc_id", sql_text("((metadata_ ->> 'ref_doc_id'))")),
        Index("ix_data_campfire_node_node_id", "node_id"),
        Index("ix_data_campfire_node_item_id", sql_text("((metadata_ ->> 'item_id'))")),
        Index("ix_data_campfire_node_library", sql_text("((metadata_ ->> 'library'))")),
        Index("ix_data_campfire_node_withdrawn", sql_text("((metadata_ ->> 'withdrawn'))")),
        # 表注释必须在此声明：迁移 113a04901d24 建表时写了 comment，而 ORM 未声明，
        # 于是 `--autogenerate` 会反复产出「drop_table_comment」——一个与本次改动
        # 无关的破坏性操作（2026-09-29 实测：生成删除账本迁移时同时产出两条）。
        # ORM 侧已声明 comment：metadata 与库内实际一致，autogenerate 不再漂移。
        {"comment": "检索节点：条目表的投影，供 PGVectorStore 读写（perform_setup=False）"},
    )
