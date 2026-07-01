"""CSLT-06: 为 consultations 表添加 plan_sections 列。

迁移内容：
1. 添加 plan_sections JSONB 列，存储 AI 生成的四段式方案结构化数据。
2. 为已有记录填充空对象 {} 作为默认值。

Revision ID: 20260628_000010
Create Date: 2026-06-28 12:56:49
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260628_000010"
down_revision: Union[str, Sequence[str], None] = "20260531_000020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：添加 plan_sections 列并设置默认值。"""

    op.add_column(
        "consultations",
        sa.Column(
            "plan_sections",
            JSONB(),
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
            comment="AI 生成的四段式应急方案结构化数据（段落标题 → 内容列表）",
        ),
    )

    # 将已有记录的 plan_sections 更新为空对象
    op.execute("UPDATE consultations SET plan_sections = '{}'::jsonb WHERE plan_sections IS NULL")


def downgrade() -> None:
    """回滚：删除 plan_sections 列。"""

    op.drop_column("consultations", "plan_sections")
