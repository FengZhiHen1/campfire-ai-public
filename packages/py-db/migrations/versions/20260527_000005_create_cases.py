"""CASE-01: 创建 cases 表。

Revision ID: 20260527_000005
Create Date: 2026-05-27 00:00:05
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision: str = "20260527_000005"
down_revision: Union[str, None] = "20260527_000004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：创建 cases 表 + case_status ENUM + 索引。"""

    op.create_table(
        "cases",
        sa.Column(
            "case_id",
            sa.String(20),
            primary_key=True,
            comment="案例唯一标识，格式 CASE-YYYY-NNNN，由序列自动生成",
        ),
        sa.Column(
            "title",
            sa.String(100),
            nullable=False,
            comment="案例标题，去个性化后的简短名称",
        ),
        sa.Column(
            "narrative",
            sa.Text(),
            nullable=False,
            comment="原始叙事文本，以自然语言撰写的完整干预故事",
        ),
        sa.Column(
            "source_type",
            sa.String(20),
            nullable=False,
            comment="案例来源类型（专家撰写/机构脱敏/工单沉淀）",
        ),
        sa.Column(
            "author_id",
            sa.String(36),
            nullable=False,
            index=True,
            comment="撰写专家标识（UUID）",
        ),
        sa.Column(
            "behavior_type",
            sa.String(20),
            nullable=False,
            comment="行为类型",
        ),
        sa.Column(
            "age_range_min",
            sa.Integer(),
            nullable=False,
            comment="适用年龄区间起始值",
        ),
        sa.Column(
            "age_range_max",
            sa.Integer(),
            nullable=False,
            comment="适用年龄区间结束值",
        ),
        sa.Column(
            "severity",
            sa.String(10),
            nullable=False,
            comment="适用严重程度（轻度/中度/重度）",
        ),
        sa.Column(
            "scene",
            sa.String(20),
            nullable=False,
            comment="发生场景",
        ),
        sa.Column(
            "ebp_labels",
            JSON,
            nullable=False,
            server_default=sa.text("'[]'::json"),
            comment="循证实践标签列表，JSON 数组",
        ),
        sa.Column(
            "family_category",
            sa.String(20),
            nullable=False,
            comment="家属端展示大类",
        ),
        sa.Column(
            "immediate_action",
            sa.Text(),
            nullable=False,
            comment="即时安全干预动作（四段式第一段）",
        ),
        sa.Column(
            "comforting_phrase",
            sa.Text(),
            nullable=False,
            comment="情绪安抚话术（四段式第二段）",
        ),
        sa.Column(
            "observation_metrics",
            sa.Text(),
            nullable=False,
            comment="后续观察指标（四段式第三段）",
        ),
        sa.Column(
            "medical_criteria",
            sa.Text(),
            nullable=False,
            comment="就医判断标准（四段式第四段）",
        ),
        sa.Column(
            "evidence_level",
            sa.String(20),
            nullable=False,
            comment="循证等级",
        ),
        sa.Column(
            "contraindications",
            sa.Text(),
            nullable=False,
            comment="禁忌与注意事项",
        ),
        sa.Column(
            "is_template",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="是否模板",
        ),
        sa.Column(
            "excluded_population",
            sa.Text(),
            nullable=True,
            default=None,
            comment="不适用人群（选填）",
        ),
        sa.Column(
            "attachment_refs",
            JSON,
            nullable=True,
            server_default=sa.text("'[]'::json"),
            comment="附件引用列表（选填），JSON 数组",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "pending_review",
                "approved",
                "rejected",
                name="case_status",
            ),
            nullable=False,
            server_default="draft",
            index=True,
            comment="案例状态（draft/pending_review/approved/rejected）",
        ),
        sa.Column(
            "review_comment",
            sa.Text(),
            nullable=True,
            default=None,
            comment="审核驳回意见，由 CASE-03 填写",
        ),
        sa.Column(
            "index_status",
            sa.Enum(
                "pending",
                "processing",
                "indexed",
                "indexing_failed",
                name="index_status_enum",
            ),
            nullable=True,
            comment="向量化索引状态",
        ),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="索引完成时间，仅 index_status='indexed' 时有值",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="记录创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
            comment="记录最后更新时间",
        ),
    )

    # 在 index_status 列上创建索引
    op.create_index("ix_cases_index_status", "cases", ["index_status"])


def downgrade() -> None:
    """回滚：删除 cases 表 + ENUM 类型。"""

    op.drop_index("ix_cases_index_status", table_name="cases")
    op.drop_table("cases")
    op.execute("DROP TYPE IF EXISTS index_status_enum")
    op.execute("DROP TYPE IF EXISTS case_status")
