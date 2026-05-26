"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

此文件由 Alembic autogenerate 自动生成或手工编写。
每份迁移脚本必须同时包含 upgrade() 和 downgrade() 函数。

禁止行为：
- 禁止在迁移脚本中硬编码数据库连接串
- 禁止在迁移脚本中使用 async/await 或异步驱动
- 禁止在迁移脚本中执行非迁移相关的 DML 操作
- 禁止使用 op.execute() 拼接用户输入的 SQL 字符串
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """执行正向迁移（DDL 操作）。

    所有 DDL 操作通过 Alembic op.* API 执行，在独立 PostgreSQL 事务中运行。
    若迁移涉及 pgvector 扩展（如创建 vector 类型列），
    必须在此函数开头显式执行：
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    """
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """执行逆向迁移（DDL 逆向操作）。

    必须与 upgrade() 的操作一一对应。
    downgrade() 中禁止 DROP EXTENSION vector（除非确认仅由本迁移使用）。
    """
    ${downgrades if downgrades else "pass"}
