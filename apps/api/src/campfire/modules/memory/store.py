"""记忆的图库读写：episode 写入与时间线回看。

归属（见 docs/技术设计/technical-details/通用记忆.md 第 1、3、4、7 节）：本模块拥有
时间线回看这条读路径与 episode 的写入；应急预注入（派生事实）见 `derived.py`。

## 三条实测约束塑造了这里的写法（都不是推断）

1. **`group_id` 在 FalkorDB 后端是图名**（第 1 节实测）：写入与读取都必须落到
   `driver.clone(database=account_id)` 那张图。在默认图上按 `group_id` 属性过滤会
   读成空——「写进去了但读不到」的静默失败。
2. **`add_episode(uuid=X)` 要求节点已存在**，且**忽略 `episode_body`**、只用库里
   的 `content`；它还会用 `SET n = {...}` **抹掉自定义属性**（第 3 节实测）。
   因此写入必须**先预建节点**（含正文与 `source_description`），再 `add_episode`。
3. **`episode_metadata` 不落库**：来源会话标识只能走 `source_description`。

## 时间线为什么是自建查询

`retrieve_episodes(reference_time, last_n, group_ids, source, saga)` 只有「某时间点
之前最近 N 条」这一种形状——**没有时间区间、没有关键词**（第 4 节实测）。而
`read_memory` 契约承诺 `since`/`until`/`query`/`limit`，因此本模块自己写 Cypher。

时间比较的注意点（实测）：FalkorDB 把 datetime 存成 ISO 字符串，Graphiti 自己在
写入前会 `ensure_utc(...).isoformat()`。**字符串比较只在偏移一致时成立**，所以本模块
的时间参数一律先归一为 UTC ISO 字符串再比较，并统一用 `Z`/`+00:00` 同一种写法。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from graphiti_core.driver.driver import GraphDriver
from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.nodes import EpisodeType

from campfire.modules.memory.errors import MemoryDataError, MemoryUnavailableError
from campfire.modules.memory.identity import AccountId, EpisodeUuid

if TYPE_CHECKING:
    # 仅为类型标注：`graph.py` 是装配层，本模块只消费它构造出的句柄。
    # 放 TYPE_CHECKING 是为了让依赖方向保持单向（装配层 → 用例层），
    # 避免将来 graph 侧引用本模块时形成环。
    from campfire.modules.memory.graph import MemoryGraph

#: 时间线单次返回的条数上界。**有界**（CORE-11）：`read_memory` 的 `limit` 由模型给出，
#: 但模型可能给很大或省略；服务端必须有兜底上界，否则「回看全部历史」会无界拉取。
#: 200 条足以覆盖一期单账号的记忆量，且远大于工具契约的常规用量。
TIMELINE_MAX_LIMIT = 200

#: `read_memory` 未给 limit 时的默认条数。
TIMELINE_DEFAULT_LIMIT = 50

#: episode 的 source 取值：记忆片段来自对话消息，固定 `message`。
#: **必须是合法 `EpisodeType`**——非法值会在读取期让 Graphiti 抛 `NotImplementedError`
#: （第 3 节实测的陷阱）。
EPISODE_SOURCE = EpisodeType.message


@dataclass(frozen=True, slots=True)
class MemoryEpisode:
    """时间线回看返回的一条记忆片段（契约见 read_memory 第 3 节）。

    字段与 `read_memory` 契约一一对应：时间（发生时间）、内容原文、来源会话标识、
    写入状态。
    """

    episode_uuid: str
    content: str
    #: 发生时间（`valid_at`），不是入库时间——契约明确要求「非提交时间」。
    occurred_at: datetime
    #: 来源会话标识。承载在 `source_description` 上（`episode_metadata` 不落库，实测）。
    source: str
    #: 写入状态。账本与图库都只含已写入的 episode，因此恒为 `done`；保留字段是为让
    #: 契约显式承载「非 done 不得出现」这条不变量（read_memory 第 3 节）。
    write_state: str = "done"


def _utc_iso(value: datetime) -> str:
    """把时间归一为 UTC ISO 字符串，与 Graphiti 写入时的写法一致。

    FalkorDB 以字符串存时间并按字典序比较（实测），因此**偏移必须一致**：
    `2026-01-01T00:00:00+08:00` 与 `2026-01-01T00:00:00+00:00` 的字典序不反映真实
    先后。统一转 UTC 是与 Graphiti 的 `ensure_utc(...).isoformat()` 对齐。
    """
    if value.tzinfo is None:
        # 朴素时间按 UTC 解释：记忆侧所有时间都应是带时区的；这里不静默改成本地时区
        # （那会引入宿主机依赖），而是明确按 UTC 解释并在下方比较中保持一致。
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def account_driver(driver: FalkorDriver, account_id: AccountId) -> GraphDriver:
    """返回指向**该账号那张图**的驱动（第 1 节实测的分区语义）。

    同库名时 `clone` 返回自身（不新建实例），因此重复调用是廉价的；
    但调用方**不应在每个请求里对多个账号反复 clone**（每次 clone 会新建驱动并调度
    一个建索引的后台任务，第 1 节实测）。

    返回类型是基类 `GraphDriver`（上游 `clone` 的声明返回值）：调用方只依赖
    `execute_query` 这一条接口，不必绑定 FalkorDB 的具体类型——若将来换图库后端，
    本函数的调用点不变。

    Note:
        这里不做缓存：缓存属于装配层的职责（`graph.py` 的 `MemoryGraph`），
        本函数只表达「哪张图」这一个事实。
    """
    return driver.clone(database=account_id)


async def read_timeline(
    graph: MemoryGraph,
    account_id: AccountId,
    *,
    deleted_keys: list[str],
    since: datetime | None = None,
    until: datetime | None = None,
    query: str | None = None,
    limit: int = TIMELINE_DEFAULT_LIMIT,
) -> list[MemoryEpisode]:
    """时间线回看：按 `valid_at` 倒序取 episode 原文，排除已删除的。

    自建 Cypher 而非 `retrieve_episodes`：后者没有时间区间与关键词参数（第 4 节实测）。
    删除过滤**下推到查询**（`NOT e.uuid IN $deleted`）：读回来再过滤会让 `limit`
    把已删除的算进配额，语义不等价（见 `ledger.py` 说明）。

    Args:
        graph: 记忆图库句柄（本函数自行切到账号那张图）。
        account_id: 分区键，由登录态决定。
        deleted_keys: 该账号已删除的 episode key（`ledger.deleted_episode_keys`）。
        since: 可选起始时间（含）。
        until: 可选结束时间（含）。
        query: 可选关键词，对 `content` 做**子串**匹配（大小写不敏感）。
        limit: 返回条数上限；超过 ``TIMELINE_MAX_LIMIT`` 时收敛到该上界。

    Returns:
        按 `valid_at` 倒序（最近的在前）的记忆片段。

    Raises:
        MemoryUnavailableError: 图库查询失败。
        MemoryDataError: 图库里的数据不合法（必填字段缺失或时间无法解析）。
        ValueError: 时间区间非法（`since > until`）。
    """
    if since is not None and until is not None and since > until:
        raise ValueError("时间区间非法：since 晚于 until")

    # 上界收敛：不信任调用方给的上限（CORE-11）。
    effective_limit = max(1, min(limit, TIMELINE_MAX_LIMIT))

    conditions = ["e.group_id = $group_id"]
    params: dict[str, object] = {"group_id": account_id, "limit": effective_limit}

    if since is not None:
        conditions.append("e.valid_at >= $since")
        params["since"] = _utc_iso(since)
    if until is not None:
        conditions.append("e.valid_at <= $until")
        params["until"] = _utc_iso(until)
    if deleted_keys:
        conditions.append("NOT e.uuid IN $deleted")
        params["deleted"] = deleted_keys
    if query:
        # FalkorDB 的 toLower + CONTAINS 做子串匹配；一期不建全文索引。
        conditions.append("toLower(e.content) CONTAINS toLower($query)")
        params["query"] = query

    cypher = (
        "MATCH (e:Episodic) WHERE "
        + " AND ".join(conditions)
        + " RETURN e.uuid AS uuid, e.content AS content, e.valid_at AS valid_at,"
        + " e.source_description AS source_description"
        + " ORDER BY e.valid_at DESC LIMIT $limit"
    )

    scoped = account_driver(graph.driver, account_id)
    try:
        records, _, _ = await scoped.execute_query(cypher, **params)
    except Exception as exc:  # noqa: BLE001 —— 驱动异常统一转成记忆侧语义
        raise MemoryUnavailableError(
            "读取记忆时间线失败",
            operation="read_timeline",
            cause=type(exc).__name__,
        ) from exc

    return [_to_episode(record) for record in records]


def _to_episode(record: dict[str, object]) -> MemoryEpisode:
    """把一条 Cypher 记录转成 `MemoryEpisode`。

    Raises:
        MemoryDataError: 必填字段缺失或类型不符（`content`/`valid_at`）。这类数据
            无法回看，必须显式失败而不是返回残缺片段。
    """
    raw_valid_at = record.get("valid_at")
    if raw_valid_at is None:
        raise MemoryDataError(
            "记忆片段的 valid_at 缺失，无法确定发生时间",
            operation="read_timeline",
            detail=f"uuid={record.get('uuid')!r}",
        )
    occurred_at = _parse_db_datetime(raw_valid_at)

    content = record.get("content")
    if content is None:
        raise MemoryDataError(
            "记忆片段的 content 缺失（episode 原文是时间线回看的唯一载体）",
            operation="read_timeline",
            detail=f"uuid={record.get('uuid')!r}",
        )

    return MemoryEpisode(
        episode_uuid=str(record.get("uuid") or ""),
        content=str(content),
        occurred_at=occurred_at,
        # 来源会话标识承载在 source_description 上（episode_metadata 不落库，实测）。
        source=str(record.get("source_description") or ""),
    )


def _parse_db_datetime(raw: object) -> datetime:
    """解析图库返回的时间值。

    FalkorDB 存的是 ISO 字符串（实测），但也可能已是 datetime（驱动差异），
    两种都接受；无法解析时抛 `MemoryDataError` 而不是静默用当前时间——
    "时间不确定"与"时间就是现在"是完全不同的语义，后者会污染时间线。
    """
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise MemoryDataError(
                "记忆片段的时间无法解析",
                operation="read_timeline",
                detail=f"valid_at={raw!r}",
            ) from exc
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    raise MemoryDataError(
        "记忆片段的时间类型不受支持",
        operation="read_timeline",
        detail=f"type={type(raw).__name__}",
    )


async def write_episode(
    graph: MemoryGraph,
    account_id: AccountId,
    episode_uuid: EpisodeUuid,
    *,
    content: str,
    occurred_at: datetime,
    source_description: str,
) -> MemoryEpisode:
    """写入一条记忆片段（幂等：同一 uuid 重复调用只留一条 episode 节点）。

    形状与理由（见模块说明）：**先预建节点**（写正文与来源），再 `add_episode` 让它
    抽取派生事实。`add_episode(uuid=...)` 会忽略 `episode_body`，所以正文必须在预建
    时写进去。

    幂等的边界（**重要**）：本函数保证「同一 uuid 不产生第二条 episode 节点」，
    但**不保证派生事实不重复**——`add_episode` 每次都会跑一遍抽取并把边挂到图上。
    端到端的重试幂等由调用方按我方"已写入"标记决定**要不要调用本函数**
    （[写入路径](写入路径.md)第 5 节）：标记为已写入就不要再调。

    Args:
        graph: 记忆图库句柄（同时持有装配好的 `Graphiti` 与底层驱动）。
        account_id: 分区键。
        episode_uuid: 由 `pending_id` 派生的确定性 uuid。
        content: 片段原文。
        occurred_at: 发生时间（进 `valid_at`）。
        source_description: 来源会话标识（`episode_metadata` 不落库，实测）。

    Returns:
        写入后的片段（含归一化后的时间）。

    Raises:
        MemoryUnavailableError: 图库写入失败。
        MemoryDataError: 内容或来源为空。
    """
    if not content:
        raise MemoryDataError("记忆内容为空，拒绝写入", operation="write_episode", detail="content 为空")
    if not source_description:
        raise MemoryDataError(
            "来源会话标识为空，拒绝写入（没有来源的记忆无法核对）",
            operation="write_episode",
            detail="source_description 为空",
        )

    # 预建节点要落在该账号那张图：group_id 在 FalkorDB 后端就是图名（第 1 节实测）。
    scoped = account_driver(graph.driver, account_id)
    valid_at = _utc_iso(occurred_at)
    # created_at 用真实入库时间；valid_at 用发生时间（第 2 节的时间语义）。
    created_at = _utc_iso(datetime.now(timezone.utc))

    try:
        # 第一步：预建节点。`MERGE` 保证同 uuid 只一个节点；`SET e = {...}` 与
        # Graphiti 自己的写法一致（它也是整节点替换），因此重跑不会残留旧属性。
        await scoped.execute_query(
            """
            MERGE (e:Episodic {uuid: $uuid})
            SET e = {uuid: $uuid, name: $name, group_id: $group_id,
                     source: $source, source_description: $source_description,
                     content: $content, entity_edges: [],
                     created_at: $created_at, valid_at: $valid_at}
            """,
            uuid=episode_uuid,
            name=f"memory:{episode_uuid}",
            group_id=account_id,
            source=EPISODE_SOURCE.value,
            source_description=source_description,
            content=content,
            created_at=created_at,
            valid_at=valid_at,
        )

        # 第二步：让 Graphiti 抽取派生事实。它会从图库加载刚预建的节点
        # （正文来自图库，episode_body 被忽略——实测），并自行按 group_id 切到
        # 同一张图（`_resolve_request_scope`）。
        await graph.graphiti.add_episode(
            name=f"memory:{episode_uuid}",
            episode_body=content,
            source_description=source_description,
            reference_time=occurred_at,
            source=EPISODE_SOURCE,
            uuid=episode_uuid,
            group_id=account_id,
        )
    except Exception as exc:  # noqa: BLE001 —— 驱动/框架异常统一转记忆侧语义
        raise MemoryUnavailableError(
            "写入记忆片段失败",
            operation="write_episode",
            cause=type(exc).__name__,
        ) from exc

    return MemoryEpisode(
        episode_uuid=episode_uuid,
        content=content,
        occurred_at=occurred_at,
        source=source_description,
    )


__all__ = [
    "EPISODE_SOURCE",
    "TIMELINE_DEFAULT_LIMIT",
    "TIMELINE_MAX_LIMIT",
    "MemoryEpisode",
    "account_driver",
    "read_timeline",
    "write_episode",
]
