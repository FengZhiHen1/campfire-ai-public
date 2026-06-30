"""为 case_cards 表添加 citation_count 列以支持案例引用计数排序。

Revision ID: 20260528_190000
Create Date: 2026-05-28 19:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260528_190000"
down_revision: Union[str, None] = "811914200e96"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # cases 表已在 20260528_000020 拆分为 case_narratives + case_cards，
    # 引用计数应落在 L2 检索单元 case_cards 上。
    op.add_column(
        "case_cards",
        sa.Column(
            "citation_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="被引用次数",
        ),
    )


def downgrade() -> None:
    op.drop_column("case_cards", "citation_count")
