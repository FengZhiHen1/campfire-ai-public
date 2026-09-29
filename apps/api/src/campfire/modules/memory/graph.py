"""Graphiti + FalkorDB 的装配：驱动、三个客户端与图库句柄。

归属（见 docs/技术设计/technical-details/通用记忆.md 第 8 节与
docs/技术设计/decisions/通用记忆归属为账号.md）：连接与客户端装配归 `modules/memory`；
连接配置的唯一真源是 ``core/config``（第 10 节「配置唯一入口」）。

## 为什么需要这一层（三个实测得到的约束）

设计文档把记忆的存储写作「Graphiti + FalkorDB」，但**构造一个可用的 Graphiti
实例有三处必须显式处理**，照默认值走会直接失败或静默连错供应商：

1. **`cross_encoder` 必须显式传入**（实测 0.30.2）：默认值 ``OpenAIRerankerClient()``
   在构造时即建 ``AsyncOpenAI(api_key=None)`` 并抛 ``OpenAIError: Missing credentials``
   ——**连 Graphiti 都构造不出来**。一期不用重排（通用记忆第 6 节：应急预注入不走
   ``search()``），因此传一个「保持原序」的空实现。
2. **`llm_client` / `embedder` 必须显式传入**：否则回落到 ``OpenAIClient()`` /
   ``OpenAIEmbedder()`` 去读 ``OPENAI_API_KEY``，即绕过 TokenHub。项目纪律是
   「全应用单一模型」（技术栈设计第 3 节），记忆侧也必须走同一个供应商与向量模型
   （RAG 策略第 11 节）。
3. **`store_raw_episode_content` 必须为 ``True``**：置 ``False`` 会清空 episode 的
   ``content``，而「时间线回看」读的就是该字段（通用记忆第 2 节）。

## 超时的落法

``FalkorDriver`` 自己没有超时参数，但它接受一个已构造的 ``falkordb`` 客户端
（``falkor_db=``），该客户端有 ``socket_timeout`` / ``socket_connect_timeout``。
我们据此把配置里的 ``falkordb_timeout_seconds`` 落到 socket 层——**有界性**
（CORE-11）要求图库慢时尽快落进降级分支，而不是拖住应急路径的首字时延。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from falkordb.asyncio import FalkorDB  # type: ignore[import-untyped]  # 上游无 py.typed；运行时行为已由集成测试锁定
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.graphiti import Graphiti
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_client import OpenAIClient

from campfire.core.config import EMBEDDING_DIM, Settings
from campfire.modules.memory.errors import MemoryConfigurationError

#: 实体抽取与消解的模型调用上限（token）。Graphiti 的默认是 16384；
#: 我们**显式传入**而不是沿用默认，理由：抽取是需要结构化输出的短任务，
#: 16k 的输出预留会让请求参数随上游默认值漂移，也不利于成本核算。
#: 4096 足够容纳一次抽取的 JSON 结果（实测抽取输出为数十条实体与边）。
LLM_MAX_TOKENS = 4096


class OrderedCrossEncoder(CrossEncoderClient):
    """不做重排的重排器：保持传入顺序。

    存在的唯一理由是 ``Graphiti`` 的 ``cross_encoder`` 默认值会在构造时抛错
    （见模块说明第 1 条）。一期不做重排——应急预注入按时间取数、不走 ``search()``
    （通用记忆第 6 节）；将来启用语义检索时，这里换成真正的重排实现即可，
    调用点不变。
    """

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        """按原顺序返回，分数一律 0.0（无重排信息）。

        Returns:
            ``(passage, score)`` 列表，顺序与入参一致。
        """
        return [(passage, 0.0) for passage in passages]


@dataclass(frozen=True, slots=True)
class MemoryGraph:
    """一个可用的记忆图库句柄：Graphiti 实例 + 它的底层驱动。

    把两者放在一起是为了让调用方**只需关一个东西**（驱动的客户端），
    同时能在需要时直接落 Cypher（时间线回看与预注入的查询都要自建——
    见通用记忆第 4 节：``retrieve_episodes`` 没有时间区间与关键词参数）。
    """

    graphiti: Graphiti
    driver: FalkorDriver

    async def aclose(self) -> None:
        """关闭底层图库连接。

        只关 ``falkordb`` 客户端：``Graphiti`` 没有自己的 ``close()``，
        它持有的 driver 的连接就是这条。
        """
        await self.driver.client.aclose()


def _normalise_proxy_env() -> None:
    """在构造 openai 客户端之前把代理豁免表归一成合法值。

    **这是环境适配，不是业务逻辑**：宿主机 ``no_proxy`` 含带方括号的 IPv6 字面量
    （如 ``[::1]``）时，``openai`` 用的 ``httpx2`` 在构造客户端时就抛
    ``InvalidURL: Invalid port: ':1]'``（见 ``apps/api/tests/conftest.py`` 的留档）。
    该问题与被测代码无关，但会让记忆模块**根本无法构造**。

    只在当前进程内改写，且仅当检测到该形态时才动——不无条件覆盖用户配置
    （企业网络可能确实需要代理豁免项）。
    """
    for name in ("no_proxy", "NO_PROXY"):
        value = os.environ.get(name)
        if value and "[" in value:
            os.environ[name] = value.replace("[::1]", "").replace("[]", "").strip(",")


def build_memory_graph(settings: Settings) -> MemoryGraph:
    """按配置装配记忆图库：驱动 + TokenHub 三客户端 + Graphiti 实例。

    Raises:
        MemoryConfigurationError: 未配置 ``TOKENHUB_API_KEY`` 时——记忆的实体抽取与
            嵌入都要调模型，缺凭据时**显式失败**，不静默降级（同
            ``EmbeddingConfigurationError`` 的处理纪律）。
    """
    if settings.tokenhub_api_key is None:
        raise MemoryConfigurationError("未配置 TOKENHUB_API_KEY，无法调用记忆侧的模型")

    _normalise_proxy_env()

    api_key = settings.tokenhub_api_key.get_secret_value()
    base_url = settings.tokenhub_base_url

    client = FalkorDB(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        password=(settings.falkordb_password.get_secret_value() if settings.falkordb_password else None),
        socket_timeout=settings.falkordb_timeout_seconds,
        socket_connect_timeout=settings.falkordb_timeout_seconds,
    )
    driver = FalkorDriver(falkor_db=client, database=settings.falkordb_database)

    llm_client = OpenAIClient(
        config=LLMConfig(api_key=api_key, model=settings.model_name, base_url=base_url),
        max_tokens=LLM_MAX_TOKENS,
    )
    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            embedding_dim=EMBEDDING_DIM,
            embedding_model=settings.embedding_model_name,
            api_key=api_key,
            base_url=base_url,
        )
    )

    graphiti = Graphiti(
        graph_driver=driver,
        llm_client=llm_client,
        embedder=embedder,
        # 必须显式传入：默认值会构造 OpenAI 客户端并抛错（模块说明第 1 条）。
        cross_encoder=OrderedCrossEncoder(),
        # 必须为 True：False 会清空 episode content，时间线回看失效（模块说明第 3 条）。
        store_raw_episode_content=True,
        max_coroutines=settings.falkordb_max_coroutines,
    )
    return MemoryGraph(graphiti=graphiti, driver=driver)


__all__ = [
    "LLM_MAX_TOKENS",
    "MemoryGraph",
    "OrderedCrossEncoder",
    "build_memory_graph",
]
