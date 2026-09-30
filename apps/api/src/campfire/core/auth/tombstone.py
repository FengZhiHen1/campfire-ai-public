"""账号注销墓碑：一次注销的、不含任何用户内容的记录。

归属（2026-09-29 用户裁决，见
docs/技术设计/decisions/账号注销与墓碑.md）：本表归 `core/auth`，不新建模块、
不并入删除账本。

为什么它必须在 `core/auth` 而不是 `modules/accounts`：

判据是依赖白名单，不是偏好（[项目结构设计] 第 7 节）：

- 墓碑的读者是 Worker——它要回答「这条在途写入的账号是否已注销」；
- 而 Worker 只允许 import `core/*` 与 `modules/{profile,memory}`，
  且禁止回查业务用例；
- `modules/*` 之间又禁止互相依赖，因此 `modules/memory` 的消费路径
  读不到 `modules/accounts` 里的表。

请求路径与 Worker 都要读它——「跨界可读」正是它唯一的归属理由，
也让它是 `core/` 里第二张带业务语义的表（第一张是 `core/pending_write`，
两者都是有意的例外，各自的形状由设计文档拥有）。

为什么不并入删除账本：

`campfire_memory_deletion_ledger` 的 `episode_key` 是 `NOT NULL` 且 UNIQUE、
语义是「某条 episode 被删」（实测 `models.py` 的列约束）。账号墓碑不对应任何
episode，塞进去会破坏该列的不变量。

为什么必须有它（不是可选记账）：

注销时可能已有 `pending_write` 在排队、甚至已被 Worker 领取。若账号删得无迹可寻，
Worker 写入时查不到账号——而「查不到」与「账号从不存在」无法区分，于是数据被
写回已注销账号的图（删后复活）。墓碑是 Worker 识别「已注销」的唯一依据。

内容边界（硬要求）：

只含账号标识、时间、原因，不含任何用户内容。由此有一条对外表述纪律：

    不得声称「已删除全部数据」；
    准确表述是「已删除全部内容，并保留一条不含内容的注销记录」。

理由：墓碑保留了 `account_id`（一个不透明 UUID）。它本身不含内容，但它是关于该
账号的一条记录——把「连记录都不剩」说成事实会是虚假陈述。若将来要求字面删净，
须一并删除墓碑并补「注销前排空队列」的机制（见决策记录的重访条件）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from campfire.core.db import Base

#: 注销原因的词表。
#:
#: 一期只有 `user_request`：账号注销由使用者口头提出、运营者经 CLI 执行
#: （[认证与账号] 第 8 节：一期账号没有邮箱与手机号，没有可自助触达的通道）。
#: 保留词表形态而不是硬编码一个值，是为了让「运营主动清理」这类将来的原因
#: 走一次迁移（而不是改语义）——与删除账本 `reason` 同一种做法。
DELETION_REASON_USER_REQUEST = "user_request"

#: 合法原因取值集合（frozenset：不可变）。
TOMBSTONE_REASONS: frozenset[str] = frozenset({DELETION_REASON_USER_REQUEST})

#: 词表的 SQL 字面量（从集合派生，避免两份手写清单漂移；排序保证文本稳定）。
_TOMBSTONE_REASONS_SQL = ", ".join(f"'{value}'" for value in sorted(TOMBSTONE_REASONS))

#: 账号标识的列宽。与 `core/pending_write`、删除账本、邀请码表一致（128）。
MAX_ACCOUNT_ID_LENGTH = 128


class AccountDeletionTombstone(Base):
    """一次账号注销的墓碑。

    一行 = 一个已注销账号。表名用 `campfire_` 前缀（`core/db` 的约定），
    避免与 SuperTokens core 自建表（实测 56 张、无前缀）撞名。
    """

    __tablename__ = "campfire_account_deletion_tombstone"

    #: 账号标识。主键——一个账号只能注销一次，重复注销必须被存储层拒绝
    #: （而不是产生第二行，让「查墓碑」变成一个需要去重的问题）。
    #:
    #: 形如 SuperTokens 的用户标识（UUID v4 文本，36 字符），但本层不假设该形状：
    #: `core/*` 不得依赖业务模块，形状校验的归属见 `PendingWrite.account_id`
    #: 的同一条说明。
    account_id: Mapped[str] = mapped_column(String(MAX_ACCOUNT_ID_LENGTH), primary_key=True)
    #: 注销时间。写入即固定，不随任何后续操作变化（它是审计事实）。
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )
    #: 注销原因，取值见 `TOMBSTONE_REASONS`。
    #:
    #: 判据落在 CHECK 约束上（CORE-05：不变量落最强通道）：词表是闭集且进审计，
    #: 静默写入未知原因会让「为什么会注销」无从查起。代价是词表变更需要一次迁移，
    #: 这是有意接受的——与删除账本 `reason` 同一种取舍。
    reason: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        # 按时间排查（「最近注销了哪些账号」）——注销是低频动作，一条索引足够。
        Index("ix_campfire_account_deletion_tombstone_deleted_at", "deleted_at"),
        # 词表的存储层判据。名字用短名：`core/db` 的 NAMING_CONVENTION 会展开为
        # `ck_campfire_account_deletion_tombstone_<name>`；写全名会被再套一层前缀并
        # 截断到 63 字符（`modules/memory/models.py` 与邀请码表都实测踩过这个坑）。
        CheckConstraint(f"reason IN ({_TOMBSTONE_REASONS_SQL})", name="reason"),
        {"comment": "账号注销墓碑：不含任何用户内容，是 Worker 判定「已注销」的唯一依据"},
    )


__all__ = [
    # 常量
    "DELETION_REASON_USER_REQUEST",
    "MAX_ACCOUNT_ID_LENGTH",
    "TOMBSTONE_REASONS",
    # 表
    "AccountDeletionTombstone",
]
