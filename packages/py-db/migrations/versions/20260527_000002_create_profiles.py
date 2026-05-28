"""PROF-01/05: 创建 profiles 表。

Revision ID: 20260527_000002
Create Date: 2026-05-27 00:00:02
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "20260527_000002"
down_revision: Union[str, None] = "20260527_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：创建 profiles 表 + 索引。"""

    op.create_table(
        "profiles",
        sa.Column(
            "profile_id",
            UUID(as_uuid=True),
            primary_key=True,
            default=sa.text("gen_random_uuid()"),
            comment="UUID v4 主键",
        ),
        sa.Column(
            "caregiver_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
            comment="所属家属用户 UUID",
        ),
        sa.Column(
            "nickname",
            sa.String(10),
            nullable=True,
            default=None,
            comment="档案昵称，最长 10 字符",
        ),
        sa.Column(
            "birth_date",
            sa.Date(),
            nullable=False,
            comment="患者出生日期",
        ),
        sa.Column(
            "diagnosis_type",
            sa.String(20),
            nullable=False,
            comment="诊断类型（ASD/疑似ASD/其他发育障碍）",
        ),
        sa.Column(
            "primary_behavior",
            sa.String(20),
            nullable=False,
            comment="主要行为类型",
        ),
        sa.Column(
            "language_level",
            sa.String(20),
            nullable=True,
            default=None,
            comment="语言水平",
        ),
        sa.Column(
            "sensory_features",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="感官特征列表（JSONB 数组）",
        ),
        sa.Column(
            "triggers",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="已知触发因素列表（JSONB 数组）",
        ),
        sa.Column(
            "medication_notes",
            sa.Text(),
            nullable=True,
            default=None,
            comment="用药备注",
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            default=False,
            comment="是否为当前家属账号的默认档案",
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
            comment="记录最后更新时间（乐观锁版本）",
        ),
    )


def downgrade() -> None:
    """回滚：删除 profiles 表。"""

    op.drop_table("profiles")
