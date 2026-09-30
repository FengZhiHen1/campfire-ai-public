"""邀请码表：注册准入的**存储层真相源**。

归属：``modules/accounts``（见 docs/项目结构设计.md 第 6 节）。
形状由[认证与账号](../../../../../../docs/技术设计/technical-details/认证与账号.md)第 4 节拥有。

## 为什么邀请码表归我们而不是身份服务

身份服务原生支持邀请码类机制，但设计选择**自己持有这张表**（第 4 节「校验在我们自己的
后端，不依赖身份服务是否原生支持邀请码」）。原因是可用性不变量：建号发生在 SuperTokens
core 这个**独立进程**内，我们本库的事务无法跨进程覆盖它（第 4 节 2026-09-29 修正）。
自己持表才能做到「**无效码绝不建号**」——第 1 步在本库原子占用，失败即拒绝，
**根本不触碰身份服务**。

## 状态机（第 4 节的 ``state`` 字段）

    issued ──占用成功──> used ──运营撤销──> revoked
       │
       └──运营撤销──> revoked

**两条迁移边都要写出来**（2026-09-30 评审指出本图此前缺了 ``used → revoked``）：
第 4 节明确「码已占用但账号未建」这一中间态**由运营在撤销/重发时处理**，
因此「撤销一个已占用的码」是**合法路径**，不是异常。它直接决定了 CHECK 的方向性（见下）。

**没有从 ``used`` 回到 ``issued`` 的正常迁移**：``used`` 的码不可再用。
唯一的例外是**补偿释放**——建号确实失败时把码退回 ``issued``（第 4 节第 3 步）。
补偿是**编排层的动作**，不改变「一个码只能用一次」这条不变量：它撤销的是
一次**未完成的**占用。

## 三条落存储层的不变量（CORE-05）

1. ``state`` 是闭集（CHECK）：静默写入未知状态会让「这个码还能用吗」的判定无声走空。
2. ``issued`` 是**无历史**态：两个时间戳都必须为空（单向蕴含）。
3. ``state = 'used'`` 时 ``used_at`` **必须非空**；``state = 'revoked'`` 时
   ``revoked_at`` **必须非空**。

**为什么是单向蕴含而不是「等价」写法**（2026-09-30 两处实测修正，原文写的是「等价」）：

- ``used_at`` **不能**写成等价 ``(state = 'used') = (used_at IS NOT NULL)``：
  ``used`` 可迁移到 ``revoked``（见上），迁移后 ``used_at`` 作为**历史事实**仍保留
  （「这张码曾在何时被占用过」不因撤销而变得不真实）。等价写法会要求
  ``state <> 'used'`` 时该列为 NULL，于是**撤销一个已占用的码直接撞约束**。
- ``issued`` 也**不能**写成等价：等价形式会给**词表外的状态**也判违规
  （``state = 'not_a_state'`` 且两时间戳为空时等价为假），于是「写了非法状态」
  这条错误会被**本约束抢先报出**、消息说成「issued 必须无历史」，把排查引向错误方向。
  PostgreSQL **不保证按书写顺序检查约束**，故不能靠调顺序解决。

**刻意不含 ``used_by_account_id``**：第 4 节的顺序是「先在本库原子占用，再调用建号」，
即占用发生在**账号尚不存在**之时，该列在那一刻**只能是 NULL**
（详见该字段自己的说明）。把它纳入必填判据会让**每一次注册都无法占用**。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from campfire.core.db import Base

#: 邀请码的长度（第 4 节：**8 位随机码**）。固定不可配置——它是运营口述与手抄的
#: 单位，长度变化会同时改变熵与可读性，属契约的一部分。
INVITE_CODE_LENGTH = 8

#: 生成邀请码用的字母表（32 个字符）。
#:
#: **为什么不用全部 62 个字母数字**：邀请码由运营**口述或手抄**发给使用者
#: （一期没有邮箱等可主动触达的通道，见第 3 节），因此形近字符是真实的失败来源。
#: 本表剔除 ``I``/``O``（与 ``1``/``0`` 形近）与 ``0``/``1``（与 ``O``/``I`` 形近），
#: 剩下 24 个字母 + 8 个数字 = 32 个字符，**恰好 5 bit/字符**。
#:
#: **熵**：8 字符 × 5 bit = **40 bit**。对一次性、30 天有效、且按 IP 限流
#: （第 5 节 Nginx 层）的准入码足够；这不是密码，不需要抗离线爆破。
#:
#: 判据同 ``modules/memory/identity`` 的框架哨兵：把「排障与口述的现实约束」
#: 写成常量而不是留给实现者随手选。
INVITE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

#: 邀请码的有效期天数（第 4 节：**30 天**）。覆盖正常发放节奏。
INVITE_CODE_TTL_DAYS = 30

#: 状态词表（第 4 节的 ``state``）。
STATE_ISSUED = "issued"
STATE_USED = "used"
STATE_REVOKED = "revoked"

#: 合法状态取值集合（frozenset：不可变）。
INVITE_CODE_STATES: frozenset[str] = frozenset({STATE_ISSUED, STATE_USED, STATE_REVOKED})

#: 运营者标识的长度上界。**它不是审计身份**——第 7 节明确「运营者身份就是能执行该
#: CLI 的人」，本期不引入应用层运营者表。此列只记录「这台机器上的哪个 OS 用户签发的」，
#: 追责仍靠 OS 层日志。宽度与账号列一致，便于跨表比对。
MAX_OPERATOR_LENGTH = 128

#: 账号标识的列宽（与 `PendingWrite.account_id`、删除账本一致）。
MAX_ACCOUNT_ID_LENGTH = 128

#: 词表的 SQL 字面量。**从集合派生**而不是另写一份（两份手写清单必然漂移）；
#: 排序保证文本稳定，避免 autogenerate 产生无意义差异。迁移里是冻结的字面量快照。
_INVITE_CODE_STATES_SQL = ", ".join(f"'{value}'" for value in sorted(INVITE_CODE_STATES))


class InviteCode(Base):
    """一张邀请码。**表名用 `campfire_` 前缀**（`core/db` 的约定），避免与
    SuperTokens core 自建表（实测 56 张，**无前缀**）撞名。"""

    __tablename__ = "campfire_invite_code"

    #: 邀请码本身，**主键**（第 4 节）。
    #:
    #: **比较必须恒定时间**：码是准入凭据，逐字符提前返回的比较会泄露前缀。
    #: 该纪律的落点在仓储层（``repository.claim_invite_code`` 用条件更新，
    #: 由数据库做等值比较），本层只负责唯一性——唯一约束自带索引，
    #: 因此按码查是索引等值查，且**不存在应用层的逐字符比较**。
    code: Mapped[str] = mapped_column(String(INVITE_CODE_LENGTH), primary_key=True)
    #: 状态，取值见 `INVITE_CODE_STATES`。默认 `issued`。
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATE_ISSUED, server_default=sql_text(f"'{STATE_ISSUED}'")
    )
    #: 有效期截止（签发时按 `INVITE_CODE_TTL_DAYS` 计）。占用的条件更新会带上
    #: ``expires_at > now()``，因此**过期的码在存储层就不可占用**，不依赖应用层先查。
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: 被使用的时间；`state = used` 时必填（CHECK 保证）。
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 使用它的账号（`account_id`，认证文档第 3 节：即身份服务的用户标识）。
    #:
    #: **必须可空，且这不是宽松而是必然**（2026-09-29 落地时对照第 4 节的顺序发现）：
    #: 第 4 节的步骤 1 是「先在本库原子占用邀请码」、步骤 2 才是「调用建号」——
    #: 占用发生在**账号尚不存在**之时，因此该列在占用那一刻**只能是 NULL**。
    #: 把它写成 `NOT NULL` 或纳入 `state = used` 的必填判据，会让**每一次注册都无法占用**。
    #: 它的值在步骤 2 成功后回填（`bind_invite_code_account`）。
    #:
    #: 由此存在一个**有意保留的中间态**：`state = used` 且 `used_by_account_id IS NULL`
    #: ——即「码已占用但账号未建」。第 4 节明确该状态**安全**（拒绝二次使用），
    #: 由运营在撤销/重发时处理，不在请求路径内自动回收。它是**排查信号**而非脏数据。
    used_by_account_id: Mapped[str | None] = mapped_column(String(MAX_ACCOUNT_ID_LENGTH), nullable=True)
    #: 撤销时间；`state = revoked` 时必填（CHECK 保证）。
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 签发者标识（运营者）。见 `MAX_OPERATOR_LENGTH` 与第 7 节：**这不是审计身份**。
    created_by: Mapped[str] = mapped_column(String(MAX_OPERATOR_LENGTH), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("now()")
    )

    __table_args__ = (
        # 运营查看（``invite list``）按状态筛、按签发时间倒序——一条复合索引覆盖它，
        # 避免全表扫描（码表随运营长期累积）。
        Index("ix_campfire_invite_code_state_created", "state", "created_at"),
        # 过期清理与「还有多少张有效码」的排查按它走。
        Index("ix_campfire_invite_code_expires_at", "expires_at"),
        # --- 词表与状态一致性落在**存储层**（CORE-05）---
        # 名字一律用短名，由 `core/db` 的 NAMING_CONVENTION 展开为
        # `ck_campfire_invite_code_<name>`；写全名会被再套一层前缀并截断到 63 字符
        # （`modules/memory/models.py` 与 `core/pending_write/models.py` 都实测踩过）。
        CheckConstraint(f"state IN ({_INVITE_CODE_STATES_SQL})", name="state"),
        # **`issued` 是「无历史」状态**：没有被占用过、也没有被撤销过。
        #
        # **必须是单向蕴含，不能写成等价**（2026-09-30 实测发现）：等价形式
        # `(state = 'issued') = (used_at IS NULL AND revoked_at IS NULL)` 会给
        # **词表外的状态**也判违规（例如 `state = 'not_a_state'` 且两个时间戳都为空时，
        # 右侧为真、左侧为假，等价即假）——于是「写了一个非法状态」这条错误会被
        # **本约束抢先报出**，错误消息说成「issued 必须无历史」，把排查引向错误方向。
        # PostgreSQL 不保证按书写顺序检查约束，所以不能靠调整顺序解决。
        #
        # 单向写法的保护是等价的：「issued 却已有占用或撤销记录」仍被拦住，
        # 而词表外的状态会正确地由 `state` CHECK 报出。
        CheckConstraint(
            "state <> 'issued' OR (used_at IS NULL AND revoked_at IS NULL)",
            name="issued_is_pristine",
        ),
        # **`used` 必须有占用时间**（单向蕴含）。
        #
        # **实测更正（2026-09-30，被 `test_revoke_accepts_an_unclaimed_occupation` 抓到）**：
        # 这里原本写成双向等价 `(state = 'used') = (used_at IS NOT NULL)`，**该写法是错的**。
        # 原因是 `used` 可以**迁移到 `revoked`**（第 4 节明确「码已占用但账号未建」这一
        # 中间态由运营在撤销时处理），迁移后 `used_at` 作为**历史事实**仍然保留
        # （「这张码曾在什么时候被占用过」并没有因为撤销而变得不真实）。等价断言却要求
        # `state != 'used'` 时 `used_at` 必须为 NULL，于是**撤销一个已占用的码直接撞约束**
        # ——实测报 `CheckViolationError: ck_campfire_invite_code_used_at_by_state`。
        # 改为单向蕴含后，「说占用了却没有时间」仍被拦住，而合法的状态迁移不再被误杀。
        CheckConstraint("state <> 'used' OR used_at IS NOT NULL", name="used_requires_timestamp"),
        # `revoked` 与撤销时间：这里用**双向等价**是安全的，因为 `revoked` 是吸收态、
        # 没有任何迁出路径（状态机见模块头部说明）；它同时拦住「used 却带着 revoked_at」
        # 这种自相矛盾行。
        CheckConstraint("(state = 'revoked') = (revoked_at IS NOT NULL)", name="revoked_at_by_state"),
        {"comment": "注册准入的邀请码：存储层是唯一真相源，校验在本库完成"},
    )


__all__ = [
    # 常量
    "INVITE_CODE_ALPHABET",
    "INVITE_CODE_LENGTH",
    "INVITE_CODE_STATES",
    "INVITE_CODE_TTL_DAYS",
    "MAX_ACCOUNT_ID_LENGTH",
    "MAX_OPERATOR_LENGTH",
    "STATE_ISSUED",
    "STATE_REVOKED",
    "STATE_USED",
    # 模型
    "InviteCode",
]
