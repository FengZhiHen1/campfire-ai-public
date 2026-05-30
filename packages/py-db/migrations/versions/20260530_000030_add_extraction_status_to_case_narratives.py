"""为 case_narratives 表添加 extraction_status 列以追踪 LLM 提取进度。

Revision ID: 20260530_000030
Create Date: 2026-05-30 23:30:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260530_000030"
down_revision: Union[str, None] = "20260528_190000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "case_narratives",
        sa.Column(
            "extraction_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending'"),
            comment="LLM 提取状态（pending/extracting/extracted/failed）",
        ),
    )
    op.create_index(
        "ix_case_narratives_extraction_status",
        "case_narratives",
        ["extraction_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_case_narratives_extraction_status", "case_narratives")
    op.drop_column("case_narratives", "extraction_status")
