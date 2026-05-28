"""CASE-01: 拆分 cases 表为 case_narratives (L1) + case_cards (L2)。

Revision ID: 20260528_000020
Create Date: 2026-05-28
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, JSONB, UUID

revision: str = "20260528_000020"
down_revision: Union[str, None] = "20260528_000010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：创建 case_narratives + case_cards，迁移数据，更新 case_chunks FK。"""

    # =========================================================================
    # 1. 创建 case_narratives 表
    # =========================================================================
    op.create_table(
        "case_narratives",
        sa.Column("narrative_id", UUID(as_uuid=True), primary_key=True,
                  comment="L1 叙事唯一标识（UUID v4）"),
        sa.Column("title", sa.String(100), nullable=False, comment="叙事标题"),
        sa.Column("narrative", sa.Text(), nullable=False, comment="完整自然语言叙事文本"),
        sa.Column("source_type", sa.String(20), nullable=False, comment="案例来源类型"),
        sa.Column("author_id", sa.String(36), nullable=False, index=True, comment="撰写专家标识"),
        sa.Column("status", sa.Enum("draft", "pending_review", "approved", "rejected",
                                    name="narrative_status"),
                  nullable=False, server_default="draft", index=True, comment="叙事状态"),
        sa.Column("review_comment", sa.Text(), nullable=True, comment="审核驳回意见"),
        sa.Column("derived_card_ids", JSON, nullable=True, comment="衍生的 L2 卡片 ID 列表"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False, comment="记录创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  onupdate=sa.func.now(), nullable=False, comment="记录最后更新时间"),
    )

    # =========================================================================
    # 2. 创建 case_cards 表
    # =========================================================================
    op.create_table(
        "case_cards",
        sa.Column("card_id", UUID(as_uuid=True), primary_key=True,
                  comment="L2 卡片唯一标识（UUID v4）"),
        sa.Column("narrative_id", UUID(as_uuid=True),
                  sa.ForeignKey("case_narratives.narrative_id", ondelete="CASCADE"),
                  nullable=False, index=True, comment="关联的 L1 叙事"),
        # 基础信息
        sa.Column("title", sa.String(100), nullable=False, comment="卡片标题"),
        sa.Column("scenario", sa.Text(), nullable=False, comment="适用场景描述"),
        sa.Column("behavior_type", sa.String(20), nullable=False, comment="行为类型"),
        sa.Column("age_range_min", sa.Integer(), nullable=False, comment="年龄区间起始"),
        sa.Column("age_range_max", sa.Integer(), nullable=False, comment="年龄区间结束"),
        sa.Column("severity", sa.String(10), nullable=False, comment="严重程度"),
        sa.Column("scene", sa.String(20), nullable=False, comment="发生场景"),
        # 循证标注
        sa.Column("ebp_labels", JSON, nullable=False, server_default=sa.text("'[]'::json"),
                  comment="NCAEP 循证实践标签"),
        sa.Column("family_category", sa.String(20), nullable=False, comment="家属端展示大类"),
        # 四段式
        sa.Column("immediate_action", sa.Text(), nullable=False, comment="即时安全干预动作"),
        sa.Column("comforting_phrase", sa.Text(), nullable=False, comment="情绪安抚话术"),
        sa.Column("observation_metrics", sa.Text(), nullable=False, comment="后续观察指标"),
        sa.Column("medical_criteria", sa.Text(), nullable=False, comment="就医判断标准"),
        # 循证与质量
        sa.Column("evidence_level", sa.String(20), nullable=False, comment="循证等级"),
        sa.Column("caution_notes", sa.Text(), nullable=False, server_default="",
                  comment="禁忌与常见误用"),
        sa.Column("contraindications", sa.Text(), nullable=False, comment="不适用人群/场景"),
        sa.Column("is_template", sa.Boolean(), nullable=False, server_default=sa.text("false"),
                  comment="是否模板"),
        # 选填
        sa.Column("excluded_population", sa.Text(), nullable=True, comment="不适用人群（选填）"),
        sa.Column("attachment_refs", JSON, nullable=True,
                  server_default=sa.text("'[]'::json"), comment="附件引用（选填）"),
        # 状态
        sa.Column("review_status", sa.Enum("draft", "pending_review", "approved", "rejected",
                                           name="card_review_status"),
                  nullable=False, server_default="draft", index=True, comment="卡片审核状态"),
        sa.Column("review_comment", sa.Text(), nullable=True, comment="审核驳回意见"),
        # 索引状态
        sa.Column("index_status", sa.Enum("pending", "processing", "indexed", "indexing_failed",
                                          name="card_index_status_enum"),
                  nullable=True, comment="向量化索引状态"),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True, comment="索引完成时间"),
        # LLM 推断
        sa.Column("inferred_fields", JSONB, nullable=True, comment="LLM 推断字段及依据"),
        # 时间戳
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False, comment="记录创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  onupdate=sa.func.now(), nullable=False, comment="记录最后更新时间"),
    )

    op.create_index("ix_case_cards_index_status", "case_cards", ["index_status"])

    # =========================================================================
    # 3. 迁移现有数据: cases → case_narratives + case_cards (1:1)
    # =========================================================================
    op.execute("""
        INSERT INTO case_narratives (narrative_id, title, narrative, source_type,
            author_id, status, review_comment, created_at, updated_at)
        SELECT gen_random_uuid(), title, narrative, source_type, author_id, status,
            review_comment, created_at, updated_at
        FROM cases
    """)

    op.execute("""
        INSERT INTO case_cards (card_id, narrative_id, title, scenario, behavior_type,
            age_range_min, age_range_max, severity, scene, ebp_labels, family_category,
            immediate_action, comforting_phrase, observation_metrics, medical_criteria,
            evidence_level, contraindications, is_template, excluded_population,
            attachment_refs, review_status, review_comment, index_status, indexed_at,
            created_at, updated_at)
        SELECT gen_random_uuid(), n.narrative_id, c.title, c.scene, c.behavior_type,
            c.age_range_min, c.age_range_max, c.severity, c.scene, c.ebp_labels,
            c.family_category, c.immediate_action, c.comforting_phrase,
            c.observation_metrics, c.medical_criteria, c.evidence_level,
            c.contraindications, c.is_template, c.excluded_population,
            c.attachment_refs, c.status, c.review_comment, c.index_status, c.indexed_at,
            c.created_at, c.updated_at
        FROM cases c
        JOIN case_narratives n ON n.title = c.title AND n.author_id = c.author_id
            AND n.created_at = c.created_at
    """)

    # 更新 derived_card_ids
    op.execute("""
        UPDATE case_narratives n
        SET derived_card_ids = (
            SELECT json_agg(cd.card_id::text)
            FROM case_cards cd
            WHERE cd.narrative_id = n.narrative_id
        )
    """)

    # =========================================================================
    # 4. 更新 case_chunks FK: cases.case_id → case_cards.card_id
    # =========================================================================
    op.execute("ALTER TABLE case_chunks DROP CONSTRAINT IF EXISTS case_chunks_case_id_fkey")
    op.execute("""
        ALTER TABLE case_chunks
        ADD COLUMN card_id UUID REFERENCES case_cards(card_id) ON DELETE CASCADE
    """)
    op.execute("""
        UPDATE case_chunks cc
        SET card_id = cd.card_id
        FROM cases c
        JOIN case_narratives n ON n.title = c.title AND n.author_id = c.author_id
        JOIN case_cards cd ON cd.narrative_id = n.narrative_id
        WHERE cc.case_id = c.case_id
    """)
    op.execute("ALTER TABLE case_chunks ALTER COLUMN card_id SET NOT NULL")
    op.execute("ALTER TABLE case_chunks DROP COLUMN case_id")
    op.create_index("ix_case_chunks_card_id", "case_chunks", ["card_id"])

    # =========================================================================
    # 5. 保留旧 cases 表作为备份（后续手动删除）
    # =========================================================================
    op.execute("ALTER TABLE cases RENAME TO cases_backup")


def downgrade() -> None:
    """回滚：恢复 cases 表，删除新表。"""
    op.execute("ALTER TABLE cases_backup RENAME TO cases")

    op.drop_index("ix_case_chunks_card_id", table_name="case_chunks")
    op.execute("ALTER TABLE case_chunks ADD COLUMN case_id VARCHAR(20)")
    op.execute("""
        UPDATE case_chunks cc
        SET case_id = c.case_id
        FROM case_cards cd
        JOIN case_narratives n ON n.narrative_id = cd.narrative_id
        JOIN cases c ON c.title = n.title AND c.author_id = n.author_id
        WHERE cc.card_id = cd.card_id
    """)
    op.execute("ALTER TABLE case_chunks DROP COLUMN card_id")
    op.execute("""
        ALTER TABLE case_chunks
        ADD CONSTRAINT case_chunks_case_id_fkey
        FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
    """)

    op.drop_index("ix_case_cards_index_status", table_name="case_cards")
    op.drop_table("case_cards")
    op.drop_table("case_narratives")
    op.execute("DROP TYPE IF EXISTS card_index_status_enum")
    op.execute("DROP TYPE IF EXISTS card_review_status")
    op.execute("DROP TYPE IF EXISTS narrative_status")
