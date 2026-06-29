"""normalize source_type to Chinese

Revision ID: c57ee6ce64e0
Revises: 20260629_000010
Create Date: 2026-06-29 13:42:15.019477

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


# revision identifiers, used by Alembic.
revision: str = 'c57ee6ce64e0'
down_revision: Union[str, None] = '20260629_000010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """将 source_type 从旧英文值统一清洗为中文枚举值。"""
    mapping = {
        "expert_written": "专家撰写",
        "institution_desensitized": "机构脱敏",
        "ticket_deposit": "工单沉淀",
    }
    for old, new in mapping.items():
        op.execute(f"UPDATE case_narratives SET source_type = '{new}' WHERE source_type = '{old}'")


def downgrade() -> None:
    """逆向：将中文 source_type 恢复为旧英文值。"""
    mapping = {
        "专家撰写": "expert_written",
        "机构脱敏": "institution_desensitized",
        "工单沉淀": "ticket_deposit",
    }
    for old, new in mapping.items():
        op.execute(f"UPDATE case_narratives SET source_type = '{new}' WHERE source_type = '{old}'")
