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

#: 账号标识的合法字符集。**必须与 Graphiti 的 `validate_group_id`
#: （正则 `^[a-zA-Z0-9_-]+$`）保持一致**——不一致会让某些账号在写入时才失败。
#: 空串在 Graphiti 里被放行（代表默认分区），但我们**拒绝**：空账号意味着
#: 所有人共用一张图，正是要避免的事。
_ACCOUNT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

#: UUID5 的命名空间：固定值，保证「同一 pending_id → 同一 episode uuid」跨进程成立。
#: 用 UUID5（基于 SHA-1 的名字派生）而不是 UUID4——后者每次随机，无法幂等。
#: 该常量一旦上线不得更改：改了会让所有历史 pending_id 派生出不同的 uuid。
EPISODE_UUID_NAMESPACE = uuid.UUID("6f2a1c3e-9b74-4d51-8a0e-2c5f7b9d4e11")


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


def to_account_id(raw: str) -> AccountId:
    """把外部传入的账号标识转成 `AccountId`，并在边界处校验。

    校验放在此处而不是写入时：不合法的账号键会变成**一张读不到的图**——写入成功、
    读取为空，属于最难排查的一类失败（2026-09-29 实测的分区语义即为此）。

    Raises:
        AccountIdError: 空值或含非 `[a-zA-Z0-9_-]` 字符时。
    """
    if not raw:
        raise AccountIdError(raw, "账号标识为空")
    if not _ACCOUNT_ID_PATTERN.fullmatch(raw):
        raise AccountIdError(raw, "含非字母数字、连字符或下划线的字符（FalkorDB 图名约束）")
    return AccountId(raw)


def derive_episode_uuid(pending_id: PendingId) -> EpisodeUuid:
    """由 `pending_id` 派生确定性的 episode uuid。

    **同一 pending_id 永远得到同一 uuid**——这是重复投递不产生第二条 episode 的
    唯一依据（图库的 `MERGE` 是覆盖语义，没有「已存在则跳过」，见通用记忆第 3 节）。

    Raises:
        MemoryDataError: `pending_id` 为空时——空值派生出的 uuid 会让所有空记录
            撞成同一条记忆，属于必须显式拒绝的输入。
    """
    if not pending_id:
        raise MemoryDataError(
            "pending_id 为空，无法派生 episode 标识",
            operation="derive_episode_uuid",
            detail="pending_id 不得为空",
        )
    return EpisodeUuid(str(uuid.uuid5(EPISODE_UUID_NAMESPACE, pending_id)))


__all__ = [
    "EPISODE_UUID_NAMESPACE",
    "AccountId",
    "AccountIdError",
    "EpisodeUuid",
    "PendingId",
    "derive_episode_uuid",
    "to_account_id",
]
