"""记忆的图库读写：episode 写入与时间线回看。

职责：本模块拥有时间线回看这条读路径与 episode 的写入；应急预注入见 `derived.py`。
边界：只做图库读写与 UTC 归一；幂等判据落在 `pending_write.state`，不在这里。
参考：通用记忆.md 第 1、3、4、7 节、`EPISODE_WRITE_STATE_PENDING`、`read_timeline`。
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from graphiti_core.nodes import EpisodeType
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.modules.memory.errors import MemoryDataError, MemoryUnavailableError
from campfire.modules.memory.identity import AccountId, EpisodeUuid
from campfire.modules.memory.ledger import deleted_episode_keys

if TYPE_CHECKING:
    # 仅为类型标注：`graph.py` 是装配层，本模块只消费它构造出的句柄。
    # 放 TYPE_CHECKING 是为了让依赖方向保持单向（装配层 → 用例层），
    # 避免将来 graph 侧引用本模块时形成环。
    from campfire.modules.memory.graph import MemoryGraph

# 归属（见 docs/技术设计/technical-details/通用记忆.md 第 1、3、4、7 节）：本模块拥有
# 时间线回看这条读路径与 episode 的写入；应急预注入（派生事实）见 `derived.py`。
#
# 三条实测约束塑造了这里的写法（都不是推断）
#
# 1. `group_id` 在 FalkorDB 后端是图名（第 1 节实测）：写入与读取都必须落到
#    `driver.clone(database=account_id)` 那张图。在默认图上按 `group_id` 属性过滤会
#    读成空——「写进去了但读不到」的静默失败。
# 2. `add_episode(uuid=X)` 要求节点已存在，且忽略 `episode_body`、只用库里
#    的 `content`；它还会用 `SET n = {...}` 抹掉自定义属性（第 3 节实测）。
#    因此写入必须先预建节点（含正文与 `source_description`），再 `add_episode`。
# 3. `episode_metadata` 不落库：来源会话标识只能走 `source_description`。

#: 时间线单次返回的条数上界。有界（CORE-11）：`read_memory` 的 `limit` 由模型给出，
#: 但模型可能给很大或省略；服务端必须有兜底上界，否则「回看全部历史」会无界拉取。
#: 200 条足以覆盖一期单账号的记忆量，且远大于工具契约的常规用量。
TIMELINE_MAX_LIMIT = 200

#: `read_memory` 未给 limit 时的默认条数。
TIMELINE_DEFAULT_LIMIT = 50

#: episode 的 source 取值：记忆片段来自对话消息，固定 `message`。
#: 必须是合法 `EpisodeType`——非法值会在读取期让 Graphiti 抛 `NotImplementedError`
#: （第 3 节实测的陷阱）。
EPISODE_SOURCE = EpisodeType.message

#: episode 节点上的完成标记属性名与取值。
#:
#: 为什么需要它
#:
#: 「已写入」不能靠「图库里存在 episode 节点」这一约定，也不能靠失败时的补偿删除。
#: 实测证明该约定不成立，有两种残留：
#:
#: 1. 进程被硬杀（SIGKILL / 部署重启）：补偿代码根本不执行，预建节点永久残留；
#:    实测用 `CancelledError` 复现（它继承 `BaseException`，原 `except Exception`
#:    接不住）→ 残留节点 1 个，`read_timeline` 仍返回它且 `write_state='done'`。
#: 2. 抽取中途失败：`add_episode` 可能已经写入实体与边，它们不挂在 episode
#:    节点上，`DETACH DELETE e` 删不掉——实测残留实体 2 个/边 1 条，且
#:    `read_emergency_facts` 会把那条从未成功写入的事实注入。
#:
#: 因此正确性依据是：预建节点不带标记，`add_episode` 成功后写标记；两条读路径
#: 只认带标记的节点/边。这样即使进程被硬杀、即使派生物已落库，未完成的写入
#: 永远不会被读到——补偿删除只是尽力清理，不是正确性依据（CORE-05：不变量
#: 落在数据与查询上，而不是落在「异常处理一定跑得到」这个假设上）。
#:
#: fail-closed 方向：无标记的节点（含改造前写入的老数据）一律不返回。
#: 实测确认该过滤生效。代价是历史数据需回填标记——一期尚无生产数据，登记于
#: TODO `TECH-22`。
#:
#: 与「实测约束四」的关系（勿误读为矛盾）
#:
#: 通用记忆第 3 节的实测约束四写着「我方『已写入』标记绝不能放在图节点上」——
#: 那是针对幂等标记说的：`add_episode` 的整节点替换（`SET n = {...}`）会把先写的
#: 自定义属性抹掉，因此幂等判据必须落在 `pending_write.state`（PostgreSQL 侧）。
#: 本标记不承担幂等职责（幂等仍由 `pending_write.state` 负责），只承担
#: 「读路径可见性」判据，且写在 `add_episode` 之后，故与被抹掉无关。
#: 而「会被抹掉」这一实测事实正是本标记降级缺陷的根因（重试已成功的 episode 时，
#: 预建的整节点替换会把 `done` 覆盖成 `pending`）——已在 `write_episode` 里以
#: `already_done` 处置。两个结论并不矛盾，是两个不同的标记、两种不同的职责。
EPISODE_WRITE_STATE_PENDING = "pending"

#: 见 `EPISODE_WRITE_STATE_PENDING` 的说明。只有带本标记的 episode 才被读路径返回。
EPISODE_WRITE_STATE_DONE = "done"


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
    #: 写入状态。值恒为 `done`——但不是硬编码的约定，而是查询判据的产物：
    #: 读路径按 `e.write_state = 'done'` 过滤（见 `_read_timeline`），该标记由
    #: `write_episode` 在 `add_episode` 成功后写入（见模块级
    #: `EPISODE_WRITE_STATE_*` 的说明）。失败时的补偿删除只是尽力清理，
    #: 不是本字段成立的依据——无标记的半写节点（硬杀残留、抽取中途失败）
    #: 从一开始就不满足过滤条件，读不到（实测复现，见
    #: `test_hard_kill_leftover_is_unreadable_by_both_paths`）。
    #:
    #: 前提条件（改动写入形状前必读）：若将来写入改成多阶段（例如「先落节点、
    #: 异步补齐派生事实」），`done` 的写入时机必须随之重新定义，本字段的语义与
    #: 契约依据（`read_memory` 第 3 节「非 `done` 不出现在返回里」）才保持一致。
    write_state: str = "done"


def _utc_iso(value: datetime) -> str:
    """把时间归一为 UTC ISO 字符串，与 Graphiti 写入时的写法一致。

    时间比较的注意点（实测）：FalkorDB 把 datetime 存成 ISO 字符串，Graphiti 自己在
    写入前会 `ensure_utc(...).isoformat()`。字符串比较只在偏移一致时成立，所以本模块
    的时间参数一律先归一为 UTC ISO 字符串再比较，并统一用 `Z`/`+00:00` 同一种写法。

    FalkorDB 以字符串存时间并按字典序比较（实测），因此偏移必须一致：
    `2026-01-01T00:00:00+08:00` 与 `2026-01-01T00:00:00+00:00` 的字典序不反映真实
    先后。统一转 UTC 是与 Graphiti 的 `ensure_utc(...).isoformat()` 对齐。
    """
    if value.tzinfo is None:
        # 朴素时间按 UTC 解释：记忆侧所有时间都应是带时区的；这里不静默改成本地时区
        # （那会引入宿主机依赖），而是明确按 UTC 解释并在下方比较中保持一致。
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


async def read_timeline(
    session: AsyncSession,
    graph: MemoryGraph,
    account_id: AccountId,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    query: str | None = None,
    limit: int = TIMELINE_DEFAULT_LIMIT,
) -> list[MemoryEpisode]:
    """时间线回看：按 `valid_at` 倒序取 episode 原文，排除已删除的。

    自建 Cypher 而非 `retrieve_episodes`：后者没有时间区间与关键词参数（第 4 节实测）。

    时间线为什么是自建查询

    `retrieve_episodes(reference_time, last_n, group_ids, source, saga)` 只有「某时间点
    之前最近 N 条」这一种形状——没有时间区间、没有关键词（第 4 节实测）。而
    `read_memory` 契约承诺 `since`/`until`/`query`/`limit`，因此本模块自己写 Cypher。
    删除过滤下推到查询（`NOT e.uuid IN $deleted`）：读回来再过滤会让 `limit`
    把已删除的算进配额，语义不等价（见 `ledger.py` 说明）。

    删除过滤的取数在本函数内完成（2026-09-30 裁决，见通用记忆第 7 节）：调用方
    不传「已删清单」，因此不存在「漏传导致用户已删除的记忆被返回」的实现路径。

    Args:
        session: 关系库会话（用于取该账号的删除账本）。
        graph: 记忆图库句柄（本函数自行切到账号那张图）。
        account_id: 分区键，由登录态决定。
        since: 可选起始时间（含）。
        until: 可选结束时间（含）。
        query: 可选关键词，对 `content` 做子串匹配（大小写不敏感）。
        limit: 返回条数上限；超过 `TIMELINE_MAX_LIMIT` 时收敛到该上界。

    Returns:
        按 `valid_at` 倒序（最近的在前）的记忆片段。

    Raises:
        MemoryUnavailableError: 图库查询失败。
        MemoryDataError: 图库里的数据不合法（必填字段缺失或时间无法解析），
            或该账号的删除账本超过上界而无法完整排除已删内容。
        ValueError: 时间区间非法（`since > until`）。
    """
    if since is not None and until is not None and since > until:
        raise ValueError("时间区间非法：since 晚于 until")

    # 取账本：必须在图库查询之前，且在此函数内完成（本函数是唯一公开入口）。
    deleted_keys = await deleted_episode_keys(session, account_id)

    return await _read_timeline(
        graph, account_id, deleted_keys=deleted_keys, since=since, until=until, query=query, limit=limit
    )


async def _read_timeline(
    graph: MemoryGraph,
    account_id: AccountId,
    *,
    deleted_keys: list[str],
    since: datetime | None = None,
    until: datetime | None = None,
    query: str | None = None,
    limit: int = TIMELINE_DEFAULT_LIMIT,
) -> list[MemoryEpisode]:
    """时间线查询的内部实现：已经拿到 `deleted_keys`，只管查图库。

    私有（前缀下划线）：不导出、不进入 `__all__`。保留它而不是把代码合并进
    `read_timeline`，是为了让「图库查询」这一层能脱离关系库被单独测试（现有集成
    测试大多只需构造图库数据、不关心账本）。公开入口只有 `read_timeline`，
    因此「忘记过滤」在对外 API 上不可表达。

    Raises:
        MemoryUnavailableError: 图库查询失败。
        MemoryDataError: 图库里的数据不合法（必填字段缺失或时间无法解析）。
    """
    # 上界收敛：不信任调用方给的上限（CORE-11）。
    effective_limit = max(1, min(limit, TIMELINE_MAX_LIMIT))

    conditions = [
        "e.group_id = $group_id",
        # 完成标记过滤（C-1 修复的落点）：只有 `add_episode` 成功后才写该标记，
        # 因此未完成的写入（硬杀残留、抽取中途失败的半写节点）永远不会被读到。
        # 这是「没写进去不得被当作写进去了」的实际判据；补偿删除不是依据。
        "e.write_state = $write_state",
    ]
    params: dict[str, object] = {
        "group_id": account_id,
        "limit": effective_limit,
        "write_state": EPISODE_WRITE_STATE_DONE,
    }

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
        # FalkorDB 的 toLower + CONTAINS 做子串匹配；
        # 一期不建全文索引。
        conditions.append("toLower(e.content) CONTAINS toLower($query)")
        params["query"] = query

    cypher = (
        "MATCH (e:Episodic) WHERE "
        + " AND ".join(conditions)
        + " RETURN e.uuid AS uuid, e.content AS content, e.valid_at AS valid_at,"
        + " e.source_description AS source_description"
        + " ORDER BY e.valid_at DESC LIMIT $limit"
    )

    scoped = graph.driver_for(account_id)
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
    occurred_at = parse_db_datetime(raw_valid_at, operation="read_timeline")

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
        # 来源会话标识承载在 source_description 上
        # （episode_metadata 不落库，实测）。
        source=str(record.get("source_description") or ""),
    )


def parse_db_datetime(raw: object, *, operation: str) -> datetime:
    """解析图库返回的时间值。

    FalkorDB 存的是 ISO 字符串（实测），但也可能已是 datetime（驱动差异），
    两种都接受；无法解析时抛 `MemoryDataError` 而不是静默用当前时间——
    「时间不确定」与「时间就是现在」是完全不同的语义，后者会污染时间线。

    Args:
        raw: 图库返回值。
        operation: 调用方操作名，用于诊断字段（两条读路径各自标识自己）。

    Raises:
        MemoryDataError: 类型不受支持或字符串无法解析。
    """
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise MemoryDataError(
                "记忆的时间无法解析",
                operation=operation,
                detail=f"value={raw!r}",
            ) from exc
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    raise MemoryDataError(
        "记忆的时间类型不受支持",
        operation=operation,
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

    形状与理由（见模块说明）：先预建节点（写正文与来源），再 `add_episode` 让它
    抽取派生事实。`add_episode(uuid=...)` 会忽略 `episode_body`，所以正文必须在预建
    时写进去。

    幂等的实测边界（2026-09-29 实测修正）

    实测（假 LLM 返回固定的实体与边，即两轮抽取结果完全一致）：

    项 → 第一次 → 第二次 → 是否重复
    - episode 节点 → 1 → 1 → 否（`MERGE` 按 uuid）
    - 实体节点 → 2 → 2 → 否
    - 派生事实边 → 1 → 1 → 否
    - `edge.episodes` → `['<uuid>']` → `['<uuid>']` → 否（未被 append 两次）

    即在抽取输出一致的前提下，重跑不会产生重复 episode、重复实体或重复边，
    `episodes` 列表也不会被重复追加。原因是边的消解按事实内容命中既有边。

    残余风险（未实测的部分，必须如实说明）：真实模型的抽取输出不确定。重跑时
    若把同一件事抽成措辞不同的事实，它会成为一条新边（而不是重复边）——两种
    结果都偏离「一次写入一条事实」，且无法用本层的任何断言拦住，因为它依赖模型
    行为。因此我方"已写入"标记（写入路径（写入路径.md）第 5 节）仍然必要：
    它不是用来防「重复 uuid 节点」，而是用来避免重复调用抽取（省一次模型成本、
    并消除上述不确定性）。本函数只负责「不产生第二条 episode 节点」这一确定的部分。

    Args:
        graph: 记忆图库句柄（同时持有装配好的 `Graphiti` 与底层驱动）。
        account_id: 分区键。
        episode_uuid: 由 `pending_id` 派生的确定性 uuid。
        content: 片段原文。
        occurred_at: 发生时间（进 `valid_at`）。
        source_description: 来源会话标识（`episode_metadata` 不落库，实测）。

    Raises:
        MemoryDataError: 内容或来源为空。
        MemoryUnavailableError: 图库写入失败。
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
    # 用 driver_for 而非裸 clone：后者每条查询泄漏一个驱动与一个后台任务（实测）。
    scoped = graph.driver_for(account_id)
    valid_at = _utc_iso(occurred_at)
    # created_at 用真实入库时间；valid_at 用发生时间
    # （第 2 节的时间语义）。
    created_at = _utc_iso(datetime.now(timezone.utc))

    # 预建节点是否本来不存在：失败时据此决定要不要回滚（见下方补偿说明）。
    # 在 MERGE 之前查，避免把「上一次成功写入的节点」误删。
    try:
        existing, _, _ = await scoped.execute_query(
            "MATCH (e:Episodic {uuid: $uuid}) RETURN e.write_state AS ws LIMIT 1", uuid=episode_uuid
        )
        node_predates_this_call = bool(existing)
        # 该节点已经写入成功（已带完成标记）。
        # 重试一条已成功的 episode 时，下面的整节点替换会把
        # `write_state` 从 `done` 降级成 `pending`；若这次 `add_episode` 又失败，
        # 一条原本可读的记忆会变成不可读（方向是 fail-closed，但确实是数据可见性缺陷）。
        # 处置：已成功过就不降级——保留 `done`。理由：
        # ① 幂等语义要求「重跑不改变已生效的结果」（第 5 节）；
        # ② 本函数成功时会把标记写成 `done`，失败时保持 `done` 也不会伪造成功——
        #    因为上一次确实成功过，图库内容就是那次的结果；
        # ③ 内容以本次为准（`SET e = {...}` 会覆盖 `content`），但正文改写不影响
        #    「这条记忆存在且可读」这一事实。
        already_done = bool(existing) and existing[0].get("ws") == EPISODE_WRITE_STATE_DONE
    except Exception as exc:  # noqa: BLE001 —— 驱动异常统一转记忆侧语义
        raise MemoryUnavailableError(
            "写入记忆片段失败",
            operation="write_episode",
            cause=type(exc).__name__,
        ) from exc

    try:
        # 第一步：预建节点。`MERGE` 保证同 uuid 只一个节点；`SET e = {...}` 与
        # Graphiti 自己的写法一致（它也是整节点替换），因此重跑不会残留旧属性。
        # `write_state`：首次写 `pending`（显式写成未完成，第三步才改成 `done`；
        # 显式写而不是省掉属性，是为了让「半写」在数据里可查）；
        # 已成功过的记录保持 `done`（见上方 `already_done` 的说明，避免降级）。
        await scoped.execute_query(
            """
            MERGE (e:Episodic {uuid: $uuid})
            SET e = {uuid: $uuid, name: $name, group_id: $group_id,
                     source: $source, source_description: $source_description,
                     content: $content, entity_edges: [],
                     created_at: $created_at, valid_at: $valid_at,
                     write_state: $write_state}
            """,
            uuid=episode_uuid,
            name=f"memory:{episode_uuid}",
            group_id=account_id,
            source=EPISODE_SOURCE.value,
            source_description=source_description,
            content=content,
            created_at=created_at,
            valid_at=valid_at,
            write_state=(EPISODE_WRITE_STATE_DONE if already_done else EPISODE_WRITE_STATE_PENDING),
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

        # 第三步：写完成标记——这是「已写入」的唯一判据（见模块级说明）。
        # 必须在 `add_episode` 之后：它对 episode 节点做整节点替换
        # （`SET n = {...}`），实测会把先写的自定义属性抹掉。
        await scoped.execute_query(
            "MATCH (e:Episodic {uuid: $uuid}) SET e.write_state = $state",
            uuid=episode_uuid,
            state=EPISODE_WRITE_STATE_DONE,
        )
    except BaseException as exc:  # noqa: BLE001 —— 含取消/超时；驱动异常统一转记忆侧语义
        # 补偿：删掉本次新建的半写节点。
        # 为什么必须补：写入分三步，第二步失败时节点已经存在。只删本次新建的节点：
        # 若它本来就在（重试场景），保留原状——破坏既有数据比留下半写节点更糟。
        #
        # ⚠️ 补偿不是正确性依据：进程被硬杀
        # （SIGKILL）时代码根本不执行，任何补偿都跑不到；而且抽取可能已经写入
        # 实体与边，它们不挂在 episode 节点上，`DETACH DELETE` 删不掉——实测：
        # 取消后残留 episode=1，抽取中途失败后实体=2/边=1 残留，且
        # `read_emergency_facts` 会把那条从未成功写入的事实注入。
        # 正确性依据是第三步的完成标记 + 两条读路径的标记过滤；这里只做尽力清理。
        # 捕获 `BaseException` 而非 `Exception`：`CancelledError` 是 `BaseException`,
        # 只写 `except Exception` 会漏掉取消路径（实测）。
        if not node_predates_this_call:
            with suppress(Exception):
                await scoped.execute_query("MATCH (e:Episodic {uuid: $uuid}) DETACH DELETE e", uuid=episode_uuid)
        if isinstance(exc, (MemoryDataError, MemoryUnavailableError)):
            raise
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
    "EPISODE_WRITE_STATE_DONE",
    "EPISODE_WRITE_STATE_PENDING",
    "TIMELINE_DEFAULT_LIMIT",
    "TIMELINE_MAX_LIMIT",
    "MemoryEpisode",
    "parse_db_datetime",
    "read_timeline",
    "write_episode",
]
