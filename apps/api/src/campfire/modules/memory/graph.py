"""Graphiti + FalkorDB 的装配：驱动、三个客户端与图库句柄。

归属（见 docs/技术设计/technical-details/通用记忆.md 第 8 节与
docs/技术设计/decisions/通用记忆归属为账号.md）：连接与客户端装配归 `modules/memory`；
连接配置的唯一真源是 ``core/config``（第 10 节「配置唯一入口」）。

## 为什么需要这一层（四个实测得到的约束）

设计文档把记忆的存储写作「Graphiti + FalkorDB」，但**构造一个可用的 Graphiti
实例有四处必须显式处理**，照默认值走会直接失败或静默连错供应商：

1. **`cross_encoder` 必须显式传入**（实测 0.30.2）：默认值 ``OpenAIRerankerClient()``
   在构造时即建 ``AsyncOpenAI(api_key=None)`` 并抛 ``OpenAIError: Missing credentials``
   ——**连 Graphiti 都构造不出来**。一期不用重排（通用记忆第 6 节：应急预注入不走
   ``search()``），因此传一个「保持原序」的空实现。
2. **`llm_client` / `embedder` 必须显式传入**：否则回落到 ``OpenAIClient()`` /
   ``OpenAIEmbedder()`` 去读 ``OPENAI_API_KEY``，即绕过 TokenHub。项目纪律是
   「全应用单一模型」（技术栈设计第 3 节），记忆侧也必须走同一个供应商与向量模型
   （RAG 策略第 11 节）。
3. **`small_model` 必须一并显式传入**（2026-09-29 评审发现，实测确认）：只传
   ``model`` 时 ``LLMConfig.small_model`` 保持 ``None``，而 ``LLMClient`` 在
   ``ModelSize.small`` 时回落到上游硬编码的 ``gpt-4.1-nano``（实测
   ``_get_model_for_size(small) == 'gpt-4.1-nano'``）。Graphiti 有 7 处抽取/消解
   调用走 ``ModelSize.small``，全都``add_episode`` 必经——**这等于绕过 TokenHub 的
   单一模型纪律，且是同一类「静默回落」缺陷的第二个入口**。因此两个档位都指向
   ``settings.model_name``：一期只有一个模型，不存在「便宜档」。
4. **`store_raw_episode_content` 必须为 ``True``**：置 ``False`` 会清空 episode 的
   ``content``，而「时间线回看」读的就是该字段（通用记忆第 2 节）。

## 超时的落法（两条腿都要有界，缺一条等于没有）

**图库腿**：``FalkorDriver`` 自己没有超时参数，但它接受一个已构造的 ``falkordb``
客户端（``falkor_db=``），该客户端有 ``socket_timeout`` / ``socket_connect_timeout``。
我们据此把 ``falkordb_timeout_seconds`` 落到 socket 层。

**模型腿**（2026-09-29 评审发现，实测确认）：只设图库超时时，两个模型客户端仍取
openai SDK 的默认值——实测 ``timeout=Timeout(connect=5.0, read=600, write=600,
pool=600)``、``max_retries=2``，再叠加 Graphiti 自身的 ``MAX_RETRIES`` 重试循环。
**读超时 600 秒**会直接顶掉 ``RQ-EMG-03`` 的 10 秒首字预算。因此这里显式设
``timeout=settings.model_request_timeout_seconds`` 与 ``max_retries=0``，与
``agent/model/gateway`` 的既有纪律一致（那里还额外把该契约断言出来，见
``build_model_settings``）。

## 代理豁免：为什么用注入而不是改写 ``os.environ``

宿主机 ``no_proxy`` 含带方括号的 IPv6 字面量（如 ``[::1]``）时，openai 用的
``httpx2`` 在构造客户端时即抛 ``InvalidURL: Invalid port: ':1]'``（见
``apps/api/tests/conftest.py`` 的留档），使记忆模块**根本无法构造**。

此前做法是就地改写 ``os.environ['no_proxy']``——**已废弃**（2026-09-29 评审指出
两个问题）：(a) 它改的是**进程全局**，会波及同进程内一切 httpx 消费者
（``agent/model/gateway``、``modules/library/embedding`` 等），一个 builder 函数
制造隐藏全局副作用；(b) 它只 ``replace("[::1]", "")``，对 ``[::2]``、
``[2001:db8::1]`` 等形态无效（实测这些同样会让构造失败），属半修。

现改为**显式构造不读代理环境的客户端并注入**（``trust_env=False``），与
``modules/library/embedding.py`` 已有做法一致。代价是服务端到服务端调用不继承
桌面代理豁免——这正是嵌入侧已确立的判断：企业网络需要代理时应显式配置。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx2
from falkordb.asyncio import FalkorDB  # type: ignore[import-untyped]  # 上游无 py.typed；运行时行为已由集成测试锁定
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.graphiti import Graphiti
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_client import OpenAIClient
from openai import AsyncOpenAI

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
    """一个可用的记忆图库句柄，**持有它创建的全部资源**。

    字段与所有权：``graphiti``（它内部持有两个模型客户端）、``driver``（持有
    falkordb 客户端与一个后台索引任务）、``model_clients``（本句柄创建、注入给
    Graphiti 的 openai 客户端）、``http_client``（注入给前者的 httpx2 客户端）。
    全部由 :meth:`aclose` **统一关闭**——所有权集中在一处，调用方不需要知道内部
    有几个连接（CORE-03：副作用的边界必须有所有者）。

    ``model_clients`` / ``http_client`` 之所以由本结构**显式持有**而不是在 ``aclose``
    里从 ``graphiti.llm_client.client`` 反查：反查依赖「Graphiti 内部一定放着
    openai 客户端」这一未受约束的实现细节，且测试用假客户端时该属性根本不存在
    （实测 ``LLMClient`` 基类不设 ``self.client``）。谁创建谁持有，才不需要猜。

    把 Graphiti 与驱动放在一起还为了能直接落 Cypher（时间线回看与预注入的查询都要
    自建——见通用记忆第 4 节：``retrieve_episodes`` 没有时间区间与关键词参数）。
    """

    graphiti: Graphiti
    driver: FalkorDriver
    #: 本句柄创建并需收口的 openai 客户端（默认空：测试可注入假客户端）。
    model_clients: tuple[AsyncOpenAI, ...] = ()
    #: 注入给上面客户端的 http 客户端；``AsyncOpenAI.close()`` 会级联关闭它，这里兜底。
    http_client: httpx2.AsyncClient | None = None

    async def aclose(self) -> None:
        """关闭**全部**资源：驱动（含后台任务）、模型客户端、http 客户端。

        为什么不是只关 ``driver.client``（2026-09-29 评审指出，实测确认）：
        ``FalkorDriver.__init__`` 会**调度一个后台任务**建索引与约束，只关
        ``driver.client`` 会让该任务在客户端关闭后继续跑并抛
        ``ConnectionError``、异常无人取回（实测 ``uv run pytest`` 打印 5 次
        ``Task exception was never retrieved``）。上游 ``FalkorDriver.close()``
        正是为此而写（``cancel()`` + 取回异常），**用它是正确做法，绕过它才是缺陷**。
        此前 docstring 称「``Graphiti`` 没有自己的 ``close()``」——**该说法错误**，
        实测 ``Graphiti.close()`` 存在且体为 ``await self.driver.close()``。

        两个 ``AsyncOpenAI`` 也从不自动关闭（各自一个连接池）；
        ``AsyncOpenAI.close()`` 实测会连带关闭注入的 ``http_client``，因此这里先关
        客户端、再兜底关 ``http_client``（``aclose()`` 幂等，重复关无副作用）。
        """
        # Graphiti.close() 即 driver.close()：取消并取回后台索引任务的异常。
        await self.graphiti.close()
        for client in self.model_clients:
            await client.close()
        if self.http_client is not None:
            await self.http_client.aclose()


def build_memory_graph(settings: Settings) -> MemoryGraph:
    """按配置装配记忆图库：驱动 + TokenHub 三客户端 + Graphiti 实例。

    Raises:
        MemoryConfigurationError: 未配置 ``TOKENHUB_API_KEY`` 时——记忆的实体抽取与
            嵌入都要调模型，缺凭据时**显式失败**，不静默降级（同
            ``EmbeddingConfigurationError`` 的处理纪律）。
    """
    if settings.tokenhub_api_key is None:
        raise MemoryConfigurationError("未配置 TOKENHUB_API_KEY，无法调用记忆侧的模型")

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

    # trust_env=False：不继承宿主机 no_proxy（含 [::1] 一类 IPv6 字面量时 httpx2 构造
    # 即抛 InvalidURL）。见模块说明「代理豁免」一节：注入而非改写 os.environ。
    # 超时与重试与 agent/model/gateway 的纪律一致：超时有界、重试唯一所有者不在 SDK。
    http_client = httpx2.AsyncClient(
        trust_env=False,
        timeout=settings.model_request_timeout_seconds,
    )
    # 两个档位都指向同一个模型：一期只有一个模型，没有「便宜档」。
    # 不传 small_model 会回落到上游硬编码的 gpt-4.1-nano（见模块说明第 3 条）。
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
    embed_openai = AsyncOpenAI(
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
    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            embedding_dim=EMBEDDING_DIM,
            embedding_model=settings.embedding_model_name,
            api_key=api_key,
            base_url=base_url,
        ),
        client=embed_openai,
    )

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
        # 必须显式传入：默认值会构造 OpenAI 客户端并抛错（模块说明第 1 条）。
        cross_encoder=OrderedCrossEncoder(),
        # 必须为 True：False 会清空 episode content，时间线回看失效（模块说明第 4 条）。
        store_raw_episode_content=True,
        max_coroutines=settings.falkordb_max_coroutines,
    )
    return MemoryGraph(
        graphiti=graphiti,
        driver=driver,
        model_clients=(llm_openai, embed_openai),
        http_client=http_client,
    )


__all__ = [
    "LLM_MAX_TOKENS",
    "MemoryGraph",
    "OrderedCrossEncoder",
    "build_memory_graph",
]
