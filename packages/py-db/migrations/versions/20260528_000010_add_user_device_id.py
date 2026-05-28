"""MVP: 为 users 表添加 device_id 列以支持匿名用户。

Revision ID: 20260528_000010
Create Date: 2026-05-28 00:00:10
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260528_000010"
down_revision: Union[str, None] = "20260527_211308"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：添加 device_id 列及索引。"""

    op.add_column(
        "users",
        sa.Column(
            "device_id",
            sa.String(32),
            nullable=True,
            unique=True,
            index=True,
            comment="小程序匿名设备标识，MVP 阶段替代认证",
        ),
    )

    op.create_index(
        "ix_users_device_id",
        "users",
        ["device_id"],
        unique=True,
    )


def downgrade() -> None:
    """回滚：删除 device_id 列及索引。"""

    op.drop_index("ix_users_device_id", table_name="users")
    op.drop_column("users", "device_id")
