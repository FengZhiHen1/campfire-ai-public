"""集成测试：记忆图库的真实连通性与「幂等依据是 uuid」的落地形状。

对应 ``docs/技术设计/technical-details/通用记忆.md`` 第 3、9 节，以及
TODO ``TECH-13`` / ``TECH-18`` 的实测项。这些事实**只能在真实 FalkorDB 上验证**，
因此带 ``integration`` marker。显式跑法：

    docker compose up -d falkordb
    uv run pytest -m integration

**注意（2026-09-29 评审更正）**：此前此处写「默认不在 ``uv run pytest`` 中运行
（见根 pyproject.toml 的 addopts）」——**该说法错误**。``addopts`` 是
``-q --import-mode=importlib``，**没有** marker 过滤，因此默认收集会包含本文件；
``uv run pytest`` 靠下面的「容器不可用则跳过」保持绿色。要真正排除请显式
``-m "not integration"``。这意味着「CI 绿」对本文件的置信度低于它看起来的样子。

锁住的三条（都是「照直觉写就会错」的坑）：

1. **驱动能连上真实容器**，且空的 ``EntityEdge.get_by_group_ids`` **抛异常**
   （``GroupsEdgesNotFoundError``）而不是返回空列表——读路径必须把
   「空分区」与「图库不可用」分开，否则新账号会被误报成故障。
2. **同 uuid 的 ``MERGE ... SET n = {...}`` 整节点覆盖**：重跑后节点数仍为 1，
   ``content`` 被新值覆盖。这否证了「靠 name 去重」的写法，也说明
   ``add_episode(uuid=...)`` 不能直接用于**首次**写入。
3. **episode 的 ``source`` 必须是合法 ``EpisodeType``**：非法值不在写入期报错，
   而在读取期让 ``retrieve_episodes`` 抛 ``NotImplementedError``（异常类型与语义无关）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from graphiti_core.edges import EntityEdge
from graphiti_core.errors import GroupsEdgesNotFoundError
from graphiti_core.nodes import EpisodicNode

from campfire.core.config import get_settings
from campfire.modules.memory.graph import build_memory_graph

pytestmark = pytest.mark.integration

#: 本文件专用的分区前缀，测试结束按它清理，不影响其他数据。
GROUP = "it_memory_probe"

#: 「容器没起」这一类异常。**只把这些**成跳过（CORE-07：边界显式）：
#: 其它异常（查询语法错、装配坏、协议变更）必须让用例**失败**。
#:
#: **为什么用 conftest 里那份而不是就地写内建类型**（2026-09-29 实测修正）：
#: FalkorDB 连不上时抛的是 **`redis.exceptions.ConnectionError`**，它继承
#: `RedisError` → `Exception`，**不是**内建 `ConnectionError`/`ConnectionRefusedError`/
#: `OSError` 的任何一个（实测逐个 `isinstance` 全为 False）。此前该元组只含内建类型，
#: 因此 `except` **匹配不到**——容器不可用时该文件 4 个用例**全部 FAILED**，
#: 而 docstring 却宣称「容器不可用则跳过」。共用一份实现避免再次踩同一个坑。
from .conftest import FALKOR_UNAVAILABLE_ERRORS as _UNAVAILABLE_ERRORS


async def _graph():  # noqa: ANN202 —— 返回 MemoryGraph，此处避免 import 循环
    """构造记忆图库；**仅当容器不可用**时跳过，其余异常照常抛出。

    **构造必须在 try 内**（2026-09-29 实测修正）：`build_memory_graph` 内部的
    `FalkorDB(...)` **构造函数本身发网络 I/O**——它内部会探测集群模式，指向死端口时
    构造期即抛 `redis.exceptions.ConnectionError`。此前把构造写在 try 之外，
    容器不可用时整个文件 4 个用例全部 FAILED（而非按 docstring 宣称的 skip）。
    """
    from campfire.modules.memory.errors import MemoryConfigurationError

    settings = get_settings()
    if settings.tokenhub_api_key is None:
        pytest.skip("未配置 TOKENHUB_API_KEY——装配需要它（不实际调用模型）")

    try:
        graph = build_memory_graph(settings)
        # 一次真实往返：连不上就跳过，而不是让整套用例以误导性的方式失败。
        await graph.driver.execute_query("RETURN 1 AS ok")
    except _UNAVAILABLE_ERRORS as exc:
        # 只把「连不上」当环境问题；其余异常直接冒泡成失败。
        pytest.skip(f"FalkorDB 不可用（{type(exc).__name__}）——先 docker compose up -d falkordb")
    except MemoryConfigurationError:
        # 配置缺失属环境问题（且已在上面按凭据判过一次，这里是兜底）。
        pytest.skip("记忆装配缺少配置——检查 .env 的 TOKENHUB_* 与 FALKORDB_*")
    except Exception:
        # 非连接类异常说明装配或查询真的坏了，必须先关资源再让用例失败。
        raise
    return graph


async def _cleanup(graph) -> None:  # noqa: ANN001
    await graph.driver.execute_query(
        "MATCH (n:Episodic) WHERE n.group_id STARTS WITH $prefix DETACH DELETE n",
        prefix=GROUP,
    )


@pytest.mark.asyncio
async def test_driver_connects_and_empty_group_raises_not_returns_empty() -> None:
    """驱动能连真实容器；空分区查询**抛异常**而非返回空列表。

    这是读路径必须处理的分支：``GroupsEdgesNotFoundError`` 表示「没有边」，
    不能当成「图库不可用」。新账号第一次应急咨询就是这条路径。
    """
    graph = await _graph()
    try:
        await _cleanup(graph)
        with pytest.raises(GroupsEdgesNotFoundError):
            await EntityEdge.get_by_group_ids(graph.driver, [f"{GROUP}_empty"])
    finally:
        await _cleanup(graph)
        await graph.aclose()


@pytest.mark.asyncio
async def test_same_uuid_merge_overwrites_and_keeps_single_node() -> None:
    """同 uuid 写入两次只留一个节点，且 ``content`` 被新值覆盖。

    证明两件事：① 图库侧的「幂等」是**覆盖**语义（没有「已存在则跳过」）；
    ② 靠 `name` 去重不成立——身份是 uuid。因此我方必须自建"已写入"标记
    （写入路径第 5 节），而不是依赖图库的 MERGE 语义。
    """
    graph = await _graph()
    fixed = "it000000-0000-4000-8000-000000000001"
    try:
        await _cleanup(graph)
        now = datetime.now(timezone.utc)
        write = """
            MERGE (n:Episodic {uuid: $uuid})
            SET n = {uuid: $uuid, name: $name, group_id: $g, content: $content,
                     source: 'text', source_description: 'integration',
                     created_at: $t, valid_at: $t, entity_edges: []}
        """
        for content in ("第一次", "第二次"):
            await graph.driver.execute_query(write, uuid=fixed, name="it-probe", g=GROUP, content=content, t=now)

        count = await graph.driver.execute_query("MATCH (n:Episodic {uuid: $uuid}) RETURN count(n) AS c", uuid=fixed)
        assert count[0][0]["c"] == 1, "同一 uuid 应只留一个节点"

        node = await EpisodicNode.get_by_uuid(graph.driver, fixed)
        assert node.content == "第二次", "MERGE ... SET 是整节点覆盖，不是「已存在则跳过」"
    finally:
        await _cleanup(graph)
        await graph.aclose()


@pytest.mark.asyncio
async def test_invalid_source_breaks_the_read_path_not_the_write_path() -> None:
    """非法 ``source`` 写入不报错，读取时才炸（异常类型与语义无关）。

    这正是读路径必须把裸 ``NotImplementedError`` 转成领域错误的原因
    （见 ``errors.MemoryDataError``）：否则调用方拿到一个语义完全无关的异常，
    既无法降级，也无法判断是不是自己的问题。
    """
    graph = await _graph()
    bad = "it000000-0000-4000-8000-000000000002"
    try:
        await _cleanup(graph)
        now = datetime.now(timezone.utc)
        # 写入期：不报错。
        await graph.driver.execute_query(
            """
            MERGE (n:Episodic {uuid: $uuid})
            SET n = {uuid: $uuid, name: 'bad-source', group_id: $g, content: '脏数据',
                     source: 'not-a-valid-source', source_description: 'integration',
                     created_at: $t, valid_at: $t, entity_edges: []}
            """,
            uuid=bad,
            g=GROUP,
            t=now,
        )

        # 读取期：抛 NotImplementedError，且与数据语义无关。
        with pytest.raises(NotImplementedError):
            await EpisodicNode.get_by_group_ids(graph.driver, [GROUP], limit=10)
    finally:
        await _cleanup(graph)
        await graph.aclose()


@pytest.mark.asyncio
async def test_retrieve_episodes_is_chronological_but_get_by_group_ids_is_by_uuid() -> None:
    """两个读入口的**顺序语义不同**，落地时间线回看时不能混用。

    - ``retrieve_episodes``：SQL `ORDER BY valid_at DESC` 后 `reversed()` →
      **按 valid_at 升序**（时间线正序）。
    - ``EpisodicNode.get_by_group_ids``：SQL `ORDER BY uuid DESC` → **按 uuid 降序**，
      与时间无关。

    测试数据**故意让 uuid 顺序与时间顺序相反**（uuid 递增而时间递减），
    否则两条断言会同时成立、这条用例就永远不会失败。
    """
    graph = await _graph()
    now = datetime.now(timezone.utc)
    try:
        await _cleanup(graph)
        # 让「uuid 降序」与「valid_at 升序」给出**相反**的顺序：
        # index 越大 uuid 越大（降序时排前），同时时间越晚（升序时排后）。
        for index in range(3):
            await graph.driver.execute_query(
                """
                MERGE (n:Episodic {uuid: $uuid})
                SET n = {uuid: $uuid, name: $name, group_id: $g, content: $content,
                         source: 'text', source_description: 'integration',
                         created_at: $t, valid_at: $t, entity_edges: []}
                """,
                uuid=f"it000000-0000-4000-8000-10000000000{index}",
                name=f"ep-{index}",
                g=GROUP,
                content=f"第 {index} 条",
                # index 越大 → 时间越晚（越近）；uuid 也越大。
                t=now - timedelta(days=2 - index),
            )

        # retrieve_episodes：按 valid_at 升序（最早的在前）→ ep-0, ep-1, ep-2。
        from graphiti_core.utils.maintenance.graph_data_operations import retrieve_episodes

        episodes = await retrieve_episodes(
            graph.driver, reference_time=now + timedelta(days=1), last_n=10, group_ids=[GROUP]
        )
        valid_ats = [ep.valid_at for ep in episodes]
        assert valid_ats == sorted(valid_ats), "retrieve_episodes 应按 valid_at 升序返回"
        assert [ep.name for ep in episodes] == ["ep-0", "ep-1", "ep-2"]

        # get_by_group_ids：按 uuid **降序**（与时间无关）→ ep-2, ep-1, ep-0。
        # 与上面**相反**，这才证明两者语义不同；若相同，本断言会失败。
        by_uuid = await EpisodicNode.get_by_group_ids(graph.driver, [GROUP], limit=10)
        assert [ep.name for ep in by_uuid] == ["ep-2", "ep-1", "ep-0"], (
            "get_by_group_ids 的排序是 uuid 降序（与 valid_at 无关）——"
            "若此断言失败说明上游改了排序契约，时间线回看不能依赖它"
        )
    finally:
        await _cleanup(graph)
        await graph.aclose()
