"""单元测试：记忆模块的异常层次与 Graphiti/FalkorDB 装配。

对应 ``docs/技术设计/technical-details/通用记忆.md`` 第 8 节与
``docs/技术设计/decisions/通用记忆归属为账号.md``。

这里锁的是**实测得到的三个装配约束**（见 ``graph.py`` 模块说明）——它们是
「照默认值走就失败」的坑，且失败形态与原因不直观：

1. ``cross_encoder`` 必须显式传入，否则 ``Graphiti`` 构造时抛 ``OpenAIError``；
2. ``llm_client`` / ``embedder`` 必须显式传入，否则回落到读 ``OPENAI_API_KEY``
   的 OpenAI 客户端（等于绕过 TokenHub 的单一供应商纪律）；
3. ``store_raw_episode_content`` 必须为 ``True``，否则 episode 原文被清空。

装配测试**不连真实图库**：只验证构造出的对象带上了我们要的参数。
真实连通性由 ``test_memory_graph_integration.py`` 承担。
"""

from __future__ import annotations

import pytest
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

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


def _settings(**overrides: object) -> Settings:
    """构造一份带假凭据的配置，避免依赖宿主机 .env。"""
    base: dict[str, object] = {
        "tokenhub_api_key": _FAKE_KEY,
        "model_name": "deepseek-v4.1-flash",
        "embedding_model_name": "kinfra-text-embedding-4b",
        "falkordb_database": "campfire_test",
    }
    base.update(overrides)
    # _env_file=None：不读仓库根的 .env，让用例结果与宿主机配置无关。
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


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
    """
    assert MemoryModuleError.__name__ != "MemoryError"
    assert not issubclass(MemoryModuleError, MemoryError)
    assert not issubclass(MemoryError, MemoryModuleError)


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
        assert graph.graphiti.llm_client.config.base_url == "https://tokenhub.tencentmaas.com/v1"
        assert graph.graphiti.embedder.config.embedding_model == "kinfra-text-embedding-4b"
        assert graph.graphiti.embedder.config.embedding_dim == EMBEDDING_DIM
        assert isinstance(graph.graphiti.cross_encoder, OrderedCrossEncoder)
        assert not isinstance(graph.graphiti.cross_encoder, OpenAIRerankerClient)
    finally:
        await graph.aclose()


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
