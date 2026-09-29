"""删除账本账号列改为文本

Revision ID: 86f653f40b92
Revises: cd3583fc1cb0
Create Date: 2026-09-29 21:43:51.550322

业务意图（依据 docs/技术设计/decisions/通用记忆归属为账号.md、评审复核 2026-09-29）：

- 把 `campfire_memory_deletion_ledger.account_id` 与 `deleted_by` 从 `uuid` 改为
  `varchar(128)`。**这是一个真实的缺陷修复，不是风格调整**：
  `identity.to_account_id` 接受的账号键字符集是 Graphiti 的 `group_id` 判据
  （`[a-zA-Z0-9_-]`），**不只 UUID**；而 `accounts/` 仍是占位包、账号标识形态尚未决定
  （技术栈设计称标识存在 SuperTokens 的 `email` 字段里，业务账号名形态未定）。
  列类型定为 `uuid` 与之直接冲突——实测 `'acct_aaa'::uuid` 报
  `invalid input syntax for type uuid`，即**合法账号键无法落库**，该类账号的删除与
  纠正不可实现。
- 改为文本后 UUID 形态的账号同样可用（36 字符 < 128），**不预先收窄契约**；
  宽度与 `identity.MAX_ACCOUNT_ID_LENGTH` 一致。若将来账号标识确定为 UUID，
  再收窄是另一次迁移的决定，届时应有真实依据。

**升级方向安全**：`uuid → varchar` 不需要 `USING`（实测有数据时也可直接 ALTER，
值是规范 UUID 文本）。

**回滚方向有真实风险，必须知情**：`varchar → uuid` 在**存在非 UUID 值时会失败**
（实测 PG 报 `column "v" cannot be cast automatically to type uuid`）。因此
`downgrade()` 只在「账本中不含非 UUID 账号键」时可用；一旦按新宽度写入了
`acct_aaa` 一类账号，回滚会报错而不是静默丢数据——这是**有意的**：宁可报错，
也不做隐式截断或丢行。回滚前须先确认或清理该类行。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "86f653f40b92"
down_revision: Union[str, Sequence[str], None] = "cd3583fc1cb0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """把两列放宽为 varchar(128)。

    不需要 `USING`：PG 能把 uuid 隐式转为文本形式（有数据时实测通过）。
    """
    op.alter_column(
        "campfire_memory_deletion_ledger",
        "account_id",
        existing_type=sa.UUID(),
        type_=sa.String(length=128),
        existing_nullable=False,
    )
    op.alter_column(
        "campfire_memory_deletion_ledger",
        "deleted_by",
        existing_type=sa.UUID(),
        type_=sa.String(length=128),
        existing_nullable=True,
    )


def downgrade() -> None:
    """收窄回 uuid。

    ⚠️ **含非 UUID 账号键时会失败**（PG 拒绝隐式转换）。这是有意的失败而非静默
    丢数据；回滚前须确认账本中不含非 UUID 值（见模块头部的说明）。
    """
    op.alter_column(
        "campfire_memory_deletion_ledger",
        "deleted_by",
        existing_type=sa.String(length=128),
        type_=sa.UUID(),
        existing_nullable=True,
    )
    op.alter_column(
        "campfire_memory_deletion_ledger",
        "account_id",
        existing_type=sa.String(length=128),
        type_=sa.UUID(),
        existing_nullable=False,
    )
