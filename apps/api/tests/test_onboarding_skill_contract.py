"""onboarding 引导的提问通道：问句只能进 `ask_user`，且机械面真的给得起这个工具。

对应缺陷 `docs/TODO.md` BUG-02（引导后续轮偶发只在正文追问、不发结构化提问卡）。
本文件守三层，判据都在这里，别处不重复：

1. **机械面**（BUG-02 三个候选根因里被排除的两个）：引导第三轮里 `ask_user` 与五个引导
   工具真的都可用——授权来自历史激活记录（`docs/技术设计/decisions/激活记录即授权真源.md`），
   `ask_user` 由基座恒可用。
2. **指令面**：基座 `ask_user` 的工具描述同时表达两种合法用法（同一批一起确认 → 同批多题；
   流程分阶段 → 按阶段每轮一题），且不含任何领域词；引导正文把「问句只能进 `items`」写成
   短合同并给正例。
3. **可复现校准**（文件末尾的 `__main__`）：合成「引导第三轮」状态的 fixture 就在本文件里，
   真模型校准用 `python apps/api/tests/test_onboarding_skill_contract.py --runs 4` 跑。

内容断言是词串级的：它能防「合同被删掉 / 退回模糊措辞 / 领域词漏进基座」，**不能**证明模型
一定遵守。BUG-02 是模型遵守度问题，遵守度只能用真实模型的校准观察，且不保证根治。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
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
from campfire.agent.runtime.ask_user_tool import ASK_USER_TOOL_NAME, build_ask_user_tool
from campfire.agent.runtime.events import (
    QuestionEvent,
    RunFailedEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextDeltaEvent,
    ToolCallFinishedEvent,
)
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

#: 基座工具描述里不得出现的领域词（基座不含领域术语，见通用基座第 1 节不变量）。
BASE_DESCRIPTION_FORBIDDEN_WORDS = ("引导", "onboarding", "档案", "应急", "照护", "支持对象")

#: `ask_user` 成功时的回执原文，与工具 handler 逐字一致（见 `test_accounts_session_items`）。
ASK_USER_OUTPUT = "已向使用者发出提问，本次运行到此结束；回答会作为下一条消息到达。"


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
        body = self._script.pop(0) if self._script else tool_call_reply(ASK_USER_TOOL_NAME, ask_args())
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


# --- 第三轮会话的合成状态（用例与校准共用同一份 fixture） ---------------------------


def ask_args(prompt: str = "如果只能用一种方式问他问题，哪种最容易得到回答？") -> Mapping[str, object]:
    """一次 `ask_user` 调用的参数（一道题、两个选项、可跳过）。"""
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


def ask_user_pair(call_id: str, prompt: str) -> list[dict[str, object]]:
    """一对真实形状的 `ask_user` 记录（调用 + 成功回执）。"""
    return [
        {
            "type": "function_call",
            "call_id": call_id,
            "name": ASK_USER_TOOL_NAME,
            "arguments": json.dumps(ask_args(prompt), ensure_ascii=False),
        },
        {"type": "function_call_output", "call_id": call_id, "output": ASK_USER_OUTPUT},
    ]


def answers_message(question_id: str, value: str) -> dict[str, object]:
    """回答渲染成的使用者消息（与 `surfaces/consult/answers.render_answers` 同形）。"""
    return {"role": "user", "content": f"以下是对提问的作答\n{question_id}：{value}\n（本组批次标识：batch-x）"}


def third_round_history(skill, *, seed_list_text: str | None = None) -> list[TResponseInputItem]:
    """「告知已发、对象已建、种子前两问已答」的历史：引导第三轮的起点。

    形状与生产落库一致：合成激活记录对（应用侧）、`create_support_object` 调用对、
    `ask_user` 的真实调用对、回答渲染的使用者消息。`seed_list_text` 给出时再补一对
    `read_skill_resource` 记录（题单全文已在上下文里）——2026-10-28 那一轮最可能的输入
    状态：事故文案「接下来八道题……第一道关于他……」说明题单当时就在模型手里。
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
    ]
    if seed_list_text is not None:
        history.extend(
            [
                {
                    "type": "function_call",
                    "call_id": "call-seeds",
                    "name": "read_skill_resource",
                    "arguments": json.dumps(
                        {"skill": "onboarding", "path": "references/seed-questions.md"}, ensure_ascii=False
                    ),
                },
                {"type": "function_call_output", "call_id": "call-seeds", "output": seed_list_text},
            ]
        )
    history.extend(
        [
            *ask_user_pair("call-q1", "在平常的日子里，他一般怎么和你交流？"),
            answers_message("q1", "能说完整句子"),
            *ask_user_pair("call-q2", "有没有哪些情况，你们已经知道会让他变得很难受？"),
        ]
    )
    return history  # type: ignore[return-value]  # 形状与 SDK 输入项一致（与 FakeSession 的同一处理）


