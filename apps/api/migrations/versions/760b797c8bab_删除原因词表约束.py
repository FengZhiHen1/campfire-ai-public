"""删除原因词表约束

Revision ID: 760b797c8bab
Revises: 86f653f40b92
Create Date: 2026-09-29 22:13:04.927428

业务意图（依据 docs/技术设计/technical-details/通用记忆.md 第 7 节；评审发现 2026-09-29）：

- 给 `campfire_memory_deletion_ledger.reason` 加 **CHECK 约束**，把 `DELETION_REASONS`
  这个闭集从「Python 侧 frozenset + 注释承诺」提升为**存储层判据**。
- **为什么必须做**：此前实测 `pg_constraint` 里只有 PK 与 UNIQUE，**没有任何 CHECK**；
  探针执行 `INSERT ... reason='not_a_valid_reason'` **成功**。即注释写着「取值见
  DELETION_REASONS」，存储层却接受任意 32 字符内的字符串——删除原因进审计，
  静默写入未知原因会让审计结论不可信（CORE-05：不变量要落到最强可行通道）。
- 词表取值：`user_request`（使用者显式删除）、`correction`（纠正）、
  `account_deletion`（账号注销/清理）。**这里是冻结的字面量快照**——迁移是历史记录，
  不随词表演进；新增原因须另写一次迁移更新本约束，这是有意接受的成本
  （见 `memory/models.py` 中 `reason` 字段的说明）。

**升级方向**：空表或已有值全部合法时直接成功。若库中已存在词表外的 `reason`，
PostgreSQL 会**拒绝加约束并报错**——这是**有意的**：宁可失败并要求人工确认那些行
该怎么归类，也不做「先改数据再加约束」这种隐式数据改写（迁移不得擅自修改业务数据）。

**回滚方向**：只是丢约束，不动数据，无风险。
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "760b797c8bab"
down_revision: Union[str, Sequence[str], None] = "86f653f40b92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: 约束名。**这里是短名**，与模型 `CheckConstraint(name="reason")` 完全一致。
#:
#: 为什么不是完整名（2026-09-29 实测踩过两次）：`op.create_check_constraint` 会经过
#: `core/db` 的 NAMING_CONVENTION（`ck_%(table_name)s_%(constraint_name)s`）展开——
#: 传完整名会得到「`ck_campfire_memory_deletion_ledger_` + 完整名」，63 字符被
#: PostgreSQL 截断成 `ck_campfire_memory_deletion_ledger_ck_campfire_memory_d_0b19`，
#: 与模型侧声明的名字不一致。**两侧都写短名**，由约定统一展开，才是同一个名字。
_CONSTRAINT_NAME = "reason"

#: 冻结的词表快照（与当时 `memory/models.py` 的 `DELETION_REASONS` 一致）。
_REASONS = ("user_request", "correction", "account_deletion")


def upgrade() -> None:
    """加上删除原因的词表约束。

    **本迁移由手工编写，不是 `--autogenerate` 的产物**：实测 Alembic 对 CHECK 约束的
    自动检测产出的是**空迁移**（`pass`），那会声称加上了约束而实际什么都没做——
    属于「永远不会失败的假闸门」，比没有迁移更危险。
    """
    values = ", ".join(f"'{reason}'" for reason in _REASONS)
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "campfire_memory_deletion_ledger",
        f"reason IN ({values})",
    )


def downgrade() -> None:
    """移除词表约束（只丢约束，不动数据）。"""
    op.drop_constraint(
        _CONSTRAINT_NAME,
        "campfire_memory_deletion_ledger",
        type_="check",
    )
