"""PROF-05: 创建 teacher_links 表。

Revision ID: 20260527_000003
Create Date: 2026-05-27 00:00:03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "20260527_000003"
down_revision: Union[str, None] = "20260527_000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：创建 teacher_links 表 + 索引。"""

    op.create_table(
        "teacher_links",
        sa.Column(
            "link_id",
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
            comment="目标个人档案 UUID",
        ),
        sa.Column(
            "teacher_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
            comment="关联老师/专家的用户 UUID",
        ),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            comment="关联角色（teacher / expert）",
        ),
        sa.Column(
            "unlinked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            default=None,
            comment="解除关联时间戳，NULL 表示关联有效",
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            default=1,
            comment="乐观锁版本号",
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


def downgrade() -> None:
    """回滚：删除 teacher_links 表。"""

    op.drop_table("teacher_links")
