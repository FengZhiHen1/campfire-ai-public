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

## 已知边界：`episodes` 为空/缺失的边不受删除过滤影响（实测确认，2026-09-29）

判据写成 `NOT any(ep IN $deleted WHERE ep IN e.episodes)`。Cypher 的 `any()` 对空列表
返回 `false`，取反为 `true`——因此**一条没有 `episodes` 属性（或该属性为空）的边会被
保留**，删除过滤对它无效。实测确认这一语义。

**为什么当前接受它**：`episodes` 为空意味着这条边**不引用任何 episode**，即它无法被
归因到某条具体记忆，也就不是「某条被删记忆的派生事实」——删除的目标（某条记忆）
与它无关联。Graphiti 在 resolve 路径上总会写入 `episodes`，空值属异常数据。
**残余风险**：若上游将来写出无 `episodes` 的边，而它事实上源自某条被删记忆，
删除对它不生效。**该风险未实测**（需要构造无 episodes 边的真实抽取场景）。
处置方向（若真出现）：在注入侧对 `episodes` 为空的边**整体排除**——那会让
「不可归因的边」不再注入，代价是可能丢掉合法边；届时应按实测数据决定。
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

#: 应急预注入的派生事实**条数**默认上限（通用记忆第 10 节参数表初值）。
#: 防记忆量线性增长击穿注入预算；实测后按真实数据调整。
EMERGENCY_MEMORY_LIMIT = 20

#: **调用方传入的 `limit` 的上界**（CORE-11：不信任调用方给的上限）。
#: 默认上限只是个默认值——若调用方给 10**9，默认值形同不存在。实测此前
#: `read_emergency_facts(limit=10**9)` 被原样接受。与 `store.TIMELINE_MAX_LIMIT`
#: 的处理对称。100 条远超一期单账号记忆量，越过它说明调用方算错了。
EMERGENCY_MEMORY_LIMIT_MAX = 100

#: 应急预注入的**字符**总量上限（第 5 节：条数上限不能代替字符上限）。
#: `fact` 文本长度无界，20 条的字符量可以远超 RAG 应急注入 top-3 的量级。
#: 6000 字符约为中文 3000 字，与档案七组同处一个注入预算管道内（第 5 节）。
#: **这是硬上界**：单条超预算时会被截断（见 `read_emergency_facts` 的实现说明）。
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
    #: **含被截断的那一条本身**——即「这一条只保留了一部分」也算进此计数，
    #: 因为它确实没有完整注入。
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
    # 条数**必须收敛**：调用方（或将来的配置）可能给一个很大的值。此前这里只做
    # `max(1, limit)`，实测 `limit=10**9` 被原样接受——即「条数上界」不成立。
    # 与 `store.read_timeline` 的 `TIMELINE_MAX_LIMIT` 收敛对称。
    effective_limit = max(1, min(limit, EMERGENCY_MEMORY_LIMIT_MAX))
    params: dict[str, object] = {"group_id": account_id, "limit": effective_limit}

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
    for index, record in enumerate(records):
        fact_text = record.get("fact")
        if fact_text is None:
            raise MemoryDataError(
                "派生事实缺 fact 文本，无法注入",
                operation="read_emergency_facts",
                detail=f"uuid={record.get('uuid')!r}",
            )
        text = str(fact_text)

        remaining = char_budget - used_chars
        if len(text) > remaining:
            # **字符预算是硬上界**（第 5 节）。此前写成
            # `if used_chars + len(text) > char_budget and facts:`——那个 `and facts`
            # 让**第一条**无条件放行，实测预算 6000 时注入了 11000 字符且
            # `truncated_by_chars=0`（把「超预算」误报成「没截断」）。
            if not facts and remaining > 0:
                # **首条**就超预算：截断它以守住上界。
                # 为什么只对首条这么做：整条丢弃会让「有记忆」的账号在预注入里完全空白，
                # 而截断至少让模型看到这条事实的开头。对**后续**条目则不截断——把一条
                # 事实截成几个字符毫无信息量，那种碎片不如不注入（见下面的分支）。
                facts.append(
                    DerivedFact(
                        fact=text[:remaining],
                        valid_at=_optional_datetime(record.get("valid_at")),
                        source_episodes=_as_str_list(record.get("episodes")),
                    )
                )
                used_chars += remaining
            # 从**本条**起都没能完整注入：计数含被截断的那条本身。
            # 用下标算而不是 `len(records) - len(facts)`——后者在「截断后仍 append」
            # 时会算成 0，又是一次误报。
            truncated = len(records) - index
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
    """把图库返回的 `episodes` 归一为 `list[str]`，用于**填充返回值的来源指针**。

    **这个函数不参与删除过滤**：过滤在 Cypher 侧完成
    （`NOT any(ep IN $deleted WHERE ep IN e.episodes)`），用的是图库自己的列表。
    本函数只是把同一份数据装进 `DerivedFact.source_episodes` 供调用方排查。

    因此「非预期类型返回 `[]`」在这里**只影响诊断字段的完整度**，不会让删除判据失效
    （2026-09-29 更正：原 docstring 把「来源清单准不准」与「删除判据准不准」混为一谈）。

    实测：FalkorDB 返回原生列表；也可能是单个字符串（属性形状差异）。两种都接受。
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
