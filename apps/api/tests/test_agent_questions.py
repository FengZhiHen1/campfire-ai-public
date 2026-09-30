"""三个新事件类与 `ask_user` 基座工具：形状、载荷边界、运行编排与思考增量。

对应 docs/技术设计/technical-details/通用基座.md 第 7.1／7.2／7.3 节，以及
docs/技术设计/面/consult/HTTP与SSE契约.md 第 4.2 节的「事件到 SSE 是恒等映射」。

本文件盯四件容易悄悄坏掉的事：

1. **载荷字段名就是线上契约**（恒等映射下 `data` 即该事件对象的 JSON），所以字段名集合
   逐字断死；改名、加字段都会在这里失败。
2. **提问的形状边界**：空组、空题面、模型自带 `batch_id`、题标识重复都必须被拒——它们
   都能让「整组提交」失去可校验的对象（第 7.2 节：组是提交单位）。
3. **运行结束于提问**：真问出问题就结束，且**参数不合法时不结束**。后者是重点：
   SDK 文档里更省事的 `tool_use_behavior={"stop_at_tool_names": [...]}` 只看工具名，
   实测参数不合法也照样结束运行，于是没有任何 `question` 事件、使用者的表现是「回复突然
   断掉」。本文件用一个「先给坏参数、再给好参数」的脚本把这个差异钉住。
4. **思考增量取不到就不产出**：绝不用正文增量冒充（第 7.1 节明令禁止），因此既要测
   「有思考字段时产出」，也要测「只有正文时一条都不产出」。
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from agents import ModelSettings
from agents.items import TResponseInputItem
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from pydantic import BaseModel, ValidationError

from campfire.agent.context import CitationRecord, CitationRecorder
from campfire.agent.model import ModelBinding
from campfire.agent.observability import RunRecorder
from campfire.agent.runtime import (
    ASK_USER_TOOL_NAME,
    ActionCardEvent,
    AgentRunner,
    AskUserArgs,
    QuestionEvent,
    QuestionGate,
    ReasoningDeltaEvent,
    RunFinishedEvent,
    RunRequest,
    RunStartedEvent,
    TextDeltaEvent,
    ToolCallFinishedEvent,
    ToolCallStartedEvent,
    build_ask_user_tool,
    stop_after_question,
)
from campfire.agent.runtime.events import RunEvent
from campfire.agent.skill_runtime import SkillRegistry
from campfire.agent.tools import (
    RESERVED_TOOL_NAMES,
    ActionCard,
    ActionCardAnnotation,
    ActionCardSection,
    ActionCardState,
    ActivationState,
    Question,
    QuestionItem,
    QuestionOption,
    ToolContext,
    ToolFailure,
    ToolPool,
    ToolRegistrationError,
    ToolResult,
    ToolSpec,
)

FIXED_TIME = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
BASE_URL = "https://tokenhub.test/v1"
MODEL_NAME = "test-model"


# --- 测试替身 ---------------------------------------------------------------


class FakeSession:
    """会话替身：行为与 SDK 的 Session 协议一致。"""

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
    """引用索引替身；本组用例不需要真的写索引。"""

    def __init__(self) -> None:
        self.records: list[CitationRecord] = []

    async def add(self, record: CitationRecord) -> None:
        self.records.append(record)

    async def list_for_run(self, run_id: str) -> Sequence[CitationRecord]:
        return [record for record in self.records if record.run_id == run_id]


def _context() -> ToolContext:
    """绑定运行事实与引用写入端的工具上下文。"""
    activation = ActivationState()
    activation.seed({"daily-consulting"})
    return ToolContext(
        run_id="run-1",
        session_id="session-1",
        surface="consult",
        activation_state=activation,
        citations=CitationRecorder(FakeCitationIndex(), run_id="run-1", clock=lambda: FIXED_TIME),
    )


def _chunk(delta: dict[str, Any], finish_reason: str | None = None) -> str:
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": MODEL_NAME,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n"


def _sse(*chunks: str) -> bytes:
    return ("".join(chunks) + "data: [DONE]\n\n").encode()


def text_reply(text: str) -> bytes:
    """一段普通文本回复。"""
    return _sse(_chunk({"role": "assistant", "content": ""}), _chunk({"content": text}), _chunk({}, "stop"))


def reasoning_reply(*parts: str) -> bytes:
    """一段「先思考、再答」的回复。

    `reasoning_content` 是 DeepSeek 思考模式的流式字段（与 `content` 同级），SDK 把它捕获成
    `ReasoningItem` 并发 `response.reasoning_summary_text.delta`（实测 SDK 0.22.3）。
    """
    return _sse(
        _chunk({"role": "assistant", "content": ""}),
        *(_chunk({"reasoning_content": part}) for part in parts),
        _chunk({"content": "结论。"}),
        _chunk({}, "stop"),
    )


def tool_call_reply(name: str, arguments: dict[str, Any], *, call_id: str) -> bytes:
    """一次工具调用的脚本。`call_id` 必须每次不同：SDK 会拒绝复用已完成的调用标识。"""
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

    def __init__(self, script: Sequence[bytes]) -> None:
        self._script = list(script)
        self.requests: list[dict[str, Any]] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        body = self._script.pop(0) if self._script else text_reply("（脚本已用尽）")
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def _binding(chat: ScriptedChat) -> ModelBinding:
    client = httpx.AsyncClient(transport=httpx.MockTransport(chat.handler))
    from openai import AsyncOpenAI

    return ModelBinding(
        name=MODEL_NAME,
        model=OpenAIChatCompletionsModel(
            model=MODEL_NAME,
            openai_client=AsyncOpenAI(api_key="test-key", base_url=BASE_URL, max_retries=0, http_client=client),
        ),
        settings=ModelSettings(),
    )


_EMPTY_ROOT: Path | None = None


def _empty_root() -> Path:
    """一个不含任何 skill 的空根目录（进程内复用，避免每个用例建目录）。"""
    global _EMPTY_ROOT
    if _EMPTY_ROOT is None:
        _EMPTY_ROOT = Path(tempfile.mkdtemp(prefix="campfire-t01-skills-"))
    return _EMPTY_ROOT


def _pool(*, with_ask_user: bool = True, extra: Sequence[ToolSpec[Any]] = ()) -> ToolPool:
    """建一个工具池；默认按装配处的做法注册提问工具（保留名走 register_base）。"""
    pool = ToolPool(list(extra))
    if with_ask_user:
        pool.register_base(build_ask_user_tool())
    return pool


def _runner(
    chat: ScriptedChat,
    *,
    pool: ToolPool | None = None,
    session: FakeSession | None = None,
    timeout_seconds: float = 5.0,
) -> AgentRunner:
    return AgentRunner(
        binding=_binding(chat),
        tools=pool if pool is not None else _pool(),
        skills=SkillRegistry.discover(_empty_root()),
        citations=FakeCitationIndex(),
        sessions=lambda session_id: session if session is not None else FakeSession(session_id),
        timeout_seconds=timeout_seconds,
    )


def _request(**overrides: Any) -> RunRequest:
    values: dict[str, Any] = {
        "session_id": "s-1",
        "surface": "consult",
        "instructions": "静态系统提示",
        "user_input": "你好",
    }
    values.update(overrides)
    return RunRequest(**values)


async def _collect(runner: AgentRunner, request: RunRequest) -> list[RunEvent]:
    return [event async for event in runner.run(request)]


def _of(events: Sequence[RunEvent], kind: type) -> list[Any]:
    """按类型筛事件（测试里读起来比列表推导清楚）。"""
    return [event for event in events if isinstance(event, kind)]


def _wire(event: object) -> Any:
    """把事件压成线上 `data` 的样子：可 JSON 序列化的纯 list/dict 结构。

    比直接比 `asdict` 更贴契约——面侧把 `data` 定义成「该事件对象的 JSON」，所以元组会变成
    数组、字段顺序无关紧要、而**字段名与嵌套键名必须逐字一致**。这里断言的就是后者。
    """
    return json.loads(json.dumps(asdict(event), ensure_ascii=False))


# --- 事件类的载荷字段名（逐字对齐基座 7.1／7.2／7.3） -----------------------


def test_reasoning_delta_event_carries_exactly_one_payload_field() -> None:
    """基座 7.1 节的载荷只有 `delta`：多一个字段就是改线上契约。"""
    assert {field.name for field in dataclasses.fields(ReasoningDeltaEvent)} == {"delta", "type"}
    assert _wire(ReasoningDeltaEvent(delta="想")) == {"delta": "想", "type": "reasoning_delta"}


def test_question_event_field_names_match_the_design_verbatim() -> None:
    """基座 7.2 节：`batch_id` + `items`，逐字一致（改名等于改契约）。"""
    assert {field.name for field in dataclasses.fields(QuestionEvent)} == {"batch_id", "items", "type"}

    event = QuestionEvent(
        batch_id="b-1",
        items=(QuestionItem(id="q1", prompt="疼吗", options=(QuestionOption(label="疼"),), allow_skip=True),),
    )

    assert _wire(event) == {
        "batch_id": "b-1",
        "items": [
            {"id": "q1", "prompt": "疼吗", "options": [{"label": "疼", "description": None}], "allow_skip": True}
        ],
        "type": "question",
    }


def test_question_payload_nested_field_names_match_the_design_verbatim() -> None:
    """嵌套形状也逐字断死：`id` / `prompt` / `options` / `allow_skip`，选项 `label` / `description`。"""
    assert {field.name for field in dataclasses.fields(QuestionItem)} == {"id", "prompt", "options", "allow_skip"}
    assert {field.name for field in dataclasses.fields(QuestionOption)} == {"label", "description"}
    assert {field.name for field in dataclasses.fields(Question)} == {"batch_id", "items"}


def test_action_card_event_is_the_generic_envelope_from_the_design() -> None:
    """基座 7.3 节：`card_id` / `title` / `sections` / `states` / `annotations`，一个不多一个不少。"""
    assert {field.name for field in dataclasses.fields(ActionCardEvent)} == {
        "card_id",
        "title",
        "sections",
        "states",
        "annotations",
        "type",
    }
    assert {field.name for field in dataclasses.fields(ActionCardSection)} == {"key", "heading", "lines"}
    assert {field.name for field in dataclasses.fields(ActionCardState)} == {"key", "value"}
    assert {field.name for field in dataclasses.fields(ActionCardAnnotation)} == {"target", "kind"}

    event = ActionCardEvent(
        card_id="c-1",
        title="现场行动卡",
        sections=(ActionCardSection(key="do_now", heading="现在做什么", lines=("离开噪音源",)),),
    )

    # 空的两个字段仍然出现在 JSON 里（可为空数组），不是被省略——前端按字段存在与否分派。
    assert _wire(event) == {
        "card_id": "c-1",
        "title": "现场行动卡",
        "sections": [{"key": "do_now", "heading": "现在做什么", "lines": ["离开噪音源"]}],
        "states": [],
        "annotations": [],
        "type": "action_card",
    }


def test_three_new_events_are_members_of_the_run_event_union() -> None:
    """三个事件必须真的进联合，否则面侧永远收不到（HTTP 契约第 4.2 节的「事件类未落地」）。"""
    union = RunEvent.__args__  # type: ignore[attr-defined]  # 判别联合的成员在运行时经 __args__ 可见

    assert {ReasoningDeltaEvent, QuestionEvent, ActionCardEvent} <= set(union)


def test_action_card_envelope_carries_no_domain_vocabulary() -> None:
    """通用信封只承载三种与领域无关的形状：字段名里不得出现领域词。

    词表（医疗风险三值、来源六类、置信四档）属产品侧，校验落它的参数模型（基座 7.3 节與
    决策记录「应急卡片由产品侧工具产出」）。这条用例把「基座只做信封」钉在字段名上。
    """
    forbidden = ("medical", "emergency", "risk", "confidence", "source", "profile", "case")
    names = set()
    for cls in (ActionCard, ActionCardSection, ActionCardState, ActionCardAnnotation, ActionCardEvent):
        names |= {field.name for field in dataclasses.fields(cls)}

    assert not [name for name in names if any(word in name.lower() for word in forbidden)]


# --- 载荷边界（空组、空题面、重复标识） --------------------------------------


def test_question_payload_rejects_an_empty_group() -> None:
    """空组不是一次提问：既不能呈现，也没有可提交的对象，且运行会结束在一张空卡片上。"""
    with pytest.raises(ValueError, match="items"):
        Question(batch_id="b-1", items=())


def test_question_payload_rejects_an_empty_batch_id() -> None:
    """批次标识是回答回指的键；空标识等于没有可关联的对象。"""
    with pytest.raises(ValueError, match="batch_id"):
        Question(batch_id="  ", items=(QuestionItem(id="q1", prompt="疼吗"),))


def test_question_item_rejects_blank_id_or_prompt() -> None:
    """空题标识让回答无从关联；空题面在使用者那里是一张没有问题的卡片。"""
    with pytest.raises(ValueError, match="id"):
        QuestionItem(id=" ", prompt="疼吗")
    with pytest.raises(ValueError, match="prompt"):
        QuestionItem(id="q1", prompt="  ")


def test_question_option_rejects_a_blank_label() -> None:
    """没有文案的选项在界面上是一个点不动的空按钮。"""
    with pytest.raises(ValueError, match="label"):
        QuestionOption(label="   ")


def test_ask_user_arguments_reject_an_empty_items_array() -> None:
    """空 items 必须在参数解析期被拒（错误码 `tool_invalid_arguments`），而不是发一张空卡片。"""
    with pytest.raises(ValidationError, match="items"):
        AskUserArgs.model_validate({"items": []})


def test_ask_user_arguments_reject_duplicate_item_ids() -> None:
    """题标识重复会让一道题的答案落到另一道上，且两题的回答互相覆盖而无人察觉。"""
    payload = {
        "items": [
            {"id": "q1", "prompt": "疼吗"},
            {"id": "q1", "prompt": "睡得好吗"},
        ]
    }

    with pytest.raises(ValidationError, match="重复"):
        AskUserArgs.model_validate(payload)


def test_ask_user_arguments_reject_a_model_supplied_batch_id() -> None:
    """批准标识由工具侧生成：模型传标识会让回答被关联到错误的题组。

    `extra="forbid"` 让多传的字段在解析期被拒，而不是被静默忽略（静默忽略等于接受了它）。
    """
    with pytest.raises(ValidationError, match="batch_id"):
        AskUserArgs.model_validate({"items": [{"id": "q1", "prompt": "疼吗"}], "batch_id": "模型自带的"})


# --- ask_user 工具：注册通道、恒可用、批次标识 ------------------------------


def test_ask_user_is_a_reserved_base_tool_name() -> None:
    """提问工具用基座保留名：产品侧工具不得占用它（重名会让机制工具被顶掉）。"""
    assert ASK_USER_TOOL_NAME in RESERVED_TOOL_NAMES


def test_ask_user_cannot_be_squatted_by_product_code() -> None:
    """产品侧走 `register` 时占用 `ask_user` 被拒。"""
    with pytest.raises(ToolRegistrationError, match="保留名"):
        ToolPool().register(build_ask_user_tool())


def test_ask_user_is_registered_through_the_base_channel() -> None:
    """基座自有工具走 `register_base`，注册后名字在池里。"""
    pool = _pool()

    assert ASK_USER_TOOL_NAME in pool.names()


def test_duplicate_ask_user_registration_is_rejected() -> None:
    """重复注册被拒：不覆盖、不忽略（否则权限判定面对一个含义不明的名字）。"""
    pool = _pool()

    with pytest.raises(ToolRegistrationError, match="重复注册"):
        pool.register_base(build_ask_user_tool())


def test_ask_user_tool_declares_no_model_supplied_batch_id() -> None:
    """参数 schema 里没有 `batch_id`：模型在结构上就无法提供批次标识。"""
    spec = build_ask_user_tool()

    assert set(spec.parameters["properties"]) == {"items"}
    assert spec.parameters["required"] == ["items"]


@pytest.mark.asyncio
async def test_ask_user_returns_a_question_with_a_tool_generated_batch_id() -> None:
    """调用一次就得到一组题，且 `batch_id` 由工具侧生成（模型没机会给）。"""
    spec = build_ask_user_tool()

    outcome = await spec.invoke(
        _context(),
        json.dumps({"items": [{"id": "q1", "prompt": "疼吗", "options": [{"label": "疼"}], "allow_skip": True}]}),
    )

    assert isinstance(outcome, ToolResult)
    assert outcome.question is not None
    assert outcome.question.batch_id
    assert [item.id for item in outcome.question.items] == ["q1"]
    assert outcome.question.items[0].options[0].label == "疼"
    assert outcome.question.items[0].allow_skip is True


@pytest.mark.asyncio
async def test_ask_user_generates_a_different_batch_id_each_call() -> None:
    """批次标识全局不重复：重名会让回答被关联到上一次的题组。"""
    spec = build_ask_user_tool()
    payload = json.dumps({"items": [{"id": "q1", "prompt": "疼吗"}]})

    first = await spec.invoke(_context(), payload)
    second = await spec.invoke(_context(), payload)

    assert isinstance(first, ToolResult) and isinstance(second, ToolResult)
    assert first.question is not None and second.question is not None
    assert first.question.batch_id != second.question.batch_id


@pytest.mark.asyncio
async def test_ask_user_rejects_invalid_arguments_with_a_recoverable_code() -> None:
    """参数不合法是**可恢复**失败：带明确错误码回给模型（第 9 节）。"""
    outcome = await build_ask_user_tool().invoke(_context(), json.dumps({"items": []}))

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_invalid_arguments"


def test_question_gate_stays_closed_until_a_question_is_really_produced() -> None:
    """闸门的判据是「真产出了提问」，不是「调用了这个名字的工具」。"""
    gate = QuestionGate()

    assert gate.final_output() is None
    gate.note_question(text="已提问")
    assert gate.final_output() == "已提问"


def test_stop_after_question_does_not_stop_without_a_question() -> None:
    """没有提问时行为与 SDK 默认的 `run_llm_again` 相同（工具结果照常回到模型）。"""
    behavior = stop_after_question(QuestionGate())
    result = behavior(None, [object()])  # type: ignore[arg-type]  # 回调只读闸门，不用上下文

    assert result.is_final_output is False


def test_stop_after_question_stops_once_a_question_exists() -> None:
    """真问出问题就结束运行，并把工具回给模型的那句话作为最终产出。"""
    gate = QuestionGate()
    gate.note_question(text="已提问")
    result = stop_after_question(gate)(None, [object()])  # type: ignore[arg-type]

    assert result.is_final_output is True
    assert result.final_output == "已提问"


# --- 运行编排：发出 question 并结束运行 -------------------------------------


@pytest.mark.asyncio
async def test_ask_user_ends_the_run_and_emits_a_question_event() -> None:
    """调用 `ask_user` 即结束本次运行并发出 `question`（基座 7.2 节）。

    结束的证据是脚本被消费的条数：第三次应答（一句正文）必须**没有**被请求到——如果运行
    没停，SDK 会回到模型再问一轮，那条正文就会出现在事件流里。
    """
    chat = ScriptedChat(
        [
            tool_call_reply(
                ASK_USER_TOOL_NAME,
                {"items": [{"id": "q1", "prompt": "疼吗", "options": [{"label": "疼"}], "allow_skip": False}]},
                call_id="call-1",
            ),
            text_reply("运行不该走到这里"),
        ]
    )
    runner = _runner(chat, pool=_pool())

    events = await _collect(runner, _request())

    questions = _of(events, QuestionEvent)
    assert len(questions) == 1
    assert questions[0].batch_id
    assert [item.id for item in questions[0].items] == ["q1"]
    # 只请求了一次模型：工具调用之后运行就结束了。
    assert len(chat.requests) == 1
    # `question` 排在 `tool_call_finished` 之前，与 `citations`／`candidates` 同一种次序：
    # 载荷事件是这次调用的产出，先交出去；`tool_call_finished` 是这次调用的收尾记账。
    assert [type(event) for event in events] == [
        RunStartedEvent,
        ToolCallStartedEvent,
        QuestionEvent,
        ToolCallFinishedEvent,
        RunFinishedEvent,
    ]
    assert events[-1].reason == "completed"  # type: ignore[union-attr]  # 末项已断言是 run_finished
    assert not _of(events, TextDeltaEvent)


@pytest.mark.asyncio
async def test_an_invalid_ask_user_call_does_not_end_the_run() -> None:
    """参数不合法时运行**不**结束：模型拿到错误码后可以改一次参数再问。

    这条用例盯的是 SDK 那条更省事的机制（`stop_at_tool_names`）的缺陷——它只看工具名，
    实测参数不合法也照样结束运行，于是事件流里没有任何 `question`，使用者的表现是
    「回复突然断掉」。补救的判据是「真的产出了提问」（见 `QuestionGate`）。
    """
    chat = ScriptedChat(
        [
            tool_call_reply(ASK_USER_TOOL_NAME, {"items": []}, call_id="call-1"),
            tool_call_reply(
                ASK_USER_TOOL_NAME,
                {"items": [{"id": "q1", "prompt": "疼吗", "options": [], "allow_skip": True}]},
                call_id="call-2",
            ),
            text_reply("运行不该走到这里"),
        ]
    )
    runner = _runner(chat, pool=_pool())

    events = await _collect(runner, _request())

    # 两次模型请求 = 第一次被拒后确实回到了模型；第三次没有被请求 = 第二次真的结束了运行。
    assert len(chat.requests) == 2
    failures = [event for event in _of(events, ToolCallFinishedEvent) if not event.ok]
    assert [event.error_code for event in failures] == ["tool_invalid_arguments"]
    assert len(_of(events, QuestionEvent)) == 1


@pytest.mark.asyncio
async def test_ask_user_is_always_available_without_being_in_allowed_tools() -> None:
    """恒可用：不进 `allowed-tools` 的并集也照常可调（提问不是某个 skill 的特权）。

    做法是把可用集合压到最小——没有激活 skill、也没有默认可用集——再断言提问工具既在
    声明里（模型看得见），也能真的走完权限门并产出事件（服务端放行）。
    """
    chat = ScriptedChat(
        [tool_call_reply(ASK_USER_TOOL_NAME, {"items": [{"id": "q1", "prompt": "疼吗"}]}, call_id="call-1")]
    )
    runner = _runner(chat)

    events = await _collect(runner, _request(activated=(), default_active_tools=()))

    declared = {tool["function"]["name"] for tool in chat.requests[0]["tools"]}
    assert ASK_USER_TOOL_NAME in declared
    # 走完了权限门：没有 tool_not_available 的拒绝，且事件流里有这次提问。
    assert [event.error_code for event in _of(events, ToolCallFinishedEvent) if not event.ok] == []
    assert len(_of(events, QuestionEvent)) == 1


@pytest.mark.asyncio
async def test_question_is_not_emitted_when_ask_user_is_not_registered() -> None:
    """没注册提问工具时池里就没有它：模型无从调用，也就不会有 `question` 事件。"""
    pool = _pool(with_ask_user=False)

    assert ASK_USER_TOOL_NAME not in pool.names()


# --- reasoning_delta：有则产出，取不到则不产出 ------------------------------


@pytest.mark.asyncio
async def test_reasoning_content_streams_become_reasoning_delta_events() -> None:
    """思考增量产出一个独立的 `reasoning_delta`，与正文增量分开（基座 7.1 节）。"""
    chat = ScriptedChat([reasoning_reply("先想一下。", "再想一下。")])
    runner = _runner(chat, pool=_pool())

    events = await _collect(runner, _request())

    reasoning = _of(events, ReasoningDeltaEvent)
    assert [event.delta for event in reasoning] == ["先想一下。", "再想一下。"]
    # 正文仍然只走 text_delta：两种增量不得混在一起（混了就是把推理当结论）。
    assert [event.delta for event in _of(events, TextDeltaEvent)] == ["结论。"]
    assert isinstance(events[-1], RunFinishedEvent)


@pytest.mark.asyncio
async def test_no_reasoning_delta_when_the_provider_returns_no_thinking() -> None:
    """只有正文时一条思考事件都不产出：**绝不用文本增量冒充**（基座 7.1 节明令禁止）。

    这是「取不到就不产出」的兜底路径：本提供方不返回思考字段时，思考区应当没有内容，
    而不是把正文复制一份进思考区。
    """
    chat = ScriptedChat([text_reply("直接给结论。")])
    runner = _runner(chat, pool=_pool())

    events = await _collect(runner, _request())

    assert _of(events, ReasoningDeltaEvent) == []
    assert [event.delta for event in _of(events, TextDeltaEvent)] == ["直接给结论。"]


@pytest.mark.asyncio
async def test_a_failed_run_emits_no_reasoning_delta() -> None:
    """失败路径同样不产出思考事件（没有可翻译的流，就不编一条出来）。"""
    chat = ScriptedChat([_sse(_chunk({"role": "assistant", "content": ""}), _chunk({}, "stop"))])
    runner = _runner(chat, pool=_pool())

    events = await _collect(runner, _request())

    assert _of(events, ReasoningDeltaEvent) == []


# --- action_card 走工具结果通道（运行继续） ---------------------------------


@pytest.mark.asyncio
async def test_action_cards_from_a_tool_result_become_events_and_the_run_continues() -> None:
    """卡片经 `ToolResult` 交回、翻成 `action_card` 事件，且**运行不结束**（基座 7.3 节）。

    与 `question` 不对称的判据在此：卡片不需要「结束本次运行」，所以工具返回后模型还能
    继续输出（这里就是那句「卡片之后的收尾文字」）。
    """

    class CardArgs(BaseModel):
        """卡片工具的入参；本用例只关心工具结果的翻译，参数形状取最小。"""

        note: str = ""

    async def handler(_context: ToolContext, _args: CardArgs) -> ToolResult:
        return ToolResult(
            text="已发出卡片",
            cards=(
                ActionCard(
                    card_id="card-1",
                    title="现场行动卡",
                    sections=(ActionCardSection(key="do_now", heading="现在做什么", lines=("离开噪音源",)),),
                    states=(ActionCardState(key="medical_risk", value="unstable"),),
                    annotations=(ActionCardAnnotation(target="0", kind="confirmed"),),
                ),
            ),
        )

    spec = ToolSpec(name="emit_card_alpha", description="发一张卡片", args_model=CardArgs, handler=handler)
    chat = ScriptedChat(
        [
            tool_call_reply("emit_card_alpha", {"note": "现在"}, call_id="call-1"),
            text_reply("卡片之后的收尾文字。"),
        ]
    )
    runner = _runner(chat, pool=_pool(extra=[spec]))

    # 卡片工具是**产品侧**工具（基座 7.3 节：卡片由产品侧工具产出，不是保留工具），
    # 因此它要像别的产品工具那样先进入可用集合，而 `ask_user` 不需要这一步。
    events = await _collect(runner, _request(default_active_tools=("emit_card_alpha",)))

    cards = _of(events, ActionCardEvent)
    assert len(cards) == 1
    assert cards[0].card_id == "card-1"
    assert cards[0].sections[0].lines == ("离开噪音源",)
    assert cards[0].states[0].value == "unstable"
    assert cards[0].annotations[0].target == "0"
    # 运行继续：第二次模型请求被消费，收尾正文出现在事件流里。
    assert len(chat.requests) == 2
    assert [event.delta for event in _of(events, TextDeltaEvent)] == ["卡片之后的收尾文字。"]
    assert isinstance(events[-1], RunFinishedEvent)


# --- 运行记录对三个新事件的处置 ---------------------------------------------


def test_run_recorder_counts_the_three_new_events() -> None:
    """记录对三个新事件有明确处置：只记条数，不存题面与卡片正文（第 8 节）。"""
    recorder = RunRecorder(started_at=FIXED_TIME)

    recorder.apply(ReasoningDeltaEvent(delta="想"))
    recorder.apply(ReasoningDeltaEvent(delta="再想"))
    recorder.apply(
        QuestionEvent(batch_id="b-1", items=(QuestionItem(id="q1", prompt="疼吗"),)),
    )
    recorder.apply(
        ActionCardEvent(
            card_id="c-1",
            title="卡",
            sections=(ActionCardSection(key="k", heading="h", lines=("行",)),),
        )
    )

    record = recorder.finish()

    assert record.reasoning_deltas == 2
    assert record.question_batches == 1
    assert record.action_cards == 1
    # 正文不进记录：题面与卡片内容只留在会话真源里。
    assert "疼吗" not in repr(record)
