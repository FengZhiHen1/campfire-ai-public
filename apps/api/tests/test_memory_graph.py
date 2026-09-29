"""单元测试：记忆模块的异常层次与 Graphiti/FalkorDB 装配。

对应 ``docs/技术设计/technical-details/通用记忆.md`` 第 8 节与
``docs/技术设计/decisions/通用记忆归属为账号.md``。

这里锁的是**实测得到的四个装配约束**（见 ``graph.py`` 模块说明）——它们是
「照默认值走就失败」的坑，且失败形态与原因不直观：

1. ``cross_encoder`` 必须显式传入，否则 ``Graphiti`` 构造时抛 ``OpenAIError``；
2. ``llm_client`` / ``embedder`` 必须显式传入，否则回落到读 ``OPENAI_API_KEY``
   的 OpenAI 客户端（等于绕过 TokenHub 的单一供应商纪律）；
3. ``small_model`` 必须一并显式传入，否则抽取路径回落到上游硬编码的
   ``gpt-4.1-nano``——同一类「静默回落」的第二个入口；
4. ``store_raw_episode_content`` 必须为 ``True``，否则 episode 原文被清空。

装配测试**不连真实图库**：只验证构造出的对象带上了我们要的参数。
真实连通性由 ``test_memory_graph_integration.py`` 承担。
"""

from __future__ import annotations

import pytest
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.llm_client.client import ModelSize

from campfire.core.config import EMBEDDING_DIM, Settings
from campfire.modules.memory.errors import (
    MemoryConfigurationError,
    MemoryDataError,
    MemoryModuleError,
    MemoryUnavailableError,
)
from campfire.modules.memory.graph import LLM_MAX_TOKENS, OrderedCrossEncoder, build_memory_graph

#: 装配测试用的假凭据：不调用任何真实服务，只需要「已配置」这一事实。
_FAKE_KEY = "test-key-not-a-real-secret"  # noqa: S105 —— 测试用假值，非真实凭据

#: 固定 base_url：宿主机若有 TOKENHUB_BASE_URL 环境变量，其优先级高于字段默认值
#: （pydantic-settings 的既有行为，实测会让本文件的断言假失败）。这里显式钉住，
#: 使用例真的「与宿主机配置无关」——与 test_library_embedding.py 的既有做法一致。
_TOKENHUB_BASE_URL = "https://tokenhub.tencentmaas.com/v1"


def _settings(**overrides: object) -> Settings:
    """构造一份带假凭据的配置，避免依赖宿主机 .env 与环境变量。"""
    base: dict[str, object] = {
        "tokenhub_api_key": _FAKE_KEY,
        "tokenhub_base_url": _TOKENHUB_BASE_URL,
        "model_name": "deepseek-v4.1-flash",
        "embedding_model_name": "kinfra-text-embedding-4b",
        "falkordb_database": "campfire_test",
    }
    base.update(overrides)
    # _env_file=None：不读仓库根的 .env；配合上面钉住 base_url，结果与宿主机配置无关。
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]  # pydantic 的 **kwargs 形状，字段值已逐项给定


# ---------------------------------------------------------------------------
# 异常层次
# ---------------------------------------------------------------------------


def test_all_memory_errors_share_one_base() -> None:
    """三个具体异常都继承统一基类，调用方可以一句 except 收口。"""
    for exc_type in (MemoryConfigurationError, MemoryUnavailableError, MemoryDataError):
        assert issubclass(exc_type, MemoryModuleError)


