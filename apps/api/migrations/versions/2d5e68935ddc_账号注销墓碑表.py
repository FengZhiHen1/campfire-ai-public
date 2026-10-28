"""账号注销墓碑表

Revision ID: 2d5e68935ddc
Revises: 772e638d0e5e
Create Date: 2026-09-30 09:40:38.172717

业务意图（依据 docs/技术设计/decisions/账号注销与墓碑.md 与
docs/技术设计/technical-details/认证与账号.md 第 8 节；
归属见 docs/项目结构设计.md 第 6 节）：

- 建 `campfire_account_deletion_tombstone`：账号注销的五步里的第 1 步
  （顺序不可调换，墓碑必须先写）。它解决的不是「记账」而是一个真实的数据复活路径：
  注销时可能已有 `pending_write` 在排队甚至已被 Worker 领取；若账号删得无迹可寻，
  Worker 写入时查不到账号——而「查不到」与「账号从不存在」无法区分，于是数据被
  写回已注销账号的图（删后复活）。墓碑是 Worker 识别「已注销」的唯一依据。
- `account_id` 是主键：一个账号只能注销一次。用存储层主键而不是应用层先查后写，
  是为了让并发两次注销请求不会产生第二行——否则「查墓碑」会变成需要去重的问题。
- 只含三列：账号标识、时间、原因。这是对外表述「该账号的内容已不再可读，并保留一条
  不含内容的注销记录」能成立的依据。⚠️ 给本表加任何承载用户内容的列，都会让该
  表述失效，必须同时改口径；`apps/api/tests/test_auth_tombstone_integration.py` 的
  `test_tombstone_has_no_user_content_columns` 把这条钉成机器化断言。
- `reason` 词表落 CHECK：一期只有 `user_request`（注销由使用者口头提出、运营经
  CLI 执行，见第 8 节）。保留词表形态而非硬编码单值，是为了让将来的原因走一次迁移
  而不是改语义——与删除账本 `reason` 同一种做法。
- 为什么归 `core/auth` 而不是 `modules/accounts`：判据是依赖白名单而非偏好。
  Worker 只允许 import `core/*` 与 `modules/{profile,memory}` 且禁止回查业务用例，
  而 `modules/*` 之间又禁止互相依赖——因此 Worker 读不到 `modules/accounts` 里的表。
  请求路径与 Worker 都要读它，跨界可读是它唯一的归属理由。
- 为什么不并入删除账本：`campfire_memory_deletion_ledger.episode_key` 是 `NOT NULL`
  且 `UNIQUE`、语义是「某条 episode 被删」，而账号墓碑不对应任何 episode。
- 表名用 `campfire_` 前缀，避免与 SuperTokens core 自建表（实测 56 张、无前缀）撞名。

回滚方向：直接删表。代价必须写明：删掉本表会让「已注销」这一事实消失，
从而重新打开删后复活的窗口——凡是在注销之后被重新投递的 `pending_write`
都会再次具备写入资格。因此回滚本表前须确认没有在途的待处理写入（或接受该风险）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2d5e68935ddc"
down_revision: Union[str, Sequence[str], None] = "772e638d0e5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建注销墓碑表、一条索引与原因词表约束。"""
    op.create_table(
        "campfire_account_deletion_tombstone",
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "reason IN ('user_request')",
            name=op.f("ck_campfire_account_deletion_tombstone_reason"),
        ),
        sa.PrimaryKeyConstraint("account_id", name=op.f("pk_campfire_account_deletion_tombstone")),
        comment="账号注销墓碑：不含任何用户内容，是 Worker 判定「已注销」的唯一依据",
    )
    op.create_index(
        "ix_campfire_account_deletion_tombstone_deleted_at",
        "campfire_account_deletion_tombstone",
        ["deleted_at"],
        unique=False,
    )


def downgrade() -> None:
    """删表与索引（会重新打开「删后复活」的窗口，见模块头部说明）。"""
    op.drop_index(
        "ix_campfire_account_deletion_tombstone_deleted_at",
        table_name="campfire_account_deletion_tombstone",
    )
    op.drop_table("campfire_account_deletion_tombstone")
