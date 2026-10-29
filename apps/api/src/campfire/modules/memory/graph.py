"""Graphiti + FalkorDB 的装配：驱动、三个客户端与图库句柄。

归属（见 docs/技术设计/technical-details/通用记忆.md 第 8 节与
docs/技术设计/decisions/通用记忆归属为账号.md）：连接与客户端装配归 `modules/memory`；
连接配置的唯一真源是 `core/config`（第 10 节「配置唯一入口」）。
边界：照默认值构造 Graphiti 会失败或静默连错供应商——五条实测约束、超时落法与代理豁免的完整论证见 `build_memory_graph` 的模块说明。
参考：`docs/技术设计/technical-details/通用记忆.md` 第 6、8、10 节。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from weakref import WeakSet

import httpx2
from falkordb.asyncio import FalkorDB  # type: ignore[import-untyped]  # 上游无 py.typed；运行时行为已由集成测试锁定
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.driver.driver import GraphDriver
from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.graphiti import Graphiti
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_client import OpenAIClient
from openai import AsyncOpenAI

from campfire.core.config import EMBEDDING_DIM, Settings, get_settings
from campfire.modules.memory.errors import MemoryConfigurationError
from campfire.modules.memory.identity import to_account_id

logger = logging.getLogger(__name__)

#: 实体抽取与消解的模型调用上限（token）。Graphiti 的默认是 16384；
#: 我们显式传入而不是沿用默认，理由：抽取是需要结构化输出的短任务，
#: 16k 的输出预留会让请求参数随上游默认值漂移，也不利于成本核算。
#: 4096 足够容纳一次抽取的 JSON 结果（实测抽取输出为数十条实体与边）。
LLM_MAX_TOKENS = 4096

#: 按账号缓存的驱动上界（CORE-11：有界）。必须有界，否则缓存本身就是
#: 另一种泄漏：FalkorDB 的运维形态是「一个账号一张图」，账号数无上界。
#: 64 个同时在用的账号驱动足以覆盖单机一期的并发量，且每个驱动只是一个连接句柄。
MAX_CACHED_ACCOUNT_DRIVERS = 64


class TokenHubEmbedder(OpenAIEmbedder):
    """Graphiti 的 OpenAI 嵌入器，额外把 `encoding_format="float"` 送进请求体。

    为什么需要子类（2026-10-02 实测确认的产品缺陷）

    上游 `graphiti_core.embedder.openai.OpenAIEmbedder` 的 `create()` 与
    `create_batch()` 只传 `input` + `model`（`embedder/openai.py:57-65`），
    而 OpenAI Python SDK 在**请求体**层面注入默认值：
    `openai/resources/embeddings.py` 的 `if not is_given(encoding_format):
    params["encoding_format"] = "base64"`。TokenHub 只接受 `float`（RAG 策略
    「依据」列早已记载该约束），于是真实端点上必失败：

        FAIL 400001 "The request is invalid: encoding_format only supports float"

    可达性：`add_episode` 必经嵌入（`EntityNode.generate_name_embedding` /
    `EntityEdge.generate_embedding` / `llm_client/utils.generate_embedding`
    三处都走 `embedder.create`，实测 0.30.2），因此该缺陷让**记忆写入路径整体不可用**。
    同一根因在 `modules/library/embedding.py:114` 已修过一次——那里传
    `additional_kwargs={"encoding_format": "float"}`，**形状相同：把该字段放进请求体**。
    本类沿用同一形态，不发明新机制。

    为什么不是给客户端传 `default_query`（2026-10-02 实测排除，别再用它）
    `default_query` 进的是 **URL 查询串**，请求体里仍是 SDK 注入的 `base64`，
    服务端照样拒绝。实测：

        URL : https://tokenhub.tencentmaas.com/v1/embeddings?encoding_format=float
        BODY: {"input": ..., "model": ..., "encoding_format": "base64"}
        ⇒ 400001（同一错误码）

    为什么不是改上游 config：`OpenAIEmbedderConfig` 是 pydantic 模型且未开
    `extra="allow"`，实测多传 `encoding_format="float"` 会被**静默丢弃**
    （`hasattr(config, "encoding_format") == False`）——那正是「以为传了其实没传」。

    为什么不是整类重写：只覆盖两个真正发请求的方法，其余（构造、`config`、
    `client` 归属）全部沿用上游。维度仍按 `config.embedding_dim` 截断，
    因此 `EMBEDDING_DIM` 契约（实测 2560）不变。

    本类不是「第二个真源」：`create()` / `create_batch()` 的其余行为必须与上游
    逐字一致，`apps/api/tests/test_memory_graph.py` 用一条对照测试钉住这一点
    （上游若改了切片或去空格行为，那条断言会失败）。
    """

    async def create(self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]) -> list[float]:
        """与上游同形，唯一区别是显式指定 `encoding_format="float"`。"""
        result = await self.client.embeddings.create(
            input=input_data,
            model=self.config.embedding_model,
            # 必须显式指定 float：SDK 默认填 base64，而 TokenHub 只接受 float（实测 400001）。
            encoding_format="float",
        )
        return result.data[0].embedding[: self.config.embedding_dim]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        """与上游同形，唯一区别是显式指定 `encoding_format="float"`。"""
        result = await self.client.embeddings.create(
            input=input_data_list,
            model=self.config.embedding_model,
            encoding_format="float",
        )
        return [embedding.embedding[: self.config.embedding_dim] for embedding in result.data]


@dataclass(frozen=True, slots=True)
class MemoryEmbedder:
    """记忆侧嵌入器，以及本处创建、需由持有者收口的 openai 客户端。

    存在的理由是**单一真源**（2026-10-05，T19）：嵌入器的构造参数里有两处曾经出过真实缺陷
    ——`TokenHubEmbedder`（不是上游 `OpenAIEmbedder`）与它显式传的
    `encoding_format="float"`。若探针另写一份构造，那两处就有了第二真源，而
    「探针与生产走不同构造」正是这类探针最典型的失效形态（探绿而生产坏）。
    因此生产装配（:func:`build_memory_graph`）与深度就绪探针（`campfire.main.check_embedding`）
    都经 :func:`build_memory_embedder` 构造，本结构就是那条路径的返回值。

    两个字段的所有权（与 :class:`MemoryGraph` 同一纪律：谁创建谁持有）：
    `client` 由本结构创建，因此由 :meth:`aclose` 关闭；`embedder` 持有 `client` 的引用，
    不单独关闭。`http_client` 可能是调用方注入的（生产与 llm 客户端共用一条连接池，
    见 :func:`build_memory_graph`），故不由本结构负责——关闭 `client` 会级联关闭它
    （实测），那是复用同一池的既有行为。
    """

    embedder: TokenHubEmbedder
    client: AsyncOpenAI

    async def aclose(self) -> None:
        """关闭本结构创建的 openai 客户端（幂等；级联关闭它注入的 http 客户端）。"""
        await self.client.close()


def build_memory_embedder(
    settings: Settings,
    *,
    http_client: httpx2.AsyncClient | None = None,
    timeout_seconds: float | None = None,
) -> MemoryEmbedder:
    """构造记忆侧的嵌入器（**生产装配与探针的唯一构造处**）。

    为什么单独成一个函数（2026-10-05，T19）：`/readyz` 的 `model` 项只探 chat 端点，
    而记忆写入路径的嵌入缺陷（`encoding_format` 漏传 ⇒ TokenHub `400001` ⇒ 写入整体不可用）
    在它眼里完全不可见——该缺陷真实发生过，表现为「健康检查全绿而记忆写入全坏」。
    修法是一次真实嵌入探针，而**探针必须走生产同一条构造**：否则探针探的是另一份配置，
    改坏生产也不会让它变红（等于没覆盖）。因此构造搬到这里，两个调用方共用它。

    参数与既有行为逐字一致（本函数只是把 `build_memory_graph` 里原来的那段搬出来）：
    模型名取 `settings.embedding_model_name`、维度取常量 `EMBEDDING_DIM`、客户端
    `max_retries=0`（重试的唯一所有者是本模块），并沿用 :class:`TokenHubEmbedder`
    （它显式传 `encoding_format="float"`，见该类的 docstring）。

    Args:
        settings: 应用配置。
        http_client: 注入的 httpx2 客户端。省略则自建一个 `trust_env=False` 的
            ——生产传入与 llm 客户端共用的那一个（见 `build_memory_graph`），
            探针自建（它是服务端到服务端调用，不继承桌面代理豁免表；
            且探针要有自己的短超时，不能借用生产的 45 秒）。
        timeout_seconds: 单次请求超时。省略则取 `settings.model_request_timeout_seconds`
            （生产取值）；探针传自己的有界值。

    Raises:
        MemoryConfigurationError: 未配置 `TOKENHUB_API_KEY` 时——显式失败，不静默降级。

    Note:
        `http_client` 省略时自建的那个**没有**独立的收口点：它被注入给 openai 客户端，
        由 :meth:`MemoryEmbedder.aclose` 经级联关闭（实测 `AsyncOpenAI.close()` 会关闭
        注入的 http 客户端）。
    """
    # 记忆侧有两个模型客户端，端点可能不是同一个：嵌入必须用嵌入端点
    # （嵌入模型与维度绑死、换家要整库重建），而这里只建嵌入用的那个。
    embedding_key = settings.resolved_embedding_api_key
    if embedding_key is None:
        raise MemoryConfigurationError("未配置 TOKENHUB_API_KEY，无法调用记忆侧的模型")

    api_key = embedding_key.get_secret_value()
    base_url = settings.resolved_embedding_base_url
    resolved_timeout = settings.model_request_timeout_seconds if timeout_seconds is None else timeout_seconds
    if http_client is None:
        # trust_env=False：与 `build_memory_graph` 注入的那个同一纪律（宿主机 no_proxy
        # 含 `[::1]` 时 httpx2 构造期即崩；见 `build_memory_graph` 的「代理豁免」一节）。
        http_client = httpx2.AsyncClient(trust_env=False, timeout=resolved_timeout)

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=http_client,
        timeout=resolved_timeout,
        max_retries=0,
    )
    embedder = TokenHubEmbedder(
        config=OpenAIEmbedderConfig(
            embedding_dim=EMBEDDING_DIM,
            embedding_model=settings.embedding_model_name,
            api_key=api_key,
            base_url=base_url,
        ),
        client=client,
    )
    return MemoryEmbedder(embedder=embedder, client=client)


class OrderedCrossEncoder(CrossEncoderClient):
    """不做重排的重排器：保持传入顺序。

    存在的唯一理由是 `Graphiti` 的 `cross_encoder` 默认值会在构造时抛错
    （见 `build_memory_graph` 的模块说明第 1 条）。一期不做重排——应急预注入按时间取数、不走 `search()`
    （通用记忆第 6 节）；将来启用语义检索时，这里换成真正的重排实现即可，
    调用点不变。
    """

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        """按原顺序返回，分数一律 0.0（无重排信息）。

        Returns:
            `(passage, score)` 列表，顺序与入参一致。
        """
        return [(passage, 0.0) for passage in passages]


@dataclass(frozen=True, slots=True)
class MemoryGraph:
    """一个可用的记忆图库句柄，持有它创建的全部资源。

    字段与所有权：`graphiti`（它内部持有两个模型客户端）、`driver`（持有
    falkordb 客户端与一个后台索引任务）、`model_clients`（本句柄创建、注入给
    Graphiti 的 openai 客户端）、`http_client`（注入给前者的 httpx2 客户端）。
    全部由 :meth:`aclose` 统一关闭——所有权集中在一处，调用方不需要知道内部
    有几个连接（CORE-03：副作用的边界必须有所有者）。

    `model_clients` / `http_client` 之所以由本结构显式持有而不是在 `aclose`
    里从 `graphiti.llm_client.client` 反查：反查依赖「Graphiti 内部一定放着
    openai 客户端」这一未受约束的实现细节，且测试用假客户端时该属性根本不存在
    （实测 `LLMClient` 基类不设 `self.client`）。谁创建谁持有，才不需要猜。

    把 Graphiti 与驱动放在一起还为了能直接落 Cypher（时间线回看与预注入的查询都要
    自建——见通用记忆第 4 节：`retrieve_episodes` 没有时间区间与关键词参数）。
    """

    graphiti: Graphiti
    driver: FalkorDriver
    #: 本句柄创建并需收口的 openai 客户端（默认空：测试可注入假客户端）。
    model_clients: tuple[AsyncOpenAI, ...] = ()
    #: 注入给上面客户端的 http 客户端；`AsyncOpenAI.close()` 会级联关闭它，这里兜底。
    http_client: httpx2.AsyncClient | None = None
    #: 账号 → 该账号那张图的驱动缓存（有界，见 `MAX_CACHED_ACCOUNT_DRIVERS`）。
    #:
    #: 为什么必须缓存（2026-09-29 实测）：`clone(database=X)` 在 X 与当前库名
    #: 不同时会构造一个新的 `FalkorDriver`，而它的 `__init__` 会调度一个建索引的
    #: 后台任务。实测：同一账号连续两次取驱动返回两个不同对象，pending task 计数
    #: 2→3→4——即每条查询泄漏一个驱动与一个后台任务。这不是理论风险，是本模块
    #: 自己踩到的缺陷。
    #:
    #: 缓存有界：账号数无上界（一个账号一张图），无界缓存只是换一种泄漏。
    #: 超出上界时按插入序淘汰最早的条目（简单 FIFO；热点账号会因反复命中而留在
    #: 队尾之外——真正需要 LRU 时再换，一期账号量远小于上界）。
    #: 字段用 `field(default_factory=...)`：`frozen=True` 不影响可变字段的内容。
    account_drivers: dict[str, GraphDriver] = field(default_factory=dict)
    #: 本句柄派生出的全部克隆驱动（弱引用），含 `driver_for` 缓存的与上游
    #: `add_episode` 内部临时 clone 且随即丢弃引用的那些——它们各有一个无人收口的
    #: 建索引后台任务，必须在关共享客户端之前逐个收口。弱引用避免因此持有驱动不放。
    spawned_drivers: WeakSet[GraphDriver] = field(default_factory=WeakSet)

    def __post_init__(self) -> None:
        """把 base 驱动的 `clone` 接上登记：谁 clone，谁在 `aclose()` 被收口。"""
        _track_cloned_drivers(self.driver, self.spawned_drivers)

    # quality-floor: ignore docstring-promise 异常由 to_account_id 抛出并原样传播，函数体只做校验委托
    def driver_for(self, account_id: str) -> GraphDriver:
        """取该账号那张图的驱动，命中缓存则不新建。

        同库名时 `clone` 本就返回 `self`（实测），因此这里对 base 库不额外缓存。

        这里做入口校验（2026-09-29 评审指出）：`driver_for` 是两条读路径与缓存
        的唯一共同入口，而此前它接受任意字符串——实测未校验的键
        （含换行/分号、5000 字符、框架哨兵 `'_'`）都会被接受并成为图名，
        而 `'_'` 还会落到 `default_db`（正是 `identity` 要拒的哨兵）。
        校验放在此处，比要求每个调用方各自记得调 `to_account_id` 更可靠。

        Args:
            account_id: 账号标识（即 `group_id` / 图名）。会被校验。

        Returns:
            指向该账号那张图的驱动。

        Raises:
            AccountIdError: 账号标识不合法（空、超长、含非法字符、或命中框架哨兵）。

        Note:
            淘汰只从字典里移除引用，不关闭被淘汰的驱动：它共享同一个
            `falkordb` 客户端（实测 `clone.client is base.client`），关它会连带
            关掉其它账号在用连接。连接由 :meth:`aclose` 统一收口。
            淘汰留下一个不再被 `aclose` 看到的后台任务（每个 clone 各调度一个）：
            它自然结束，但失败必须留痕——淘汰时已挂观察者（`_watch_driver_init_task`）。

        Note:
            本函数只覆盖读路径（2026-09-29 实测说明）：`add_episode`（写路径）
            内部自己调 `_resolve_request_scope` → `driver.clone(...)`，不经过这里，
            因此写入期间仍会临时新建驱动。实测：3 次 `write_episode` 期间可见 2 个新
            `build_indices` 任务，但这些任务会结束，且连续 12 次写入后存活的
            `FalkorDriver` 对象数不增长（恒为 2）——即那是每次调用的临时分配，
            不是无界累积。若将来发现它随写入次数线性增长，处置方向是让写入复用本缓存
            的驱动（需绕过 `add_episode` 的内部 clone，属上游接口限制）。
        """
        # 入口校验：见 docstring。已校验过的键（合法）走同一个函数不会有额外代价
        # （正则匹配）。
        validated = to_account_id(account_id)

        cached = self.account_drivers.get(validated)
        if cached is not None:
            return cached

        scoped = self.driver.clone(database=validated)
        if scoped is self.driver:
            # 账号恰好等于配置库名：clone 返回自身，无需缓存（也不该占用一个名额）。
            return scoped

        if len(self.account_drivers) >= MAX_CACHED_ACCOUNT_DRIVERS:
            # 淘汰最早插入的一条（FIFO）。见字段说明：这里只丢引用，不关连接。
            oldest = next(iter(self.account_drivers))
            evicted = self.account_drivers.pop(oldest)
            # 淘汰后 aclose 再也看不到它：挂观察者取回其后台任务异常（见 `_watch_driver_init_task`）。
            _watch_driver_init_task(evicted, account_id=oldest)
        self.account_drivers[validated] = scoped
        return scoped

    async def release_account_driver(self, account_id: str) -> bool:
        """收口该账号的全部派生驱动：**删除该账号的图之前必须先调用**。

        范围按图名匹配 `spawned_drivers`（缓存 + 被淘汰的 + 上游临时 clone 的），
        因为只要有一条该图的建索引任务还在跑，紧随其后的 `GRAPH.DELETE` 就会让在途
        `CREATE INDEX` 失败。顺序：取消并等待任务 → 移出缓存；不关共享客户端。

        Returns:
            收口了至少一个驱动为 True；该账号没有任何派生驱动时为 False（无副作用）。
        """
        validated = to_account_id(account_id)
        targets = [
            scoped
            for scoped in list(self.spawned_drivers)
            if scoped is not self.driver and getattr(scoped, "_database", None) == validated
        ]
        for scoped in targets:
            self.spawned_drivers.discard(scoped)
        # 缓存里若有未被登记的驱动（例如测试直接注入），一并收口。
        cached = self.account_drivers.pop(validated, None)
        if cached is not None and cached is not self.driver and all(cached is not seen for seen in targets):
            targets.append(cached)
        for scoped in targets:
            await _cancel_driver_init_task(scoped, account_id=validated)
        return bool(targets)

    async def aclose(self) -> None:
        """关闭全部资源：驱动（含后台任务）、模型客户端、http 客户端。

        为什么不是只关 `driver.client`（2026-09-29 评审指出，实测确认）：
        `FalkorDriver.__init__` 会调度一个后台任务建索引与约束，只关
        `driver.client` 会让该任务在客户端关闭后继续跑并抛
        `ConnectionError`、异常无人取回（实测 `uv run pytest` 打印 5 次
        `Task exception was never retrieved`）。上游 `FalkorDriver.close()`
        正是为此而写（`cancel()` + 取回异常），用它是正确做法，绕过它才是缺陷。
        此前 docstring 称「`Graphiti` 没有自己的 `close()`」——该说法错误，
        实测 `Graphiti.close()` 存在且体为 `await self.driver.close()`。

        两个 `AsyncOpenAI` 也从不自动关闭（各自一个连接池）；
        `AsyncOpenAI.close()` 实测会连带关闭注入的 `http_client`，因此这里先关
        客户端、再兜底关 `http_client`（`aclose()` 幂等，重复关无副作用）。

        缓存的账号驱动为什么不能逐个调 `close()`（2026-09-29 评审指出，实测确认）：
        克隆驱动与 base 共享同一个 `falkordb` 客户端（实测
        `clone.client is base.client`），而 `FalkorDriver.close()` 内部就是
        `await self.client.aclose()`——逐个调它会把同一个共享客户端关闭 N+1 次。
        实测：3 个缓存账号时 `client.aclose()` 被调用 4 次（应为 1 次），且会
        打断在途查询（`ConnectionError`）。因此这里只取消各克隆驱动自己的后台
        索引任务（那是每个克隆独有的资源），客户端只由 `graphiti.close()` 关一次。

        收尾顺序：先收口全部派生驱动，再 `graphiti.close()`——反过来会先关共享客户端，
        让在途索引查询以 `ConnectionError` 失败。任何一步失败都继续释放其余资源，
        最后抛出第一个异常（收尾是退出路径，短路会把连接池留给解释器回收）。
        """
        failures: list[Exception] = []

        async def attempt(step: str, action: Awaitable[None]) -> None:
            try:
                await action
            except Exception as exc:  # noqa: BLE001 —— 收尾要继续跑完，异常最后统一抛出
                logger.warning("记忆图库收尾的一步失败（%s，异常=%s），继续释放其余资源", step, type(exc).__name__)
                failures.append(exc)

        # 1. 克隆驱动各有自己的后台索引任务，但客户端共享：只取消任务，不关客户端。
        #    取登记表与缓存的并集（登记表可能漏，例如测试直接注入缓存）。
        clones = list(self.spawned_drivers)
        clones.extend(scoped for scoped in self.account_drivers.values() if all(scoped is not seen for seen in clones))
        for scoped in clones:
            if scoped is not self.driver:
                await attempt(
                    "cancel_clone_init_task",
                    _cancel_driver_init_task(scoped, account_id=getattr(scoped, "_database", None)),
                )
        self.spawned_drivers.clear()
        self.account_drivers.clear()
        # 2. Graphiti.close() 即 driver.close()：取消并取回 base 驱动的后台索引任务，
        #    并关闭共享的 falkordb 客户端（唯一一次）。
        await attempt("close_base_driver", self.graphiti.close())
        for client in self.model_clients:
            await attempt("close_model_client", client.close())
        if self.http_client is not None:
            await attempt("close_http_client", self.http_client.aclose())
        if failures:
            raise failures[0]


def _track_cloned_drivers(base: GraphDriver, registry: WeakSet[GraphDriver]) -> None:
    """把 base 驱动的 `clone` 接到登记表上，供 `aclose()` 收口（含上游内部 clone）。

    上游 `_resolve_request_scope` 会自己 clone 并丢弃引用，其驱动的建索引任务因此没有
    所有者；包一层公开方法 `clone` 是不改上游就能拿到它们的最小手段。

    Args:
        base: 本句柄的 base 驱动。
        registry: 登记表（弱引用；不阻止驱动被回收）。
    """
    original = getattr(base, "clone", None)
    if not callable(original):
        return

    def clone(database: str) -> GraphDriver:
        cloned = original(database)
        if cloned is not base:
            registry.add(cloned)
        return cloned

    base.clone = clone  # type: ignore[method-assign]  # 有意替换 base 驱动实例上的 clone（见本函数说明）


def _report_driver_init_failure(task: asyncio.Task[None], *, account_id: str | None) -> None:
    """取回后台初始化任务的异常并记一条 warning（带图名归属）。

    不取回会在任务回收时打印 `Task exception was never retrieved`；只 `pass` 则失败彻底
    静默。异常消息可能带连接串，故只记类型名。主动取消不算失败，不记日志。

    Args:
        task: 驱动的 `_init_task`。
        account_id: 该驱动指向的图名；base 驱动为 `None`。
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is None:
        return
    # 只记异常类型与图名：异常消息可能带主机端口（`Error 111 connecting to h:p`）
    # 甚至连接串，按安全纪律不复述。
    logger.warning(
        "记忆图库的后台建索引任务以异常结束（图=%s，异常=%s）：索引可能未建成，读写仍按查询本身的结果判定",
        account_id or "<base>",
        type(exc).__name__,
    )


