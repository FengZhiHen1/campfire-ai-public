"""读取侧的删除过滤：把账本里的 `episode_key` 取出来供图库侧排除。

归属（见 docs/技术设计/technical-details/通用记忆.md 第 7 节）：**账本过滤是语义
删除的唯一生效点**，图库物理删除不是。两条读路径都必须先经这里。

**为什么是「取 key 再传给图库」而不是「读回来再过滤」**：先在图库查询里排除
（`WHERE NOT e.uuid IN $deleted`）可以让过滤与分页/上限在同一层生效。若读回来再
过滤，`limit` 会先把已删除的算进去——「取最近 20 条」可能实际只剩 3 条可见，
这不是等价变换。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.memory.models import MemoryDeletionLedger

#: 单次查询取回的已删 key 上界。**有界**（CORE-11）：读路径是应急首字时延的一部分，
#: 不能把「该账号删过的全部记忆」无界拉进内存再塞进 Cypher 参数。超出部分会退化为
#: 「按账号整体排除」——见 `deleted_episode_keys` 的说明。10k 远超一期单账号记忆量
#: （参数表 `emergency_memory_limit` 为 20 条量级），越界即说明该账号需要物理清理。
DELETED_KEYS_LIMIT = 10_000


async def deleted_episode_keys(session: AsyncSession, account_id: object) -> list[str]:
    """取该账号已删除的 episode key 列表（升序，稳定）。

    Args:
        session: 关系库会话。
        account_id: 账号标识（与 `group_id` 同源）。

    Returns:
        已删 `episode_key`；无删除记录时为空列表（**正常状态，不是错误**）。

    Note:
        超过 ``DELETED_KEYS_LIMIT`` 时只返回前 N 条。这是**有意的降级**而非静默截断：
        调用方（`store.py`）在条数触顶时会额外标注无法完整排除，避免把"排除了前 N 条"
        误当成"已全部排除"。
    """
    result = await session.execute(
        select(MemoryDeletionLedger.episode_key)
        .where(MemoryDeletionLedger.account_id == account_id)
        .order_by(MemoryDeletionLedger.deleted_at)
        .limit(DELETED_KEYS_LIMIT)
    )
    return list(result.scalars())


def keys_are_complete(keys: Sequence[str]) -> bool:
    """`deleted_episode_keys` 的结果是否**完整**（未触顶）。

    触顶意味着可能仍有已删记忆未被排除。调用方据此决定是否标注降级——
    静默截断会让"删除生效"这个不变量在实际数据量下悄悄失效。
    """
    return len(keys) < DELETED_KEYS_LIMIT


__all__ = [
    "DELETED_KEYS_LIMIT",
    "deleted_episode_keys",
    "keys_are_complete",
]
