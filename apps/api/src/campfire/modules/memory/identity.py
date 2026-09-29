"""记忆的身份与派生标识。

归属（见 docs/技术设计/technical-details/通用记忆.md 第 1、3 节与
docs/技术设计/decisions/通用记忆归属为账号.md）：分区键是**账号**，且
episode 的确定性标识由 `pending_id` 派生。

## 两个必须集中在此处的理由

1. **账号标识要过两道校验**，而两道都不可省：
   - Graphiti 的 `validate_group_id`（`^[a-zA-Z0-9_-]+$`）；
   - FalkorDB 的图名约束——2026-09-29 实测：在 FalkorDB 后端 **`group_id` 就是图名**
     （`driver.clone(database=group_id)`），不是同图内的属性分区。
   任一不合法都会在运行期变成难查的失败，因此在**入口处**转成显式错误。
2. **确定性 uuid 是幂等的唯一依据**（第 3 节实测）：图库的身份是 `uuid` 而非 `name`，
   但同一个 uuid 不能直接交给 `add_episode(uuid=...)`（该参数要求节点已存在）。
   把「派生」与「写入」分开，是为了让写入侧能先查我方幂等标记再决定要不要碰图库。
"""

from __future__ import annotations

import re
import uuid
from typing import NewType

from campfire.modules.memory.errors import MemoryDataError

# === AccountId ===
# 前置: 来自登录态（分区键由会话决定，不接受调用方传入）
# 后置: 用于 FalkorDB 的图名与 Graphiti 的 group_id
# 输入约束: 仅 ASCII 字母数字、连字符、下划线（与 validate_group_id 同判据）
# 输出约束: 通过 NewType 防止与 episode uuid / pending id 混用
AccountId = NewType("AccountId", str)

# === PendingId ===
# 前置: pending_write 表的幂等键（请求事务内生成）
# 后置: 派生出确定性 episode uuid；同一条待处理记录永远得到同一个 uuid
# 输入约束: 非空字符串
# 输出约束: 防止与 AccountId / episode uuid 混用
PendingId = NewType("PendingId", str)

# === EpisodeUuid ===
# 前置: 由 pending_id 经 `derive_episode_uuid` 派生
# 后置: 作为图库 episode 的 uuid 与我方删除账本的 episode_key
# 输入约束: 合法 uuid 字符串
# 输出约束: 防止与 AccountId / PendingId 混用
EpisodeUuid = NewType("EpisodeUuid", str)

#: 账号标识的合法字符集。依据是 **Graphiti 的 `validate_group_id`**
#: （源码 `helpers.py`：`re.match(r'^[a-zA-Z0-9_-]+$', group_id)`，不合法即抛
#: `GroupIdValidationError`）——账号键最终要作为 `group_id` 传给 Graphiti，不满足它
#: 就会在写入时失败。
#:
#: **实测更正（2026-09-29，评审复核）**：此前本节声称还有「FalkorDB 图名约束」这第二道，
#: **该说法不成立**——FalkorDB 图名没有字符集限制（逐值实测 `acct.aaa`、`acct aaa`、
#: `账号一号`、`acct:aaa`、`acct/aaa`、`_` 全部建图成功）；客户端唯一真实的限制是
#: **空图名**（`falkordb/asyncio/falkordb.py` 抛 `TypeError: Expected a string parameter`）。
#: 因此本判断的**唯一**依据是 Graphiti 的正则，它同时也覆盖了「空值」——我们另行显式
#: 拒绝空值，理由见 `to_account_id`。
#:
#: 与 Graphiti 的判据有一处**方向性差异**：它用 `re.match`（`$` 允许尾随换行，
#: 实测 `validate_group_id('acct\n') is True`），我们用 `fullmatch`（拒绝）。我方更严，
#: 属安全方向：宁可少收一个畸形键，也不让尾随换行进入图名。
_ACCOUNT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

#: 账号标识的长度上界（CORE-11：外部输入必须有界）。实测此前无上界——100000 字符的
#: 键会被接受并成为 Redis 的图名。128 与账本列宽（`campfire_memory_deletion_ledger`
#: 的 `account_id`）一致；SuperTokens 的用户标识是 36 字符 UUID，128 留有充分余量。
MAX_ACCOUNT_ID_LENGTH = 128

#: 框架哨兵值：`FalkorDriver.default_group_id` 就是 `'_'`，且 `clone(database='_')`
#: 会走 `elif database == self.default_group_id` 分支、**落到 `default_db`**（实测），
#: 与我们写 `'_'` 那张图的位置不一致。若允许账号叫 `_`，就会出现「我方写入图 `'_'`、
#: Graphiti 写入图 `default_db`」的静默分叉。因此显式排除。
_FRAMEWORK_SENTINEL_ACCOUNT_IDS: frozenset[str] = frozenset({"_"})

