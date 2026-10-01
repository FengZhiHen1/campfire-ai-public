"""端到端：走真实生产装配链跑一次咨询运行。

本文件的存在理由（这是它区别于其它测试的地方）：

现有测试各覆盖一段，但没有一条把「装配 → 运行 → 落库 → 读回」串起来跑通：

- `test_consult_endpoints_integration.py` 用 `ScriptedRunner` 替身，**不经过真实
  `AgentRunner`**，因此「生产组合根能不能装出来」它答不了；
- `test_agent_runtime.py` 用真 `AgentRunner`，但工具池是自造的、skill 根是空目录、
  引用索引是内存替身，因此「真工具池 / 真 skill / 真引用索引」这条链它答不了；
- 生产装配此前**根本不存在**（`assembly.set_runner_factory` 只有测试调用点），所以这条链
  在 2026-10-01 之前没有任何测试覆盖过——这正是「部署出来核心端点稳定 503」能潜伏至今的原因。

本文件刻意只在**与外部世界的边界**上替换：模型供应商换成脚本化 SSE 响应。
其余全部是真的——真 `ModelGateway`（只注入 `MockTransport`）、真 `ToolPool`（10 个产品工具
+ 3 个保留名工具）、真 `SkillRegistry`（`apps/api/skills` 下 4 个 skill）、
真 `SqlCitationIndex`（写进 `campfire_citation` 表）、真 SDK 会话（写进 `agent_sessions` /
`agent_messages`）。

替换模型是必要而非偷懒：真实 TokenHub 调用会消耗额度、结果不确定、且实测会限流
（`RateLimitError`），把它纳入测试会让用例随外部服务抖动。但**接线本身必须是真的**——
本文件断言的就是接线。

标记 `integration`：需要 PostgreSQL（引用索引与会话表都在库里）。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
import pytest_asyncio
from sqlalchemy import delete, text

from campfire.agent.model import ModelGateway
from campfire.agent.runtime import RunEvent, RunRequest
from campfire.core.config import Settings, get_settings
from campfire.core.db import get_engine, session_scope
from campfire.core.db.citations import Citation
from campfire.surfaces.consult import composition
from campfire.surfaces.consult.assembly import (
    CONSULT_INSTRUCTIONS,
    clear_skill_registries,
    get_skill_registry,
)
from campfire.surfaces.consult.citations import SqlCitationIndex

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_MODEL_NAME = "deepseek-v4.1-flash"
_BASE_URL = "https://tokenhub.test/v1"

#: 10 个产品工具的名字（真源是 `surfaces/consult/registry.build_product_tools`）。
_PRODUCT_TOOLS = frozenset(
    {
        "create_support_object",
        "emit_emergency_action_card",
        "finish_onboarding",
        "propose_profile_item",
        "read_memory",
        "read_profile_items",
        "read_profile_summary",
        "search_cases",
        "search_knowledge",
        "write_memory",
    }
)

#: 3 个基座保留名工具。
_RESERVED_TOOLS = frozenset({"ask_user", "skill", "read_skill_resource"})


class ScriptedChat:
    """脚本化模型响应：按顺序回放预先录好的 SSE 正文。

    只实现 `AsyncHTTPTransport` 需要的 `handle_async_request`，因此它是一次「假供应商」
    而不是一个假模型抽象——被测的 `OpenAIChatCompletionsModel`、`AgentRunner`、
    工具派发与事件翻译全部照常执行。
    """

    def __init__(self, *bodies: bytes) -> None:
        self._bodies = list(bodies)
        self.requests: list[dict[str, Any]] = []

    def queue(self, *bodies: bytes) -> None:
        """追加待回放的响应（可在夹具之外按用例需要补脚本）。"""
        self._bodies.extend(bodies)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        body = self._bodies.pop(0) if self._bodies else _text_reply("（脚本已用尽）")
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    @property
    def messages_seen(self) -> list[list[dict[str, Any]]]:
        """每次请求里模型看到的 messages。"""
        return [list(request.get("messages", [])) for request in self.requests]


def _chunk(delta: dict[str, Any], finish_reason: str | None = None) -> str:
    payload = {
        "id": "chatcmpl-e2e",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": _MODEL_NAME,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n"


def _sse(*chunks: str, usage: dict[str, int] | None = None) -> bytes:
    body = "".join(chunks)
    if usage is not None:
        tail: dict[str, Any] = {
            "id": "chatcmpl-e2e",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": _MODEL_NAME,
            "choices": [],
            "usage": usage,
        }
        body += f"data: {json.dumps(tail)}\n\n"
    return (body + "data: [DONE]\n\n").encode()


def _text_reply(text_: str, *, usage: dict[str, int] | None = None) -> bytes:
    """一段普通文本回复的 SSE 脚本。"""
    return _sse(
        _chunk({"role": "assistant", "content": ""}),
        _chunk({"content": text_}),
        _chunk({}, "stop"),
        usage=usage,
    )


def _tool_call_reply(*, call_id: str, name: str, arguments: dict[str, Any]) -> bytes:
    """一次工具调用的 SSE 脚本（OpenAI 流式工具调用的形状）。"""
    return _sse(
        _chunk({"role": "assistant", "content": ""}),
        _chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
                    }
                ]
            }
        ),
        _chunk({}, "tool_calls"),
    )


async def _never_called(_request: httpx2.Request) -> httpx2.Response:  # pragma: no cover —— 只用于构造
    raise AssertionError("本用例不应发起模型请求")


def _settings_for_assembly() -> Settings:
    """装配用的配置：缺失的凭据补一个假值。

    为什么需要它（2026-10-01 实测）：`ModelGateway` 构造期要求 `TOKENHUB_API_KEY`
    （未配置即抛 `ModelConfigurationError`），而 **GitHub CI 里没有 `.env`**，因此
    真实配置的该字段是 `None`。本文件的模型传输是 `MockTransport`，不会发出任何真实
    请求，所以假凭据在这里不产生外部影响——它的作用只是让「装配」这一段能在无凭据的
    CI 上跑起来（否则本文件在 CI 里必失败，而它要验的接线恰恰与凭据无关）。

    `supertokens_api_key` 同理：`composition.install` 不碰它，但 `Settings` 的构造
    不应因它而受影响——这里显式给出，避免测试依赖宿主机的 `.env`。
    """
    base = get_settings().model_dump()
    base["tokenhub_api_key"] = "e2e-test-key-not-a-secret"
    base.setdefault("supertokens_api_key", "e2e-test-key-not-a-secret")
    return Settings(**base)  # type: ignore[arg-type]  # 由 model_dump 往返构造，键值形状与字段一致


def _scripted_gateway(chat: ScriptedChat) -> ModelGateway:
    """真 `ModelGateway`，只把 HTTP 传输换成 `MockTransport`。

    `ModelGateway` 内部用 `AsyncOpenAI`（其底层是 httpx2），因此 `MockTransport` 替换的
    正是「与外部世界的那一段」——我们自己的装配代码全部照常执行。
    """
    return ModelGateway(
        _settings_for_assembly(),
        http_transport=httpx2.MockTransport(chat.handle_async_request),
    )


def _install_production_runner(gateway: ModelGateway) -> None:
    """调用生产的 `composition.install` 装配并注入（只把网关换成脚本化的那个）。

    刻意调 `install` 而不在测试里自己拼 `AgentRunner(...)`：后者会让测试通过而生产路径
    仍旧缺失——那正是本次修的缺陷形状（`set_runner_factory` 曾只有测试调用点）。
    `install` 的 `gateway=` 参数就是为这条留的缝。
    """
    composition.install(_settings_for_assembly(), gateway=gateway)


def _current_runner(settings: Settings) -> Any:
    """从注入点取运行器——与端点 `routes.py` 取用的是同一个口。"""
    from campfire.surfaces.consult import assembly

    return assembly.get_runner(settings)


async def _collect(runner: Any, request: RunRequest) -> list[RunEvent]:
    return [event async for event in runner.run(request)]


def _is_json(payload: str) -> bool:
    """这段存储文本是不是 JSON 对象（SDK 的消息行是，但保守处理未知形状）。"""
    stripped = payload.lstrip()
    return stripped.startswith("{") and stripped.endswith("}")


def _content_text(payload: str) -> str:
    """从一条存储的消息里取出可读文本。

    形状有两种，都要处理：`content` 是字符串（普通消息），或是一个部件列表
    （多模态消息，实测出现）。判形状而不是假设——直接对 `content` 做字符串拼接会在
    列表形状上抛 `TypeError`，那会让「消息确实落库了」被误报成失败。
    """
    if not _is_json(payload):
        return payload
    content = json.loads(payload).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _database_is_reachable_sync() -> bool:
    """本机 PostgreSQL 是否可达（同步探测，供 session 级 guard 用）。

    为什么需要它：本文件的全部用例都要真实数据库（引用索引与会话表）。没有数据库时
    ——例如 GitHub CI 的当前配置——应当**明确跳过**，而不是让 fixture 在收集后抛
    `RuntimeError` 把整批用例变成 ERROR。ERROR 与 skip 的区别是判读者要的：前者看起来
    像「代码坏了」，后者是「环境不满足」，而 CI 的输出会被很多人看到。

    用同步 socket 探测而不是 async：guard 要跑在 fixture 建立之前，用 asyncio 会与
    pytest-asyncio 的循环作用域纠缠。这里只判「端口通不通」，不建库连接。
    """
    import socket
    from urllib.parse import urlparse

    url = get_settings().database_url
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def _require_database() -> None:
    """数据库不可达时跳过本文件的用例。

    为什么用 autouse fixture 而不是别的写法：

    - `@pytest.mark.skipif` 的条件在**模块导入期**求值，而本仓的
      `conftest.pytest_configure` 会把 `localhost` 归一成 `127.0.0.1` 并清
      `get_settings` 缓存——导入期读到的是归一之前的配置。
    - 在本文件里定义 `pytest_collection_modifyitems` **不会生效**（实测）：
      pytest 只从 conftest 与插件收集钩子，测试模块里的同名函数不是钩子。
      这正是我第一版尝试失败的原因（5 条用例仍是 ERROR/FAILED，没有 skip）。

    用 fixture 则天然在导入之后、用例之前执行，时机正确且不依赖钩子机制。

    `autouse=True` 覆盖本文件全部用例——它们都要真实数据库（引用索引与会话表）。
    跳过而不是失败，是因为「没有数据库」是环境不满足，而不是代码坏了；把前者报成
    ERROR 会让 CI 输出看起来像缺陷。
    """
    if not _database_is_reachable_sync():
        pytest.skip("PostgreSQL 不可达——本文件需要真实数据库（docker compose up -d postgres）")


async def _sessions_tables_exist() -> bool:
    """SDK 的两张会话表是否已由迁移建出（未建则无法验证落库）。"""
    try:
        async with session_scope(get_settings()) as session:
            await session.execute(text("SELECT 1 FROM agent_sessions LIMIT 1"))
    except Exception:
        return False
    return True


@pytest_asyncio.fixture
async def scripted_gateway() -> AsyncIterator[tuple[ModelGateway, ScriptedChat]]:
    """真网关 + 可排脚本的假供应商。"""
    chat = ScriptedChat()
    gateway = _scripted_gateway(chat)
    try:
        yield gateway, chat
    finally:
        await gateway.aclose()


@pytest_asyncio.fixture
async def clean_assembly() -> AsyncIterator[None]:
    """隔离注入点与技能缓存（注入点是模块级全局，不清会互相看到对方的运行器）。"""
    composition.reset()
    clear_skill_registries()
    try:
        yield
    finally:
        composition.reset()
        clear_skill_registries()


# ---------------------------------------------------------------------------
# 装配链：生产组合根装出的运行器真的完整
# ---------------------------------------------------------------------------


async def test_production_composition_builds_a_complete_runner(clean_assembly: None) -> None:
    """生产组合根装出的 `AgentRunner` 具备完整能力（真工具池 + 真 skill + 真引用索引）。

    这是本文件最核心的一条：它断言的不是某个函数返回值，而是「部署出来的东西能不能跑」。

    判别性：把 `build_tool_pool` 里的 `pool.register_base(build_skill_tool(skills))` 去掉，
    `AgentRunner.__init__` 直接抛 `RuntimeAssemblyError`（存在 autoload skill 时必须注册
    激活工具），本用例失败。
    """
    settings = get_settings()
    skills = get_skill_registry(settings)
    pool = composition.build_tool_pool(skills)

    assert _PRODUCT_TOOLS <= set(pool.names()), f"产品工具缺失：{_PRODUCT_TOOLS - set(pool.names())}"
    assert _RESERVED_TOOLS <= set(pool.names()), f"保留名工具缺失：{_RESERVED_TOOLS - set(pool.names())}"
    assert set(pool.names()) == _PRODUCT_TOOLS | _RESERVED_TOOLS, (
        f"池里有意外工具：{set(pool.names()) - _PRODUCT_TOOLS - _RESERVED_TOOLS}"
    )

    # 真 skill（内容产物在 apps/api/skills）
    assert set(skills.names()) == {
        "daily-consulting",
        "emergency-consulting",
        "onboarding",
        "profile-curation",
    }

    # 端到端装配：这一步会跑 AgentRunner.__init__ 的两条装配期校验
    # （缺 skill 激活工具、skill 的 allowed-tools 指向未注册工具，都在这里抛）
    gateway = ModelGateway(settings, http_transport=httpx2.MockTransport(_never_called))
    try:
        engine = get_engine(settings)
        runner = composition.build_runner_factory(engine=engine, gateway=gateway)(settings)
        assert type(runner).__name__ == "AgentRunner"
    finally:
        await gateway.aclose()


async def test_install_injects_the_runner_into_the_assembly_point(
    clean_assembly: None,
    scripted_gateway: tuple[ModelGateway, ScriptedChat],
) -> None:
    """`composition.install` 真的把运行器注入了 `assembly` 的注入点。

    这条是「发消息端点会不会回 503」的最小判据：503 的唯一成因是 `ConsultAssemblyError`
    （注入点为空）。端点自身行为已由 `test_consult_endpoints_integration.py` 覆盖，
    这里只钉住装配那一段。

    判别性：不调 `install`（即修复前的生产状态），`get_runner` 抛 `ConsultAssemblyError`，
    本用例失败。
    """
    gateway, _ = scripted_gateway
    _install_production_runner(gateway)

    from campfire.surfaces.consult import assembly

    assert assembly.runner_is_wired() is True
    assert _current_runner(get_settings()) is not None


# ---------------------------------------------------------------------------
# 一次完整运行：注入 → 模型回复 → 落库
# ---------------------------------------------------------------------------


async def test_one_full_run_streams_text_and_persists_the_session(
    clean_assembly: None,
    scripted_gateway: tuple[ModelGateway, ScriptedChat],
) -> None:
    """一次完整运行：真装配、脚本化模型、真会话落库。

    覆盖从 `AgentRunner.run` 进入、经真实注入渲染与真实 SDK 会话读写、
    到最后消息真的落进 `agent_sessions`/`agent_messages` 的整条链。

    判别性：把 `build_runner_factory` 里的 `sessions=functools.partial(...)` 换成
    内存替身，第 3 步的落库断言失败。
    """
    if not await _sessions_tables_exist():
        pytest.skip("SDK 会话表不存在——先跑 uv run alembic upgrade head")

    gateway, chat = scripted_gateway
    chat.queue(_text_reply("这是端到端测试的回复。"))
    _install_production_runner(gateway)

    session_id = f"e2e-{uuid.uuid4().hex}"
    request = RunRequest(
        session_id=session_id,
        surface="consult",
        instructions=CONSULT_INSTRUCTIONS,
        user_input="你好",
        default_active_tools=("read_profile_summary",),
    )

    events = await _collect(_current_runner(get_settings()), request)

    # 1. 模型真的被调用过，且事件流以结束事件收尾
    assert chat.requests, "模型必须被调用一次"
    kinds = [type(event).__name__ for event in events]
    assert "RunStartedEvent" in kinds
    assert kinds[-1] == "RunFinishedEvent", (
        f"运行未正常收尾（{kinds[-1]}）：{[e for e in events if type(e).__name__ == 'RunFailedEvent']}"
    )

    # 2. 文本回复真的流出来了
    text_out = "".join(str(getattr(event, "delta", "")) for event in events if type(event).__name__ == "TextDeltaEvent")
    assert "端到端测试的回复" in text_out, f"未见预期文本，实际={text_out!r}"

    # 3. 会话真的落库了（SDK 的两张表，经由生产装配注入的会话工厂）
    async with session_scope(get_settings()) as session:
        message_rows = (
            await session.execute(
                text("SELECT COUNT(*) FROM agent_messages WHERE session_id = :sid"), {"sid": session_id}
            )
        ).scalar_one()
        session_rows = (
            await session.execute(
                text("SELECT COUNT(*) FROM agent_sessions WHERE session_id = :sid"), {"sid": session_id}
            )
        ).scalar_one()
        payloads = [
            str(row)
            for row in (
                await session.execute(
                    text("SELECT message_data FROM agent_messages WHERE session_id = :sid"),
                    {"sid": session_id},
                )
            ).scalars()
        ]
    assert session_rows >= 1, "会话行未落库"
    assert message_rows >= 1, "消息行未落库"

    # 4. 使用者输入与助手回复都在历史里（注入项与模型回复都是消息，不是旁路）
    #
    # 解码后再比对：SDK 把消息存成 JSON 文本，而 `json.dumps` 默认把非 ASCII 转义
    # （实测库里是 `\u4f60\u597d`），因此直接做子串匹配会假失败。
    decoded = "\n".join(_content_text(payload) for payload in payloads)
    assert "你好" in decoded, f"使用者输入未落库：{decoded[:400]}"
    assert "端到端测试的回复" in decoded, f"助手回复未落库：{decoded[:400]}"


async def test_citation_index_roundtrip_against_the_real_table() -> None:
    """引用索引端口：写入后按运行读回，字段逐项一致，且重复写入幂等。

    这里用生产实现 `SqlCitationIndex`（不是替身），因此它同时是「端口实现可用」与
    「表结构与实现一致」的判据——此前全仓只有协议与测试替身，没有任何持久化实现。

    判别性：把 `list_for_run` 的 `where(Citation.run_id == run_id)` 去掉，
    `test_citation_rows_are_scoped_per_run` 会失败（见下一条）。
    """
    from campfire.agent.context.citations import CitationRecord

    settings = get_settings()
    index = SqlCitationIndex(settings)
    run_id = f"e2e-run-{uuid.uuid4().hex}"
    record = CitationRecord(
        citation_id=uuid.uuid4().hex,
        run_id=run_id,
        source="knowledge",
        reference="knowledge:e2e-1",
        recorded_at=datetime.now(UTC),
        summary="端到端引用",
    )
    try:
        await index.add(record)
        read_back = await index.list_for_run(run_id)
        assert len(read_back) == 1, f"应读回一条，实际 {len(read_back)}"
        got = read_back[0]
        assert got.citation_id == record.citation_id
        assert got.run_id == run_id
        assert got.source == "knowledge"
        assert got.reference == "knowledge:e2e-1"
        assert got.summary == "端到端引用"
        assert got.recorded_at.tzinfo is not None, "时间必须带时区"

        # 幂等：同 id 重复写入不产生第二行（端口契约要求超时后重试安全）
        await index.add(record)
        assert len(await index.list_for_run(run_id)) == 1, "重复写入不幂等"
    finally:
        async with session_scope(settings) as session:
            await session.execute(delete(Citation).where(Citation.run_id == run_id))


async def test_citation_rows_are_scoped_per_run() -> None:
    """引用按运行隔离：别的运行读不到本运行的记录。

    判别性：把 `list_for_run` 的 `where(Citation.run_id == run_id)` 去掉，本用例失败
    （会读到上一个运行的记录）。
    """
    from campfire.agent.context.citations import CitationRecord

    settings = get_settings()
    index = SqlCitationIndex(settings)
    mine = f"e2e-mine-{uuid.uuid4().hex}"
    other = f"e2e-other-{uuid.uuid4().hex}"

    await index.add(
        CitationRecord(
            citation_id=uuid.uuid4().hex,
            run_id=mine,
            source="s",
            reference="r",
            recorded_at=datetime.now(UTC),
        )
    )
    try:
        assert len(await index.list_for_run(mine)) == 1
        assert list(await index.list_for_run(other)) == [], "别的运行不应看到本运行的引用"
    finally:
        async with session_scope(settings) as session:
            await session.execute(delete(Citation).where(Citation.run_id.in_([mine, other])))
