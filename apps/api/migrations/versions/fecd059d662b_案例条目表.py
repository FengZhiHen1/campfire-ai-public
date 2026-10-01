"""案例条目表

Revision ID: fecd059d662b
Revises: 711fc22a40fd
Create Date: 2026-09-30 21:02:40.422546

# down_revision 由 2d5e68935ddc 重挂到 711fc22a40fd（2026-09-30 编排器）：
# 本迁移在 t03 泳道生成时基线是 T02 合并前的 feature 分支（head 为 2d5e68935ddc）；
# 合并时 T02 的 711fc22a40fd 已先入主仓，重挂使其串在单链 head 上。
# 两迁移均为纯新增表、零表交集（T03 审查确认），重挂安全。

业务意图（依据 docs/技术设计/technical-details/公共案例库.md 第 3、4、7 节与
docs/技术设计/technical-details/资料与案例检索.md 第 1、3 节）：

- 本迁移补上案例库缺的那张条目表。此前 `campfire_knowledge_item` 是唯一的
  条目表，`LIBRARY_CASE` 常量被定义却没有使用点，检索链硬编码只查资料库——
  因此 `search_cases` 在现状下不可实现（见 TODO 的「案例条目表不存在」条）。
- 另立一张表而不是给资料表加库别列：两库是两个独立集合（`RQ-KB-01`），
  合并成一张表加类型标签会让两库的过滤条件再也无法在 SQL 层静态确定，而案例的
  必带字段（授权、循证等级、审阅状态、访谈时间）对资料无意义——只能是大量可空列
  加「看库别才知道读哪几列」的隐式约定。分开建表后，库别是表身份而非可写错的列值。
- 七个案例专属字段（`authorization`、`source_type`、`evidence_level`、
  `review_status`、`interview_at`、`makes_claims_high_risk`、`inferred_fields`）
  是返回契约的必带项：前五个是公共案例库第 8 节呈现规则能落地的前提——缺任一个，
  输出就无法如实回答「谁说的、多可信、什么时候」；`inferred_fields` 是「被推断的
  字段必须标为推断」的前提（同文第 4 节）。
- 值域与必填判据落成 CHECK 约束（CORE-05：不变量落最强可行通道）：`status` 三值、
  `review_status` 三档、`evidence_level` 三值、`subject_type` 四值，以及
  「具名审阅者只在 `professional` 档存在」——该判据表达为等价式
  `(review_status = 'professional') = (reviewer IS NOT NULL)`，让「owner/pending
  却填了 reviewer」（冒充专业审阅）与「professional 却没填」（无法追溯谁审的）
  撞在同一处。
- `source` 与 `applicable_scope` 为 NOT NULL：缺来源或缺适用范围的条目
  「不进入检索结果、不补默认值」是不变量（资料与案例检索第 1 节、`RQ-KB-02`），
  存储层的 NOT NULL 是它的第一道闸门。
- 三个字面路 GIN trigram 索引与资料侧同形（RAG 策略第 3.1 节）。用文本列而非
  数组：`gin_trgm_ops` 不接受 `text[]`（2026-09-29 实测）。
- 本迁移不加节点表列：两库共用 `data_campfire_node`，库别与案例过滤维度都写在
  节点 metadata 上，因此「节点表加 library 列」不需要——加列反而会让同一事实
  出现两处（列与 metadata）。

⚠️ 本迁移只增表：不改动 `campfire_knowledge_item` 与 `data_campfire_node`，
因此对既有资料检索零影响。`--autogenerate` 未提议任何 remove_table（白名单过滤器
正常工作，排除了 SuperTokens core 的 56 张无前缀表）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "fecd059d662b"
down_revision: Union[str, Sequence[str], None] = "711fc22a40fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建案例条目表与其索引、值域约束。"""
    op.create_table(
        "campfire_case_item",
        sa.Column("id", sa.UUID(), nullable=False),
        #: 上游目录名，不重写（追溯用）。唯一：同一上游目录重复导入应被拦下。
        sa.Column("external_key", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        #: 缺来源的条目不进入检索（不变量）——故 NOT NULL。
        sa.Column("source", sa.Text(), nullable=False),
        #: 缺适用范围的输出无法说明局限（`RQ-CON-03`）——故 NOT NULL。
        sa.Column("applicable_scope", sa.Text(), nullable=False),
        # --- 案例专属七字段（返回契约必带，见模块头部）---
        sa.Column("authorization", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("evidence_level", sa.String(length=20), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("interview_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("makes_claims_high_risk", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        #: 被推断字段清单。默认空数组而非 NULL：返回契约要求它是清单，
        #: NULL 会逼每个消费者自己判空（CORE-07：边界显式）。
        sa.Column(
            "inferred_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        # --- 与资料条目共有 ---
        sa.Column("subject_type", sa.String(length=20), nullable=False),
        sa.Column("consent_scope", sa.String(length=50), nullable=False),
        sa.Column("consent_recorded_at", sa.Text(), nullable=True),
        sa.Column("reviewer", sa.String(length=200), nullable=True),
        #: 转写稿引用；不复制转写原文入库（公共案例库第 3 节）。
        sa.Column("transcript_ref", sa.Text(), nullable=True),
        sa.Column("version", sa.String(length=100), server_default=sa.text("'1'"), nullable=False),
        sa.Column("withdrawn", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_reason", sa.Text(), nullable=True),
        #: 默认 `internal`：案例是访谈得来的经验、不是同行评议结论，默认不对外发布。
        sa.Column("status", sa.String(length=20), server_default=sa.text("'internal'"), nullable=False),
        sa.Column("keywords", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("aliases", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("doc_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        # --- 值域与必填判据（CORE-05：落存储层，拒绝一切写入者含运维旁路）---
        # 约束名用短名，由 `core/db` 的 NAMING_CONVENTION 展开为
        # `ck_campfire_case_item_<name>`（与 ORM 声明逐字一致，否则 autogenerate 漂移）。
        sa.CheckConstraint(
            "status IN ('fictional', 'internal', 'published')",
            name=op.f("ck_campfire_case_item_status"),
        ),
        sa.CheckConstraint(
            "review_status IN ('owner', 'pending', 'professional')",
            name=op.f("ck_campfire_case_item_review_status"),
        ),
        sa.CheckConstraint(
            "evidence_level IN ('EBP', 'INSTITUTIONAL', 'OBSERVATIONAL')",
            name=op.f("ck_campfire_case_item_evidence_level"),
        ),
        sa.CheckConstraint(
            "subject_type IN ('专业人员', '其他', '家长', '老师')",
            name=op.f("ck_campfire_case_item_subject_type"),
        ),
        sa.CheckConstraint(
            "(review_status = 'professional') = (reviewer IS NOT NULL)",
            name=op.f("ck_campfire_case_item_reviewer_by_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campfire_case_item")),
        sa.UniqueConstraint("external_key", name=op.f("uq_campfire_case_item_external_key")),
        sa.UniqueConstraint("source_path", "doc_hash", name="uq_campfire_case_item_source_doc"),
        comment="案例条目：事实真源（访谈得来的实践经验，非同行评议结论）",
    )
    # 字面路索引（RAG 策略第 3.1 节）：中文须用 LIKE/ILIKE 才走 GIN。
    op.create_index(
        "ix_campfire_case_item_title_trgm",
        "campfire_case_item",
        ["title"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_campfire_case_item_keywords_trgm",
        "campfire_case_item",
        ["keywords"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"keywords": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_campfire_case_item_aliases_trgm",
        "campfire_case_item",
        ["aliases"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"aliases": "gin_trgm_ops"},
    )
    # 检索的 SQL 内过滤维度（不变量：过滤在 SQL 内完成）。
    op.create_index(
        "ix_campfire_case_item_withdrawn_status",
        "campfire_case_item",
        ["withdrawn", "status"],
        unique=False,
    )


def downgrade() -> None:
    """回滚：删案例条目表及其索引。

    不触碰资料条目表与节点表：本迁移只建新表，回滚它不该影响到两库共用的
    节点表（删节点表会连带删掉资料侧的检索数据）。
    """
    op.drop_index("ix_campfire_case_item_withdrawn_status", table_name="campfire_case_item")
    op.drop_index(
        "ix_campfire_case_item_aliases_trgm",
        table_name="campfire_case_item",
        postgresql_using="gin",
        postgresql_ops={"aliases": "gin_trgm_ops"},
    )
    op.drop_index(
        "ix_campfire_case_item_keywords_trgm",
        table_name="campfire_case_item",
        postgresql_using="gin",
        postgresql_ops={"keywords": "gin_trgm_ops"},
    )
    op.drop_index(
        "ix_campfire_case_item_title_trgm",
        table_name="campfire_case_item",
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.drop_table("campfire_case_item")
