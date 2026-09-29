"""应急预注入的取数：派生事实（EntityEdge）+ 时效过滤。

归属（见 docs/技术设计/technical-details/通用记忆.md 第 4、6、7 节）：这是**第二条
读路径**，服务应急入口——由应用侧取数、随应急上下文注入，不走工具轮次
（`RQ-EMG-03` 的时延纪律）。日常咨询的按需回看见 `store.read_timeline`。

## 为什么自建查询而不是 `search()`

第 6 节已定：Graphiti 的 `search()` 是嵌入 + BM25 + 图遍历 + 重排的混合检索，每次
应急入口前跑一次会引入不确定时延与嵌入调用，违背首字 ≤10 秒；一期每账号记忆量小，
「近期全量 + 让模型自行判断相关性」是零嵌入成本的确定性方案。

## 两个必须显式处理的点（都是实测结论）

1. **`EntityEdge.get_by_group_ids` 不能用**（第 4 节实测）：它**不过滤 `invalid_at`**
   （会把已失效的事实注入成"当前认识"，直接违反 `RQ-MEM-01`）、按 `uuid` 排序而非
   时间，且**空结果抛 `GroupsEdgesNotFoundError`** 而不是返回空列表——那会让
   「该账号还没有记忆」被误判成「图库不可用」。因此本模块自建 Cypher。
2. **多来源边的删除判据是「至少一条来源在账本中即排除」**（第 7 节）：`EntityEdge.episodes`
   是列表，Graphiti 命中既有事实时会 `episodes.append(...)`，多来源是常态。取「全部被删」
   会让只删一条的情形漏过（删除未生效）；取「任一条」才与 `RQ-MEM-03` 一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from campfire.modules.memory.errors import MemoryDataError, MemoryUnavailableError
from campfire.modules.memory.identity import AccountId
from campfire.modules.memory.store import parse_db_datetime

if TYPE_CHECKING:
    # 仅为类型标注：装配层（graph.py）是本模块的依赖方向上游，运行期不 import 它，
    # 以免形成环（graph.py 不需要知道读路径的形状）。
    from campfire.modules.memory.graph import MemoryGraph

#: 应急预注入的派生事实**条数**硬上限（通用记忆第 10 节参数表初值）。
#: 防记忆量线性增长击穿注入预算；实测后按真实数据调整。
EMERGENCY_MEMORY_LIMIT = 20

#: 应急预注入的**字符**总量上限（第 5 节：条数上限不能代替字符上限）。
#: `fact` 文本长度无界，20 条的字符量可以远超 RAG 应急注入 top-3 的量级。
#: 6000 字符约为中文 3000 字，与档案七组同处一个注入预算管道内（第 5 节）。
EMERGENCY_MEMORY_CHARS = 6000


@dataclass(frozen=True, slots=True)
class DerivedFact:
    """一条当前有效的派生事实（注入形状见第 6 节）。

    字段对齐第 6 节的注入形状：`fact` 文本、`valid_at`、来源 episode 指针。
    """

    fact: str
    #: 事实开始成立的时间。
    valid_at: datetime | None
    #: 来源 episode 的 uuid 列表（多来源是常态）。
    source_episodes: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class EmergencyMemory:
    """应急预注入的取数结果。

    ``facts`` 为空表示**该账号还没有记忆**（正常状态，不标注降级）；
    图库不可用会抛 `MemoryUnavailableError`——两者必须区分（第 6 节）。
    """

    facts: list[DerivedFact]
    #: 因字符上限被截断的条数（>0 时调用方应知道"记忆被压缩过"）。
    truncated_by_chars: int = 0

    @property
    def is_empty(self) -> bool:
        """是否没有任何可注入的记忆（正常空态）。"""
        return not self.facts


async def read_emergency_facts(
    graph: MemoryGraph,
    account_id: AccountId,
    *,
    deleted_keys: list[str],
    limit: int = EMERGENCY_MEMORY_LIMIT,
    char_budget: int = EMERGENCY_MEMORY_CHARS,
) -> EmergencyMemory:
    """取「当前有效」的派生事实，按时效过滤，供应急预注入。

    Args:
        graph: 记忆图库句柄（本函数自行切到账号那张图，并复用装配层的驱动缓存）。
        account_id: 分区键，由登录态决定。
        deleted_keys: 该账号已删除的 episode key；**引用这些 episode 的边一律排除**
            （第 7 节的多来源边判据）。
        limit: 条数上限。
        char_budget: 字符总量上限。

    Returns:
        按 `valid_at` 倒序的派生事实；**没有记忆时返回空结果而不是抛错**。

    Raises:
        MemoryUnavailableError: 图库查询失败（与"没有记忆"严格区分）。
        MemoryDataError: 取回的数据不合法（缺 `fact` 文本）。
    """
    conditions = ["e.group_id = $group_id", "e.invalid_at IS NULL"]
    params: dict[str, object] = {"group_id": account_id, "limit": max(1, limit)}

    if deleted_keys:
        # 多来源边判据（第 7 节）：**至少一条**来源 episode 在账本中即排除。
        # 用列表推导做交集判断，而不是「全部被删」——后者会让只删一条的情形漏过。
        conditions.append("NOT any(ep IN $deleted WHERE ep IN e.episodes)")
        params["deleted"] = deleted_keys

    cypher = (
        "MATCH (n:Entity)-[e:RELATES_TO]->(m:Entity) WHERE "
        + " AND ".join(conditions)
        + " RETURN e.uuid AS uuid, e.fact AS fact, e.valid_at AS valid_at,"
        + " e.episodes AS episodes ORDER BY e.valid_at DESC LIMIT $limit"
    )

    scoped = graph.driver_for(account_id)
    try:
        records, _, _ = await scoped.execute_query(cypher, **params)
    except Exception as exc:  # noqa: BLE001 —— 驱动异常统一转记忆侧语义
        raise MemoryUnavailableError(
            "读取应急预注入的派生事实失败",
            operation="read_emergency_facts",
            cause=type(exc).__name__,
        ) from exc

    facts: list[DerivedFact] = []
    used_chars = 0
    truncated = 0
    for record in records:
        fact_text = record.get("fact")
        if fact_text is None:
            raise MemoryDataError(
                "派生事实缺 fact 文本，无法注入",
                operation="read_emergency_facts",
                detail=f"uuid={record.get('uuid')!r}",
            )
        text = str(fact_text)

        # 字符预算：逐条累加，放不下就停止（并记下被截断的条数，供调用方如实告知）。
        if used_chars + len(text) > char_budget and facts:
            truncated = len(records) - len(facts)
            break
        used_chars += len(text)

        facts.append(
            DerivedFact(
                fact=text,
                valid_at=_optional_datetime(record.get("valid_at")),
                source_episodes=_as_str_list(record.get("episodes")),
            )
        )

    return EmergencyMemory(facts=facts, truncated_by_chars=truncated)


def _optional_datetime(raw: object) -> datetime | None:
    """解析可空时间：缺失返回 None（`valid_at` 允许为空）。"""
    if raw is None:
        return None
    return parse_db_datetime(raw, operation="read_emergency_facts")


def _as_str_list(raw: object) -> list[str]:
    """把图库返回的 episode 列表归一为 `list[str]`。

    实测：FalkorDB 返回的是原生列表；但也可能是单个字符串（属性形状差异）。
    两种都接受，其它类型返回空列表——**不猜**（猜出来的来源清单会让删除判据失准）。
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    return []


__all__ = [
    "EMERGENCY_MEMORY_CHARS",
    "EMERGENCY_MEMORY_LIMIT",
    "DerivedFact",
    "EmergencyMemory",
    "read_emergency_facts",
]
