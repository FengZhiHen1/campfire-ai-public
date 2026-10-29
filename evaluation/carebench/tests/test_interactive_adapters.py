"""interactive 适配器（N/P/C）的确定性测试：脚本化网关与脚本化运行器，不连库、不调模型。

覆盖的判据（都是「错了会静默污染结论」的那一类）：

- 原样输入：家长那句话逐字进入请求，没有背景/问题标题；
- 提示隔离：N 与 P 的系统提示不同、C 的提示来自产品（不被评测替换）；
- 历史隔离：N/P 每个 episode 一段独立 history，`open_case` 清空、续轮接上；
- 应急首次轮：程序激活 `emergency-consulting`、空档案/空记忆注入、`what_happened` 渲染；
- 应急后续轮与日常入口：不重复激活、不注入，沿同一会话；
- 负控：入口只看事前冻结的 `entry`（不看 `risk_hint`）、场景里没给的事实不进入请求、
  缺应急技能时明确失败而不是降级成日常、失败信息不夹带端点细节；
- 来源核验：结构化产出、工具轨迹、引用元数据保留，并显式标注检索正文未保存。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from campfire.agent.context import CitationRecord
from campfire.agent.runtime import (
    ActionCardEvent,
    CitationEvent,
    QuestionEvent,
    RunFinishedEvent,
    RunStartedEvent,
    RunUsage,
    TextDeltaEvent,
    ToolCallFinishedEvent,
    ToolCallStartedEvent,
)
from campfire.agent.tools.payloads import (
    ActionCardSection,
    ActionCardState,
    QuestionItem,
    QuestionOption,
)
from campfire.surfaces.consult import assembly as consult_assembly
from campfire.surfaces.consult.injections import (
    EMERGENCY_INTAKE_PREFIX,
    EMERGENCY_MEMORY_PREFIX,
    EMERGENCY_MEMORY_SOURCE,
    EMERGENCY_PROFILE_PREFIX,
    EMERGENCY_PROFILE_SOURCE,
    UNCOLLECTED_MARK,
)
from evaluation.carebench import prompts
from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan
from evaluation.carebench.interactive.adapters import (
    EMERGENCY_SKILL_NAME,
    ENTRY_DAILY,
    ENTRY_EMERGENCY,
    MINIMAL_SYSTEM_PROMPT,
    PROMPTED_SYSTEM_PROMPT,
    InteractiveAgentSystem,
    InteractiveTurn,
    NaturalChatSystem,
    build_interactive_adapters,
)
from evaluation.carebench.systems.agent import AgentSystem

from .conftest import load_cases, make_cases_file

#: 测试里的产品面常量（与 `surfaces.consult.routes` 同值；真实常量另由产品测试核对）。
SURFACE = "consult"
INSTRUCTIONS = "测试用面提示"
ACCOUNT_PAYLOAD_KEY = "account_id"
DAILY_TOOLS = ("ask_user",)

#: 埋进案例的「隐藏事实」标记：任何请求里都不该出现。
HIDDEN_FACT = "隐藏真相：孩子上周被雷声吓到过，这件事没有在开场里说"


class ScriptedCompletions:
    """脚本化 `chat.completions.create`：按顺序吐回复，并记录收到的请求。"""

    def __init__(self, replies: list[str | Exception]) -> None:
        self._replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        if not self._replies:
            raise AssertionError("脚本没有更多回复：用例对模型调用次数的假设不成立")
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        )


class ScriptedGateway:
    """脚本化网关：只实现适配器真正用到的 `client.chat.completions` 与 `model_name`。"""

    def __init__(self, replies: list[str | Exception], *, model_name: str = "scripted-model") -> None:
        self.model_name = model_name
        self.completions = ScriptedCompletions(replies)
        self.client = SimpleNamespace(chat=SimpleNamespace(completions=self.completions))
        self.closed = False

    @property
    def requests(self) -> list[dict[str, Any]]:
        """收到的模型请求（按顺序）。"""
        return self.completions.requests

    async def aclose(self) -> None:
        """记录关闭（用于核对「网关所有权不在适配器」）。"""
        self.closed = True


class ScriptedRunner:
    """脚本化 `AgentRunner`：记录 `RunRequest` 并按顺序吐事件。"""

    def __init__(self, events: list[Any]) -> None:
        self._events = events
        self.requests: list[Any] = []

    async def run(self, request: Any) -> Any:
        """记录请求后逐个产出事件。"""
        self.requests.append(request)
        for event in self._events:
            yield event


def make_case(tmp_path: Any, *, risk_hint: str = "测试用", shared_context: str | None = None) -> Any:
    """一条 legacy 案例（`request.case` 仍是旧形状：natural 输入不走它，用于验证不泄漏）。"""
    path = make_cases_file(tmp_path / "cases.jsonl", count=1)
    case = load_cases(path).cases[0]
    return case.__class__(
        id=case.id,
        split=case.split,
        category=case.category,
        risk_hint=risk_hint,
        user_message="旧形状的问题文本（不应进入 interactive 请求）",
        shared_context=HIDDEN_FACT if shared_context is None else shared_context,
        followup=None,
        must_check=case.must_check,
        must_not=case.must_not,
        source_kind=case.source_kind,
        review_status=case.review_status,
    )


def make_turn(case: Any, *, user_text: str, entry: str = ENTRY_DAILY, turn: int = 1, session_id: str = "s1") -> Any:
    """一条 interactive 轮次。"""
    return InteractiveTurn(
        case=case,
        system_id="C",
        turn=turn,
        session_id=session_id,
        account_id="acct-synthetic",
        user_text=user_text,
        entry=entry,
    )


def make_natural(system_id: str, gateway: ScriptedGateway) -> NaturalChatSystem:
    """N/P 适配器（不调 `prepare`：它只需要网关与配置）。"""
    return NaturalChatSystem(
        system_id=system_id,
        settings=SimpleNamespace(tokenhub_base_url="https://example.invalid/v1"),
        config=RunConfig(label="calibration"),
        gateway=gateway,  # type: ignore[arg-type]  # 脚本化网关与真网关同形
    )


def make_agent(
    settings: Any,
    runner: ScriptedRunner,
    *,
    session_items: list[int] | None = None,
) -> InteractiveAgentSystem:
    """C 组适配器：脚本化运行器 + 固定的会话条目读数（不触库）。"""
    system = InteractiveAgentSystem(
        settings=settings,
        config=RunConfig(label="calibration"),
        gateway=SimpleNamespace(model_name="scripted-model"),
        faults=FaultPlan(requested={}),
        runner=runner,
    )
    system._constants = {
        "surface": SURFACE,
        "instructions": INSTRUCTIONS,
        "default_active_tools": DAILY_TOOLS,
        "account_payload_key": ACCOUNT_PAYLOAD_KEY,
    }
    system._session_item_count = AsyncMock(side_effect=session_items or [0, 2])  # type: ignore[method-assign]
    return system


def finished(text: str = "先陪在孩子身边。") -> list[Any]:
    """一次「正常完成」的最小事件流。"""
    return [
        RunStartedEvent(
            run_id="run-1",
            session_id="s1",
            surface=SURFACE,
            model="scripted-model",
            activated_skills=(),
            injection_sources=(),
            appended_messages=0,
        ),
        TextDeltaEvent(delta=text),
        RunFinishedEvent(reason="completed", citations=(), usage=RunUsage(requests=1), elapsed_seconds=0.01),
    ]


# ---------------------------------------------------------------------------
# 输入形状
# ---------------------------------------------------------------------------


def test_unknown_entry_is_rejected() -> None:
    """入口只有 daily/emergency：拼错不能被静默当成日常。"""
    with pytest.raises(ValueError, match="未知入口"):
        InteractiveTurn(
            case=SimpleNamespace(id="X"), system_id="C", turn=1, session_id="s", account_id="a", entry="urgent"
        )


@pytest.mark.parametrize("system_id", ["N", "P"])
@pytest.mark.asyncio
async def test_natural_groups_reject_empty_and_foreign_requests(tmp_path: Any, system_id: str) -> None:
    """空文本与非 InteractiveTurn 都在入口处失败，而不是送一段空对话给模型。"""
    adapter = make_natural(system_id, ScriptedGateway(["不应被调用"]))
    case = make_case(tmp_path)
    with pytest.raises(ValueError, match="user_text 不能为空"):
        await adapter.run_turn(make_turn(case, user_text="   "))
    with pytest.raises(TypeError, match="InteractiveTurn"):
        await adapter.run_turn(SimpleNamespace(session_id="s1", user_text="x"))  # type: ignore[arg-type]
    assert adapter._gateway.requests == []


# ---------------------------------------------------------------------------
# N / P：提示与输入
# ---------------------------------------------------------------------------


def test_n_and_p_prompts_are_distinct_and_n_stays_minimal() -> None:
    """P 逐字复用旧强提示；N 只有助手角色与基础边界（没有格式/追问/现场条件纪律）。"""
    assert PROMPTED_SYSTEM_PROMPT == prompts.COMMON_TASK_INSTRUCTIONS
    assert MINIMAL_SYSTEM_PROMPT != PROMPTED_SYSTEM_PROMPT
    assert len(MINIMAL_SYSTEM_PROMPT) < len(PROMPTED_SYSTEM_PROMPT)
    # N 不含 P 独有的任务编排纪律（这正是两组的对照条件，不许漂移）。
    assert "不要使用 markdown" not in MINIMAL_SYSTEM_PROMPT
    assert "在场成人数量" not in MINIMAL_SYSTEM_PROMPT
    assert "已经确认的背景信息" not in MINIMAL_SYSTEM_PROMPT
    # 两组都有的基础边界：中文、不编造。
    for prompt in (MINIMAL_SYSTEM_PROMPT, PROMPTED_SYSTEM_PROMPT):
        assert "中文" in prompt
        assert "不要编造" in prompt


@pytest.mark.asyncio
async def test_natural_meta_records_prompt_history_and_default_sampling() -> None:
    """装配事实要能核对三件事：提示 hash 是本组那份、历史每 episode 隔离、采样没被评测改。"""
    gateway = ScriptedGateway(["ok"])
    for system_id, expected_prompt in (("N", MINIMAL_SYSTEM_PROMPT), ("P", PROMPTED_SYSTEM_PROMPT)):
        adapter = make_natural(system_id, gateway)
        meta = await adapter.prepare()
        assert meta.model_id == "scripted-model"
        assert meta.prompt_sha256 == prompts.sha256_text(expected_prompt)
        assert meta.notes["history"].startswith("per_episode")
        assert meta.notes["tools"] == "none" and meta.notes["skills"] == "none"
        assert meta.notes["sampling_params"] == {"explicit": {}, "owner": "provider_default"}


@pytest.mark.asyncio
async def test_natural_meta_reports_explicit_sampling_when_config_sets_it() -> None:
    """配置显式给了采样参数时如实记录（「没改默认」与「按配置改」不能混成一句话）。"""
    adapter = NaturalChatSystem(
        system_id="N",
        settings=SimpleNamespace(tokenhub_base_url="https://example.invalid/v1"),
        config=RunConfig(label="calibration", temperature=0.2),
        gateway=ScriptedGateway(["ok"]),  # type: ignore[arg-type]  # 脚本化网关与真网关同形
    )
    meta = await adapter.prepare()
    assert meta.notes["sampling_params"] == {"explicit": {"temperature": 0.2}, "owner": "run_config"}


@pytest.mark.parametrize(
    ("system_id", "expected_prompt"), [("N", MINIMAL_SYSTEM_PROMPT), ("P", PROMPTED_SYSTEM_PROMPT)]
)
@pytest.mark.asyncio
async def test_raw_user_text_goes_to_model_without_background_headings(
    tmp_path: Any, system_id: str, expected_prompt: str
) -> None:
    """请求体只有「本组提示 + 该会话历史 + 原样那句家长的话」。"""
    gateway = ScriptedGateway(["先蹲下来，别急着讲道理。"])
    adapter = make_natural(system_id, gateway)
    case = make_case(tmp_path)
    user_text = "他在超市躺地上尖叫，我一个人，怎么办"
    outcome = await adapter.run_turn(make_turn(case, user_text=user_text))

    assert outcome.status == "completed"
    assert outcome.raw_output == "先蹲下来，别急着讲道理。"
    messages = gateway.requests[0]["messages"]
    assert messages[0] == {"role": "system", "content": expected_prompt}
    assert messages[1:] == [{"role": "user", "content": user_text}]
    serialized = json.dumps(messages, ensure_ascii=False)
    assert prompts.CONTEXT_HEADING not in serialized
    assert prompts.QUESTION_HEADING not in serialized
    assert prompts.FOLLOWUP_HEADING not in serialized
    # 旧形状的案例字段一律没进请求（隐藏事实与旧问题文本都是负控）。
    assert HIDDEN_FACT not in serialized
    assert "旧形状的问题文本" not in serialized
    # 两组提示互不串场。
    other = PROMPTED_SYSTEM_PROMPT if system_id == "N" else MINIMAL_SYSTEM_PROMPT
    assert other not in serialized


@pytest.mark.asyncio
async def test_natural_history_is_isolated_per_episode(tmp_path: Any) -> None:
    """两个 episode 各一段历史；同一会话里的第二轮能看到第一轮。"""
    gateway = ScriptedGateway(["第一段回复", "别段回复", "第二轮回复"])
    adapter = make_natural("P", gateway)
    case = make_case(tmp_path)

    await adapter.run_turn(make_turn(case, user_text="第一个 scenario 的开场", session_id="ep-1"))
    await adapter.run_turn(make_turn(case, user_text="第二个 scenario 的开场", session_id="ep-2"))

    second = gateway.requests[1]["messages"]
    assert all("第一个 scenario 的开场" not in message["content"] for message in second)
    assert all("第一段回复" not in message["content"] for message in second)

    await adapter.run_turn(make_turn(case, user_text="同会话追问", turn=2, session_id="ep-1"))
    third = gateway.requests[2]["messages"]
    assert [message["role"] for message in third] == ["system", "user", "assistant", "user"]
    assert third[1]["content"] == "第一个 scenario 的开场"
    assert third[2]["content"] == "第一段回复"
    assert third[3]["content"] == "同会话追问"


@pytest.mark.asyncio
async def test_open_case_resets_history(tmp_path: Any) -> None:
    """新 episode 必须从干净历史开始（否则上一个场景会被当成「说过了」）。"""
    gateway = ScriptedGateway(["第一次回复", "第二次回复"])
    adapter = make_natural("N", gateway)
    case = make_case(tmp_path)
    await adapter.run_turn(make_turn(case, user_text="第一次", session_id="ep-1"))
    await adapter.open_case(case=case, session_id="ep-1", account_id="acct-synthetic")
    outcome = await adapter.run_turn(make_turn(case, user_text="重新开始", session_id="ep-1"))

    assert outcome.trace["history_messages_before"] == 0
    assert [message["role"] for message in gateway.requests[1]["messages"]] == ["system", "user"]


@pytest.mark.asyncio
async def test_empty_model_reply_is_no_output(tmp_path: Any) -> None:
    """空回复是模型的真实产出，记 `no_output`（不是 error，也不重试）。"""
    gateway = ScriptedGateway([""])
    adapter = make_natural("N", gateway)
    outcome = await adapter.run_turn(make_turn(make_case(tmp_path), user_text="孩子不吃饭"))
    assert outcome.status == "no_output"
    assert outcome.raw_output == ""
    assert outcome.has_output is False


@pytest.mark.asyncio
async def test_chat_failure_does_not_leak_endpoint_detail(tmp_path: Any) -> None:
    """失败只留类型：原始消息可能带端点/凭据细节，不能进轨迹。"""
    gateway = ScriptedGateway([RuntimeError("connect to https://tokenhub.example/v1 failed with key sk-x")])
    adapter = make_natural("P", gateway)
    outcome = await adapter.run_turn(make_turn(make_case(tmp_path), user_text="孩子打人"))
    assert outcome.status == "error"
    assert outcome.error_type == "RuntimeError"
    dumped = json.dumps(outcome.trace, ensure_ascii=False)
    assert "tokenhub.example" not in dumped
    assert "sk-x" not in dumped


# ---------------------------------------------------------------------------
# C：应急首次轮 / 后续轮 / 日常入口
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emergency_first_turn_activates_skill_and_injects_empty_profile_memory(
    tmp_path: Any, settings_for_tests: Any
) -> None:
    """应急首次轮 = 产品 `POST /consult/emergency` 的形状：激活 + 空档案/空记忆 + 八项首条消息。"""
    runner = ScriptedRunner(finished("先把周围清空，陪着他。"))
    system = make_agent(settings_for_tests, runner)
    # 风险标签写「日常」：入口只看事前冻结的 entry，不看这个字段。
    case = make_case(tmp_path, risk_hint="日常照护，无风险")
    user_text = "他突然用头撞墙，我一个人按不住"
    outcome = await system.run_turn(make_turn(case, user_text=user_text, entry=ENTRY_EMERGENCY))

    assert outcome.status == "completed"
    request = runner.requests[0]
    assert [skill.name for skill in request.activated] == ["emergency-consulting"]
    assert len(request.activated_record) == 2
    call, output = request.activated_record
    assert call["name"] == "skill"
    assert json.loads(call["arguments"]) == {"name": "emergency-consulting"}
    assert output["call_id"] == call["call_id"]
    assert EMERGENCY_SKILL_NAME in json.dumps(output["output"], ensure_ascii=False)

    assert [item.source for item in request.injections.items] == [
        EMERGENCY_PROFILE_SOURCE,
        EMERGENCY_MEMORY_SOURCE,
    ]
    profile_text = request.injections.items[0].content
    memory_text = request.injections.items[1].content
    assert profile_text.startswith(EMERGENCY_PROFILE_PREFIX)
    assert 'state="absent"' in profile_text
    assert "本次未使用个性化档案" in profile_text
    assert memory_text.startswith(EMERGENCY_MEMORY_PREFIX)
    assert 'state="empty"' in memory_text
    assert request.injections.unavailable == ()

    assert request.user_input.startswith(EMERGENCY_INTAKE_PREFIX)
    assert f"what_happened：{user_text}" in request.user_input
    assert request.user_input.count(UNCOLLECTED_MARK) == 7
    # 产品应急入口不传默认工具集：本轮工具由激活的 skill 决定。
    assert request.default_active_tools == ()
    assert request.context_payload == {ACCOUNT_PAYLOAD_KEY: "acct-synthetic"}

    serialized = json.dumps(
        {
            "user_input": request.user_input,
            "injections": [item.content for item in request.injections.items],
        },
        ensure_ascii=False,
    )
    assert HIDDEN_FACT not in serialized
    assert "旧形状的问题文本" not in serialized

    assert outcome.trace["interactive"]["entry"] == ENTRY_EMERGENCY
    assert outcome.trace["interactive"]["first_emergency_turn"] is True
    assert outcome.trace["run_request"]["activated"] == ["emergency-consulting"]
    assert outcome.trace["run_request"]["injections"] == 2
    assert outcome.trace["interactive"]["request"]["injection_items"] == [
        {"source": item.source, "role": item.role, "content": item.content} for item in request.injections.items
    ]
    assert outcome.meta["activated_skills"] == []


@pytest.mark.asyncio
async def test_emergency_followup_continues_without_reinjection(tmp_path: Any, settings_for_tests: Any) -> None:
    """应急会话的第二轮：同一会话、原样输入、不再激活、不再注入。"""
    runner = ScriptedRunner(finished())
    system = make_agent(settings_for_tests, runner)
    case = make_case(tmp_path)
    user_text = "他还在撞，我需要叫救护车吗"
    outcome = await system.run_turn(make_turn(case, user_text=user_text, entry=ENTRY_EMERGENCY, turn=2))

    request = runner.requests[0]
    assert request.session_id == "s1"
    assert request.activated == ()
    assert request.activated_record == ()
    assert request.injections.items == ()
    assert request.injections.unavailable == ()
    assert request.user_input == user_text
    assert request.default_active_tools == DAILY_TOOLS
    assert outcome.trace["run_request"]["injections"] == 0
    assert outcome.trace["interactive"]["request"]["injection_items"] == []
    assert outcome.trace["interactive"]["first_emergency_turn"] is False
    assert outcome.meta["activated_skills"] == []


@pytest.mark.asyncio
async def test_daily_entry_never_activates_emergency_even_when_urgent(tmp_path: Any, settings_for_tests: Any) -> None:
    """daily 入口即使场景写着紧急，也不切应急（这条负控就是「系统会不会自己乱切」的判据）。"""
    runner = ScriptedRunner(finished())
    system = make_agent(settings_for_tests, runner)
    case = make_case(tmp_path, risk_hint="紧急：必须走应急入口")
    user_text = "他刚才差点冲到马路上"
    outcome = await system.run_turn(make_turn(case, user_text=user_text, entry=ENTRY_DAILY))

    request = runner.requests[0]
    assert request.activated == ()
    assert request.activated_record == ()
    assert request.injections.items == ()
    assert request.user_input == user_text
    assert request.default_active_tools == DAILY_TOOLS
    assert outcome.trace["run_request"]["activated"] == []


def test_emergency_skill_name_matches_product() -> None:
    """本模块写的技能名必须与产品常量一致（否则应急轮会静默装配失败）。"""
    assert EMERGENCY_SKILL_NAME == consult_assembly.EMERGENCY_SKILL_NAME


def test_missing_emergency_skill_fails_loudly(
    tmp_path: Any, settings_for_tests: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """内容目录里没有应急技能时，构建应急请求必须抛错，不能降级成日常。"""
    stub = SimpleNamespace(names=lambda: ("daily-consulting",))
    monkeypatch.setattr(consult_assembly, "get_skill_registry", lambda _settings: stub)
    system = make_agent(settings_for_tests, ScriptedRunner(finished()))
    with pytest.raises(consult_assembly.ConsultAssemblyError, match="emergency-consulting"):
        system._build_request(make_turn(make_case(tmp_path), user_text="他撞墙了", entry=ENTRY_EMERGENCY))


def test_overlong_emergency_text_fails_instead_of_truncating(tmp_path: Any, settings_for_tests: Any) -> None:
    """超出产品八项采集上界的文本原样失败（产品会 422）：截断会把场景改短。"""
    system = make_agent(settings_for_tests, ScriptedRunner(finished()))
    with pytest.raises(ValidationError):
        system._build_request(make_turn(make_case(tmp_path), user_text="啊" * 501, entry=ENTRY_EMERGENCY))


@pytest.mark.parametrize("turn", [0, -1])
def test_non_positive_turn_is_rejected(tmp_path: Any, settings_for_tests: Any, turn: int) -> None:
    """轮次从 1 起：应急首轮判据依赖它，0/-1 会静默重复注入。"""
    system = make_agent(settings_for_tests, ScriptedRunner(finished()))
    with pytest.raises(ValueError, match="轮次从 1 起"):
        system._build_request(make_turn(make_case(tmp_path), user_text="他撞墙了", entry=ENTRY_EMERGENCY, turn=turn))


# ---------------------------------------------------------------------------
# C：产物与来源元数据
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_output_tool_trace_and_source_metadata_are_preserved(
    tmp_path: Any, settings_for_tests: Any
) -> None:
    """卡片/提问、工具调用、引用元数据全保留；检索正文标注为「未保存」而不是补写。"""
    record = CitationRecord(
        citation_id="cite-1",
        run_id="run-1",
        source="library",
        reference="entry-autism-001",
        recorded_at=datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
        summary="关于感官过载的处置",
        status="published",
        applicable_scope="学龄前·家庭场景",
        withdrawn=False,
    )
    events: list[Any] = [
        RunStartedEvent(
            run_id="run-1",
            session_id="s1",
            surface=SURFACE,
            model="scripted-model",
            activated_skills=("emergency-consulting",),
            injection_sources=(EMERGENCY_PROFILE_SOURCE, EMERGENCY_MEMORY_SOURCE),
            appended_messages=2,
        ),
        ToolCallStartedEvent(tool_name="search_knowledge", call_id="call-1"),
        ToolCallFinishedEvent(
            tool_name="search_knowledge",
            call_id="call-1",
            ok=True,
            error_code=None,
            summary="命中 2 条",
        ),
        CitationEvent(citation=record),
        TextDeltaEvent(delta="先把能碰伤他的东西挪开。"),
        ActionCardEvent(
            card_id="card-1",
            title="现在先做",
            sections=(ActionCardSection("now", "现在", ("清空周围硬物",)),),
            states=(ActionCardState("breathing", "unknown"),),
            annotations=(),
        ),
        QuestionEvent(
            batch_id="batch-1",
            items=(
                QuestionItem(id="q1", prompt="他有没有呼吸急促？", options=(QuestionOption("有"),), allow_skip=True),
            ),
        ),
        RunFinishedEvent(
            reason="completed",
            citations=(record,),
            usage=RunUsage(requests=1, input_tokens=3, output_tokens=4, total_tokens=7),
            elapsed_seconds=0.02,
        ),
    ]
    system = make_agent(settings_for_tests, ScriptedRunner(events))
    outcome = await system.run_turn(make_turn(make_case(tmp_path), user_text="他撞墙", entry=ENTRY_EMERGENCY))

    assert outcome.status == "completed"
    assert [block["kind"] for block in outcome.structured] == ["action_card", "question"]
    assert "清空周围硬物" in outcome.output_text
    assert "他有没有呼吸急促？" in outcome.output_text
    assert outcome.tool_calls == [
        {
            "name": "search_knowledge",
            "call_id": "call-1",
            "ok": True,
            "error_code": None,
            "summary": "命中 2 条",
        }
    ]
    assert outcome.citations[0]["reference"] == "entry-autism-001"

    source_metadata = outcome.trace["source_metadata"]
    assert source_metadata["retrieval_snippets_captured"] is False
    assert source_metadata["citation_records"][0]["applicable_scope"] == "学龄前·家庭场景"
    assert source_metadata["citation_records"][0]["status"] == "published"
    assert source_metadata["citation_records"][0]["recorded_at"] == "2026-10-29T12:00:00+00:00"
    assert source_metadata["search_tool_calls"][0]["ok"] is True
    # 轨迹必须可 JSON 落盘（引用记录带 datetime，序列化由本适配器负责）。
    assert json.loads(json.dumps(outcome.trace, ensure_ascii=False))["source_metadata"]


# ---------------------------------------------------------------------------
# 装配
# ---------------------------------------------------------------------------


def test_build_interactive_adapters_returns_npc_and_keeps_gateway_open(
    settings_for_tests: Any, config_for_tests: RunConfig
) -> None:
    """键恰为 N/P/C，三组共享同一个网关，且不声明所有权（关闭是调用方的事）。"""
    gateway = ScriptedGateway(["ok"])
    bundle = build_interactive_adapters(settings=settings_for_tests, config=config_for_tests, gateway=gateway)  # type: ignore[arg-type]
    assert tuple(sorted(bundle.adapters)) == ("C", "N", "P")
    assert bundle.gateway is gateway
    assert bundle.owns_gateway is False
    assert isinstance(bundle.adapters["N"], NaturalChatSystem)
    assert isinstance(bundle.adapters["P"], NaturalChatSystem)
    assert isinstance(bundle.adapters["C"], InteractiveAgentSystem)
    # C 必须是**真实产品适配器**的子类：复用它的运行链，只覆写请求装配。
    assert isinstance(bundle.adapters["C"], AgentSystem)


@pytest.mark.asyncio
async def test_bundle_close_does_not_close_borrowed_gateway(
    settings_for_tests: Any, config_for_tests: RunConfig
) -> None:
    """`aclose()` 只关适配器；网关由调用方持有（关闭它会让共享连接池被拔掉）。"""
    gateway = ScriptedGateway(["ok"])
    bundle = build_interactive_adapters(settings=settings_for_tests, config=config_for_tests, gateway=gateway)  # type: ignore[arg-type]
    await bundle.aclose()
    assert gateway.closed is False


def test_build_requires_external_gateway(settings_for_tests: Any, config_for_tests: RunConfig) -> None:
    """不替调用方造网关：传 None 直接拒绝（否则所有权与模型 id 都会失去唯一真源）。"""
    with pytest.raises(ValueError, match="gateway"):
        build_interactive_adapters(settings=settings_for_tests, config=config_for_tests, gateway=None)  # type: ignore[arg-type]
