"""v0.2 多轮自然家长表达的 N / P / C 三组适配器（interactive 协议的唯一实现处）。

职责：把「家长自然说出的一句话」原样送进三条不同的装配——N 最小提示、P 原强提示、
C 真实产品 `AgentSystem`（含应急入口的首次程序激活）。

边界：旧模块（`systems/*`）只被**继承**，不修改；不跑批次、不落盘（主 Agent 的
`runner`/`storage`）；不做评审（`review.py`）。本模块不自己连库、不自己调模型：
会话、检索与工具全部走被复用的产品运行链；测试用脚本化网关与脚本化运行器替换的正是
「外部供应商」这一层，装配代码与生产路径完全相同。

三条与旧 40 例的差别（也就是本模块存在的理由）：

1. **输入是自然文本**：`InteractiveTurn.user_text` 原样进入对话。N/P 不包装
   「【已确认的背景信息】/【我的问题】」这类标题——旧批次把信息整理成结构化背景，
   这里要测的恰恰是「家长怎么说，系统能不能接住」。
2. **N/P 的历史按 episode 隔离**：一个 scenario（= 一个 case-group）一段独立 history，
   `open_case` 清空、续跑由已落盘轮次重建（复用 `ChatSystem` 的同一份实现）。
3. **C 是真实产品链**：继承 `systems.agent.AgentSystem`，行为差异集中在 `_build_request`：
   日常入口原样送 `user_text`；`entry=emergency` 的**首次**轮按 `POST /consult/emergency`
   的实际形状装配——程序激活 `emergency-consulting`、注入「空档案 + 空记忆」信封、
   把 `user_text` 渲染成八项现场采集的 `what_happened`。后续轮次沿同一会话继续，
   不再重复激活或注入（与产品「应急会话后续消息走 `send_message`」的形状一致）。
   另有三处薄覆写：`prepare` 核对应急技能存在并补装配事实、`_trace` 补来源元数据、
   `_runner_for` 提供脚本化运行器缝——运行链本身仍是产品的。

`entry` 是**事前冻结的场景标签**，不是风险判断：适配器只读这个字段，不读
`case.risk_hint`（urgent 场景可以落在 daily，用来测「系统会不会自己乱切入口」）。

来源核验口径：C 组 `trace` 里额外记录**能取得的**引用元数据（引用记录 + 检索工具调用），
并显式标注「检索正文未保存」——复核时不得据此声称读过全文，也不得补写没出现过的证据。
C 组是**程序内产品装配**（`AgentRunner.run`），**不是浏览器端到端**；
浏览器链路由 `e2e-real` 等验收流程覆盖，两者不可互相冒充。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from campfire.agent.context import InjectionBatch
from campfire.agent.model import ModelGateway
from campfire.agent.runtime import CitationEvent, RunRequest
from campfire.core.config import Settings
from campfire.modules.memory.derived import EmergencyMemory
from campfire.surfaces.consult.emergency import EmergencyItem
from campfire.surfaces.consult.injections import build_emergency_injections, render_emergency_intake

from .. import prompts
from ..config import RunConfig
from ..faults import FaultPlan
from ..hashing import sha256_text
from ..systems.agent import AgentSystem
from ..systems.base import (
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_NO_OUTPUT,
    SystemMeta,
    TurnInput,
    TurnOutcome,
)
from ..systems.build import AdapterBundle
from ..systems.chat import ChatSystem

#: 三组标识。取值即批次主键的一部分（case × 组别 = case-group）。
SYSTEM_N = "N"
SYSTEM_P = "P"
SYSTEM_C = "C"
INTERACTIVE_SYSTEM_IDS: tuple[str, str, str] = (SYSTEM_N, SYSTEM_P, SYSTEM_C)

#: 入口词表：场景事前冻结，适配器不得据此推断风险，也不得看 `risk_hint`。
ENTRY_DAILY = "daily"
ENTRY_EMERGENCY = "emergency"
ENTRIES: tuple[str, str] = (ENTRY_DAILY, ENTRY_EMERGENCY)

#: N 组的系统提示：只剩「助手是谁 + 基础边界」。
#:
#: 与 P 组共用的 `COMMON_TASK_INSTRUCTIONS` 相比，这里刻意不留：任务说明、现场条件
#: 优先级、追问纪律、正文纯文本格式。N 组要回答的问题是「最小提示下，模型自己能不能
#: 接住自然表达」——把 P 的约束抄过来，两组就只剩长度差异，对照失去意义。
MINIMAL_SYSTEM_PROMPT = (
    "你是一个用中文交流的助手，请帮助用户。"
    "不要编造事实，不确定时说明不确定。"
    "涉及紧急安全风险时建议及时寻求专业或紧急帮助。"
)

#: P 组的系统提示：原 v0.1 的 `COMMON_TASK_INSTRUCTIONS`，逐字复用（不复制一份）。
PROMPTED_SYSTEM_PROMPT = prompts.COMMON_TASK_INSTRUCTIONS

#: 组别 → 系统提示（只有 N/P 有；C 的提示来自产品面）。
GROUP_PROMPTS: dict[str, str] = {SYSTEM_N: MINIMAL_SYSTEM_PROMPT, SYSTEM_P: PROMPTED_SYSTEM_PROMPT}

#: 检索工具名（来源核验要按名字从工具轨迹里挑出来；名字取自产品工具池）。
SEARCH_TOOL_NAME = "search_knowledge"

#: 应急技能名（与产品 `assembly.EMERGENCY_SKILL_NAME` 同值）。
#:
#: 写常量而不是在模块导入期 import `surfaces.consult.assembly`：与旧适配器的延迟 import
#: 口径一致（`--help` 一类路径不该拉起整个 HTTP 面）。与产品常量的一致性由
#: `tests/test_interactive_adapters.py` 对照用例机械核对——这里写错会让应急轮静默装配失败。
EMERGENCY_SKILL_NAME = "emergency-consulting"


@dataclass(frozen=True)
class InteractiveTurn(TurnInput):
    """一次（scenario × 组别 × 轮次）的输入：自然文本 + 事前冻结的入口。

    `user_text` 是家长**原样**说出的一句话，三组收到的是同一个字符串（不同组别的差别
    只在装配，不在输入）。`entry` 只取 :data:`ENTRIES`：其它取值说明把场景标签写错或
    自己发明了入口，直接拒绝比让它静默按日常跑掉安全。

    轮次仍沿用基座的 1 起编号（见 :class:`~evaluation.carebench.systems.base.TurnInput`），
    :class:`InteractiveAgentSystem` 靠它区分「应急首次」与「应急后续」；两者混用会让
    首次轮的注入被重复施加。
    """

    #: 家长原样说的话（不做包装、不补背景）。
    user_text: str = ""
    #: 事前冻结的入口：`daily` / `emergency`。
    entry: str = ENTRY_DAILY

    def __post_init__(self) -> None:
        """校验入口词表。

        Raises:
            ValueError: `entry` 不在 :data:`ENTRIES` 内。
        """
        if self.entry not in ENTRIES:
            raise ValueError(f"未知入口 {self.entry!r}：只允许 {ENTRIES}")


def _require_user_text(request: TurnInput) -> str:
    """取原样自然输入，并拒绝空文本与旧形状的请求。

    Raises:
        TypeError: 传进来的不是 :class:`InteractiveTurn`（旧形状没有 `user_text`，
            强行取属性只会在别处炸成 AttributeError，诊断成本更高）。
        ValueError: `user_text` 为空白——空输入不是「家长没说话」的证据，
            而是调用方装配出错。
    """
    if not isinstance(request, InteractiveTurn):
        raise TypeError("interactive 适配器只接受 InteractiveTurn（自然输入在 user_text 里）")
    if not request.user_text.strip():
        raise ValueError("user_text 不能为空：自然输入是这三组唯一的输入")
    return request.user_text


class NaturalChatSystem(ChatSystem):
    """N / P：原样自然输入 + 每 episode 独立历史的单次对话调用。

    沿用 `ChatSystem` 的网关、超时与历史容器（`self._history` 以会话 id 为键、
    `open_case` 清空），只换掉两件事：系统提示按组别取（:data:`GROUP_PROMPTS`），
    使用者文本原样送出（不调 `prompts.render_user_turn`）。

    为什么不直接改 `ChatSystem.run_turn`：它的输入渲染与旧 40 例的
    「背景 + 问题」包装绑在一起，而旧协议逐字不改。因此这里覆盖 `run_turn`，
    保留同样的「计时起点在任何工作之前」「三样输出分开」「历史成功后才追加」口径。
    """

    def __init__(
        self,
        *,
        system_id: str,
        settings: Settings,
        config: RunConfig,
        gateway: ModelGateway,
    ) -> None:
        """绑定组别、配置与共享网关。

        Raises:
            ValueError: 组别不是 N/P（C 走 :class:`InteractiveAgentSystem`）。
        """
        if system_id not in GROUP_PROMPTS:
            raise ValueError(f"N/P 适配器不接受的组别 {system_id!r}")
        super().__init__(settings=settings, config=config, gateway=gateway)
        self.system_id = system_id

    # --- SystemAdapter ---
    async def prepare(self) -> SystemMeta:
        """返回装配事实（提示 hash、原样输入与历史隔离口径）。

        显式写明「不传采样参数」：:meth:`ChatSystem.complete` 只在 `RunConfig` 显式给了
        temperature/top_p/max_tokens 时才带这些字段，默认（全为 None）就是把采样交给
        供应商默认值——这一条必须可核对，否则「两组拿到的条件是否相同」只能靠读代码。
        """
        from ..knowledge import endpoint_host

        return SystemMeta(
            system_id=self.system_id,
            label="natural_minimal" if self.system_id == SYSTEM_N else "natural_prompted",
            assembly=self.assembly_note,
            model_id=self._gateway.model_name,
            prompt_sha256=prompts.sha256_text(self.prompt_text),
            notes={
                "chat_endpoint_host": endpoint_host(self._settings.tokenhub_base_url),
                "sdk_client_max_retries": 0,
                "outer_retry_owner": "carebench",
                "user_text": "原样 user_text（无背景/问题标题）",
                "history": "per_episode（open_case 清空，续跑按已落盘轮次重建）",
                "tools": "none",
                "skills": "none",
                "sampling_params": self._sampling_facts(),
            },
        )

    async def run_turn(self, request: InteractiveTurn) -> TurnOutcome:
        """跑一轮：system（本组提示）+ 该会话历史 + 原样 user_text → 一次完成调用。"""
        user_text = _require_user_text(request)
        started = time.monotonic()
        history = self._history.setdefault(request.session_id, [])
        messages: list[dict[str, str]] = [{"role": "system", "content": self.prompt_text}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        # 轨迹在调用前就固定：失败路径也要能证明「送出去的是什么」。
        trace_base: dict[str, Any] = {
            "system_id": self.system_id,
            "turn": request.turn,
            "entry": request.entry,
            "user_text_sha256": sha256_text(user_text),
            "history_messages_before": len(history),
        }
        try:
            text, usage = await self.complete(messages)
        except Exception as exc:  # noqa: BLE001 —— 只留类型，原始消息可能含端点细节
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return TurnOutcome(
                status=STATUS_ERROR,
                latency_ms=elapsed_ms,
                error_type=type(exc).__name__,
                error_detail=f"chat 调用失败（{type(exc).__name__}）",
                trace={**trace_base, "messages_sent": messages, "error_type": type(exc).__name__},
                meta={"model_id": self._gateway.model_name},
            )
        latency_ms = int((time.monotonic() - started) * 1000)

        # 只在调用成功后追加历史：失败轮不得在下一轮里冒充「说过了」。
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": text})

        return TurnOutcome(
            status=STATUS_COMPLETED if text.strip() else STATUS_NO_OUTPUT,
            raw_output=text,
            output_text=text,
            latency_ms=latency_ms,
            usage=usage,
            trace={
                **trace_base,
                "messages_sent": messages,
                "response_text": text,
                "usage": usage,
                "history_messages_after": len(history),
            },
            meta={"model_id": self._gateway.model_name},
        )

    # --- 子类接口（`ChatSystem` 的同一组钩子）---
    @property
    def prompt_text(self) -> str:
        """本组的系统提示（N 最小、P 原强提示）。"""
        return GROUP_PROMPTS[self.system_id]

    @property
    def assembly_note(self) -> str:
        """装配说明（进 manifest），把「原样输入 + 每 episode 独立历史」写明。"""
        if self.system_id == SYSTEM_N:
            return (
                "同一模型客户端 + 最小中文助手角色与基础边界（无任务说明/无追问纪律/无格式纪律）；"
                "原样 user_text；每 episode 独立历史；无检索、无工具、无 skill、无档案"
            )
        return (
            "同一模型客户端 + 原 COMMON_TASK_INSTRUCTIONS（v0.1 强提示，逐字复用）；"
            "原样 user_text；每 episode 独立历史；无检索、无工具、无 skill、无档案"
        )

    def system_prompt(self, *, evidence: str | None = None) -> str:
        """本轮的 system 提示（N/P 不看证据：两组都没有检索）。"""
        return self.prompt_text

    def _sampling_facts(self) -> dict[str, Any]:
        """采样参数事实：只有被显式传下去的才算「改变默认」。"""
        explicit = {
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
            "max_output_tokens": self._config.max_output_tokens,
        }
        passed = {key: value for key, value in explicit.items() if value is not None}
        return {
            "explicit": passed,
            "owner": "provider_default" if not passed else "run_config",
        }


class InteractiveAgentSystem(AgentSystem):
    """C：真实产品 `AgentSystem`，行为差异集中在「请求怎么装」这一处。

    复用产品的全部真实零件（`AgentRunner`、工具池、skill 注册表、会话真源），因此
    工具轨迹、结构化产出与引用记录都是产品自己的形状。两处增量：

    - **自然输入**：`user_text` 原样进 `RunRequest.user_input`（日常）；
    - **应急首次轮**：按 `POST /consult/emergency` 的形状程序激活
      `emergency-consulting`、注入空档案与空记忆、把 `user_text` 渲染成八项采集里的
      `what_happened`。`entry` 事前冻结，不看 `risk_hint`。

    刻意**不做**产品的两层东西：

    - 引导（`onboarding`）注入：本评测不给日常会话加引导告知，C 组只测咨询能力；
      因此也不需要 `mark_first_run_injected`（那条标记只服务于「后续消息要不要补引导」）。
    - 档案/记忆取数：合成账号没有支持对象、没有记忆，注入的是产品在同样情形下会写的
      同一份成稿（`state="absent"` / `state="empty"`），不是伪造的个人资料。
    """

    system_id = SYSTEM_C

    def __init__(
        self,
        *,
        settings: Settings,
        config: RunConfig,
        gateway: ModelGateway,
        faults: FaultPlan,
        runner: Any | None = None,
    ) -> None:
        """绑定配置、共享网关与注入计划。

        Args:
            runner: 测试缝——脚本化运行器（只需有 `async def run(request)` 异步迭代器）。
                与产品 `composition.install(gateway=...)` 同一种做法：装配代码完全相同，
                只把外部运行器换掉。生产路径传 `None`，走产品的注入点。
        """
        super().__init__(settings=settings, config=config, gateway=gateway, faults=faults)
        self._runner_override = runner
        self._request_facts: dict[tuple[str, int], dict[str, Any]] = {}

    # --- SystemAdapter ---
    async def prepare(self) -> SystemMeta:
        """装配产品运行器，并核对应急技能存在（缺了就等于应急入口跑不起来）。

        Raises:
            ConsultAssemblyError: 内容目录里没有 `emergency-consulting`——应急场景
                无法装配，必须在运行前失败，而不是等到第一次应急轮才炸。
        """
        meta = await super().prepare()
        skill = self._emergency_skill()
        notes = dict(meta.notes)
        notes.update(
            {
                "natural_input": "原样 user_text：日常直送；应急首次渲染成八项采集的 what_happened",
                "entry_lifecycle": (
                    "entry 事前冻结、不看 risk_hint；首次 emergency 程序激活 emergency-consulting"
                    " + 空档案/空记忆注入；后续轮次沿同一会话，不再激活或注入"
                ),
                "emergency_skill": skill.name,
                "evidence_scope": "程序内产品装配（AgentRunner.run）；不是浏览器端到端（browsere2e 另由验收流程覆盖）",
            }
        )
        return replace(meta, notes=notes)

    # --- 请求装配（唯一的覆写点）---
    def _build_request(self, request: InteractiveTurn) -> RunRequest:
        """按入口装配运行请求。

        Raises:
            TypeError: 请求不是 :class:`InteractiveTurn`。
            ValueError: `user_text` 为空，或轮次编号不是 1 起。
            ConsultAssemblyError: 应急首次轮找不到 `emergency-consulting`。
            pydantic.ValidationError: `user_text` 超过产品八项采集的单值上界
                （产品会 422；这里原样失败，不做截断——截断会把场景改短）。
        """
        user_text = _require_user_text(request)
        if request.turn < 1:
            raise ValueError("轮次从 1 起编号：应急首次轮的激活判据依赖它")
        if request.entry == ENTRY_EMERGENCY and request.turn == 1:
            assembled = self._emergency_request(request, user_text)
        else:
            assembled = self._daily_request(request, user_text)
        self._request_facts[request.session_id, request.turn] = {
            "user_input": assembled.user_input,
            "activated_skills": [skill.name for skill in assembled.activated],
            "activation_record_items": len(assembled.activated_record),
            "injection_items": [
                {"source": item.source, "role": item.role, "content": item.content}
                for item in assembled.injections.items
            ],
        }
        return assembled

    def _daily_request(self, request: InteractiveTurn, user_text: str) -> RunRequest:
        """日常入口：与 `send_message` 同形，原样文本、无激活、无注入。"""
        return RunRequest(
            session_id=request.session_id,
            surface=str(self._constants["surface"]),
            instructions=str(self._constants["instructions"]),
            injections=InjectionBatch(),
            user_input=user_text,
            activated=(),
            activated_record=(),
            default_active_tools=tuple(self._constants["default_active_tools"]),
            context_payload={str(self._constants["account_payload_key"]): request.account_id},
        )

    def _emergency_request(self, request: InteractiveTurn, user_text: str) -> RunRequest:
        """应急首次轮：与 `POST /consult/emergency` 同形（激活 + 注入 + 八项首条消息）。

        与产品的差别只有取数来源：产品从库里读档案与记忆，这里用合成账号在同样情形下
        会得到的同一份结果——没有支持对象（`profile=None`）与空记忆
        （`EmergencyMemory(facts=[])`）。渲染由产品函数完成，因而不存在第二套措辞。
        """
        skill = self._emergency_skill()
        batch = build_emergency_injections(
            profile=None,
            memory=EmergencyMemory(facts=[]),
        )
        return RunRequest(
            session_id=request.session_id,
            surface=str(self._constants["surface"]),
            instructions=str(self._constants["instructions"]),
            injections=batch,
            user_input=render_emergency_intake([EmergencyItem(key="what_happened", value=user_text)]),
            activated=(skill,),
            activated_record=_activation_records((skill,)),
            # 产品应急入口不传 default_active_tools：本轮的工具集由激活的 skill 决定。
            context_payload={str(self._constants["account_payload_key"]): request.account_id},
        )

    def _emergency_skill(self) -> Any:
        """取应急技能（内容产物来自 `apps/api/skills/emergency-consulting`）。

        Raises:
            ConsultAssemblyError: 技能注册表不可用，或目录里没有该技能。
        """
        from campfire.surfaces.consult import assembly as consult_assembly

        registry = consult_assembly.get_skill_registry(self._settings)
        if EMERGENCY_SKILL_NAME not in registry.names():
            raise consult_assembly.ConsultAssemblyError(
                f"内容目录里没有应急技能 {EMERGENCY_SKILL_NAME}：应急首次轮无法装配"
            )
        return registry.get(EMERGENCY_SKILL_NAME)

    # --- 测试缝与轨迹 ---
    def _runner_for(self, request: InteractiveTurn) -> Any:
        """取本轮运行器：测试缝优先，否则走产品注入点（与旧 C 组同一形状）。"""
        if self._runner_override is not None:
            return self._runner_override
        return super()._runner_for(request)

    def _trace(
        self,
        request: InteractiveTurn,
        events: list[Any],
        tool_calls: list[dict[str, Any]],
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        """在产品的原始轨迹上追加 interactive 事实与来源元数据。"""
        trace = super()._trace(request, events, tool_calls, extra)
        actual_request = self._request_facts.pop((request.session_id, request.turn), None)
        # 历史适配器仅走日常，曾把注入数写死为零；新版按实际装配记录。
        if actual_request is not None and "run_request" in trace:
            trace["run_request"]["injections"] = len(actual_request["injection_items"])
        trace["interactive"] = {
            "entry": request.entry,
            "first_emergency_turn": request.entry == ENTRY_EMERGENCY and request.turn == 1,
            "session_id": request.session_id,
            "user_text_sha256": sha256_text(request.user_text),
            "user_text_chars": len(request.user_text),
            "request": actual_request,
        }
        trace["source_metadata"] = _source_metadata(events, tool_calls)
        # 落盘前只做一处无损转换：产品轨迹里的 `CitationRecord.recorded_at` 是 datetime，
        # 而 `storage` 按 JSON 写盘；这里显式转换，避免取得引用后落盘失败。
        # 只换表示（ISO 字符串），
        # 不删字段——删字段等于把可核对的证据改小。
        return _json_safe(trace)


def _activation_records(skills: tuple[Any, ...]) -> tuple[Any, ...]:
    """把程序注入的激活集合翻成合成激活记录对（与 `routes._activation_records` 同形）。

    不 import 端点里的私有函数：记录形状由基座 `build_activation_record` 拥有，这里只
    照抄调用方式（`app-activate-<序号>` 的 call_id 也一致，便于和产品日志对照）。
    """
    from campfire.agent.skill_runtime import build_activation_record

    records: list[Any] = []
    for index, skill in enumerate(skills, start=1):
        call, output = build_activation_record(skill, call_id=f"app-activate-{index}")
        records.append(dict(call))
        records.append(dict(output))
    return tuple(records)


def _source_metadata(events: list[Any], tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    """抽出**能取得的**引用元数据，并显式标注「检索正文未保存」。

    复核要回答的是「这条结论当时有没有依据」，而不是「有没有一整段可复述的原文」。
    本函数只搬运运行里真实出现过的东西：引用记录（含可核对性三项）与该轮检索工具调用；
    检索返回的正文不在事件流里，因此标注为未保存——**不得**补写。
    """
    records: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, CitationEvent):
            continue
        record = event.citation
        recorded_at = getattr(record, "recorded_at", None)
        records.append(
            {
                "citation_id": getattr(record, "citation_id", None),
                "source": getattr(record, "source", ""),
                "reference": getattr(record, "reference", ""),
                "summary": getattr(record, "summary", None),
                "status": getattr(record, "status", None),
                "applicable_scope": getattr(record, "applicable_scope", None),
                "withdrawn": getattr(record, "withdrawn", None),
                "recorded_at": recorded_at.isoformat() if isinstance(recorded_at, datetime) else None,
            }
        )
    return {
        "citation_records": records,
        "search_tool_calls": [dict(call) for call in tool_calls if call.get("name") == SEARCH_TOOL_NAME],
        "retrieval_snippets_captured": False,
        "note": (
            "只记录本运行里可取得的引用元数据与检索工具调用；检索返回的正文未保存，"
            "复核不得据此声称读过全文，也不得补写未出现的证据。"
        ),
    }


def _json_safe(value: Any) -> Any:
    """把轨迹值转成可 JSON 落盘的形式：datetime → ISO 字符串，其余原样。

    只做表示转换，不做裁剪：轨迹的用途是复核，删字段等于把证据改小。
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def build_interactive_adapters(
    *,
    settings: Settings,
    config: RunConfig,
    gateway: ModelGateway,
) -> AdapterBundle:
    """构造 N/P/C 三组适配器，共享调用方给的网关。

    Args:
        settings: 运行配置（与产品同一份 `Settings`）。
        config: 本批次的 `RunConfig`。只取采样/超时等条件；组别集合固定为 N/P/C
            （`systems` 字段是 v0.1 的 A/B/C 口径，本模块不读它）。
        gateway: 由调用方构造并**持有**的模型网关。三组共用同一个客户端与同一个模型 id
            （首字时延里不该混进三次 TLS 握手，也不该出现两个模型名）。

    Returns:
        `AdapterBundle`，键恰为 N/P/C；`owns_gateway=False`——关闭网关是调用方的事。

    Raises:
        ValueError: `gateway` 为 `None`（本模块不替调用方造网关，也不会去关它）。
    """
    if gateway is None:
        raise ValueError("build_interactive_adapters 需要调用方提供并持有 gateway（本模块不关闭它）")
    bundle = AdapterBundle(gateway=gateway, owns_gateway=False)
    for system_id in (SYSTEM_N, SYSTEM_P):
        bundle.adapters[system_id] = NaturalChatSystem(
            system_id=system_id,
            settings=settings,
            config=config,
            gateway=gateway,
        )
    bundle.adapters[SYSTEM_C] = InteractiveAgentSystem(
        settings=settings,
        config=config,
        gateway=gateway,
        # 本轮不注入任何工具故障：交互式评测的变量是输入表达与入口，不是故障处置。
        faults=FaultPlan(requested={}),
    )
    return bundle


__all__ = [
    "EMERGENCY_SKILL_NAME",
    "ENTRIES",
    "ENTRY_DAILY",
    "ENTRY_EMERGENCY",
    "GROUP_PROMPTS",
    "INTERACTIVE_SYSTEM_IDS",
    "InteractiveAgentSystem",
    "InteractiveTurn",
    "MINIMAL_SYSTEM_PROMPT",
    "NaturalChatSystem",
    "PROMPTED_SYSTEM_PROMPT",
    "SYSTEM_C",
    "SYSTEM_N",
    "SYSTEM_P",
    "build_interactive_adapters",
]
