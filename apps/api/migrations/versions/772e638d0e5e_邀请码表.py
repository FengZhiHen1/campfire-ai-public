"""邀请码表

Revision ID: 772e638d0e5e
Revises: 5e27503214c3
Create Date: 2026-09-30 09:24:28.557557

业务意图（依据 docs/技术设计/technical-details/认证与账号.md 第 4 节；
归属见 docs/项目结构设计.md 第 6 节）：

- 建 `campfire_invite_code`：**注册准入的存储层真相源**。设计选择自己持表、不依赖
  身份服务是否原生支持邀请码，理由是可用性不变量——建号发生在 SuperTokens core 这个
  **独立进程**内，我们本库的事务无法跨进程覆盖它（第 4 节 2026-09-29 修正）。自己持表
  才能做到「**无效码绝不建号**」：先在本库原子占用，失败即拒绝，**不触碰身份服务**。
- **`code` 是主键**（自带唯一索引）：按码占用是索引等值查，因此**不存在应用层的逐字符
  比较**——第 4 节要求「比较须恒定时间，避免计时旁路」，其落点就在这里加仓储层的条件更新。
- **四条约束的判据来自状态机，方向性不是随意选的**：

  | 约束 | 表达式 | 为什么是这个方向 |
  |---|---|---|
  | `state` | `IN ('issued','revoked','used')` | 闭集词表；静默写入未知状态会让「还能用吗」走空 |
  | `issued_is_pristine` | `state <> 'issued' OR (两时间戳均为空)` | **单向**——见下 |
  | `used_requires_timestamp` | `state <> 'used' OR used_at IS NOT NULL` | **单向**——见下 |
  | `revoked_at_by_state` | `(state = 'revoked') = (revoked_at IS NOT NULL)` | `revoked` 是**吸收态**、无迁出路径，双向都成立 |

- **两处单向写法都是实测修正的结果（不是风格偏好）**：

  ① `used_at` **不能**写成双向等价 `(state = 'used') = (used_at IS NOT NULL)`。
  `used` 可以**迁移到 `revoked`**（第 4 节明确「码已占用但账号未建」这一中间态由运营在
  撤销时处理），迁移后 `used_at` 作为**历史事实**仍保留（「这张码曾在何时被占用过」并没有
  因为撤销而变得不真实）。等价断言却要求 `state <> 'used'` 时该列为 NULL，于是
  **撤销一个已占用的码直接撞约束**——实测报 `CheckViolationError`。

  ② `issued_is_pristine` **也不能**写成双向等价。等价形式会给**词表外的状态**也判违规
  （`state = 'not_a_state'` 且两时间戳为空时，右侧为真、左侧为假，等价即假），于是
  「写了一个非法状态」这条错误会被**本约束抢先报出**，消息说成「issued 必须无历史」，
  把排查引向错误方向。PostgreSQL **不保证按书写顺序检查约束**，因此不能靠调整顺序解决。
  实测：先报的正是 `issued_is_pristine` 而不是 `state`。

- **刻意不含 `used_by_account_id`**（对照第 4 节的**顺序**才发现，不是宽松）：第 4 节
  步骤 1 是「先在本库原子占用」、步骤 2 才是「调用建号」，即占用发生在**账号尚不存在**
  之时，该列在占用那一刻**只能是 NULL**。把它纳入 `state = used` 的必填判据，会让
  **每一次注册都无法占用**。它的值在步骤 2 成功后回填（`bind_invite_code_account`）。
  由此保留一个**有意的中间态**：`state = used` 且 `used_by_account_id IS NULL`
  ——「码已占用但账号未建」。第 4 节明确该状态**安全**（拒绝二次使用），由运营在
  撤销/重发时处理，不在请求路径内自动回收；它是**排查信号**而非脏数据。
- **索引**对应两条运营查询：`invite list`（按状态筛 + 按签发时间倒序）与
  「还剩多少张有效码 / 过期清理」（按 `expires_at`）。
- 表名用 `campfire_` 前缀。**这不是风格问题**：SuperTokens core 在同一个库里建了
  **56 张无前缀表**（`session_info`、`emailpassword_users`…），前缀是防止撞名的实际手段。

**回滚方向**：直接删表。**已签发但未使用的邀请码会随之丢失**——回滚后这些码无法再用，
需要重新签发。已完成的注册**不受影响**（账号在身份服务的表里，与本表无外键绑定——
这是有意的：本表可独立重建，账号不会因它被级联删除）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "772e638d0e5e"
down_revision: Union[str, Sequence[str], None] = "5e27503214c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建邀请码表、两条索引与四条 CHECK 约束。"""
    op.create_table(
        "campfire_invite_code",
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("state", sa.String(length=16), server_default=sa.text("'issued'"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_account_id", sa.String(length=128), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(state = 'revoked') = (revoked_at IS NOT NULL)",
            name=op.f("ck_campfire_invite_code_revoked_at_by_state"),
        ),
        sa.CheckConstraint(
            "state <> 'issued' OR (used_at IS NULL AND revoked_at IS NULL)",
            name=op.f("ck_campfire_invite_code_issued_is_pristine"),
        ),
        sa.CheckConstraint(
            "state <> 'used' OR used_at IS NOT NULL",
            name=op.f("ck_campfire_invite_code_used_requires_timestamp"),
        ),
        sa.CheckConstraint("state IN ('issued', 'revoked', 'used')", name=op.f("ck_campfire_invite_code_state")),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_campfire_invite_code")),
        comment="注册准入的邀请码：存储层是唯一真相源，校验在本库完成",
    )
    op.create_index("ix_campfire_invite_code_expires_at", "campfire_invite_code", ["expires_at"], unique=False)
    op.create_index(
        "ix_campfire_invite_code_state_created",
        "campfire_invite_code",
        ["state", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """删表与索引（**已签发未使用的邀请码会丢失**，见模块头部说明）。"""
    op.drop_index("ix_campfire_invite_code_state_created", table_name="campfire_invite_code")
    op.drop_index("ix_campfire_invite_code_expires_at", table_name="campfire_invite_code")
    op.drop_table("campfire_invite_code")
