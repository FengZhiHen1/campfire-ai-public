"""PROF-03: 创建 event_logs 表。

Revision ID: 20260527_000004
Create Date: 2026-05-27 00:00:04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "20260527_000004"
down_revision: Union[str, None] = "20260527_000003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：创建 event_logs 表 + 复合索引。"""

    op.create_table(
        "event_logs",
        sa.Column(
            "event_id",
            UUID(as_uuid=True),
            primary_key=True,
            default=sa.text("gen_random_uuid()"),
            comment="UUID v4 主键",
        ),
        sa.Column(
            "profile_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
            comment="所属档案 UUID",
        ),
        sa.Column(
            "recorded_by",
            UUID(as_uuid=True),
            nullable=False,
            comment="记录人用户 UUID",
        ),
        sa.Column(
            "recorded_by_role",
            sa.String(20),
            nullable=False,
            server_default="parent",
            comment="记录人角色，固定为 'parent'",
        ),
        sa.Column(
            "event_time",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="事件实际发生时间（UTC）",
        ),
        sa.Column(
            "behavior_type",
            sa.String(20),
            nullable=False,
            comment="行为类型",
        ),
        sa.Column(
            "severity_level",
            sa.String(10),
            nullable=False,
            comment="家属自评严重程度",
        ),
        sa.Column(
            "setting",
            sa.String(20),
            nullable=True,
            default=None,
            comment="事件发生场景",
        ),
        sa.Column(
            "trigger_description",
            sa.Text(),
            nullable=False,
            comment="触发因素描述",
        ),
        sa.Column(
            "manifestation",
            sa.Text(),
            nullable=False,
            comment="具体表现描述",
        ),
        sa.Column(
            "intervention_tried",
            sa.Text(),
            nullable=False,
            comment="尝试干预措施",
        ),
        sa.Column(
            "intervention_result",
            sa.Text(),
            nullable=False,
            comment="干预结果",
        ),
        sa.Column(
            "is_professional",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="是否有专业评估补充",
        ),
        sa.Column(
            "tags",
            JSONB,
            nullable=True,
            default=None,
            comment="自定义标签列表（JSONB 数组）",
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
        sa.Index("ix_event_logs_profile_event_time", "profile_id", "event_time"),
    )


def downgrade() -> None:
    """回滚：删除 event_logs 表。"""

    op.drop_table("event_logs")