def third_round_request() -> RunRequest:
    """第三轮请求：不携带任何激活（授权只能来自历史），使用者最新消息是 q2 的作答。"""
    return RunRequest(
        session_id="s-onboarding",
        surface="consult",
        instructions=CONSULT_INSTRUCTIONS,
        user_input=str(answers_message("q2", "很大的声音")["content"]),
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
    return [event async for event in runner.run(third_round_request())]


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
    chat = ScriptedChat([tool_call_reply(ASK_USER_TOOL_NAME, ask_args(), call_id="call-q3")])
    session = FakeSession("s-onboarding", third_round_history(skill))
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


def test_the_contract_reaches_the_model_in_a_later_round() -> None:
    """合同必须出现在**模型读到的那份渲染载荷**里（首轮注入，后续轮来自会话历史）。

    只改 `SKILL.md` 而渲染路径漏掉它（换渲染函数、截断正文），这条会红。
    """
    skills = SkillRegistry.discover(SKILL_ROOT)
    payload = render_activation(skills.get("onboarding"))
    assert ASK_USER_TOOL_NAME in payload
    assert "提问的唯一通道" in payload
    assert "只能出现在" in payload


# --- 2. 指令面：基座工具描述与引导内容 -------------------------------------------


def test_ask_user_description_states_both_legal_shapes_without_domain_words() -> None:
    """基座 `ask_user` 描述同时表达两种合法用法，且不含领域词。

    判别性：退回「一次调用要把该问的一次问完，不要一道道分次提问」这种**无条件**措辞，
    就与「流程按阶段每轮一题」（引导就是这种流程）直接矛盾——本用例把两种用法都钉住，
    并断言那个矛盾措辞不再出现。领域词断言对应另一条裁决：引导语义只写在 skill 内容里，
    不塞进公共工具描述（基座不含领域术语）。
    """
    description = build_ask_user_tool().description

    # 批量用法（一次性信息补齐）：这批答案一起确认 → 同一次调用。
    assert "一起确认" in description
    assert "items" in description
    # 分阶段用法：按阶段每轮一题合法。
    assert "分阶段" in description and "每轮一题" in description
    # 无条件禁令不得残留（正是本次修掉的矛盾）。
    assert "不要一道道分次提问" not in description
    assert "一次问完" not in description

    for word in BASE_DESCRIPTION_FORBIDDEN_WORDS:
        assert word not in description, f"基座工具描述里出现领域词 {word!r}"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_onboarding_skill_states_the_short_contract() -> None:
    """引导正文的合同要短而可执行：一处通道 + 一轮一题 + 正例。"""
    body = _read(ONBOARDING_ROOT / "SKILL.md")

    assert "## 提问的唯一通道（硬约束）" in body
    assert f"`{ASK_USER_TOOL_NAME}` 的 `items`" in body
    assert "正文里不写问句" in body and "不预告题目" in body
    assert "一次调用只放一道题" in body
    # 正例必须真的是一段 `ask_user` 调用（模型可照着写的那种）。
    assert f"{ASK_USER_TOOL_NAME}(items=[" in body
    assert '"allow_skip": true' in body


def test_onboarding_content_names_the_tool_of_every_questioning_rule() -> None:
    """凡引导内容里要求提问之处，都点名 `ask_user`——不留「结构化提问事件」这种无主语措辞。"""
    for relative in ("SKILL.md", "references/seed-questions.md", "references/telling-first.md"):
        text = _read(ONBOARDING_ROOT / relative)
        assert "结构化提问事件" not in text, f"{relative} 退回模糊措辞：应点名 {ASK_USER_TOOL_NAME}"

    seeds = _read(ONBOARDING_ROOT / "references" / "seed-questions.md")
    discipline = seeds.split("## 1. 提问纪律")[1].split("## 2.")[0]
    assert ASK_USER_TOOL_NAME in discipline
    assert "正文里不写问题" in discipline

    telling = _read(ONBOARDING_ROOT / "references" / "telling-first.md")
    order_rule = [line for line in telling.splitlines() if "首条 assistant 消息之前" in line]
    assert order_rule, "telling-first.md 的「先告知后询问」顺序约束不见了"
    assert any(ASK_USER_TOOL_NAME in line for line in order_rule)


@pytest.mark.parametrize("tool", [ASK_USER_TOOL_NAME])
def test_ask_user_stays_a_reserved_base_tool_outside_allowed_tools(tool: str) -> None:
    """`ask_user` 不进 `allowed-tools`：它是基座保留名，恒可用，写进内容产物即失败。

    防一种「看似修好」的错误修法：把它塞进 `allowed-tools`——模型看不到 frontmatter，
    那既不会让它更愿意调用，还会让技能以为自己能声明一个机制工具。
    """
    frontmatter = _read(ONBOARDING_ROOT / "SKILL.md").split("---")[1]
    allowed = next(line for line in frontmatter.splitlines() if line.startswith("allowed-tools:"))
    assert tool not in allowed


# --- 3. 可复现校准（真模型；手工运行，不是 pytest 用例）---------------------------
#
# 为什么脚本化替身代替不了这一节：BUG-02 是**模型遵守度**问题，脚本化模型永远按剧本调用
# 工具，看不出遵守度。校准只替换「会话存储」（内存替身），装配走生产入口
# （`ModelGateway` + `composition.build_tool_pool` + 真实 `SkillRegistry`）。
#
# 运行：
#     .venv/bin/python apps/api/tests/test_onboarding_skill_contract.py --runs 4
#     .venv/bin/python apps/api/tests/test_onboarding_skill_contract.py --runs 4 --state seeds
#     .venv/bin/python apps/api/tests/test_onboarding_skill_contract.py --runs 4 --skill-root <内容快照目录>
#
# 记数与判读纪律：**每次尝试都进分母**。模型端点 5xx（`failed == "model_unavailable"`）不是
# 模型行为观测，但**不从分母里剔除**——报告写「尝试 N 次 / 完成 M 次 / 端点失败 K 次」。
# 结论只到「这批输入下模型是否经工具提问」，不外推到发生率。


class _NoopCitations:
    """校准用的引用索引替身（要让工具真跑，索引不能报错）。"""

    async def add(self, record: CitationRecord) -> None:
        return None

    async def list_for_run(self, run_id: str) -> Sequence[CitationRecord]:
        return []


async def _calibration_attempt(*, skill_root: str, with_seed_list: bool) -> dict[str, object]:
    """跑一次真实模型运行，返回「是否经 `ask_user` 提问」等观测。"""
    from campfire.agent.model import ModelGateway
    from campfire.agent.model.proxy_env import normalized_no_proxy_environment
    from campfire.core.config import get_settings

    settings = get_settings()
    skills = SkillRegistry.discover(skill_root)
    skill = skills.get("onboarding")
    seed_text = (
        (Path(skill_root) / "onboarding" / "references" / "seed-questions.md").read_text(encoding="utf-8")
        if with_seed_list
        else None
    )
    session = FakeSession("s-calibration", third_round_history(skill, seed_list_text=seed_text))
    gateway = ModelGateway(settings)
    try:
        runner = AgentRunner(
            binding=gateway.binding,
            tools=build_tool_pool(skills),
            skills=skills,
            citations=_NoopCitations(),
            sessions=lambda session_id: session,
            timeout_seconds=240.0,
        )
        with normalized_no_proxy_environment():
            events = [event async for event in runner.run(third_round_request())]
    finally:
        await gateway.aclose()

    failed = next((event.code for event in events if isinstance(event, RunFailedEvent)), None)
    tools = [(event.tool_name, event.ok) for event in events if isinstance(event, ToolCallFinishedEvent)]
    text = "".join(event.delta for event in events if isinstance(event, TextDeltaEvent))
    return {
        "asked_via_tool": any(isinstance(event, QuestionEvent) for event in events),
        "tool_calls": tools,
        "failed": failed,
        "final_text_head": text.strip().replace("\n", " / ")[:160],
        "final_text_chars": len(text),
    }


def _calibration_main(argv: Sequence[str]) -> int:
    """校准入口：逐次打印观测，最后打印分母与命中数。"""
    parser = argparse.ArgumentParser(description="引导第三轮的 ask_user 遵守度校准（真模型）")
    parser.add_argument("--skill-root", default=str(SKILL_ROOT), help="skill 内容根目录（默认仓库内）")
    parser.add_argument("--runs", type=int, default=4, help="尝试次数（端点 5xx 也计一次尝试）")
    parser.add_argument("--state", choices=("plain", "seeds"), default="plain", help="历史里是否已含题单全文")
    parser.add_argument("--label", default="arm", help="打印用的臂名")
    args = parser.parse_args(list(argv))

    # 宿主机 no_proxy 里的 [::1] 会让 httpx2 在构造期失败（见 `agent/model/gateway` 的说明）。
    for key in ("no_proxy", "NO_PROXY"):
        if key in os.environ:
            os.environ[key] = os.environ[key].replace("[::1]", "::1")

    from agents import set_tracing_disabled

    set_tracing_disabled(True)

    results = []
    for index in range(1, args.runs + 1):
        result = asyncio.run(_calibration_attempt(skill_root=args.skill_root, with_seed_list=args.state == "seeds"))
        results.append(result)
        print(json.dumps({"label": args.label, "attempt": index, **result}, ensure_ascii=False), flush=True)

    endpoint_failures = sum(1 for item in results if item["failed"] == "model_unavailable")
    asked = sum(1 for item in results if item["asked_via_tool"])
    print(
        f"== {args.label}（state={args.state}）：尝试 {len(results)} 次，完成 {len(results) - endpoint_failures} 次，"
        f"端点失败 {endpoint_failures} 次，其中经 ask_user 提问 {asked} 次 ==",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_calibration_main(sys.argv[1:]))
