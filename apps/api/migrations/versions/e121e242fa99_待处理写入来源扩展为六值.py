"""待处理写入来源扩展为六值

Revision ID: e121e242fa99
Revises: 5fe0de69e768
Create Date: 2026-10-01 00:23:20.662448

业务意图（依据 docs/技术设计/technical-details/写入路径.md 第 3 节；
docs/技术设计/technical-details/个性化档案.md 第 3 节；
docs/技术设计/面/consult/tools/propose_profile_item.md 第 4 节）：

- `campfire_pending_write.origin` 的词表是契约的一部分，不是实现细节。
  `third_party_report`（第三方转述）与 `document`（文档记录）和使用者自述、
  监护人观察一样直接进稳定层（个性化档案第 3 节），因此存储层必须接受它们。
- 缺了这两个取值时的现象是工具失败而不是落层错误：
  `tools/profile.py:propose_profile_item` 把落库异常统一转成 `tool_failed`
  （`except Exception` 分支，那是有意的：写入失败不得回执 submitted），
  于是调用方读不到「是约束不接受」这一原因。
- 为什么在 `711fc22a40fd` 已经加宽过之后还要再落一次：alembic 不会重跑已标记为
  应用过的 revision。任何库若在 `711fc22a40fd` 的加宽语句生效之前就把它记为已应用，
  `alembic upgrade head` 之后再也不会修它——升级是幂等的，但它幂等地什么都不做。
  实测本机 `campfire_t03` 正处于该状态（`alembic_version = fecd059d662b` 已含该
  revision，而约束仍是四值）。本迁移因此是幂等的重新断言：库内已是六值时执行结果
  与之一致，仍是四值时把它修到六值。
- 与既有数据的兼容：新约束只放宽取值集合（四值是六值的子集），
  因此库中已存在的合法行都仍然合法。若库中存在词表外的历史值，
  PostgreSQL 会拒绝加约束并报错——那是有意的：宁可失败并要求人工确认，
  也不做隐式的数据改写。
- 六值在这里是冻结快照，不 import 模型：迁移是历史记录，若 import
  `core/pending_write/models.py` 的 `ORIGINS`，同一条 revision 在不同提交上就会产生
  不同的 CHECK——旧库升级得到的是当时的词表、新库得到的是将来的词表，复现与回滚都
  失去确定性（`711fc22a40fd` 的 `_ORIGINS_SIX` 是同一处置的先例）。
  代价是两侧必须同步：将来增删 `ORIGINS` 的取值，必须另写一次迁移。
  这条同步义务由 `apps/api/tests/test_pending_write_integration.py` 的一致性用例在真库上
  守着（断言库内 CHECK 的取值集合 == 模型 `ORIGINS`）——alembic 的 autogenerate
  不比对 CHECK 约束（见 `760b797c8bab` 的说明），这类漂移只有测试能发现。
- 手工编写而非 `--autogenerate`：实测给既有表改 CHECK 约束时 autogenerate 产出空操作，
  照它生成会得到一条「声称补齐了而实际什么都没做」的假迁移。

回滚方向：本迁移不引入新的 schema 状态（六值自 `711fc22a40fd` 起就是本链声明的
schema），因此 `downgrade` 同样重新断言六值，而不是退回四值。退回四值会凭空制造一次漂移
——回退到 `5fe0de69e768` 时按链的定义仍应是六值；而且只要库中已有
`document` / `third_party_report` 的记录，那次收紧会直接失败，把一次普通的迁移回滚
变成需要人工清理数据的事故。
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e121e242fa99"
down_revision: Union[str, Sequence[str], None] = "5fe0de69e768"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: `origin` 词表的六值快照，与 `core/pending_write/models.py` 的 `ORIGINS` 一致
#: （同步义务与不 import 模型的理由见模块头部说明）。排序与模型侧 `sorted(ORIGINS)` 相同，
#: 让两处的约束文本逐字一致、autogenerate 不再产出噪音。
_ORIGINS_SIX = (
    "ai_inference",
    "document",
    "guardian_observation",
    "system_observation",
    "third_party_report",
    "user_statement",
)

#: 约束名用短名：`core/db` 的 NAMING_CONVENTION 会展开为
#: `ck_campfire_pending_write_origin`。写完整名会被再套一层前缀并截断到 63 字符
#: （`760b797c8bab` 实测踩过两次），两侧写法不一致会让 autogenerate 反复产出噪音。
_ORIGIN_CONSTRAINT = "origin"

#: 被重新断言约束的表。
_PENDING_WRITE_TABLE = "campfire_pending_write"


def _reassert_origin_check() -> None:
    """把 `campfire_pending_write.origin` 的 CHECK 重新断定为六值。

    `if_exists=True` 让「约束不存在」也走同一个分支：新库与老库、四值库与六值库
    都收敛到同一个结果，不需要分支判断。
    """
    op.drop_constraint(_ORIGIN_CONSTRAINT, _PENDING_WRITE_TABLE, type_="check", if_exists=True)
    values = ", ".join(f"'{origin}'" for origin in _ORIGINS_SIX)
    op.create_check_constraint(_ORIGIN_CONSTRAINT, _PENDING_WRITE_TABLE, f"origin IN ({values})")


def upgrade() -> None:
    """重新断言六值，修复只应用了四值约束的库（见模块头部说明）。"""
    _reassert_origin_check()


def downgrade() -> None:
    """同样重新断言六值——本迁移不引入新的 schema 状态（见模块头部说明）。"""
    _reassert_origin_check()