def _watch_driver_init_task(driver: GraphDriver, *, account_id: str) -> None:
    """给已从缓存淘汰、再无人收口的驱动挂一个只观察的下钩子。

    淘汰路径是同步函数、无法 await，因此用 `add_done_callback` 取回异常；不取消任务
    （淘汰时可能有在途查询正在用该驱动）。

    Args:
        driver: 刚被淘汰的驱动。
        account_id: 它指向的图名（日志归属）。
    """
    task = getattr(driver, "_init_task", None)
    if task is None:
        return
    task.add_done_callback(lambda finished: _report_driver_init_failure(finished, account_id=account_id))


async def _cancel_driver_init_task(driver: GraphDriver, *, account_id: str | None = None) -> None:
    """取消某个驱动自己的后台初始化任务，不触碰共享客户端，并等它真正结束。

    为什么需要这个函数（而不是直接用 `driver.close()`）：`FalkorDriver.close()`
    做两件事——取消任务 + 关闭客户端——而克隆驱动的客户端是与 base 共享的
    （实测 `clone.client is base.client`），调它会重复关闭同一个客户端。

    为什么必须 await（2026-09-29 实测）：只调 `task.cancel()` 而不 await 时，
    任务仍会在 `asyncio.all_tasks()` 中短暂可见，测试里表现为「残留后台索引任务」
    ——取消是请求，只有让出控制权后任务才会真正结束。`await` 它并吞掉
    `CancelledError` 才能确保收口完成（上游 `FalkorDriver.close()` 也是这么做的：
    `with suppress(asyncio.CancelledError): await self._init_task`）。

    这里访问 `_init_task` 这个私有属性是有意的妥协：上游没有暴露「只取消任务」
    的公开接口。范围被压到最小（只读该属性、只 cancel + await），并用 `getattr`
    兜住上游改名——改名后不会静默漏收口，而是退化为「不取消」，
    由实测（`Task exception was never retrieved`）暴露出来。

    已完成的任务同样要处理：任务可能在 `cancel()` 之前就已失败，此时异常必须取回
    （对齐上游 `FalkorDriver.close()` 的 `elif not task.cancelled(): ...exception()`），
    并记进日志（见 :func:`_report_driver_init_failure`）——只 `pass` 等于消音。

    Args:
        driver: 驱动；只依赖它的 `_init_task`。
        account_id: 该驱动指向的图名，用于日志归属；省略时不带归属。

    Note:
        `driver` 参数用基类 `GraphDriver`：调用方只依赖「有个可取消的初始化任务」
        这一点，不绑定 FalkorDB 的具体类型。
    """
    task = getattr(driver, "_init_task", None)
    if task is None:
        return
    if not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    # 无论「刚被取消」还是「早已结束」都取回异常：后者可能是真实的索引初始化失败。
    _report_driver_init_failure(task, account_id=account_id)


