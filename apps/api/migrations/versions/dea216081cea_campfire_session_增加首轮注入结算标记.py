"""campfire_session 增加首轮注入结算标记

Revision ID: dea216081cea
Revises: 5fe0de69e768
Create Date: 2026-10-01 01:45:11.337875

业务意图（依据编排器 T07b 裁决 9 与 docs/技术设计/面/consult/HTTP与SSE契约.md 第 3.1 节）：

- 契约 3.1 规定：`onboarding_pending` 为真时，该会话的**第一次运行**由服务端程序注入
  onboarding skill 与静态告知文本。判定「是不是第一次运行」需要一个每会话只翻一次
  的开关，本迁移把它加到会话归属表上。
- 为什么在 `campfire_session` 而不是账号级的 `campfire_onboarding`：两者的粒度不同。
  `campfire_onboarding.state` 回答「这个账号还要不要引导」，本列回答「这个会话的那一次
  注入结算了没有」。同一个账号可以先后建多个会话，而每个会话都有它自己的第一次运行。
- 为什么这个标记可以落库（该表的原则是不存消息内容与标题这类派生值）：它记的是
  「服务端已经替这个会话结算过那一次注入」这一历史事实，从会话内容反推并不可靠
  ——注入正文可能被压缩改写、可能因该次运行起步失败而根本没落进会话真源，
  也无从与使用者自己写下的同文内容区分。字段说明里写了完整论证。
- 默认 `false` 且非空：存量会话（本迁移之前建的）一律视为「尚未结算」，于是它们
  的第一次运行仍会按引导状态决定是否注入——这与迁移前的行为一致，不制造静默的行为
  变化。应急会话在建会话时显式写为 `true`。

本迁移经 `--autogenerate` 生成，实测只含这一条 `add_column`（无与本改动无关的漂移）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dea216081cea"
# 重挂：本迁移与 `e121e242fa99`（待处理记录来源扩展为六值）同从 `5fe0de69e768`
# 分出，两个泳道并行产出时形成双 head。按单一链的要求，后合入的挂到先合入的之后——
# 两条改的是互不相关的表，先后不影响结果。
down_revision: Union[str, Sequence[str], None] = "e121e242fa99"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """加一列布尔标记，默认 false。

    `server_default` 必须显式给：列是非空的，存量行需要一个确定值。
    `false` 是唯一安全的方向——把存量会话当成「已结算」会让它们再也拿不到引导。
    """
    op.add_column(
        "campfire_session",
        sa.Column("first_run_injected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    """回滚：删列。

    删列即丢掉「哪些会话已结算过注入」这一历史。回滚后所有会话的第一次运行都会
    重新按引导状态判定，因此可能对已引导过的老会话再注入一次引导（重复一段可跳过的
    引导，不损失数据——技能设计第 4 节对误注入的代价判断正是如此）。
    """
    op.drop_column("campfire_session", "first_run_injected")
