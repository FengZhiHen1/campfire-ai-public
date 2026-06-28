"""为 case_narratives 表添加 extraction_error 列以持久化 LLM 提取失败原因。

Revision ID: 20260628_000020
Create Date: 2026-06-28 12:56:49
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260628_000020"
down_revision: Union[str, None] = "20260628_000010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：添加 extraction_error 列。"""

    op.add_column(
        "case_narratives",
        sa.Column(
            "extraction_error",
            sa.Text(),
            nullable=True,
            default=None,
            comment="LLM 提取失败原因/错误详情（仅失败时写入）",
        ),
    )


def downgrade() -> None:
    """回滚：删除 extraction_error 列。"""

    op.drop_column("case_narratives", "extraction_error")
