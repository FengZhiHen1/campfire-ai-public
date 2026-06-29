"""CSLT-05/06: 为 consultations 表添加置信度后校验结果字段。

迁移内容：
1. 添加 confidence_score FLOAT 列，存储 CSLT-05 综合置信度得分（0.0-1.0）。
2. 添加 validation_verdict VARCHAR(20) 列，存储判定结论（PASS/APPEND_WARNING/FORCE_BLOCK）。

Revision ID: 20260629_000010
Create Date: 2026-06-29 05:14:18
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260629_000010"
down_revision: Union[str, None] = "20260628_000020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：添加置信度相关列。"""

    op.add_column(
        "consultations",
        sa.Column(
            "confidence_score",
            sa.Float(),
            nullable=True,
            comment="CSLT-05 置信度后校验综合得分（0.0-1.0）。null 表示尚未完成校验或校验失败",
        ),
    )

    op.add_column(
        "consultations",
        sa.Column(
            "validation_verdict",
            sa.String(20),
            nullable=True,
            comment="CSLT-05 置信度判定结论（PASS/APPEND_WARNING/FORCE_BLOCK）。null 表示尚未完成校验",
        ),
    )


def downgrade() -> None:
    """回滚：删除置信度相关列。"""

    op.drop_column("consultations", "validation_verdict")
    op.drop_column("consultations", "confidence_score")
