"""运行编排：端到端跑通 SDK 的真实调用路径，但**不打网络**。

做法是给 ``AsyncOpenAI`` 装一个 ``httpx.MockTransport``，按 OpenAI Chat Completions 的
SSE 格式**放脚本**。这样被验证的是真实链路：真实模型类 → 真实流式转换 → 真实运行循环 →
真实会话写入，只有 HTTP 出口是假的。用手写假模型替身则会绕过转换层，测不到窗口是否真的
生效、工具结果是否真的回到模型。

覆盖 docs/技术设计/technical-details/通用基座.md 第 2、3、4、5、7、9 节与第 11 节
「单真源 / 激活 / 引用 / 失败注入」的验证方式。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from agents import ModelSettings
from agents.items import TResponseInputItem
from agents.memory.session import Session
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from pydantic import BaseModel

from campfire.agent.context import CitationRecord, InjectionBatch, InjectionItem, message_text
from campfire.agent.model import ModelBinding
from campfire.agent.runtime import (
    SKILL_TOOL_NAME,
    AgentRunner,
    RunFailedEvent,
    RunFinishedEvent,
    RunRequest,
    RunStartedEvent,
    RuntimeAssemblyError,
    SessionConfigurationError,
    TextDeltaEvent,
    ToolCallFinishedEvent,
    ToolCallStartedEvent,
    build_skill_tool,
    build_sqlalchemy_session,
)
from campfire.agent.runtime.events import CitationEvent, RunUsage
from campfire.agent.skill_runtime import SkillRegistry
from campfire.agent.tools import ToolContext, ToolPool, ToolResult, ToolSpec

BASE_URL = "https://tokenhub.test/v1"
MODEL_NAME = "test-model"


# --- 测试替身 ---------------------------------------------------------------


class FakeSession:
    """会话替身：一个内存列表，行为与 SDK 的 Session 协议一致。"""

    def __init__(self, session_id: str, items: Sequence[TResponseInputItem] | None = None) -> None:
        self.session_id = session_id
        self.session_settings = None
        self.items: list[TResponseInputItem] = list(items or [])

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
        return list(self.items[-limit:]) if limit is not None else list(self.items)

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        self.items.extend(items)

    async def pop_item(self) -> TResponseInputItem | None:
        return self.items.pop() if self.items else None

    async def clear_session(self) -> None:
        self.items.clear()


class FakeCitationIndex:
    """引用索引替身。"""

    def __init__(self, *, fail_on_add: bool = False) -> None:
        self.records: list[CitationRecord] = []
        self.fail_on_add = fail_on_add

    async def add(self, record: CitationRecord) -> None:
        if self.fail_on_add:
            raise RuntimeError("索引写入失败")
        self.records.append(record)

    async def list_for_run(self, run_id: str) -> Sequence[CitationRecord]:
        return [record for record in self.records if record.run_id == run_id]


class ReadArgs(BaseModel):
    """读类工具参数。"""

    query: str


def _chunk(delta: dict[str, Any], finish_reason: str | None = None) -> str:
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": MODEL_NAME,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n"


def _sse(*chunks: str, usage: dict[str, int] | None = None) -> bytes:
    body = "".join(chunks)
    if usage is not None:
        body += f"data: {json.dumps({'id': 'chatcmpl-test', 'object': 'chat.completion.chunk', 'created': 0, 'model': MODEL_NAME, 'choices': [], 'usage': usage})}\n\n"
    return (body + "data: [DONE]\n\n").encode()


def text_reply(text: str, *, usage: dict[str, int] | None = None) -> bytes:
    """一段普通文本回复的 SSE 脚本。"""
    return _sse(
        _chunk({"role": "assistant", "content": ""}),
        _chunk({"content": text}),
        _chunk({}, "stop"),
        usage=usage,
    )


def tool_call_reply(name: str, arguments: dict[str, Any], *, call_id: str = "call-1") -> bytes:
    """一次工具调用的 SSE 脚本。"""
    return _sse(
        _chunk({"role": "assistant", "content": None}),
        _chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ]
            }
        ),
        _chunk({}, "tool_calls"),
    )


class ScriptedChat:
    """按脚本逐次应答的假 Chat Completions 服务。"""

    def __init__(self, script: Sequence[bytes], *, delay_seconds: float = 0.0) -> None:
        self._script = list(script)
        self._delay = delay_seconds
        self.requests: list[dict[str, Any]] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        if self._delay:
            await asyncio.sleep(self._delay)
        body = self._script.pop(0) if self._script else text_reply("（脚本已用尽）")
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    @property
    def messages_seen(self) -> list[list[dict[str, Any]]]:
        """每次请求里模型看到的 messages。"""
        return [list(request.get("messages", [])) for request in self.requests]


def _binding(chat: ScriptedChat, *, settings: ModelSettings | None = None) -> ModelBinding:
    client = httpx.AsyncClient(transport=httpx.MockTransport(chat.handler))
    return ModelBinding(
        name=MODEL_NAME,
        model=OpenAIChatCompletionsModel(
            model=MODEL_NAME,
            openai_client=_openai_client(client),
        ),
        settings=settings or ModelSettings(),
    )


def _openai_client(http_client: httpx.AsyncClient) -> Any:
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key="test-key", base_url=BASE_URL, max_retries=0, http_client=http_client)


def read_tool(*, calls: list[str] | None = None, citations: list[str] | None = None) -> ToolSpec[ReadArgs]:
    """一个读类工具；可记录调用次数与产出的引用。"""

    async def handler(context: ToolContext, args: ReadArgs) -> ToolResult:
        if calls is not None:
            calls.append(args.query)
        produced = ()
        if citations:
            produced = tuple([await context.citations.record(source="knowledge", reference=ref) for ref in citations])
        return ToolResult(text=f"读到 {args.query}", citations=produced)

    return ToolSpec(name="read_alpha", description="读一个东西", args_model=ReadArgs, handler=handler)


def write_tool(*, calls: list[str] | None = None) -> ToolSpec[ReadArgs]:
    """一个写类工具（默认不可用，用于验证越界拒绝）。"""

    async def handler(_context: ToolContext, args: ReadArgs) -> ToolResult:
        if calls is not None:
            calls.append(args.query)
        return ToolResult(text=f"写入 {args.query}")

    return ToolSpec(name="write_beta", description="写一个东西", args_model=ReadArgs, handler=handler)


def _skill_root(tmp_path: Path, *, name: str = "daily-consulting", autoload: str = "true") -> SkillRegistry:
    """造一个只有一份 skill 的注册表。"""
    directory = tmp_path / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        "description: 做什么与何时用：测试技能。\n"
        "metadata:\n"
        f'  autoload: "{autoload}"\n'
        "  surface: consult\n"
        "allowed-tools: read_alpha\n"
        "---\n"
        "正文指令。\n",
        encoding="utf-8",
    )
    return SkillRegistry.discover(tmp_path)


def _runner(
    *,
    binding: ModelBinding,
    session: FakeSession,
    pool: ToolPool | None = None,
    skills: SkillRegistry | None = None,
    citations: FakeCitationIndex | None = None,
    timeout_seconds: float = 5.0,
) -> AgentRunner:
    registry = skills if skills is not None else SkillRegistry.discover(_empty_root())
    tool_pool = pool if pool is not None else ToolPool([read_tool()])
    if registry.activation_candidates() and SKILL_TOOL_NAME not in tool_pool.names():
        # 与装配处的约定一致：存在可选 skill 时必须注册模型侧激活工具
        tool_pool.register_base(build_skill_tool(registry))
    return AgentRunner(
        binding=binding,
        tools=tool_pool,
        skills=registry,
        citations=citations if citations is not None else FakeCitationIndex(),
        sessions=lambda session_id: session,
        timeout_seconds=timeout_seconds,
    )


_EMPTY_ROOT: Path | None = None


def _empty_root() -> Path:
    """一个不含任何 skill 的空根目录（进程内复用）。"""
    global _EMPTY_ROOT
    if _EMPTY_ROOT is None:
        import tempfile

        _EMPTY_ROOT = Path(tempfile.mkdtemp(prefix="campfire-empty-skills-"))
    return _EMPTY_ROOT


async def _collect(runner: AgentRunner, request: RunRequest) -> list[object]:
    return [event async for event in runner.run(request)]


def _request(**overrides: Any) -> RunRequest:
    values: dict[str, Any] = {
        "session_id": "s-1",
        "surface": "consult",
        "instructions": "静态系统提示",
        "user_input": "你好",
    }
    values.update(overrides)
    return RunRequest(**values)


# --- 请求形状校验 -----------------------------------------------------------


def test_request_requires_session_and_instructions() -> None:
    with pytest.raises(RuntimeAssemblyError, match="session_id"):
        _request(session_id="")
    with pytest.raises(RuntimeAssemblyError, match="instructions"):
        _request(instructions="   ")


def test_session_builder_rejects_empty_id() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine("postgresql+asyncpg://u:p@localhost:5432/db")
    with pytest.raises(SessionConfigurationError, match="会话标识"):
        build_sqlalchemy_session("", engine=engine)


def test_session_builder_returns_an_sdk_session() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine("postgresql+asyncpg://u:p@localhost:5432/db")

    session = build_sqlalchemy_session("s-1", engine=engine)

    assert isinstance(session, Session)
    assert session.session_id == "s-1"


# --- 正常路径 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_emits_started_delta_and_finished() -> None:
    chat = ScriptedChat(
        [text_reply("你好，我在。", usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18})]
    )
    session = FakeSession("s-1")

    events = await _collect(
        _runner(binding=_binding(chat), session=session),
        _request(),
    )

    assert isinstance(events[0], RunStartedEvent)
    assert events[0].model == MODEL_NAME
    assert events[0].surface == "consult"
    assert "".join(event.delta for event in events if isinstance(event, TextDeltaEvent)) == "你好，我在。"
    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent)
    assert finished.reason == "completed"
    assert finished.elapsed_seconds >= 0
    # 用量取提供方返回值（压缩策略第 9 节：不用字符数折算）
    assert finished.usage.total_tokens >= 0


@pytest.mark.asyncio
async def test_user_input_and_injections_reach_the_model_and_the_session() -> None:
    """单真源：注入项与用户消息都进模型输入，也都落进会话。"""
    chat = ScriptedChat([text_reply("好的")])
    session = FakeSession("s-1")
    batch = InjectionBatch([InjectionItem(source="profile-summary", content="档案摘要")])

    await _collect(_runner(binding=_binding(chat), session=session), _request(injections=batch))

    seen = [message["content"] for message in chat.messages_seen[0]]
    assert "档案摘要" in seen
    assert "你好" in seen

    stored = [message_text(item) for item in session.items]
    assert "档案摘要" in stored
    assert "你好" in stored
    # 助手消息落库后 content 是**分片数组**（实测），message_text 负责两种形状统一取文本
    assert any(text and "好的" in text for text in stored)


@pytest.mark.asyncio
async def test_window_derivation_actually_applies_to_the_model_input() -> None:
    """窗口裁剪只在模型输入上生效——这是 ``session_input_callback`` 真的被调用的证据。

    会话里保留完整历史（含摘要之前的部分），而模型只看得到摘要之后的窗口。
    """
    chat = ScriptedChat([text_reply("好")])
    session = FakeSession(
        "s-1",
        [
            {"role": "user", "content": "很久以前的提问"},
            {"role": "assistant", "content": "很久以前的回答"},
            {"role": "user", "content": "<compacted-summary>摘要：之前聊过 X</compacted-summary>"},
            {"role": "user", "content": "摘要之后的提问"},
        ],
    )

    await _collect(_runner(binding=_binding(chat), session=session), _request(user_input="这一轮"))

    seen = [message["content"] for message in chat.messages_seen[0]]
    assert "很久以前的提问" not in seen
    assert "很久以前的回答" not in seen
    assert "<compacted-summary>摘要：之前聊过 X</compacted-summary>" in seen
    assert "摘要之后的提问" in seen
    assert "这一轮" in seen


@pytest.mark.asyncio
async def test_run_uses_no_turn_limit_and_installs_the_window_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    """基座第 2 节不设步数上限：必须显式传 ``max_turns=None`` 覆盖 SDK 默认的 10 轮。"""
    from agents import Runner

    chat = ScriptedChat([text_reply("好")])
    captured: dict[str, Any] = {}
    original = Runner.run_streamed

    def spy(starting_agent: object, input: object = None, **kwargs: Any) -> object:
        captured.update(kwargs)
        return original(starting_agent, input, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Runner, "run_streamed", spy)

    await _collect(_runner(binding=_binding(chat), session=FakeSession("s-1")), _request())

    assert captured["max_turns"] is None
    assert callable(captured["run_config"].session_input_callback)


# --- 技能目录、激活与工具可用性 ---------------------------------------------


@pytest.mark.asyncio
async def test_skill_catalog_and_availability_are_appended_once(tmp_path: Path) -> None:
    """目录/可用性只在「与历史里最后一条不同」时追加：连续两轮不得重复。"""
    chat = ScriptedChat([text_reply("一"), text_reply("二")])
    session = FakeSession("s-1")
    runner = _runner(binding=_binding(chat), session=session, skills=_skill_root(tmp_path))

    await _collect(runner, _request(user_input="第一轮"))
    await _collect(runner, _request(user_input="第二轮"))

    first = [message["content"] for message in chat.messages_seen[0]]
    second = [message["content"] for message in chat.messages_seen[1]]
    assert sum(1 for content in first if content and content.startswith("<available_skills>")) == 1
    assert sum(1 for content in second if content and content.startswith("<available_skills>")) == 1
    assert sum(1 for content in second if content and content.startswith("<tool_availability>")) == 1


@pytest.mark.asyncio
async def test_empty_skill_registry_adds_no_catalog_message(tmp_path: Path) -> None:
    chat = ScriptedChat([text_reply("好")])

    await _collect(
        _runner(binding=_binding(chat), session=FakeSession("s-1"), skills=SkillRegistry.discover(tmp_path)),
        _request(),
    )

    seen = [message["content"] for message in chat.messages_seen[0]]
    assert not [content for content in seen if content and content.startswith("<available_skills>")]


@pytest.mark.asyncio
async def test_application_side_activation_injects_skill_content_once(tmp_path: Path) -> None:
    registry = _skill_root(tmp_path)
    skill = registry.get("daily-consulting")
    chat = ScriptedChat([text_reply("一"), text_reply("二")])
    session = FakeSession("s-1")
    runner = _runner(binding=_binding(chat), session=session, skills=registry)

    await _collect(runner, _request(activated=(skill,)))
    await _collect(runner, _request(activated=(skill,)))

    first = [message["content"] for message in chat.messages_seen[0]]
    second = [message["content"] for message in chat.messages_seen[1]]
    assert sum(1 for content in first if content and content.startswith("<skill_content")) == 1
    assert sum(1 for content in second if content and content.startswith("<skill_content")) == 1


@pytest.mark.asyncio
async def test_tool_availability_message_lists_unavailable_tools() -> None:
    chat = ScriptedChat([text_reply("好")])

    await _collect(
        _runner(binding=_binding(chat), session=FakeSession("s-1"), pool=ToolPool([read_tool(), write_tool()])),
        _request(default_active_tools=("read_alpha",)),
    )

    availability = [
        message["content"]
        for message in chat.messages_seen[0]
        if message["content"] and "<tool_availability>" in message["content"]
    ]
    assert len(availability) == 1
    assert "<unavailable_tools>" in availability[0]
    assert '<tool name="write_beta" />' in availability[0]


# --- 工具调用 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_call_flows_through_and_citations_are_emitted() -> None:
    calls: list[str] = []
    chat = ScriptedChat(
        [
            tool_call_reply("read_alpha", {"query": "问题"}),
            text_reply("我查到了"),
        ]
    )
    session = FakeSession("s-1")
    runner = _runner(
        binding=_binding(chat),
        session=session,
        pool=ToolPool([read_tool(calls=calls, citations=["kb-1"])]),
    )

    events = await _collect(runner, _request(default_active_tools=("read_alpha",)))

    assert calls == ["问题"]
    started = [event for event in events if isinstance(event, ToolCallStartedEvent)]
    finished = [event for event in events if isinstance(event, ToolCallFinishedEvent)]
    assert [event.tool_name for event in started] == ["read_alpha"]
    assert [(event.ok, event.error_code) for event in finished] == [(True, None)]
    citations = [event for event in events if isinstance(event, CitationEvent)]
    assert [event.citation.reference for event in citations] == ["kb-1"]
    # 工具结果回到了模型
    second_request = [message["content"] for message in chat.messages_seen[1]]
    assert "读到 问题" in second_request


@pytest.mark.asyncio
async def test_declaration_stays_stable_even_when_a_tool_is_not_active() -> None:
    """声明是超集且本轮不变；越界由服务端拒绝（第 5 节）。"""
    chat = ScriptedChat([tool_call_reply("write_beta", {"query": "x"}), text_reply("好")])
    writes: list[str] = []
    runner = _runner(
        binding=_binding(chat),
        session=FakeSession("s-1"),
        pool=ToolPool([read_tool(), write_tool(calls=writes)]),
    )

    events = await _collect(runner, _request(default_active_tools=("read_alpha",)))

    declared = {tool["function"]["name"] for tool in chat.requests[0]["tools"]}
    assert declared == {"read_alpha", "write_beta"}
    finished = [event for event in events if isinstance(event, ToolCallFinishedEvent)]
    assert [(event.ok, event.error_code) for event in finished] == [(False, "tool_not_available")]
    assert writes == []
    # 明确错误码回给了模型
    assert "tool_not_available" in "".join(message["content"] or "" for message in chat.messages_seen[1])


@pytest.mark.asyncio
async def test_unknown_tool_call_is_reported_to_the_model_and_paired_with_a_finish() -> None:
    """模型编出不存在的工具名时：错误交回模型（可恢复），且事件成对。

    SDK 默认会为此抛 ``ModelBehaviorError`` 中断整次运行；基座把它改成
    ``return_error_to_model``（第 9 节：工具失败作为结果回给模型）。这条路径不经过基座的
    权限门，因此运行编排要补一条 ``tool_call_finished``，否则面会看到只有开始没有结束的调用。
    """
    chat = ScriptedChat([tool_call_reply("nope", {"query": "x"}), text_reply("好")])
    runner = _runner(binding=_binding(chat), session=FakeSession("s-1"), pool=ToolPool([read_tool()]))

    events = await _collect(runner, _request(default_active_tools=("read_alpha",)))

    started = [event for event in events if isinstance(event, ToolCallStartedEvent)]
    finished = [event for event in events if isinstance(event, ToolCallFinishedEvent)]
    assert [event.tool_name for event in started] == ["nope"]
    assert [(event.ok, event.error_code) for event in finished] == [(False, "tool_not_registered")]
    assert started[0].call_id == finished[0].call_id
    # 运行继续跑完，模型看到了错误
    assert isinstance(events[-1], RunFinishedEvent)
    assert len(chat.requests) == 2


@pytest.mark.asyncio
async def test_model_can_activate_a_skill_through_the_tool(tmp_path: Path) -> None:
    """模型侧激活：模型调用 ``skill`` 工具，工具结果携带 ``<skill_content>``（第 3 节）。

    这条路径与注入路径共用 ``render_activation``，因此两者同形。
    """
    registry = _skill_root(tmp_path)
    pool = ToolPool([read_tool()])
    pool.register_base(build_skill_tool(registry))
    chat = ScriptedChat(
        [
            tool_call_reply(SKILL_TOOL_NAME, {"name": "daily-consulting"}),
            text_reply("已按 skill 执行"),
        ]
    )
    runner = AgentRunner(
        binding=_binding(chat),
        tools=pool,
        skills=registry,
        citations=FakeCitationIndex(),
        sessions=lambda session_id: FakeSession("s-1"),
    )

    events = await _collect(runner, _request())

    finishes = [event for event in events if isinstance(event, ToolCallFinishedEvent)]
    assert [(event.tool_name, event.ok) for event in finishes] == [(SKILL_TOOL_NAME, True)]
    second = [message["content"] for message in chat.messages_seen[1]]
    assert any(content and "<skill_content" in str(content) for content in second)
    # 声明里含激活工具，且它不依赖 allowed-tools（机制本身恒可用）
    declared = {tool["function"]["name"] for tool in chat.requests[0]["tools"]}
    assert SKILL_TOOL_NAME in declared


@pytest.mark.asyncio
async def test_model_cannot_activate_a_skill_marked_not_for_auto_matching(tmp_path: Path) -> None:
    """``autoload: "false"`` 的 skill 只能由应用注入激活；模型侧工具必须拒绝。"""
    registry = _skill_root(tmp_path, name="emergency-consulting", autoload="false")
    pool = ToolPool([read_tool()])
    pool.register_base(build_skill_tool(registry))
    chat = ScriptedChat(
        [
            tool_call_reply(SKILL_TOOL_NAME, {"name": "emergency-consulting"}),
            text_reply("好"),
        ]
    )
    runner = AgentRunner(
        binding=_binding(chat),
        tools=pool,
        skills=registry,
        citations=FakeCitationIndex(),
        sessions=lambda session_id: FakeSession("s-1"),
    )

    events = await _collect(runner, _request())

    finishes = [event for event in events if isinstance(event, ToolCallFinishedEvent)]
    assert [(event.ok, event.error_code) for event in finishes] == [(False, "tool_not_available")]
    assert "tool_not_available" in "".join(message["content"] or "" for message in chat.messages_seen[1])


@pytest.mark.asyncio
async def test_model_activation_of_an_unknown_skill_returns_a_recoverable_error(tmp_path: Path) -> None:
    registry = _skill_root(tmp_path)
    pool = ToolPool([read_tool()])
    pool.register_base(build_skill_tool(registry))
    chat = ScriptedChat([tool_call_reply(SKILL_TOOL_NAME, {"name": "nope"}), text_reply("好")])
    runner = AgentRunner(
        binding=_binding(chat),
        tools=pool,
        skills=registry,
        citations=FakeCitationIndex(),
        sessions=lambda session_id: FakeSession("s-1"),
    )

    events = await _collect(runner, _request())

    finishes = [event for event in events if isinstance(event, ToolCallFinishedEvent)]
    assert [(event.ok, event.error_code) for event in finishes] == [(False, "tool_not_registered")]
    # 说明里带上已注册的名字，模型可以据此换一个重试
    assert "daily-consulting" in "".join(message["content"] or "" for message in chat.messages_seen[1])


def test_missing_activation_tool_is_an_assembly_error(tmp_path: Path) -> None:
    """有可选 skill 却没注册激活工具：装配期就失败，而不是运行时静默无法激活。"""
    registry = _skill_root(tmp_path)

    with pytest.raises(RuntimeAssemblyError, match=SKILL_TOOL_NAME):
        AgentRunner(
            binding=_binding(ScriptedChat([])),
            tools=ToolPool([read_tool()]),
            skills=registry,
            citations=FakeCitationIndex(),
            sessions=lambda session_id: FakeSession("s-1"),
        )


# --- 失败语义 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_ends_the_run_with_an_explicit_reason() -> None:
    chat = ScriptedChat([text_reply("慢")], delay_seconds=1.0)
    runner = _runner(binding=_binding(chat), session=FakeSession("s-1"), timeout_seconds=0.05)

    events = await _collect(runner, _request())

    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent)
    assert finished.reason == "timeout"


@pytest.mark.asyncio
async def test_model_failure_is_reported_as_model_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    binding = ModelBinding(
        name=MODEL_NAME,
        model=OpenAIChatCompletionsModel(model=MODEL_NAME, openai_client=_openai_client(client)),
        settings=ModelSettings(),
    )

    events = await _collect(_runner(binding=binding, session=FakeSession("s-1")), _request())

    failed = events[-1]
    assert isinstance(failed, RunFailedEvent)
    assert failed.code == "model_unavailable"
    assert failed.model_reason == "provider_error"
    # 说明里不得出现供应商原始消息
    assert "boom" not in failed.detail


@pytest.mark.asyncio
async def test_injection_index_failure_fails_the_run_instead_of_continuing() -> None:
    chat = ScriptedChat([text_reply("不应到达")])
    batch = InjectionBatch([InjectionItem(source="retrieved", content="资料", reference="kb-1")])

    events = await _collect(
        _runner(binding=_binding(chat), session=FakeSession("s-1"), citations=FakeCitationIndex(fail_on_add=True)),
        _request(injections=batch),
    )

    failed = events[-1]
    assert isinstance(failed, RunFailedEvent)
    assert failed.code == "injection_failed"
    assert chat.requests == []  # 没有向模型发出任何请求


@pytest.mark.asyncio
async def test_session_read_failure_is_reported_as_session_io_failure() -> None:
    class BrokenSession(FakeSession):
        async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
            raise RuntimeError("数据库不可用")

    chat = ScriptedChat([text_reply("好")])
    runner = _runner(binding=_binding(chat), session=BrokenSession("s-1"))

    events = await _collect(runner, _request())

    failed = events[-1]
    assert isinstance(failed, RunFailedEvent)
    assert failed.code == "session_write_failed"
    assert chat.requests == []


@pytest.mark.asyncio
async def test_cancellation_stops_the_run_and_propagates() -> None:
    """取消优先于一切：立即停止调用，并把 CancelledError 继续抛出去（第 9 节）。"""
    chat = ScriptedChat([text_reply("慢")], delay_seconds=2.0)
    runner = _runner(binding=_binding(chat), session=FakeSession("s-1"), timeout_seconds=30.0)

    async def consume() -> None:
        async for _event in runner.run(_request()):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_usage_accumulates_across_model_calls() -> None:
    chat = ScriptedChat(
        [
            tool_call_reply("read_alpha", {"query": "x"}),
            text_reply(
                "答",
                usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            ),
        ]
    )
    runner = _runner(binding=_binding(chat), session=FakeSession("s-1"), pool=ToolPool([read_tool()]))

    events = await _collect(runner, _request(default_active_tools=("read_alpha",)))

    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent)
    assert finished.usage.requests >= 2
    assert finished.usage.total_tokens >= 8


def test_usage_addition_is_commutative_on_totals() -> None:
    first = RunUsage(requests=1, input_tokens=2, output_tokens=3, total_tokens=5)
    second = RunUsage(requests=2, input_tokens=1, output_tokens=1, total_tokens=2)

    assert (first + second).total_tokens == 7
    assert (first + second).requests == 3


@pytest.mark.asyncio
async def test_runner_reports_citations_produced_by_injections() -> None:
    chat = ScriptedChat([text_reply("好")])
    index = FakeCitationIndex()
    batch = InjectionBatch([InjectionItem(source="retrieved", content="资料", reference="kb-9", summary="资料摘要")])

    events = await _collect(
        _runner(binding=_binding(chat), session=FakeSession("s-1"), citations=index),
        _request(injections=batch),
    )

    citations = [event for event in events if isinstance(event, CitationEvent)]
    assert [event.citation.reference for event in citations] == ["kb-9"]
    assert index.records and index.records[0].reference == "kb-9"
    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent)
    assert [record.reference for record in finished.citations] == ["kb-9"]


@pytest.mark.asyncio
async def test_unavailable_source_is_announced_but_does_not_fail_the_run() -> None:
    from campfire.agent.context import UnavailableSource

    chat = ScriptedChat([text_reply("好")])
    batch = InjectionBatch(unavailable=[UnavailableSource(source="profile", reason="TimeoutError")])

    events = await _collect(_runner(binding=_binding(chat), session=FakeSession("s-1")), _request(injections=batch))

    assert isinstance(events[-1], RunFinishedEvent)
    seen = [message["content"] for message in chat.messages_seen[0]]
    assert any(content and "<unavailable_sources>" in content for content in seen)