def build_memory_graph(settings: Settings) -> MemoryGraph:
    """按配置装配记忆图库：驱动 + TokenHub 三客户端 + Graphiti 实例。

    为什么需要这一层（四个实测得到的约束）

    设计文档把记忆的存储写作「Graphiti + FalkorDB」，但构造一个可用的 Graphiti
    实例有四处必须显式处理，照默认值走会直接失败或静默连错供应商：

    1. `cross_encoder` 必须显式传入（实测 0.30.2）：默认值 `OpenAIRerankerClient()`
       在构造时即建 `AsyncOpenAI(api_key=None)` 并抛 `OpenAIError: Missing credentials`
       ——连 Graphiti 都构造不出来。一期不用重排（通用记忆第 6 节：应急预注入不走
       `search()`），因此传一个「保持原序」的空实现。
    2. `llm_client` / `embedder` 必须显式传入：否则回落到 `OpenAIClient()` /
       `OpenAIEmbedder()` 去读 `OPENAI_API_KEY`，即绕过 TokenHub。项目纪律是
       「全应用单一模型」（技术栈设计第 3 节），记忆侧也必须走同一个供应商与向量模型
       （RAG 策略第 11 节）。
    3. `small_model` 必须一并显式传入（2026-09-29 评审发现，实测确认）：只传
       `model` 时 `LLMConfig.small_model` 保持 `None`，而 `LLMClient` 在
       `ModelSize.small` 时回落到上游硬编码的 `gpt-4.1-nano`（实测
       `_get_model_for_size(small) == 'gpt-4.1-nano'`）。Graphiti 有 7 处抽取/消解
       调用走 `ModelSize.small`，全都`add_episode` 必经——这等于绕过 TokenHub 的
       单一模型纪律，且是同一类「静默回落」缺陷的第二个入口。因此两个档位都指向
       `settings.model_name`：一期只有一个模型，不存在「便宜档」。
    4. `store_raw_episode_content` 必须为 `True`：置 `False` 会清空 episode 的
       `content`，而「时间线回看」读的就是该字段（通用记忆第 2 节）。

    另有一条**第五个**上游约束（2026-10-02 实测确认的产品缺陷，P1）：

    5. `embedder` 必须用 :class:`TokenHubEmbedder` 而非裸 `OpenAIEmbedder`：上游的
       `create()` / `create_batch()` 只传 `input` + `model`，SDK 于是把
       `encoding_format` 填成 `base64`，而 TokenHub 只接受 `float` ⇒ 真实端点
       稳定 `400001` ⇒ `add_episode` 必失败 ⇒ **记忆写入路径整体不可用**。
       该缺陷已存在于 `origin/master`（`git log origin/master..HEAD -- modules/memory/graph.py`
       为 0 个提交），且因 `/readyz` 的 `model` 项只探 chat 端点而不探 embedding，
       表现为**健康检查全绿而写入全坏**。完整实测与两条被排除的修法见
       :class:`TokenHubEmbedder` 的 docstring。

    超时的落法（两条腿都要有界，缺一条等于没有）

    图库腿：`FalkorDriver` 自己没有超时参数，但它接受一个已构造的 `falkordb`
    客户端（`falkor_db=`），该客户端有 `socket_timeout` / `socket_connect_timeout`。
    我们据此把 `falkordb_timeout_seconds` 落到 socket 层。

    模型腿（2026-09-29 评审发现，实测确认）：只设图库超时时，两个模型客户端仍取
    openai SDK 的默认值——实测 `timeout=Timeout(connect=5.0, read=600, write=600,
    pool=600)`、`max_retries=2`，再叠加 Graphiti 自身的 `MAX_RETRIES` 重试循环。
    读超时 600 秒会直接顶掉 `RQ-EMG-03` 的 10 秒首字预算。因此这里显式设
    `timeout=settings.model_request_timeout_seconds` 与 `max_retries=0`，与
    `agent/model/gateway` 的既有纪律一致（那里还额外把该契约断言出来，见
    `build_model_settings`）。

    代理豁免：为什么用注入而不是改写 `os.environ`

    宿主机 `no_proxy` 含带方括号的 IPv6 字面量（如 `[::1]`）时，openai 用的
    `httpx2` 在构造客户端时即抛 `InvalidURL: Invalid port: ':1]'`（见
    `apps/api/tests/conftest.py` 的留档），使记忆模块根本无法构造。

    就地改写 `os.environ['no_proxy']` 的做法已废弃（2026-09-29 评审指出
    两个问题）：(a) 它改的是进程全局，会波及同进程内一切 httpx 消费者
    （`agent/model/gateway`、`modules/library/embedding` 等），一个 builder 函数
    制造隐藏全局副作用；(b) 它只 `replace("[::1]", "")`，对 `[::2]`、
    `[2001:db8::1]` 等形态无效（实测这些同样会让构造失败），属半修。

    现改为显式构造不读代理环境的客户端并注入（`trust_env=False`），与
    `modules/library/embedding.py` 已有做法一致。代价是服务端到服务端调用不继承
    桌面代理豁免——这正是嵌入侧已确立的判断：企业网络需要代理时应显式配置。

    Raises:
        MemoryConfigurationError: 未配置 `TOKENHUB_API_KEY` 时——记忆的实体抽取与
            嵌入都要调模型，缺凭据时显式失败，不静默降级（同
            `EmbeddingConfigurationError` 的处理纪律）。
    """
    # 记忆侧的 LLM 端点可以独立于对话端点（见 `core/config` 的 `memory_llm_base_url`）：
    # Graphiti 取结构化输出走 Responses API，chat-only 的网关不支持。
    memory_key = settings.resolved_memory_llm_api_key
    if memory_key is None:
        raise MemoryConfigurationError("未配置 TOKENHUB_API_KEY，无法调用记忆侧的模型")

    api_key = memory_key.get_secret_value()
    base_url = settings.resolved_memory_llm_base_url

    client = FalkorDB(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        password=(settings.falkordb_password.get_secret_value() if settings.falkordb_password else None),
        socket_timeout=settings.falkordb_timeout_seconds,
        socket_connect_timeout=settings.falkordb_timeout_seconds,
    )
    driver = FalkorDriver(falkor_db=client, database=settings.falkordb_database)

    # trust_env=False：不继承宿主机 no_proxy（含 [::1] 一类 IPv6 字面量时 httpx2 构造
    # 即抛 InvalidURL）。见 `build_memory_graph` 的模块说明「代理豁免」一节：注入而非改写 os.environ。
    # 超时与重试与 agent/model/gateway 的纪律一致：超时有界、重试唯一所有者不在 SDK。
    http_client = httpx2.AsyncClient(
        trust_env=False,
        timeout=settings.model_request_timeout_seconds,
    )
    # 两个档位都指向同一个模型：一期只有一个模型，没有「便宜档」。
    # 不传 small_model 会回落到上游硬编码的 gpt-4.1-nano（见 `build_memory_graph` 的模块说明第 3 条）。
    llm_config = LLMConfig(
        api_key=api_key,
        model=settings.model_name,
        small_model=settings.model_name,
        base_url=base_url,
    )
    # 两个客户端共用同一条 http 连接池：它们指向同一个供应商与同一组超时，
    # 分开建池只会多一份连接开销（关闭时 AsyncOpenAI.close() 会级联关它）。
    llm_openai = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=http_client,
        timeout=settings.model_request_timeout_seconds,
        max_retries=0,
    )
    llm_client = OpenAIClient(
        config=llm_config,
        max_tokens=LLM_MAX_TOKENS,
        client=llm_openai,
    )
    # 嵌入器的构造经 `build_memory_embedder`（**必须走它**）：那里是「记忆侧嵌入器怎么造」
    # 的唯一真源，深度就绪探针（`campfire.main.check_embedding`）用的是同一个函数。
    # 生产路径若在这里自己再写一份构造，探针就会与生产分叉——而「探针探的是另一份配置」
    # 正是本探针最典型的失效形态（见该函数的 docstring）。
    # 注入共用的 http_client：与 llm 客户端同一条连接池（理由见本函数说明）。
    memory_embedder = build_memory_embedder(settings, http_client=http_client)
    embedder = memory_embedder.embedder
    embed_openai = memory_embedder.client

    # 契约断言（同 agent/model/gateway.build_model_settings 的做法）：两个档位必须是
    # 同一个模型、重试必须已关。不留「靠上游默认值恰好正确」的活口。
    if llm_client.config.small_model != settings.model_name:
        raise MemoryConfigurationError(
            f"small_model 未与 model 对齐（{llm_client.config.small_model!r}）："
            "Graphiti 的抽取路径会回落到上游默认模型，绕过 TokenHub 的单一模型纪律"
        )
    if llm_client.client.max_retries != 0:
        raise MemoryConfigurationError(
            f"LLM 客户端 max_retries={llm_client.client.max_retries}，必须为 0："
            "重试的唯一所有者是本模块，SDK 层的重试会让最坏耗时成倍放大"
        )

    graphiti = Graphiti(
        graph_driver=driver,
        llm_client=llm_client,
        embedder=embedder,
        # 必须显式传入：默认值会构造 OpenAI 客户端并抛错
        # （见 `build_memory_graph` 的模块说明第 1 条）。
        cross_encoder=OrderedCrossEncoder(),
        # 必须为 True：False 会清空 episode content，时间线回看失效
        # （见 `build_memory_graph` 的模块说明第 4 条）。
        store_raw_episode_content=True,
        max_coroutines=settings.falkordb_max_coroutines,
    )
    return MemoryGraph(
        graphiti=graphiti,
        driver=driver,
        model_clients=(llm_openai, embed_openai),
        http_client=http_client,
    )