#: UUID5 的命名空间：固定值，保证「同一 pending_id → 同一 episode uuid」跨进程成立。
#: 用 UUID5（基于 SHA-1 的名字派生）而不是 UUID4——后者每次随机，无法幂等。
#: 该常量一旦上线不得更改：改了会让所有历史 pending_id 派生出不同的 uuid。
#: 值本身是任意选定的固定 UUID（非从其它命名空间派生），只需全局唯一且永不改动。
#: 它的「被真正接线到派生输出上」由测试中的黄金向量断言钉住（见 test_memory_identity）。
EPISODE_UUID_NAMESPACE = uuid.UUID("6f2a1c3e-9b74-4d51-8a0e-2c5f7b9d4e11")

#: `pending_id` 的长度上界。它来自 `pending_write.id`（uuid4 文本，36 字符）；
#: 上界防止畸形输入被用来构造超长图名或异常长的派生输入。
MAX_PENDING_ID_LENGTH = 64


class AccountIdError(MemoryDataError):
    """账号标识不满足分区键的约束。

    单独成型是为了让调用方能区分「参数不合法」（调用方的问题，不该重试）
    与「图库不可用」（基础设施问题，可重试）。
    """

    def __init__(self, account_id: str, reason: str) -> None:
        """记录被拒绝的账号标识与原因。"""
        self.account_id = account_id
        super().__init__(
            f"账号标识不合法（{reason}）",
            operation="validate_account_id",
            detail=reason,
        )


def to_account_id(raw: object) -> AccountId:
    """把外部传入的账号标识转成 `AccountId`，并在边界处校验。

    校验放在此处而不是写入时：不合法的账号键会变成**一张读不到的图**——写入成功、
    读取为空，属于最难排查的一类失败（2026-09-29 实测的分区语义即为此）。

    参数类型是 `object` 而不是 `str`：这是**运行时数据边界**（CORE-04），外部传入的
    未必是字符串。类型标注写 `str` 会让「传了 int」这类错误在静态检查里被放过，
    而运行期抛出与校验无关的 `TypeError`（实测此前 `to_account_id(123)` 会抛
    `TypeError: expected string or bytes-like object`，调用方无法按 `AccountIdError`
    处理）。因此显式收窄并转成领域错误。

    Raises:
        AccountIdError: 非字符串、空值、超长、含非法字符，或命中框架哨兵值 `'_'`。
    """
    if not isinstance(raw, str):
        raise AccountIdError(str(raw), f"账号标识必须是字符串，收到 {type(raw).__name__}")
    if not raw:
        raise AccountIdError(raw, "账号标识为空")
    if len(raw) > MAX_ACCOUNT_ID_LENGTH:
        raise AccountIdError(raw[:32] + "…", f"账号标识超过 {MAX_ACCOUNT_ID_LENGTH} 字符上界")
    if raw in _FRAMEWORK_SENTINEL_ACCOUNT_IDS:
        raise AccountIdError(raw, "该值是 Graphiti 的默认分区哨兵，会导致我方与框架写入不同的图")
    if not _ACCOUNT_ID_PATTERN.fullmatch(raw):
        raise AccountIdError(raw, "含非字母数字、连字符或下划线的字符（Graphiti 的 group_id 判据）")
    return AccountId(raw)


def derive_episode_uuid(pending_id: PendingId) -> EpisodeUuid:
    """由 `pending_id` 派生确定性的 episode uuid。

    **同一 pending_id 永远得到同一 uuid**——这是重复投递不产生第二条 episode 的
    唯一依据（图库的 `MERGE` 是覆盖语义，没有「已存在则跳过」，见通用记忆第 3 节）。

    **安全性前提（不可省）**：UUID5 基于 SHA-1，对选择前缀碰撞已不牢靠。本设计成立
    完全依赖「`pending_id` 永远由我们自己的 uuid4 主键生成、不接受调用方传入」——
    若将来允许外部指定 pending_id，可预测性就从理论风险变成可选攻击面。
    这里用长度与空白校验兜住畸形输入，但**真正的保证是调用方不转发外部值**。

    Raises:
        MemoryDataError: `pending_id` 为空、非字符串、超长或全为空白时。
    """
    if not isinstance(pending_id, str):
        raise MemoryDataError(
            "pending_id 必须是字符串",
            operation="derive_episode_uuid",
            detail=f"type={type(pending_id).__name__}",
        )
    if not pending_id or not pending_id.strip():
        raise MemoryDataError(
            "pending_id 为空或全为空白，无法派生 episode 标识",
            operation="derive_episode_uuid",
            detail="pending_id 不得为空或全为空白",
        )
    if len(pending_id) > MAX_PENDING_ID_LENGTH:
        raise MemoryDataError(
            f"pending_id 超过 {MAX_PENDING_ID_LENGTH} 字符上界",
            operation="derive_episode_uuid",
            detail=f"length={len(pending_id)}",
        )
    return EpisodeUuid(str(uuid.uuid5(EPISODE_UUID_NAMESPACE, pending_id)))


__all__ = [
    # 常量
    "EPISODE_UUID_NAMESPACE",
    "MAX_ACCOUNT_ID_LENGTH",
    "MAX_PENDING_ID_LENGTH",
    # 语义类型
    "AccountId",
    "EpisodeUuid",
    "PendingId",
    # 异常
    "AccountIdError",
    # 函数
    "derive_episode_uuid",
    "to_account_id",
]
