"""专业资料与案例的表结构：条目（事实真源）与检索节点（投影）。

职责：声明条目表与检索节点表的映射、索引与约束，供迁移与检索链使用。
边界：不定义检索行为；节点表结构必须与 `PGVectorStore` 期望的逐列一致。
参考：docs/项目结构设计.md 第 6 节；docs/技术设计/technical-details/RAG策略.md 第 2 节；docs/技术设计/decisions/检索链归入library模块.md；细节见 `KnowledgeItem` 与 `RetrievedNode` 的 docstring。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from campfire.core.config import EMBEDDING_DIM
from campfire.core.db import Base, Vector, new_uuid

#: 嵌入维度常量由 :mod:`campfire.core.config` 拥有（它与嵌入模型名同处唯一配置点，
#: 因为检索链与记忆侧必须共用同一维度，而 `modules/*` 之间不得互相 import）；
#: 此处只转出，供迁移与调用方从本模块取用。
__all__ = [
    # 常量
    "CASE_STATUSES",
    "EMBEDDING_DIM",
    "EVIDENCE_LEVELS",
    "ITEM_MODELS",
    "ITEM_TABLES",
    "LIBRARIES",
    "LIBRARY_CASE",
    "LIBRARY_KNOWLEDGE",
    "MANUAL_REVIEW_TABLE",
    "NODE_TABLE",
    "REVIEW_STATUSES",
    "SUBJECT_TYPES",
    # 模型
    "CaseItem",
    "KnowledgeItem",
    "ManualReviewItem",
    "RetrievedNode",
    # 库别映射
    "as_case_item",
]

#: 库别：资料库与案例库是两个独立集合，不合并成一张表加类型标签（`RQ-KB-01`）。
LIBRARY_KNOWLEDGE = "knowledge"
LIBRARY_CASE = "case"

# ---------------------------------------------------------------------------
# 案例专属字段的取值域（公共案例库第 3、4、7 节）
# ---------------------------------------------------------------------------
#
# 为什么这些值域不只是在 Python 里校验、还要落成 CHECK 约束（CORE-05：不变量落
# 最强可行通道）：它们驱动「多可信、谁说的」的呈现判定（review_status 决定能否
# 作为依据、evidence_level 决定信任度），静默写入未知值会让呈现规则无声失效——
# 写入者包含将来的运维旁路与手工 SQL，CHECK 是唯一能一并拒绝它们的通道。

#: 案例状态。`fictional` 是虚构样例：它与真实案例必须可辨（`AC-06`），
#: 因此取值域是封闭的——多出第四种状态就没有对应的呈现规则。
CASE_STATUSES: frozenset[str] = frozenset({"published", "internal", "fictional"})

#: 审阅状态（第 7 节三档）。`owner` 不等于专业审阅，系统不得把它显示为专业审阅。
REVIEW_STATUSES: frozenset[str] = frozenset({"professional", "owner", "pending"})

#: 循证等级（沿用上游值域，公共案例库第 4 节「值域不重写」）。
EVIDENCE_LEVELS: frozenset[str] = frozenset({"EBP", "INSTITUTIONAL", "OBSERVATIONAL"})

#: 被访谈对象的类型（第 3 节）。
SUBJECT_TYPES: frozenset[str] = frozenset({"家长", "老师", "专业人员", "其他"})

#: 用于 `CHECK` 的 SQL 字面量。从上面的集合派生，避免两份清单漂移；排序保证文本稳定。
_CASE_STATUSES_SQL = ", ".join(f"'{value}'" for value in sorted(CASE_STATUSES))
_REVIEW_STATUSES_SQL = ", ".join(f"'{value}'" for value in sorted(REVIEW_STATUSES))
_EVIDENCE_LEVELS_SQL = ", ".join(f"'{value}'" for value in sorted(EVIDENCE_LEVELS))
_SUBJECT_TYPES_SQL = ", ".join(f"'{value}'" for value in sorted(SUBJECT_TYPES))

#: 检索节点表名。两库共用一张节点表，库别写在节点 metadata 的 `library` 键上
#: （节点表本身没有 library 列，因此加字段只需投影，不需要改表结构）。
NODE_TABLE = "data_campfire_node"


class KnowledgeItem(Base):
    """专业资料条目（研究、指南、机构材料）。

    字段依据：`docs/技术设计/technical-details/资料与案例检索.md` 第 1 节
    「每个条目必须有：来源、适用范围、状态、版本与撤下标记」（`RQ-KB-02`），
    以及 RAG 策略第 1.4 节（`keywords`/`aliases` 供字面路使用）。

    归属（见 docs/项目结构设计.md 第 6 节与
    docs/技术设计/decisions/检索链归入library模块.md）：条目表与检索链同属本模块。
    """

    __tablename__ = "campfire_knowledge_item"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_uuid)
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


class CaseItem(Base):
    """案例条目（访谈得来的实践经验），与 `KnowledgeItem` 同构并扩展案例专属字段。

    为什么另立一张表而不是给资料表加一个库别列（本包裁决 1、`RQ-KB-01`）：
    两库是两个独立集合，各自带来源与状态。合并成一张表加类型标签会让
    「资料库查询」与「案例库查询」共用一套列，而案例的必带字段（授权、循证等级、
    审阅状态、访谈时间）对资料无意义、资料的版本号对案例也无意义——结果只能是
    大量可空列与「看库别才知道该读哪几列」的隐式约定，且两库的过滤条件再也无法
    在 SQL 层静态确定。分开建表后，库别是表身份而非一个可被写错的列值。

    不变量（`RQ-KB-02`、[资料与案例检索] 第 1 节）：缺来源或缺适用范围的条目
    不进入检索结果，不补默认值——因此在表上把 `source` 与 `applicable_scope`
    声明为 NOT NULL，并在检索的 SQL 里一并过滤（见 `retrieval._active_filters`）。

    字段依据：[公共案例库] 第 3 节（我们侧的真源形状）、第 7 节（审阅三档）、
    第 8 节（呈现规则）；[资料与案例检索] 第 3 节（返回契约的案例必带项）。

    归属：与资料条目、检索链同属 `modules/library`（[项目结构设计] 第 6 节）。
    """

    __tablename__ = "campfire_case_item"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_uuid)
    #: 上游目录名（如 `2026-05-25_1448_respecting-pace-asd`）。不重写，用于追溯
    #: （第 3、10 节「追溯」）。唯一：同一上游目录重复导入应被幂等拦下。
    external_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    #: 出处。案例侧由 manifest 的 `authorization` 与 `source_type` 共同承载
    #: 「谁说的」，此处存可读的出处串以复用共有的返回契约字段。
    source: Mapped[str] = mapped_column(Text, nullable=False)
    applicable_scope: Mapped[str] = mapped_column(Text, nullable=False)

    # --- 案例专属七字段（本包裁决 1；返回契约的必带项，见资料与案例检索第 3 节）---
    #: 素材授权状态（`RQ-KB-02`：真实案例与虚构样例必须可辨）。
    authorization: Mapped[str] = mapped_column(Text, nullable=False)
    #: 来源类型。一期只有「专家访谈转写」一种（第 3 节）。
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    #: 循证等级，取值见 `EVIDENCE_LEVELS`。
    evidence_level: Mapped[str] = mapped_column(String(20), nullable=False)
    #: 审阅状态，取值见 `REVIEW_STATUSES`。`owner` 不等于专业审阅（第 7 节）。
    review_status: Mapped[str] = mapped_column(String(20), nullable=False)
    #: 访谈时间（上游目录名里的时间戳）。「什么时候」是三个必答问题之一，
    #: 缺失即不得作为依据，因此 NOT NULL。
    interview_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: 是否含高风险内容（第 5 节）。为真的案例在检索返回时必须带该标记，
    #: 供 skill 决定呈现方式（转述语而非祈使句）。
    makes_claims_high_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("false"))
    #: 被推断字段的清单（第 4 节）。「被推断的字段必须标为推断」的可执行载体；
    #: `_inferred` 的内容本身也保留，但不参与检索注入/嵌入。
    inferred_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=sql_text("'[]'::jsonb"))

    # --- 与资料条目共有的字段 ---
    #: 被访谈对象类型，取值见 `SUBJECT_TYPES`。
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    #: 同意范围与记录时间（第 3、5 节）。由用户确认覆盖到 AI 检索与建议。
    consent_scope: Mapped[str] = mapped_column(String(50), nullable=False)
    consent_recorded_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 仅 `review_status = professional` 时必填（具名，第 7 节）。该「按状态必填」
    #: 的判据由 CHECK 承载，见 `__table_args__`。
    reviewer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: 上游转写稿引用。不复制转写原文入库（第 3 节）：转写稿可能含未脱敏内容
    #: 且属于上游，案例库只存抽取后的案例与卡片并以此回指。
    transcript_ref: Mapped[str | None] = mapped_column(Text, nullable=True)

    version: Mapped[str] = mapped_column(String(100), nullable=False, server_default=sql_text("'1'"))
    withdrawn: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_text("false"))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 状态，取值见 `CASE_STATUSES`。默认 `internal` 而非 `published`：案例属于
    #: 访谈得来的经验，不是经同行评议的结论（第 1 节），默认不对外发布。
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=sql_text("'internal'"))
    #: 字面路字段，与资料侧同形（文本列、空格分隔多值）。理由见 `KnowledgeItem`。
    keywords: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    aliases: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    #: 摄取来源目录与 manifest 内容哈希，供撤下时回溯（RAG 策略第 7 节纪律 3）。
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )

    __table_args__ = (
        # 字面路三个 GIN trigram 索引，与资料侧同形（RAG 策略第 3.1 节）。
        Index(
            "ix_campfire_case_item_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_campfire_case_item_keywords_trgm",
            "keywords",
            postgresql_using="gin",
            postgresql_ops={"keywords": "gin_trgm_ops"},
        ),
        Index(
            "ix_campfire_case_item_aliases_trgm",
            "aliases",
            postgresql_using="gin",
            postgresql_ops={"aliases": "gin_trgm_ops"},
        ),
        # 检索的 SQL 内过滤维度（不变量：过滤在 SQL 内完成）。
        Index("ix_campfire_case_item_withdrawn_status", "withdrawn", "status"),
        # 摄取幂等：同一上游目录同一 hash 不重复入库（RAG 策略第 7 节）。
        UniqueConstraint("source_path", "doc_hash", name="uq_campfire_case_item_source_doc"),
        # --- 值域与必填判据落存储层（CORE-05）---
        # 名字用短名，由 `core/db` 的 NAMING_CONVENTION 展开为
        # `ck_campfire_case_item_<name>`。
        CheckConstraint(f"status IN ({_CASE_STATUSES_SQL})", name="status"),
        CheckConstraint(f"review_status IN ({_REVIEW_STATUSES_SQL})", name="review_status"),
        CheckConstraint(f"evidence_level IN ({_EVIDENCE_LEVELS_SQL})", name="evidence_level"),
        CheckConstraint(f"subject_type IN ({_SUBJECT_TYPES_SQL})", name="subject_type"),
        # 具名审阅者只在 `professional` 档必填（第 7 节）：`owner` 与 `pending`
        # 出现具名审阅者会把「项目所有者核准」冒充成专业审阅。
        CheckConstraint(
            "(review_status = 'professional') = (reviewer IS NOT NULL)",
            name="reviewer_by_status",
        ),
        {"comment": "案例条目：事实真源（访谈得来的实践经验，非同行评议结论）"},
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


# ---------------------------------------------------------------------------
# 库别 → 条目模型/表名（检索链按库取数的唯一映射处）
# ---------------------------------------------------------------------------
#
# 为什么用映射表而不是一串 if/elif：字面路与条目装载都要「按库别取表名/模型」，
# 两处各写一份分支就会漂移（新增第三个库时必漏一处）。集中成一份 dict 后，
# `LIBRARIES` 即合法取值域，非法库别由 `retrieval` 在入口拒绝。
#
# 注意：节点表不分库——两库共用 `data_campfire_node`，库别写在节点 metadata 的
# `library` 键上。因此此处只映条目侧，节点侧不参与。

#: 库别 → 条目 ORM 模型。
ITEM_MODELS: dict[str, type[KnowledgeItem | CaseItem]] = {
    LIBRARY_KNOWLEDGE: KnowledgeItem,
    LIBRARY_CASE: CaseItem,
}

#: 库别 → 条目表名（字面路 SQL 用它参数化表名，见 `retrieval.literal_search`）。
#: 表名取自模型而非手写字符串，避免与模型声明漂移。
ITEM_TABLES: dict[str, str] = {library: model.__tablename__ for library, model in ITEM_MODELS.items()}

#: 合法库别集合。检索入口据此拒绝非法取值（本包质量地板校验点 ③）。
LIBRARIES: frozenset[str] = frozenset(ITEM_MODELS)

#: 用于 `CHECK` 的库别 SQL 字面量。从 `LIBRARIES` 派生，避免两份清单漂移；
#: 排序保证文本稳定。它与上面四个案例值域字面量同一手法，只是那个要等
#: `LIBRARIES` 落地后才能派生，故写在这里。
_LIBRARIES_SQL = ", ".join(f"'{value}'" for value in sorted(LIBRARIES))

# ---------------------------------------------------------------------------
# 人工处理队列（RAG 策略第 1.2 节：不可分块的可移交复核件）
# ---------------------------------------------------------------------------
#
# 为什么单立一张表而不是只打印一个计数（RAG 策略第 1.2 节「仍不可分的单元标记
# `needs_manual_review` 并计入人工处理队列，不静默截断」）：这条纪律的全部内容是
# 「有人来收拾」，而「不静默截断」的替代品是一份可移交的复核件——既要能回答
# 「是哪一份文件、哪一节」，也要拿得到正文与原因。计数在进程退出后消失，
# 因此它不能是唯一的落点。
#
# 为什么跨两库共用一张表而条目表分两张：条目表分表的理由是「两库的必带字段与
# 过滤条件不同」（见 `CaseItem` 的 docstring）；复核件的字段与用途对两库完全一致
# （定位 + 正文 + 原因），分表只会让「今天有多少待人工处理」变成两次查询。
# 库别因此是列（`library`）而不是表身份，由 CHECK 约束封住取值域。
#
# 为什么没有指向条目表的外键：一条复核件可能属于资料条目或案例条目，两条外键
# 只能二者必有其一（可空 + CHECK），而条目表删除时复核件按什么语义消失尚无裁决
# ——撤下走的是「显式删行」（见 `manual_review.delete_manual_reviews`），
# 不是级联。等这条语义有裁决时再谈外键，不为将来加约束。

#: 人工处理队列表名。
MANUAL_REVIEW_TABLE = "campfire_manual_review"


class ManualReviewItem(Base):
    """一条待人工处理的复核件：某个不可嵌入的块及其定位与原因。

    行身份是「某条目当前无法嵌入的块」这一集合的成员，不是历史账本：
    重摄取时该条目的复核件整批替换（`manual_review.record_manual_reviews`），
    因此「同一条目多轮摄取堆出多份重复行」不会发生。

    为什么 `excerpt` 存正文摘录而不是全文：它是给复核人看的定位材料，
    不是第二份语料（真源仍是源文件）。上界与截断留痕见
    `manual_review.MANUAL_REVIEW_EXCERPT_CHARS`。

    归属：与本模块的条目表、节点表同属 `modules/library`
    （docs/项目结构设计.md 第 6、10 节「表归属与模块同名」）——不可分块的判定、
    摄取与撤下都在本模块，复核件是它们共同的产物，放到别的模块会逼出跨模块写入。
    """

    __tablename__ = MANUAL_REVIEW_TABLE

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_uuid)
    #: 库别（`LIBRARIES` 的取值）：复核件属于哪个库的条目。
    library: Mapped[str] = mapped_column(String(20), nullable=False)
    #: 所属条目的 id。不加外键：条目可能来自两张表（见本节说明）。
    item_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    #: 摄取来源路径（资料侧是文件、案例侧是包目录），运维据此定位原件。
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    #: 该块在源文件里的位置（`Chunk.locator`，章节路径）。无标题的源文件取 `/`——
    #: 这不是编出来的定位，而是「该文件没有章节路径」的如实表示。
    locator: Mapped[str] = mapped_column(Text, nullable=False)
    #: 正文摘录（超上界时截断并在文末写明原文总长，见 `manual_review.build_excerpt`）。
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    #: 为什么这个块没能嵌入（`Chunk.review_reason`，由分块后处理给出）。
    review_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )

    __table_args__ = (
        # 重摄取时按条目整批替换，删除条件就是这两列；查询「这个条目还有什么待处理」
        # 也走它。不建 `created_at` 索引：表规模是本轮摄取的不可分块，量级在条级，
        # 排序走全表扫描即可。
        Index("ix_campfire_manual_review_library_item", "library", "item_id"),
        # 库别取值域落存储层（CORE-05）：库别在这里是列而不是表身份，写错一个值
        # 就会产出一条任何按库取的查询都看不到的孤儿复核件。
        CheckConstraint(f"library IN ({_LIBRARIES_SQL})", name="library"),
        {"comment": "人工处理队列：超限且不可分、未嵌入的块（不静默截断的落点）"},
    )


def as_case_item(value: object) -> CaseItem:
    """把 `ITEM_MODELS` 取出的条目收窄为 `CaseItem`，供案例聚合消费。

    为什么需要它：`ITEM_MODELS` 的值类型是 `KnowledgeItem | CaseItem` 的联合，
    而案例聚合要读案例专属字段。用 `isinstance` 收窄而不是 `cast`——后者会
    把类型错误变成运行期的 `AttributeError`（PY-11：类型阻抗用适配器/收窄）。

    Raises:
        TypeError: 传入的不是案例条目。调用方（`retrieval`）已按库别取值，
            走到这里说明映射表与聚合逻辑不一致，属编程错误，应尽早暴露。
    """
    if not isinstance(value, CaseItem):
        raise TypeError(f"期望案例条目，实际 {type(value).__name__}")
    return value