def test_memory_error_does_not_shadow_the_builtin() -> None:
    """基类不得叫 `MemoryError`——那是 Python 内建异常的名字。

    同名会遮蔽内建异常（内建语义是「内存耗尽」），使本模块内任何
    `except MemoryError` 捕捉到错误的对象，是典型的静默错误捕获。
    这条断言把「不遮蔽」钉成可执行事实，而不是模块 docstring 里的承诺。

    Note:
        这里**不写** ``assert not issubclass(MemoryError, MemoryModuleError)``：
        要让内建 ``MemoryError`` 继承一个项目类，只能靠改 ``__bases__`` 或猴补丁，
        那条断言在实践中恒真（2026-09-29 评审指出），属「永远不会失败的检查」。
    """
    assert MemoryModuleError.__name__ != "MemoryError"
    assert not issubclass(MemoryModuleError, MemoryError)
    # 反向：确认内建 MemoryError 确实是内建的那个，而不是被本模块覆盖过。
    assert issubclass(MemoryError, Exception)
    assert MemoryModuleError is not MemoryError


def test_unavailable_error_carries_diagnostic_fields() -> None:
    """图库不可用异常携带操作名与原因类型，便于日志定位。"""
    exc = MemoryUnavailableError("图库不可用", operation="read_timeline", cause="TimeoutError")
    assert exc.operation == "read_timeline"
    assert exc.cause == "TimeoutError"


def test_data_error_carries_diagnostic_fields() -> None:
    """数据非法异常携带操作名与原因，供读路径转译脏数据错误。"""
    exc = MemoryDataError("数据非法", operation="read_timeline", detail="source 取值非法")
    assert exc.operation == "read_timeline"
    assert exc.detail == "source 取值非法"


# ---------------------------------------------------------------------------
# 重排器（不重排的空实现）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ordered_cross_encoder_preserves_input_order() -> None:
    """空重排器原样返回顺序与文本——它只为绕过 OpenAI 默认值而存在。"""
    passages = ["一", "二", "三"]
    ranked = await OrderedCrossEncoder().rank("问题", passages)
    assert [p for p, _ in ranked] == passages


# ---------------------------------------------------------------------------
# 装配
# ---------------------------------------------------------------------------


def test_build_memory_graph_raises_without_api_key() -> None:
    """缺凭据时显式失败——不构造出一个连不上模型的半成品。"""
    settings = _settings(tokenhub_api_key=None)
    with pytest.raises(MemoryConfigurationError, match="TOKENHUB_API_KEY"):
        build_memory_graph(settings)


@pytest.mark.asyncio
async def test_build_memory_graph_wires_all_three_clients_to_tokenhub() -> None:
    """LLM、嵌入与重排三者都被显式接管，不残留 OpenAI 默认值。

    这是「全应用单一模型」纪律在记忆侧的落点：任何一项回落到默认值，
    都会去读 `OPENAI_API_KEY` 并连向 OpenAI。
    """
    graph = build_memory_graph(_settings())
    try:
        assert graph.graphiti.llm_client.config.model == "deepseek-v4.1-flash"
        assert graph.graphiti.llm_client.config.base_url == _TOKENHUB_BASE_URL
        assert graph.graphiti.embedder.config.embedding_model == "kinfra-text-embedding-4b"
        assert graph.graphiti.embedder.config.embedding_dim == EMBEDDING_DIM
        assert isinstance(graph.graphiti.cross_encoder, OrderedCrossEncoder)
        assert not isinstance(graph.graphiti.cross_encoder, OpenAIRerankerClient)
    finally:
        await graph.aclose()


@pytest.mark.asyncio
async def test_small_model_does_not_fall_back_to_the_upstream_default() -> None:
    """**两个模型档位都必须指向 TokenHub 的同一模型。**

    为什么必须有这条（2026-09-29 评审发现的真实缺陷）：只传 ``model`` 时
    ``LLMConfig.small_model`` 保持 ``None``，``LLMClient`` 在 ``ModelSize.small``
    时回落到上游硬编码的 ``gpt-4.1-nano``。Graphiti 有 7 处抽取/消解调用走
    ``ModelSize.small``（``add_episode`` 必经），因此实体抽取会去请求一个
    **TokenHub 上不存在**的模型名——而原测试只断言 ``config.model``，看不出问题。

    断言分两层：配置字段已对齐，且**实际解析结果**不再是上游默认名
    （后者才是有行为意义的那一层）。
    """
    graph = build_memory_graph(_settings())
    try:
        llm = graph.graphiti.llm_client
        assert llm.config.small_model == "deepseek-v4.1-flash"
        resolved = llm._get_model_for_size(ModelSize.small)
        assert resolved != "gpt-4.1-nano", "small 档位回落到上游默认模型，会绕过 TokenHub"
        assert resolved == "deepseek-v4.1-flash"
        # medium 档位同样指向同一模型（一期只有一个模型，不存在「便宜档」）。
        assert llm._get_model_for_size(ModelSize.medium) == "deepseek-v4.1-flash"
    finally:
        await graph.aclose()