#: 进程内共享的记忆图库句柄。
#:
#: 必须复用：每次 `build_memory_graph` 都会新建 FalkorDB 驱动（其构造函数会调度建索引
#: 的后台任务）、三个模型客户端与一个 http 客户端；按调用重建等于每次泄漏一整套连接池
#: （实测依据见 `MemoryGraph.aclose` 与 `MemoryGraph.driver_for` 的说明）。
#:
#: 放在本模块（而不是 `worker.py`）的理由：投递与读路径是两个入口——Worker 消费
#: 待处理记录、API 侧的工具读时间线，两者要共用同一个句柄；而 `tools/*` 的白名单只有
#: `modules/*` 与 `core/*`，不能 import 入口模块 `campfire.worker`
#: （项目结构设计（../../../../docs/项目结构设计.md）第 7 节）。因此句柄的归属必须下沉到这里。
_shared_graph: MemoryGraph | None = None


def get_shared_memory_graph(settings: Settings | None = None) -> MemoryGraph:
    """取（或首次构造）进程内共享的记忆图库句柄。

    Args:
        settings: 可选配置；首次构造时使用，省略则读全局配置。

    Raises:
        MemoryConfigurationError: 配置不完整（未配凭据）时——记忆的抽取与嵌入都要调模型，
            缺凭据显式失败，不静默降级。
    """
    global _shared_graph
    if _shared_graph is None:
        _shared_graph = build_memory_graph(settings if settings is not None else get_settings())
    return _shared_graph


async def aclose_shared_memory_graph() -> None:
    """关闭并清空共享句柄（进程退出或测试收尾时调用）。幂等。

    先摘全局引用、再关闭：关闭任一条腿失败时异常照常上抛，但不会留下一个半关闭的
    句柄被下一次 `get_shared_memory_graph()` 当可用实例取回。后台索引任务的失败由
    `aclose()` 取回并记 warning，不阻断这条收尾链。
    """
    global _shared_graph
    graph, _shared_graph = _shared_graph, None
    if graph is not None:
        await graph.aclose()


__all__ = [
    "LLM_MAX_TOKENS",
    "MemoryEmbedder",
    "MemoryGraph",
    "OrderedCrossEncoder",
    "TokenHubEmbedder",
    "aclose_shared_memory_graph",
    "build_memory_embedder",
    "build_memory_graph",
    "get_shared_memory_graph",
]
