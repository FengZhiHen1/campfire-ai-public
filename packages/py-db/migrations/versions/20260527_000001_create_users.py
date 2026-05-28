"""AUTH-01: 创建 users 表。

Revision ID: 20260527_000001
Create Date: 2026-05-27 00:00:01
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "20260527_000001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：创建 users 表 + 索引。"""

    op.create_table(
        "users",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            default=sa.text("gen_random_uuid()"),
            comment="UUID v4 主键",
        ),
        sa.Column(
            "username",
            sa.String(32),
            nullable=False,
            unique=True,
            index=True,
            comment="登录名称，全局唯一（大小写不敏感）",
        ),
        sa.Column(
            "password_hash",
            sa.String(255),
            nullable=False,
            comment="bcrypt 哈希值，以 $2b$ 或 $2a$ 开头",
        ),
        sa.Column(
            "role",
            sa.Enum("family", "teacher", "expert", "admin", "maintainer", name="user_role"),
            nullable=False,
            comment="用户角色（family/teacher/expert/admin/maintainer）",
        ),
        sa.Column(
            "phone",
            sa.String(11),
            nullable=False,
            unique=True,
            index=True,
            comment="中国大陆 11 位手机号",
        ),
        sa.Column(
            "real_name",
            sa.String(20),
            nullable=True,
            comment="真实姓名，家属和老师可选填",
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
    """回滚：删除 users 表 + ENUM。"""

    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS user_role")
