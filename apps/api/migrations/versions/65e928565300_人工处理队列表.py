"""人工处理队列表

Revision ID: 65e928565300
Revises: dea216081cea
Create Date: 2026-10-01 08:57:02.026006

业务意图（依据 docs/技术设计/technical-details/RAG策略.md 第 1.2 节）：

- 本迁移建出不可分块的可移交落点。RAG 策略第 1.2 节要求「仍不可分的单元标记
  `needs_manual_review` 并计入人工处理队列，不静默截断」——而此前的实现里这条队列
  只是一句 CLI 打印的计数：运维既不知道是哪一份文件、哪一节，也拿不到正文与原因，
  计数在进程退出后彻底消失。被拒绝嵌入的内容实际是被静默丢弃的，与「不静默截断」
  正相反。本表把那份复核件落成可查询的行。
- 一行 = 一个「超限且不可分、因此未嵌入」的块：库别、条目、来源路径、locator、
  正文摘录、原因、时间。
- 字段取「能移交」的最小集合：`locator` 回答「哪一节」（`Chunk.locator`，
  章节路径），`excerpt` 回答「是什么内容」，`review_reason` 回答「为什么不能切」。
  正文只存摘录而不存全文：真源仍是源文件，本表不是第二份语料；截断上界与留痕
  见 `manual_review.MANUAL_REVIEW_EXCERPT_CHARS`。
- `library` 落成 CHECK 约束（CORE-05：不变量落最强可行通道）：两库共用这一张表
  （复核件的字段与用途对两库完全一致，分表只会让「今天有多少待人工处理」变成两次
  查询），于是库别成了列——写错一个值就会产出一条任何按库取的查询都看不到的孤儿行。
- 不建指向条目表的外键：一条复核件可能属于资料条目或案例条目，两条外键只能
  二者必有其一（可空 + CHECK），而「条目被撤下时复核件怎么消失」的语义已由撤下
  路径显式删行表达（`manual_review.delete_manual_reviews`），不是级联。
- 不建 `(item_id, locator, review_reason)` 唯一约束：重摄取时整批替换已保证不堆积，
  而同一份文件里两个不同小节落到同一 `locator` 并非不可能（无标题的小节都取 `/`），
  唯一约束会把那变成写入报错——那不是缺陷。

⚠️ 逐行核对过 `upgrade()`：只建本表与其一个索引，没有任何 drop/remove。
`--autogenerate` 本次只报告「Detected added table 'campfire_manual_review'」与
「Detected added index 'ix_campfire_manual_review_library_item'」，未提议任何
remove_table / remove_index——白名单过滤器（`migrations/env.py` 的 `include_object`）
正常工作，SuperTokens core 建在同一个库里的 60 张无前缀表未被当成待删对象。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "65e928565300"
down_revision: Union[str, Sequence[str], None] = "dea216081cea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建人工处理队列表与其索引、库别取值域约束。"""
    op.create_table(
        "campfire_manual_review",
        sa.Column("id", sa.UUID(), nullable=False),
        #: 库别：复核件属于哪个库的条目。两库共用本表，故库别是列而非表身份。
        sa.Column("library", sa.String(length=20), nullable=False),
        #: 所属条目 id。不加外键：条目可能来自两张表（见模块头部）。
        sa.Column("item_id", sa.UUID(), nullable=False),
        #: 摄取来源路径（资料侧是文件、案例侧是包目录），运维据此定位原件。
        sa.Column("source_path", sa.Text(), nullable=False),
        #: 该块在源文件里的位置（`Chunk.locator`）。无标题的源文件取 `/`——
        #: 不是编出来的定位，而是「该文件没有章节路径」的如实表示。
        sa.Column("locator", sa.Text(), nullable=False),
        #: 正文摘录；超上界时截断并在文末写明原文总长（不静默截断）。
        sa.Column("excerpt", sa.Text(), nullable=False),
        #: 未能嵌入的原因（`Chunk.review_reason`，由分块后处理给出）。
        sa.Column("review_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        #: 约束名用短名，由 `core/db` 的 NAMING_CONVENTION 展开为
        #: `ck_campfire_manual_review_library`（与 ORM 声明逐字一致，否则 autogenerate 漂移）。
        sa.CheckConstraint("library IN ('case', 'knowledge')", name=op.f("ck_campfire_manual_review_library")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campfire_manual_review")),
        comment="人工处理队列：超限且不可分、未嵌入的块（不静默截断的落点）",
    )
    # 重摄取时按条目整批替换（删除条件就是这两列），「这个条目还有什么待处理」也走它。
    op.create_index(
        "ix_campfire_manual_review_library_item",
        "campfire_manual_review",
        ["library", "item_id"],
        unique=False,
    )


def downgrade() -> None:
    """回滚：删人工处理队列表及其索引。

    不触碰条目表与节点表：本迁移只建新表，回滚它不该影响摄取与检索的任何数据。
    删掉本表意味着「不可分块重新回到只有一个计数」的状态，因此回滚前应先把待处理
    明细导出（本表是那批内容唯一的可查询落点）。
    """
    op.drop_index("ix_campfire_manual_review_library_item", table_name="campfire_manual_review")
    op.drop_table("campfire_manual_review")
