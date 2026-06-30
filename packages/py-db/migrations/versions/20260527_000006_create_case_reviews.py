"""CASE-03: 创建 case_reviews 和 review_audit_logs 表。

Revision ID: 20260527_000006
Create Date: 2026-05-27 00:00:06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "20260527_000006"
down_revision: Union[str, None] = "20260527_000005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：创建 case_reviews 表 + review_audit_logs 表 + 索引。"""

    # ------------------------------------------------------------------
    # case_reviews 表
    # ------------------------------------------------------------------
    op.create_table(
        "case_reviews",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            default=sa.text("gen_random_uuid()"),
            comment="UUID v4 主键",
        ),
        sa.Column(
            "case_id",
            sa.String(20),
            sa.ForeignKey("cases.case_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
            comment="关联的案例标识（FK → cases.case_id）",
        ),
        sa.Column(
            "review_round",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="第几次审核（从 1 开始）",
        ),
        sa.Column(
            "ai_review_report",
            JSONB,
            nullable=True,
            comment="AI 预审完整报告（JSONB）",
        ),
        sa.Column(
            "decision",
            sa.String(20),
            nullable=False,
            comment="专家裁决（approved / rejected）",
        ),
        sa.Column(
            "review_comment",
            sa.Text(),
            nullable=True,
            default=None,
            comment="审核意见（驳回时必填，>=10 字）",
        ),
        sa.Column(
            "reviewer_id",
            sa.String(36),
            nullable=False,
            comment="审核人标识（UUID）",
        ),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="审核完成时间",
        ),
        sa.Column(
            "is_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="是否覆盖了 AI 预审结果",
        ),
        sa.Column(
            "override_reason",
            sa.Text(),
            nullable=True,
            default=None,
            comment="覆盖理由（is_override=True 时必填）",
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

    # ------------------------------------------------------------------
    # review_audit_logs 表
    # ------------------------------------------------------------------
    op.create_table(
        "review_audit_logs",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
            comment="BIGSERIAL 自增主键，记录顺序不可伪造",
        ),
        sa.Column(
            "case_id",
            sa.String(20),
            nullable=False,
            index=True,
            comment="关联的案例标识",
        ),
        sa.Column(
            "action",
            sa.String(40),
            nullable=False,
            comment="审计动作类型",
        ),
        sa.Column(
            "operator_id",
            sa.String(36),
            nullable=False,
            comment="操作人 UUID",
        ),
        sa.Column(
            "operator_role",
            sa.String(20),
            nullable=False,
            comment="操作人角色",
        ),
        sa.Column(
            "details",
            JSONB,
            nullable=True,
            default=None,
            comment="操作详情（JSONB）",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="操作时间",
        ),
    )


def downgrade() -> None:
    """回滚：删除 case_reviews 和 review_audit_logs 表。"""

    op.drop_table("review_audit_logs")
    op.drop_table("case_reviews")
