"""单元测试：记忆模块的异常层次与 Graphiti/FalkorDB 装配。

对应 `docs/技术设计/technical-details/通用记忆.md` 第 8 节与
`docs/技术设计/decisions/通用记忆归属为账号.md`。

这里锁的是实测得到的四个装配约束（见 `graph.py` 模块说明）——它们是
「照默认值走就失败」的坑，且失败形态与原因不直观：

1. `cross_encoder` 必须显式传入，否则 `Graphiti` 构造时抛 `OpenAIError`；
2. `llm_client` / `embedder` 必须显式传入，否则回落到读 `OPENAI_API_KEY`
   的 OpenAI 客户端（等于绕过 TokenHub 的单一供应商纪律）；
3. `small_model` 必须一并显式传入，否则抽取路径回落到上游硬编码的
   `gpt-4.1-nano`——同一类「静默回落」的第二个入口；
4. `store_raw_episode_content` 必须为 `True`，否则 episode 原文被清空。

装配测试不连真实图库：只验证构造出的对象带上了我们要的参数。
真实连通性由 `test_memory_graph_integration.py` 承担。
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from collections.abc import Callable

import httpx2
import pytest
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.client import ModelSize
from graphiti_core.llm_client.openai_client import OpenAIClient
from openai import AsyncOpenAI

from campfire.core.config import EMBEDDING_DIM, Settings
from campfire.modules.memory.errors import (
    MemoryConfigurationError,
    MemoryDataError,
    MemoryModuleError,
    MemoryUnavailableError,
)
from campfire.modules.memory.graph import (
    LLM_MAX_TOKENS,
    OrderedCrossEncoder,
    TokenHubEmbedder,
    build_memory_graph,
)

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
    # 下面两个错误码的理由必须写在同一行——质量地板只从行内注释取理由：
    # arg-type 是 `**base` 的 dict 展开静态不收敛，call-arg 是本仓未启用 pydantic 的
    # mypy 插件、其合成签名只含字段而不含 `_env_file`。
    return Settings(_env_file=None, **base)  # type: ignore[arg-type,call-arg]  # **base 展开静态不收敛；_env_file 不在合成签名里


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
        这里不写 `assert not issubclass(MemoryError, MemoryModuleError)`：
        要让内建 `MemoryError` 继承一个项目类，只能靠改 `__bases__` 或猴补丁，
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
        # 收窄到具体客户端：`Graphiti` 把它们声明成基类（`LLMClient` / `EmbedderClient`），
        # 而本用例要断言的正是「装的是 TokenHub 的 OpenAI 系列实现」——这层收窄本身
        # 就是判别性断言（若装配退回基类或别的实现，这里直接失败）。
        llm = graph.graphiti.llm_client
        embedder = graph.graphiti.embedder
        assert isinstance(llm, OpenAIClient), "LLM 客户端不是 OpenAI 系列实现"
        assert isinstance(embedder, OpenAIEmbedder), "嵌入客户端不是 OpenAI 系列实现"
        assert llm.config.model == "deepseek-v4.1-flash"
        assert llm.config.base_url == _TOKENHUB_BASE_URL
        assert embedder.config.embedding_model == "kinfra-text-embedding-4b"
        assert embedder.config.embedding_dim == EMBEDDING_DIM
        assert isinstance(graph.graphiti.cross_encoder, OrderedCrossEncoder)
        assert not isinstance(graph.graphiti.cross_encoder, OpenAIRerankerClient)
    finally:
        await graph.aclose()


@pytest.mark.asyncio
async def test_small_model_does_not_fall_back_to_the_upstream_default() -> None:
    """两个模型档位都必须指向 TokenHub 的同一模型。

    为什么必须有这条（2026-09-29 评审发现的真实缺陷）：只传 `model` 时
    `LLMConfig.small_model` 保持 `None`，`LLMClient` 在 `ModelSize.small`
    时回落到上游硬编码的 `gpt-4.1-nano`。Graphiti 有 7 处抽取/消解调用走
    `ModelSize.small`（`add_episode` 必经），因此实体抽取会去请求一个
    TokenHub 上不存在的模型名——而原测试只断言 `config.model`，看不出问题。

    断言分两层：配置字段已对齐，且实际解析结果不再是上游默认名
    （后者才是有行为意义的那一层）。
    """
    graph = build_memory_graph(_settings())
    try:
        llm = graph.graphiti.llm_client
        # 收窄到具体客户端：`_get_model_for_size` 与 `config` 都声明在
        # `BaseOpenAIClient` / `OpenAIClient` 上，基类 `LLMClient` 看不到它们。
        # 这条收窄同时钉住「装配装的就是 OpenAI 系列实现」。
        assert isinstance(llm, OpenAIClient), "LLM 客户端不是 OpenAI 系列实现"
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
    """两条腿都要有界：模型客户端的超时与重试都必须显式设过。

    为什么必须有这条（2026-09-29 评审发现的真实缺陷）：只设图库超时时，两个
    openai 客户端取 SDK 默认——实测 `read=600` 秒、`max_retries=2`，直接顶掉
    `RQ-EMG-03` 的 10 秒首字预算。原测试对超时零断言，有界性只活在注释里。

    断言的是有行为意义的事实（不是 SDK 默认值、且等于配置值），而不是复述代码。
    `openai` 客户端的 `timeout` 有两种形态：显式传数值时是 `float`，
    未传时是 `Timeout` 对象（`read` 默认 600）——两种都要能判。
    """
    settings = _settings()
    graph = build_memory_graph(settings)
    try:
        configured = settings.model_request_timeout_seconds
        # 收窄到具体客户端：注入的 `client` 只声明在 OpenAI 系列实现上，
        # 基类 `LLMClient` / `EmbedderClient` 不声明它（见 `aclose` 的说明）。
        llm = graph.graphiti.llm_client
        embedder = graph.graphiti.embedder
        assert isinstance(llm, OpenAIClient), "LLM 客户端不是 OpenAI 系列实现"
        assert isinstance(embedder, OpenAIEmbedder), "嵌入客户端不是 OpenAI 系列实现"
        for label, client in (
            ("llm", llm.client),
            ("embedder", embedder.client),
        ):
            timeout = client.timeout
            # 超时不得为空：`build_memory_graph` 显式传入配置值，None 意味着这条腿
            # 取 SDK 默认（实测读超时 600 秒），正是本用例要拦的形态。
            assert timeout is not None, f"{label} 客户端未配置超时，会取 SDK 默认读超时"
            effective = timeout if isinstance(timeout, (int, float)) else timeout.read
            assert effective == configured, f"{label} 客户端超时不是配置值 {configured}"
            assert effective != 600.0, f"{label} 客户端仍是 SDK 默认读超时 600 秒"
            assert client.max_retries == 0, f"{label} 客户端仍开着 SDK 层重试"
    finally:
        await graph.aclose()


@pytest.mark.asyncio
async def test_aclose_releases_the_driver_background_task_and_clients() -> None:
    """`aclose()` 必须收口全部资源，包括驱动的后台索引任务。

    为什么必须有这条（2026-09-29 评审发现的真实缺陷）：`FalkorDriver.__init__`
    会调度一个建索引的后台任务，只关 `driver.client` 会让该任务在客户端关闭后
    继续跑、抛 `ConnectionError` 且异常无人取回（实测 pytest 打印
    `Task exception was never retrieved`）。
    """
    graph = build_memory_graph(_settings())
    task = graph.driver._init_task
    await graph.aclose()
    if task is not None:
        assert task.done(), "驱动的后台索引任务未被收口——应走 driver.close() 而非只关 client"
    llm = graph.graphiti.llm_client
    embedder = graph.graphiti.embedder
    assert isinstance(llm, OpenAIClient), "LLM 客户端不是 OpenAI 系列实现"
    assert isinstance(embedder, OpenAIEmbedder), "嵌入客户端不是 OpenAI 系列实现"
    assert llm.client.is_closed(), "LLM 客户端未关闭"
    assert embedder.client.is_closed(), "嵌入客户端未关闭"
    # 注入的 http 客户端必须存在（`build_memory_graph` 总会造一个）：断言里不能
    # 容忍 None，否则「没造出来」会被静默当成「已关闭」。
    assert graph.http_client is not None, "未注入 http 客户端，本断言失去对象"
    assert graph.http_client.is_closed, "注入的 http 客户端未关闭"


@pytest.mark.asyncio
async def test_episode_content_is_stored_and_dim_is_pinned() -> None:
    """episode 原文必须落库（时间线回看依赖它），维度固定 2560。"""
    graph = build_memory_graph(_settings())
    try:
        embedder = graph.graphiti.embedder
        llm = graph.graphiti.llm_client
        assert isinstance(embedder, OpenAIEmbedder), "嵌入客户端不是 OpenAI 系列实现"
        assert isinstance(llm, OpenAIClient), "LLM 客户端不是 OpenAI 系列实现"
        assert graph.graphiti.store_raw_episode_content is True
        assert embedder.config.embedding_dim == 2560
        assert llm.max_tokens == LLM_MAX_TOKENS
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


# ---------------------------------------------------------------------------
# 嵌入请求体：`encoding_format` 必须是 float（P1 缺陷的回归闸门）
# ---------------------------------------------------------------------------


def _recording_transport(sink: list[dict[str, object]], dim: int = 3000) -> httpx2.MockTransport:
    """造一个记录请求体、并按输入条数回向量的假传输。

    向量故意长于 `EMBEDDING_DIM`（3000 > 2560）：这样「按 config 截断」这一步
    也被覆盖到——若实现漏了截断，`len(...) == 2560` 的断言会失败。
    必须**按输入条数**回：`create_batch` 的语义是「一批进、一批出」，
    只回一条会让「批量」这一步的断言失去对象（实测踩过：误报成实现少了一条）。
    """

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        sink.append(body)
        raw_input = body["input"]
        count = len(raw_input) if isinstance(raw_input, list) else 1
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "model": "kinfra-text-embedding-4b",
                "data": [{"object": "embedding", "index": index, "embedding": [0.25] * dim} for index in range(count)],
            },
        )

    return httpx2.MockTransport(handler)


@pytest.mark.asyncio
async def test_embedder_body_carries_float_encoding_format() -> None:
    """真实装配出的 embedder，其**请求体**必须带 `encoding_format="float"`。

    为什么不能只断言构造代码（2026-10-02 实测确认的产品缺陷就长这样）：
    上游 `graphiti_core` 的 `OpenAIEmbedder.create()` / `create_batch()` 只传
    `input` + `model`，而 OpenAI SDK 在请求体层面补 `encoding_format="base64"`
    （`openai/resources/embeddings.py:110-111`），TokenHub 只接受 `float` ⇒
    真实端点稳定 `400001`，`add_episode` 必失败、记忆写入路径整体不可用。
    「代码里看着传了、body 里其实没有」正是本项目吃过的亏，因此本用例断言
    **实际发出的 JSON body**，而不是构造参数。

    撤掉修复（把 `build_memory_graph` 里的 `TokenHubEmbedder` 换回
    `OpenAIEmbedder`）⇒ 本用例必然红：body 会变回 `"base64"`（实测）。
    """
    graph = build_memory_graph(_settings())
    bodies: list[dict[str, object]] = []
    try:
        # 换掉最底层的传输：`httpx2` 没有公开的 transport 读写口，而这里要断言的是
        # 「请求真的长这样」，只能从传输层截获。测试里访问私有属性在本仓已有先例
        # （`graph.driver._init_task` / `graph.driver._database`）。
        assert graph.http_client is not None, "未注入 http 客户端，本断言失去对象"
        graph.http_client._transport = _recording_transport(bodies)  # type: ignore[attr-defined]  # httpx2 无公开 transport 读写口

        embedder = graph.graphiti.embedder
        assert isinstance(embedder, TokenHubEmbedder), "装配未使用 TokenHubEmbedder，等于回到 400001"

        vector = await embedder.create("一条记忆片段")
        assert len(bodies) == 1, "未捕获到请求体，本断言失去对象"
        assert bodies[0]["encoding_format"] == "float", (
            f"单条嵌入的请求体 encoding_format={bodies[0].get('encoding_format')!r}，"
            "必须是 'float'（SDK 默认注入 base64，TokenHub 会拒 400001）"
        )
        assert len(vector) == EMBEDDING_DIM == 2560, "维度契约被破坏"

        batch = await embedder.create_batch(["第一条", "第二条"])
        assert len(bodies) == 2, "未捕获到批量请求体"
        assert bodies[1]["encoding_format"] == "float", (
            f"批量嵌入的请求体 encoding_format={bodies[1].get('encoding_format')!r}，必须是 'float'"
        )
        assert [len(v) for v in batch] == [EMBEDDING_DIM, EMBEDDING_DIM], "批量维度契约被破坏"
    finally:
        await graph.aclose()


@pytest.mark.asyncio
async def test_tokenhub_embedder_differs_from_upstream_only_in_encoding_format() -> None:
    """与上游逐字对照：唯一差异是 `encoding_format`，其余行为必须一致。

    为什么要有这条对照（防止「修一个坑、挖另一个坑」）：本类是对上游两个方法的重写，
    若上游改了切片、去空格或多条返回顺序，我们的副本会静默偏离。这里把两个实现
    挂在同一个假传输上跑同一批输入，断言：

    1. **输出完全相同**（向量与截断行为未被改动）；
    2. **上游的 body 是 base64、我们的是 float**——即差异被限定在该字段上，
       同时证明「上游确实会发 base64」这一缺陷前提仍然成立。

    第 2 条同时是一条会随上游修复而失败的哨兵：若将来 `graphiti_core` 自己补了
    `encoding_format`，上游 body 会变成 float，用例会红——那时应当删掉本类而不是
    继续叠一层。
    """
    bodies: list[dict[str, object]] = []
    http_client = httpx2.AsyncClient(transport=_recording_transport(bodies))
    client = AsyncOpenAI(
        api_key=_FAKE_KEY,
        base_url=_TOKENHUB_BASE_URL,
        http_client=http_client,
        max_retries=0,
    )
    config = OpenAIEmbedderConfig(
        embedding_dim=EMBEDDING_DIM,
        embedding_model="kinfra-text-embedding-4b",
        api_key=_FAKE_KEY,
        base_url=_TOKENHUB_BASE_URL,
    )
    upstream = OpenAIEmbedder(config=config, client=client)
    ours = TokenHubEmbedder(config=config, client=client)
    try:
        upstream_batch = await upstream.create_batch(["甲", "乙"])
        ours_batch = await ours.create_batch(["甲", "乙"])
        upstream_one = await upstream.create("丙")
        ours_one = await ours.create("丙")

        assert upstream_batch == ours_batch, "批量输出与上游不一致——本类引入了额外行为差异"
        assert upstream_one == ours_one, "单条输出与上游不一致——本类引入了额外行为差异"
        assert [len(v) for v in ours_batch] == [EMBEDDING_DIM, EMBEDDING_DIM]

        # 差异必须**只在** encoding_format 这一个键上。
        for upstream_body, ours_body in ((bodies[0], bodies[1]), (bodies[2], bodies[3])):
            assert upstream_body["encoding_format"] == "base64", (
                "上游不再注入 base64——缺陷前提变了，应重新评估是否还需要本类"
            )
            assert ours_body["encoding_format"] == "float"
            assert {k: v for k, v in ours_body.items() if k != "encoding_format"} == {
                k: v for k, v in upstream_body.items() if k != "encoding_format"
            }, "除 encoding_format 外还有其它差异"
    finally:
        await client.close()
        await http_client.aclose()


# ---------------------------------------------------------------------------
# 覆盖完备性守卫：上游若新增「发请求的方法」，子类必须同步覆盖（P2-R1）
# ---------------------------------------------------------------------------


def _call_chain_paths(tree: ast.AST) -> list[str]:
    """列出 AST 子树里全部属性调用链，形如 `self.client.embeddings.create`。

    只认「整条链的根是一个 `Name`」的调用（`self`、局部变量都算）——链根是其它
    形态（下标、再调用结果）时丢弃，避免把 `x[0].create` 一类误当嵌入请求。
    """
    paths: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        segments: list[str] = []
        cursor: ast.expr = node.func
        while isinstance(cursor, ast.Attribute):
            segments.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name):
            segments.append(cursor.id)
            paths.append(".".join(reversed(segments)))
    return paths


def _embedding_request_call(function: Callable[..., object]) -> str | None:
    """函数体是否**直接**调用嵌入端点；是则返回那条调用链，否则 `None`。

    判据（本守卫的全部定义在此，不写死方法名）：
    **函数体里存在一条调用链，其最后一段是 `create`、且 `create` 之前的链段里含
    `embeddings`**（即 `...embeddings.create(...)`）。

    为什么这样界定（正反两向都给出理由）：

    - **正向（在）**：`create` / `create_batch` 的方法体是
      `await self.client.embeddings.create(...)` —— 它们是**唯一**直接到达
      `openai` SDK embeddings 资源、因而由 SDK 决定请求体的方法。SDK 注入
      `encoding_format="base64"` 就发生在这一层，所以「绕过子类覆盖」的风险
      恰好只属于这一类方法。
    - **反向（不在）**：`__init__` 落在外面，因为它构造的是 `AsyncOpenAI(...)`，
      调用链是 `OpenAIEmbedderConfig` / `AsyncOpenAI`，不含 `embeddings.create`
      （实测）。**关键的是**：上游若新增 `async def foo(self): return await
      self.create(x)` 这种**委派**方法，它同样落在外面——这是有意的，因为
      `self.create` 在子类实例上会**动态派发到我方覆盖**，不存在静默复发。
      （同理，基类 `EmbedderClient` 上的非嵌入成员也不会被算进来。）
    - **不比「方法名黑名单」松，也不比它紧**：名字完全由上游决定，判据只看
      方法体到达了哪个资源。

    已知边界（诚实声明，见测试报告「证据边界」）：本判据只认**方法体内直接出现**
    的调用链——即链尾是 `create`、且链段里含 `embeddings`。三种上游重构会削弱它：

    1. 上游把**全部**嵌入调用改成间接形态（模块级辅助函数，或先取别名
       `emb = self.client.embeddings` 再 `emb.create(...)`）⇒ 自省结果为空集
       ⇒ 用例里的「检测器自检」断言失败 ⇒ **红**（响亮失效，不是静默通过）。
    2. 上游**保留**现有两个方法不动、只**新增**一个走间接形态的发请求方法
       ⇒ 自省看不到那个新方法 ⇒ **本条漏报**。
    3. 上游把 embeddings 资源改名（不再含 `embeddings` 字样）⇒ 两条现有方法都
       识别不到 ⇒ 自省为空集 ⇒ 按第 1 条变红，由人工裁决。

    第 2 条是真实残余，本包不宣称覆盖：要在不执行上游代码的前提下判定「某个方法
    是否发请求」只能靠静态形态，而静态形态无法穷尽间接调用。**它不构成「永远不会
    失败的检查」**：第 1、3 条下本守卫是红的，且真上游上的两个方法一旦被改动
    也会经由 `test_tokenhub_embedder_differs_from_upstream_only_in_encoding_format`
    的逐值对照暴露。
    """
    source = textwrap.dedent(inspect.getsource(function))
    for path in _call_chain_paths(ast.parse(source)):
        segments = path.split(".")
        if segments[-1] == "create" and "embeddings" in segments[:-1]:
            return path
    return None


def _as_plain_function(member: object) -> Callable[..., object] | None:
    """取出可被 `inspect.getsource` 读取的**真函数**；取不到就返回 `None`。

    为什么不能直接用 `inspect.isfunction`（实测踩到）：`vars(cls)` 里
    `@staticmethod` / `@classmethod` 存的是 **descriptor 包装对象**
    （实测 `inspect.isfunction` 对它们均为 `False`），直接过滤会把这类方法整个
    漏掉。漏掉的方向不对称，必须分别纠正：

    - 在**上游**侧漏掉 ⇒ 新方法不被识别 ⇒ 守卫**假绿**（这正是本包要防的失效）；
    - 在**我方**侧漏掉 ⇒ 已覆盖被误判为未覆盖 ⇒ 守卫**假红**。

    因此这里显式拆开包装（`.__func__`），只接受「拆开后是函数」的成员；
    其它形态（`property`、普通实例属性、`functools.partial`）一律返回 `None`
    ——它们不是「方法体里有调用链」这种对象，`_embedding_request_call` 也读不了。
    """
    unwrapped = member.__func__ if isinstance(member, (staticmethod, classmethod)) else member
    if inspect.isfunction(unwrapped):
        return unwrapped
    return None


def _effective_methods(cls: type) -> dict[str, Callable[..., object]]:
    """该类实例实际可见的全部纯 Python 函数（含继承），按 MRO 从基到派生累计。

    为什么要走 MRO 而不是 `vars(cls)`：上游的发请求方法可能定义在基类
    （实测 0.30.2 的 `create` 是抽象方法、`create_batch` 也定义在
    `EmbedderClient` 上），只查 `vars(OpenAIEmbedder)` 会漏掉它们。
    """
    effective: dict[str, Callable[..., object]] = {}
    for klass in reversed(cls.__mro__):
        for name, member in vars(klass).items():
            function = _as_plain_function(member)
            if function is not None:
                effective[name] = function
    return effective


def _upstream_request_methods(cls: type) -> dict[str, str]:
    """自省得到「直接发嵌入请求的方法」→「它用的那条调用链」。"""
    return {
        name: chain
        for name, function in _effective_methods(cls).items()
        if (chain := _embedding_request_call(function)) is not None
    }


def _missing_request_method_coverage(upstream: type, ours: type) -> dict[str, str]:
    """上游发嵌入请求、而我方子类**没有自己定义**的方法（继承不算覆盖）。

    用 `vars(ours)` 而不是 `hasattr`：`hasattr` 会把「继承自上游的实现」
    也算成已覆盖——那正是本守卫要拦的形态（继承来的实现带 `base64`）。
    """
    ours_own = {name for name, member in vars(ours).items() if _as_plain_function(member) is not None}
    return {name: chain for name, chain in _upstream_request_methods(upstream).items() if name not in ours_own}


def test_tokenhub_embedder_overrides_every_upstream_request_method() -> None:
    """`TokenHubEmbedder` 必须覆盖上游**全部**发嵌入请求的方法。

    为什么必须有这条（2026-10-02 复查提出，编排器裁定「做」）：本类是对上游方法
    的**副本**——它的正确性依赖「集合恰好相等」。上游若新增第三个发请求的方法
    （例如 `create_batch_iter`），那个方法会**绕回上游实现**（只传 `input` + `model`
    ⇒ SDK 注入 `encoding_format="base64"`）⇒ **本包修掉的 400001 缺陷静默复发**，
    而当时 14 条用例**没有一条枚举该集合**（它们只调用 `create` / `create_batch`）
    ⇒ 上游加方法后不会变红。

    判据**完全来自上游自省**（见 `_embedding_request_call`）：**不写死方法名**。
    写死 `{"create", "create_batch"}` 就等于没做——上游新增方法时那种断言不会红，
    而「上游新增方法时变红」正是本条唯一的存在理由。

    为什么不会误红（真上游上必须绿）：判据要求「方法体里出现
    `...embeddings.create(...)` 调用链」。实测上游 0.30.2 沿 MRO 合计只有 3 个
    函数（`__init__` / `create` / `create_batch`），其中只有后两个命中
    （`__init__` 的调用链是 `OpenAIEmbedderConfig` / `AsyncOpenAI`，不含
    `embeddings.create`），我方两个都自定义 ⇒ 真上游上缺口为空，用例绿。
    反向风险也已实测排除：委派方法（`return await self.create(...)`）、
    `client.chat.completions.create`、`client.files.create` 三类都不被判为
    发请求方法（见测试报告第 2 节）。**「能红」的证明见测试报告第 3 节**
    （在 `tmp/` 副本里给上游动态加一个发请求方法 ⇒ 本用例红）。

    下面的「检测器自检」不是装饰：若上游把调用搬进模块级辅助函数，自省结果为
    空集，本条会以「判据失效」失败，而不是静默变成一条永远通过的检查。

    Note:
        **本守卫只管「覆盖了没有」，不管「覆盖得对不对」。** 实测确认这一残余：
        上游新增 + 我方照抄上游地覆盖（漏传 `encoding_format="float"`）时，本守卫
        **绿**，而请求体确实是 `base64`。那种形态由
        `test_embedder_body_carries_float_encoding_format` 按 body 断言拦下
        ——但它只覆盖 `create` / `create_batch` 两个方法。**两半缺一不可**：
        本条保证「新方法不会被漏掉」，body 断言保证「已覆盖的方法真的发了 float」。
    """
    upstream_methods = _upstream_request_methods(OpenAIEmbedder)
    assert upstream_methods, (
        "未在上游 OpenAIEmbedder 上识别出任何发嵌入请求的方法——判据已失效"
        "（上游可能改成间接调用），本守卫已失去对象，必须人工复查而不是当它通过"
    )

    missing = _missing_request_method_coverage(OpenAIEmbedder, TokenHubEmbedder)
    assert not missing, (
        f"上游这些发嵌入请求的方法未被 TokenHubEmbedder 覆盖：{sorted(missing)}"
        f"（对应调用链 {missing}）。未覆盖 = 沿用上游实现 = 请求体回到 "
        "encoding_format='base64' ⇒ TokenHub 400001 ⇒ 记忆写入路径整体不可用。"
        "请在 TokenHubEmbedder 里按上游签名补上覆盖（显式传 encoding_format='float'）。"
    )
