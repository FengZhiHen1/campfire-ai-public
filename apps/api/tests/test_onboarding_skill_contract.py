"""onboarding 引导的终态合同：每一轮必须真的经 `ask_user` 提问，或真的收束。

对应缺陷 `docs/TODO.md` BUG-02（引导后续轮偶发只在正文追问、不发结构化提问卡）。
本文件守两件事：

1. **机械面**（BUG-02 的两个候选根因之一）：引导第三轮里 `ask_user` 与五个引导工具
   真的都可用——授权来自历史激活记录（`docs/技术设计/decisions/激活记录即授权真源.md`），
   `ask_user` 由基座恒可用。这两条任何一条被收回，`tool_not_available` 就会让模型只能
   改用正文说话，而使用者看到的是没有作答入口的文字。
2. **内容面**（真正的修复方向）：引导 skill 把「提问只能经 `ask_user`」写成硬约束并给出
   反例，且该约束必须出现在**模型读到的那份渲染产物里**（首轮注入的 `<skill_content>`，
   后续轮来自会话历史）——写在文档里但没进渲染载荷等于没写。

内容断言是词串级的，它能防「约束被删掉/退回模糊措辞」，但**不能**证明模型一定遵守：
BUG-02 是模型遵守度问题，遵守度只能用真实模型的校准对照观察（见提交说明）。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx2
import pytest
from agents import ModelSettings, SessionSettings
from agents.items import TResponseInputItem
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel

from campfire.agent.context import CitationRecord
from campfire.agent.model import ModelBinding
from campfire.agent.runtime import AgentRunner, RunRequest
from campfire.agent.runtime.ask_user_tool import ASK_USER_TOOL_NAME
from campfire.agent.runtime.events import QuestionEvent, RunFinishedEvent, RunStartedEvent, ToolCallFinishedEvent
from campfire.agent.skill_runtime import SkillRegistry, build_activation_record, render_activation
from campfire.surfaces.consult.assembly import CONSULT_INSTRUCTIONS
from campfire.surfaces.consult.composition import build_tool_pool

SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills"
ONBOARDING_ROOT = SKILL_ROOT / "onboarding"
BASE_URL = "https://tokenhub.test/v1"
MODEL_NAME = "test-model"

#: 引导激活后模型侧可用的五个产品工具（`SKILL.md` 的 `allowed-tools`）。
ONBOARDING_PRODUCT_TOOLS = (
    "create_support_object",
    "finish_onboarding",
    "propose_profile_item",
    "read_profile_items",
    "write_memory",
)


# --- 替身 -------------------------------------------------------------------


class FakeSession:
    """会话替身：内存列表，与 SDK 的 `Session` 协议同形。"""

    def __init__(self, session_id: str, items: Sequence[TResponseInputItem] | None = None) -> None:
        self.session_id = session_id
        self.session_settings: SessionSettings | None = None
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

    def __init__(self) -> None:
        self.records: list[CitationRecord] = []

    async def add(self, record: CitationRecord) -> None:
        self.records.append(record)

    async def list_for_run(self, run_id: str) -> Sequence[CitationRecord]:
        return [record for record in self.records if record.run_id == run_id]


def _chunk(delta: Mapping[str, object], finish_reason: str | None = None) -> str:
    payload = {
        "id": "chatcmpl-onboarding",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": MODEL_NAME,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n"


def _sse(*chunks: str) -> bytes:
    return ("".join(chunks) + "data: [DONE]\n\n").encode()


def tool_call_reply(name: str, arguments: Mapping[str, object], *, call_id: str = "call-1") -> bytes:
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
                        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
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

    async def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        body = self._script.pop(0) if self._script else tool_call_reply(ASK_USER_TOOL_NAME, _ask_args())
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    @property
    def messages_seen(self) -> list[list[dict[str, Any]]]:
        """每次请求里模型看到的 messages。"""
        return [list(request.get("messages", [])) for request in self.requests]


def _binding(chat: ScriptedChat) -> ModelBinding:
    from openai import AsyncOpenAI

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(chat.handler))
    return ModelBinding(
        name=MODEL_NAME,
        model=OpenAIChatCompletionsModel(
            model=MODEL_NAME,
            openai_client=AsyncOpenAI(api_key="test-key", base_url=BASE_URL, max_retries=0, http_client=client),
        ),
        settings=ModelSettings(),
    )


# --- 第三轮会话的合成历史 ------------------------------------------------------


def _ask_args(prompt: str = "如果只能用一种方式问他问题，哪种最容易得到回答？") -> Mapping[str, object]:
    return {
        "items": [
            {
                "id": "seed-3",
                "prompt": prompt,
                "options": [{"label": "Yes/No"}, {"label": "二选一"}],
                "allow_skip": True,
            }
        ]
    }


def _ask_user_pair(call_id: str, prompt: str) -> list[dict[str, object]]:
    return [
        {
            "type": "function_call",
            "call_id": call_id,
            "name": ASK_USER_TOOL_NAME,
            "arguments": json.dumps(_ask_args(prompt), ensure_ascii=False),
        },
        {
            "type": "function_call_output",
            "call_id": call_id,
            "output": "已向使用者发出提问，本次运行到此结束；回答会作为下一条消息到达。",
        },
    ]


def _answers_message(question_id: str, value: str) -> dict[str, object]:
    return {"role": "user", "content": f"以下是对提问的作答\n{question_id}：{value}\n（本组批次标识：batch-x）"}


def _third_round_history(skill) -> list[TResponseInputItem]:
    """「告知已发、对象已建、种子前两问已答」的历史：引导第三轮的起点。

    形状与生产落库一致：合成激活记录对（应用侧）、`ask_user` 的真实调用对、回答渲染的
    使用者消息。它是 BUG-02 复现时的那一轮——模型在这一轮要么再问一次，要么收束。
    """
    call, output = build_activation_record(skill, call_id="app-activate-1")
    history: list[dict[str, object]] = [
        {"role": "assistant", "content": "【应用告知】本次输入的内容用于生成回答……"},
        dict(call),
        dict(output),
        {"role": "user", "content": "孩子五岁，最近超市里一放音乐就捂耳朵、原地不动，我该怎么做？"},
        {
            "type": "function_call",
            "call_id": "call-obj",
            "name": "create_support_object",
            "arguments": json.dumps({"display_name": "小满"}, ensure_ascii=False),
        },
        {
            "type": "function_call_output",
            "call_id": "call-obj",
            "output": '{"support_object_id": "obj-1", "display_name": "小满"}',
        },
        *_ask_user_pair("call-q1", "在平常的日子里，他一般怎么和你交流？"),
        _answers_message("q1", "能说完整句子"),
        *_ask_user_pair("call-q2", "有没有哪些情况，你们已经知道会让他变得很难受？"),
    ]
    return history  # type: ignore[return-value]  # 形状与 SDK 输入项一致（与 tests/test_agent_runtime.FakeSession 的同一处理）


def _request() -> RunRequest:
    return RunRequest(
        session_id="s-onboarding",
        surface="consult",
        instructions=CONSULT_INSTRUCTIONS,
        user_input="以下是对提问的作答\nq2：很大的声音\n（本组批次标识：batch-x）",
        context_payload={"account_id": "acc-1"},
    )


def _runner(*, chat: ScriptedChat, session: FakeSession, skills: SkillRegistry) -> AgentRunner:
    return AgentRunner(
        binding=_binding(chat),
        tools=build_tool_pool(skills),
        skills=skills,
        citations=FakeCitationIndex(),
        sessions=lambda session_id: session,
    )


async def _collect(runner: AgentRunner) -> list[object]:
    return [event async for event in runner.run(_request())]


def _available_tools(messages: Sequence[Mapping[str, Any]]) -> frozenset[str]:
    """从注入的 `<tool_availability>` 里取「此刻可用」的工具名。"""
    for message in messages:
        content = message.get("content")
        if not isinstance(content, str) or "<tool_availability>" not in content:
            continue
        available = content.split("<unavailable_tools>")[0]
        return frozenset(line.split('"')[1] for line in available.splitlines() if '<tool name="' in line)
    raise AssertionError("本轮没有注入 <tool_availability>：可用范围无从判定")


# --- 1. 机械面：第三轮的工具范围 ------------------------------------------------


def test_third_onboarding_round_exposes_ask_user_and_every_onboarding_tool() -> None:
    """引导第三轮必须仍可用 `ask_user` 与五个引导工具（授权跨运行，`ask_user` 恒可用）。

    判别性：把 `ask_user` 从运行编排的恒可用集合里去掉，或让历史激活记录不再推导出
    onboarding，本用例立刻变红。BUG-02 的「工具暴露时机」假设正是被这条排除的——
    第三轮并不是工具被收回，模型只是没调用。
    """
    skills = SkillRegistry.discover(SKILL_ROOT)
    skill = skills.get("onboarding")
    chat = ScriptedChat([tool_call_reply(ASK_USER_TOOL_NAME, _ask_args(), call_id="call-q3")])
    session = FakeSession("s-onboarding", _third_round_history(skill))
    runner = _runner(chat=chat, session=session, skills=skills)

    events = asyncio.run(_collect(runner))

    started = events[0]
    assert isinstance(started, RunStartedEvent)
    # 本轮请求不携带任何激活：生效集合只能来自历史激活记录。
    assert started.activated_skills == ("onboarding",)

    available = _available_tools(chat.messages_seen[0])
    for tool in (ASK_USER_TOOL_NAME, *ONBOARDING_PRODUCT_TOOLS):
        assert tool in available, f"第三轮的可用工具里缺 {tool}：模型只剩正文这条路"

    finishes = [event for event in events if isinstance(event, ToolCallFinishedEvent)]
    assert [(event.tool_name, event.ok, event.error_code) for event in finishes] == [(ASK_USER_TOOL_NAME, True, None)]
    assert any(isinstance(event, QuestionEvent) for event in events), "提问必须变成可作答的提问事件"
    assert isinstance(events[-1], RunFinishedEvent)


def test_the_prompt_fix_reaches_the_model_in_a_later_round() -> None:
    """硬约束必须出现在**模型读到的那份渲染载荷**里（首轮注入 / 后续轮的历史）。

    只改 `SKILL.md` 的正文而渲染路径漏掉它（例如换渲染函数、截断正文），这条会红。
    """
    skills = SkillRegistry.discover(SKILL_ROOT)
    payload = render_activation(skills.get("onboarding"))
    assert ASK_USER_TOOL_NAME in payload
    assert "提问的唯一通道" in payload
    assert "正文里不写问题" in payload or "不在正文里问" in payload


# --- 2. 内容面：硬约束与反例 ---------------------------------------------------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_onboarding_skill_states_the_hard_constraint_and_the_counterexample() -> None:
    """硬约束、四条禁令里的关键两条、真实事故形状的反例都在 `SKILL.md` 正文里。"""
    body = _read(ONBOARDING_ROOT / "SKILL.md")

    assert "## 提问的唯一通道（硬约束）" in body
    # 判据句：提问是唯一通道，且必须落在 items 里。
    assert f"`{ASK_USER_TOOL_NAME}` 的 `items`" in body
    # 禁令 1、2：不在正文里问、不预告题单。
    assert "不在正文里问" in body
    assert "不预告题单" in body
    # 反例必须是**真实事故形状**（BUG-02 那一轮的原话形态），否则反例不可辨。
    assert "接下来还有几道题" in body
    assert "没有作答入口" in body


def test_onboarding_content_names_the_tool_of_every_questioning_rule() -> None:
    """凡引导内容里要求提问之处，都点名 `ask_user`——不留「结构化提问事件」这种无主语措辞。

    为什么这条值得机械守：BUG-02 的事故形态正是「约束抽象成机制名，模型照着机制名说不出
    该调哪个工具」。退回模糊措辞即红。
    """
    for relative in ("SKILL.md", "references/seed-questions.md", "references/telling-first.md"):
        text = _read(ONBOARDING_ROOT / relative)
        assert "结构化提问事件" not in text, f"{relative} 退回模糊措辞：应点名 {ASK_USER_TOOL_NAME}"

    seeds = _read(ONBOARDING_ROOT / "references" / "seed-questions.md")
    discipline = seeds.split("## 1. 提问纪律")[1].split("## 2.")[0]
    assert ASK_USER_TOOL_NAME in discipline, "seed-questions.md 的提问纪律没有点名 ask_user"
    assert "正文里不写问题" in discipline

    telling = _read(ONBOARDING_ROOT / "references" / "telling-first.md")
    order_rule = [line for line in telling.splitlines() if "首条 assistant 消息之前" in line]
    assert order_rule, "telling-first.md 的「先告知后询问」顺序约束不见了"
    assert any(ASK_USER_TOOL_NAME in line for line in order_rule), "顺序约束应点名 ask_user"


@pytest.mark.parametrize("tool", ["ask_user"])
def test_ask_user_stays_a_reserved_base_tool_outside_allowed_tools(tool: str) -> None:
    """`ask_user` 不进 `allowed-tools`：它是基座保留名，恒可用，写进内容产物即失败。

    这条防一种「看似修好」的错误修法：把 `ask_user` 塞进 `allowed-tools`——那既不会让
    模型更愿意调用它（模型看不到 frontmatter），还会让技能以为自己能声明一个机制工具。
    """
    frontmatter = _read(ONBOARDING_ROOT / "SKILL.md").split("---")[1]
    allowed = next(line for line in frontmatter.splitlines() if line.startswith("allowed-tools:"))
    assert tool not in allowed