@pytest.mark.asyncio
async def test_model_clients_have_bounded_timeout_and_no_sdk_retries() -> None:
    """**两条腿都要有界**：模型客户端的超时与重试都必须显式设过。

    为什么必须有这条（2026-09-29 评审发现的真实缺陷）：只设图库超时时，两个
    openai 客户端取 SDK 默认——实测 ``read=600`` 秒、``max_retries=2``，直接顶掉
    ``RQ-EMG-03`` 的 10 秒首字预算。原测试对超时**零断言**，有界性只活在注释里。

    断言的是**有行为意义的事实**（不是 SDK 默认值、且等于配置值），而不是复述代码。
    ``openai`` 客户端的 ``timeout`` 有两种形态：显式传数值时是 ``float``，
    未传时是 ``Timeout`` 对象（``read`` 默认 600）——两种都要能判。
    """
    settings = _settings()
    graph = build_memory_graph(settings)
    try:
        configured = settings.model_request_timeout_seconds
        for label, client in (
            ("llm", graph.graphiti.llm_client.client),
            ("embedder", graph.graphiti.embedder.client),
        ):
            timeout = client.timeout
            effective = timeout if isinstance(timeout, (int, float)) else timeout.read
            assert effective == configured, f"{label} 客户端超时不是配置值 {configured}"
            assert effective != 600.0, f"{label} 客户端仍是 SDK 默认读超时 600 秒"
            assert client.max_retries == 0, f"{label} 客户端仍开着 SDK 层重试"
    finally:
        await graph.aclose()


@pytest.mark.asyncio
async def test_aclose_releases_the_driver_background_task_and_clients() -> None:
    """``aclose()`` 必须收口**全部**资源，包括驱动的后台索引任务。

    为什么必须有这条（2026-09-29 评审发现的真实缺陷）：``FalkorDriver.__init__``
    会调度一个建索引的后台任务，只关 ``driver.client`` 会让该任务在客户端关闭后
    继续跑、抛 ``ConnectionError`` 且异常无人取回（实测 pytest 打印
    ``Task exception was never retrieved``）。
    """
    graph = build_memory_graph(_settings())
    task = graph.driver._init_task
    await graph.aclose()
    if task is not None:
        assert task.done(), "驱动的后台索引任务未被收口——应走 driver.close() 而非只关 client"
    assert graph.graphiti.llm_client.client.is_closed(), "LLM 客户端未关闭"
    assert graph.graphiti.embedder.client.is_closed(), "嵌入客户端未关闭"
    assert graph.http_client.is_closed, "注入的 http 客户端未关闭"


@pytest.mark.asyncio
async def test_episode_content_is_stored_and_dim_is_pinned() -> None:
    """episode 原文必须落库（时间线回看依赖它），维度固定 2560。"""
    graph = build_memory_graph(_settings())
    try:
        assert graph.graphiti.store_raw_episode_content is True
        assert graph.graphiti.embedder.config.embedding_dim == 2560
        assert graph.graphiti.llm_client.max_tokens == LLM_MAX_TOKENS
    finally:
        await graph.aclose()


@pytest.mark.asyncio
async def test_graph_uses_the_configured_database_not_a_default() -> None:
    """图库名取自配置——回落默认库会把不同用途的数据混进同一个图。"""
    graph = build_memory_graph(_settings(falkordb_database="campfire_test"))
    try:
        assert graph.driver._database == "campfire_test"
    finally:
        await graph.aclose()
