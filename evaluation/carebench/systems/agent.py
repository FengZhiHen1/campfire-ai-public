"""C 组：当前生产 Agent 运行时（真 AgentRunner、真工具池、真 skill、真会话）。

职责：用产品自己的组合根把运行器装起来（`surfaces.consult.composition.install` /
`assembly.get_runner`），按 `send_message` 端点的**同一形状**构造 `RunRequest` 并驱动
`AgentRunner.run()`，把基座事件原样翻译成本工具的输出记录。

边界：**不写简化假 C**。这里没有自造 agent loop、没有自造工具、没有 FakeModel、
没有把模型回复合成出来。工具池、技能注册表、引用索引、会话工厂全部来自产品装配；
评测工具只做三件产品之外的事：

1. 每个 case-group 现造一个合成账号与会话行（隔离，不碰真实用户）；
2. 单轮墙钟上限与超时处置（评测侧的统一口径）；
3. 按 fixture 计划替换**单个工具的 handler**（故障注入的唯一缝，见 :mod:`..faults`）。

为什么用 `AgentRunner.run()` 而不是走 HTTP/SSE：评测要的是原始输出、工具轨迹、token 与
时延；SSE 会把它们先编码成帧再解码回来，且引入 Redis 缓冲与前端契约的时序问题。
产品侧「真正生产」的那部分是运行器与装配，HTTP 层只是传输。这一点必须写进报告措辞：
本工具测的是**程序内**生产运行链，不是浏览器端到端体验（后者另有 e2e 用例覆盖）。
"""

from __future__ import annotations

import functools
import time
from dataclasses import asdict, is_dataclass
from typing import Any

from campfire.agent.model import ModelGateway
from campfire.agent.runtime import (
    ActionCardEvent,
    AgentRunner,
    CandidateEvent,
    ProgressEvent,
    QuestionEvent,
    RunFailedEvent,
    RunFinishedEvent,
    RunRequest,
    RunStartedEvent,
    TextDeltaEvent,
    ToolCallFinishedEvent,
    ToolCallStartedEvent,
    build_sqlalchemy_session,
)
from campfire.core.config import Settings
from campfire.core.db import get_engine, session_scope
from campfire.modules.accounts.sessions import register_session

from ..cases import Case
from ..config import RunConfig
from ..faults import FaultPlan
from ..hashing import sha256_text
from ..render import project as project_text
from .base import (
    RETRY_NEW_SESSION,
    RETRY_SAME_SESSION,
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_NO_OUTPUT,
    STATUS_TIMEOUT,
    SystemMeta,
    TurnInput,
    TurnOutcome,
)


def _product_constants() -> dict[str, Any]:
    """取产品面侧的常量（延迟 import：避免 `--help` 之类的路径拉起整个 HTTP 面）。

    这些常量决定「C 组收到的运行请求」与真端点是否同形，因此必须取自产品而不是抄一份；
    取到的值进 manifest，漂移在证据里可见。
    """
    from campfire.surfaces.consult import assembly as consult_assembly
    from campfire.surfaces.consult import routes

    return {
        "surface": routes.SURFACE_NAME,
        "default_active_tools": tuple(routes.DEFAULT_ACTIVE_TOOLS),
        "account_payload_key": routes.ACCOUNT_PAYLOAD_KEY,
        "instructions": consult_assembly.CONSULT_INSTRUCTIONS,
    }


def _event_to_dict(event: Any) -> Any:
    """把事件对象转成可 JSON 化的字典（dataclass 递归，其余按类型名兜底）。"""
    if is_dataclass(event) and not isinstance(event, type):
        payload: dict[str, Any] = {}
        for key, value in asdict(event).items():
            payload[key] = value
        payload["type"] = getattr(event, "type", type(event).__name__)
        return payload
    return repr(event)


class AgentSystem:
    """C 组适配器：产品生产运行链。"""

    system_id = "C"

    def __init__(
        self,
        *,
        settings: Settings,
        config: RunConfig,
        gateway: ModelGateway,
        faults: FaultPlan,
    ) -> None:
        """绑定配置、共享网关与注入计划（装配在 `prepare()` 里做一次）。"""
        self._settings = settings
        self._config = config
        self._gateway = gateway
        self._faults = faults
        self._constants: dict[str, Any] = {}
        self._tool_names: tuple[str, ...] = ()
        self._skill_names: tuple[str, ...] = ()

    # --- SystemAdapter ---
    async def prepare(self) -> SystemMeta:
        """装配生产运行器并返回装配事实。

        Raises:
            Exception: 装配失败（缺凭据、技能根不可用、工具与 skill 不一致）原样抛出——
                装配失败不得被记成「模型不行」。
        """
        from campfire.surfaces.consult import assembly as consult_assembly
        from campfire.surfaces.consult import composition

        composition.install(self._settings, gateway=self._gateway)
        # 取一次运行器：与端点取用的是同一个注入口（装配没装上时这里就会失败）。
        consult_assembly.get_runner(self._settings)
        skills = consult_assembly.get_skill_registry(self._settings)
        pool = composition.build_tool_pool(skills)
        self._constants = _product_constants()
        self._tool_names = pool.names()
        self._skill_names = skills.names()

        return SystemMeta(
            system_id=self.system_id,
            label="v3_agent",
            assembly=(
                "产品生产装配：surfaces.consult.composition.install → assembly.get_runner；"
                "真 AgentRunner + 真工具池 + 真 SkillRegistry + SqlCitationIndex + SDK 会话表"
            ),
            model_id=self._gateway.model_name,
            prompt_sha256=sha256_text(str(self._constants["instructions"])),
            notes={
                "surface": self._constants["surface"],
                "default_active_tools": list(self._constants["default_active_tools"]),
                "tool_pool": list(self._tool_names),
                "skills": list(self._skill_names),
                "sdk_retry": {
                    "owner": "agents-sdk runner-managed retry",
                    "model_max_retries": self._settings.model_max_retries,
                    "request_timeout_seconds": self._settings.model_request_timeout_seconds,
                },
                "transport": "in-process AgentRunner.run()（不是 HTTP/SSE；见模块 docstring）",
            },
        )

    async def open_case(
        self,
        *,
        case: Case,
        session_id: str,
        account_id: str,
        prior_turns: tuple[tuple[str, str], ...] = (),
    ) -> None:
        """登记会话归属行（与 `create_session` 端点同一函数、同一顺序：先落归属）。

        `prior_turns` 刻意不用：C 组的对话真源在产品库里（SDK 会话表），
        续跑时同一 `session_id` 自然续上，重建历史反而会造出第二份对话真源。
        """
        async with session_scope(self._settings) as db:
            await register_session(db, session_id=session_id, account_id=account_id)

    async def run_turn(self, request: TurnInput) -> TurnOutcome:
        """驱动一次运行，翻译事件并返回原始产出。

        三样输出分开保存（见 :class:`..systems.base.TurnOutcome`）：正文增量逐字拼接、
        结构化产出（行动卡 / 提问）保留原始载荷、再给一份**规范文本投影**。
        纯卡片作答的回合因此是「有产出」而不是 `no_output`——这与产品侧 live（SSE 帧）
        和 history（`question-record` / `action_card` part）的口径一致。
        """

        runner = self._runner_for(request)
        run_request = self._build_request(request)
        items_before = await self._session_item_count(request.session_id)
        started = time.monotonic()
        events: list[Any] = []
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        structured: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        progress_messages: list[str] = []
        candidate_count = 0
        terminal: Any = None
        activated_skills: list[str] = []

        try:
            async for event in runner.run(run_request):
                events.append(event)
                if isinstance(event, RunStartedEvent):
                    activated_skills = list(event.activated_skills)
                if isinstance(event, TextDeltaEvent):
                    text_parts.append(event.delta)
                elif isinstance(event, ActionCardEvent):
                    structured.append(self._structured_payload("action_card", event))
                elif isinstance(event, QuestionEvent):
                    structured.append(self._structured_payload("question", event))
                elif isinstance(event, ProgressEvent):
                    progress_messages.append(str(event.message))
                elif isinstance(event, CandidateEvent):
                    candidate_count += 1
                elif isinstance(event, ToolCallStartedEvent):
                    tool_calls.append({"name": event.tool_name, "call_id": event.call_id, "ok": None})
                elif isinstance(event, ToolCallFinishedEvent):
                    for entry in reversed(tool_calls):
                        if entry["call_id"] == event.call_id:
                            entry["ok"] = event.ok
                            entry["error_code"] = event.error_code
                            entry["summary"] = event.summary
                            break
                elif type(event).__name__ == "ReasoningDeltaEvent":
                    reasoning_parts.append(getattr(event, "delta", ""))
                elif type(event).__name__ == "CitationEvent":
                    record = event.citation
                    citations.append(
                        {
                            "source": getattr(record, "source", ""),
                            "reference": getattr(record, "reference", ""),
                            "summary": getattr(record, "summary", None),
                        }
                    )
                if isinstance(event, (RunFinishedEvent, RunFailedEvent)):
                    terminal = event
        except Exception as exc:  # noqa: BLE001 —— 只留类型名，原始消息可能含端点细节
            elapsed_ms = int((time.monotonic() - started) * 1000)
            items_after = await self._session_item_count(request.session_id)
            return TurnOutcome(
                status=STATUS_ERROR,
                latency_ms=elapsed_ms,
                error_type=type(exc).__name__,
                error_detail=f"AgentRunner 运行抛出异常（{type(exc).__name__}）",
                tool_calls=tool_calls,
                structured=structured,
                output_text=project_text("".join(text_parts), structured),
                retry_safety=self._retry_safety(items_before, items_after),
                trace=self._trace(
                    request,
                    events,
                    tool_calls,
                    {"exception": type(exc).__name__, "phase": "run"},
                ),
                meta=self._meta(request, items_before, items_after, structured, activated_skills),
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        items_after = await self._session_item_count(request.session_id)
        text = "".join(text_parts)
        output_text = project_text(text, structured)
        usage = None
        error_type = None
        error_code = None
        error_detail = None
        finish_reason: str | None = None

        if isinstance(terminal, RunFailedEvent):
            status = STATUS_ERROR
            error_code = terminal.code
            error_type = terminal.model_reason
            error_detail = terminal.detail
            citations = [self._citation(record) for record in terminal.citations] or citations
            usage = self._usage(terminal.usage)
        elif isinstance(terminal, RunFinishedEvent):
            finish_reason = str(getattr(terminal, "reason", "completed"))
            citations = [self._citation(record) for record in terminal.citations] or citations
            usage = self._usage(terminal.usage)
            if finish_reason == "timeout":
                # 产品自己的运行预算耗尽：这是一次真实超时，不能记成 completed。
                status = STATUS_TIMEOUT
                error_type = "RunBudgetExhausted"
                error_code = "run_budget_timeout"
                error_detail = "产品运行预算耗尽（run_finished.reason=timeout）"
            elif finish_reason == "cancelled":
                status = STATUS_ERROR
                error_type = "RunCancelled"
                error_code = "run_cancelled"
                error_detail = "运行以 run_finished.reason=cancelled 结束（被取消，不是正常完成）"
            else:
                # 有正文或有结构化产出都算「有产出」（与产品 live/history 同一口径）。
                status = STATUS_COMPLETED if (text.strip() or structured) else STATUS_NO_OUTPUT
        else:
            status = STATUS_ERROR
            error_type = "MissingTerminalEvent"
            error_detail = "事件流结束时没有 run_finished / run_failed（运行被中断）"

        return TurnOutcome(
            status=status,
            raw_output=text,
            structured=structured,
            output_text=output_text,
            latency_ms=latency_ms,
            usage=usage,
            citations=citations,
            tool_calls=tool_calls,
            error_type=error_type,
            error_code=error_code,
            error_detail=error_detail,
            retry_safety=self._retry_safety(items_before, items_after),
            trace=self._trace(
                request,
                events,
                tool_calls,
                {
                    "reasoning_chars": len("".join(reasoning_parts)),
                    "progress_messages": progress_messages,
                    "candidate_events": candidate_count,
                    "run_request": {
                        "surface": run_request.surface,
                        "instructions_sha256": sha256_text(run_request.instructions),
                        "activated": [skill.name for skill in run_request.activated],
                        "default_active_tools": list(run_request.default_active_tools),
                        "user_input_chars": len(run_request.user_input or ""),
                        "injections": 0,
                    },
                    "terminal": terminal.type if terminal is not None else None,
                    "finish_reason": finish_reason,
                    "session_items_before": items_before,
                    "session_items_after": items_after,
                },
            ),
            meta=self._meta(request, items_before, items_after, structured, activated_skills, finish_reason),
        )

    async def aclose(self) -> None:
        """不关闭网关（它的所有者是 runner，且 A/B 共用同一个客户端）。"""
        return None

    # --- 内部 ---
    @staticmethod
    def _structured_payload(kind: str, event: Any) -> dict[str, Any]:
        """把结构化事件的原载荷转成字典（字段名与产品事件逐字一致，不改写）。"""
        payload: dict[str, Any] = {"kind": kind}
        for field_name in getattr(event, "__dataclass_fields__", {}):
            payload[field_name] = getattr(event, field_name)
        payload.pop("type", None)
        return payload

    async def _session_item_count(self, session_id: str) -> int | None:
        """读一次会话条目数（用于判断这次尝试有没有在会话里留下痕迹）。

        判「失败后能不能原地重试」只靠这个读数：SDK 在运行结束时才把条目写进会话，
        但超时/取消路径可能只写了一半——**猜**会重复历史，**读**不会。
        读不到（会话不可用）就返回 None，由 :meth:`_retry_safety` 按保守方向处理。
        """
        try:
            session = build_sqlalchemy_session(session_id, engine=get_engine(self._settings))
            items = await session.get_items()
            return len(items)
        except Exception:  # noqa: BLE001 —— 读不到不等于没写，交给 _retry_safety 保守处理
            return None

    @staticmethod
    def _retry_safety(items_before: int | None, items_after: int | None) -> str:
        """这次尝试之后能否在同一会话里重试。

        只有「明确读到没有增长」才算安全：读不到（None）按不安全处理，因为重复历史会
        直接污染下一次尝试，而多开一个会话的代价只是多一次登记。
        """
        if items_before is None or items_after is None:
            return RETRY_NEW_SESSION
        if items_after > items_before:
            return RETRY_NEW_SESSION
        return RETRY_SAME_SESSION

    def _meta(
        self,
        request: TurnInput,
        items_before: int | None,
        items_after: int | None,
        structured: list[dict[str, Any]],
        activated_skills: list[str],
        finish_reason: str | None = None,
    ) -> dict[str, Any]:
        """记录的工程事实（进 outputs 的 `system_meta`）。"""
        return {
            "model_id": self._gateway.model_name,
            "runner": self._runner_label(request),
            "activated_skills": activated_skills,
            "structured_blocks": len(structured),
            "session_items_before": items_before,
            "session_items_after": items_after,
            "finish_reason": finish_reason,
            "tool_overrides": self._override_facts(request),
        }

    def _override_facts(self, request: TurnInput) -> list[dict[str, Any]]:
        """被替换的工具的装配事实（证明「说明与参数模型与产品逐字相同」）。"""
        facts: list[dict[str, Any]] = []
        for name in self._tool_replacements(request):
            product = self._product_tool(name)
            facts.append(
                {
                    "tool": name,
                    "description_sha256": sha256_text(str(getattr(product, "description", ""))),
                    "args_model": type(getattr(product, "args_model", None)).__name__,
                    "description_reused_from_product": True,
                }
            )
        return facts

    def _product_tool(self, name: str) -> Any:
        """取产品工具池里的原工具（说明与参数模型的唯一真源）。"""
        from campfire.surfaces.consult import assembly as consult_assembly
        from campfire.surfaces.consult import composition

        skills = consult_assembly.get_skill_registry(self._settings)
        pool = composition.build_tool_pool(skills)
        tool = pool.tools.get(name)
        if tool is None:
            raise RuntimeError(f"产品工具池里没有 {name}：注入替身必须复用产品定义，不能自造")
        return tool

    def _build_request(self, request: TurnInput) -> RunRequest:
        """按 `send_message` 端点的形状构造运行请求（同一字段集合、同一来源常量）。"""
        from campfire.agent.context import InjectionBatch

        from .. import prompts

        user_text = prompts.render_user_turn(
            shared_context=request.case.shared_context,
            message=request.case.message_for_turn(request.turn),
            is_followup=request.turn > 1,
        )
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

    def _runner_for(self, request: TurnInput) -> AgentRunner:
        """取本轮运行器：无工具类注入时走生产注入点；有注入时用同一批零件重装一个。"""
        from campfire.surfaces.consult import assembly as consult_assembly

        replacements = self._tool_replacements(request)
        if not replacements:
            return consult_assembly.get_runner(self._settings)
        return self._build_runner_with_tools(replacements)

    def _runner_label(self, request: TurnInput) -> str:
        """运行器标签：`production` 或 `production+tool_pool_override:<names>`。"""
        replacements = self._tool_replacements(request)
        if not replacements:
            return "production"
        return "production+tool_pool_override:" + ",".join(sorted(replacements))

    def _tool_replacements(self, request: TurnInput) -> dict[str, Any]:
        """按 fixture 计划决定要替换哪些工具。

        替身**只换 handler**：`name` / `description` / `args_model` 一律取自产品工具池里的
        原工具。此前替身的 description 里写了「本次由评测注入空结果」——那句话会被模型看见，
        等于提前把故障说破，测到的就不再是「系统在故障下如何表现」。故障只能在**实际
        handler 边界**上显现（工具真的返回了空结果/失败/超时），说明文本不得泄漏。
        """
        replacements: dict[str, Any] = {}
        modes: dict[str, str] = {}
        if self._faults.active(request.case.id, "C", "tool_search_empty"):
            modes["search_knowledge"] = "empty"
        if self._faults.active(request.case.id, "C", "tool_search_unavailable"):
            modes["search_knowledge"] = "unavailable"
        if self._faults.active(request.case.id, "C", "tool_search_timeout"):
            modes["search_knowledge"] = "timeout"
        for name, mode in modes.items():
            product = self._product_tool(name)
            replacements[name] = _injected_search_tool(
                product,
                mode=mode,
                hang_seconds=self._faults.hang_seconds("tool_search_timeout"),
            )
        return replacements

    def _build_runner_with_tools(self, replacements: dict[str, Any]) -> AgentRunner:
        """用产品同一批零件重装运行器，只替换指定工具。

        与 `composition.build_runner_factory` 的构造逐项一致（技能注册表、引用索引、
        会话工厂、模型绑定），唯一的差别是被替换的那一个工具——因此「C 组仍然是产品 C 组」
        这句话在实现上成立，而不是靠注释。
        """
        from campfire.agent.tools import RESERVED_TOOL_NAMES, ToolPool
        from campfire.surfaces.consult import assembly as consult_assembly
        from campfire.surfaces.consult import composition
        from campfire.surfaces.consult.citations import SqlCitationIndex

        skills = consult_assembly.get_skill_registry(self._settings)
        base_pool = composition.build_tool_pool(skills)
        tools = [
            replacements.get(name, tool) for name, tool in base_pool.tools.items() if name not in replacements
        ] + list(replacements.values())
        # 必须按「保留名」走 `register_base`：`ToolPool.register` 会拒绝基座保留名
        # （`skill` / `read_skill_resource` / `ask_user`），用构造函数重建整池会在装配期抛
        # `ToolRegistrationError`——实测踩过（2026-10-29），表现为 C 组 10 ms 内失败。
        pool = ToolPool()
        for tool in tools:
            if tool.name in RESERVED_TOOL_NAMES:
                pool.register_base(tool)
            else:
                pool.register(tool)
        return AgentRunner(
            binding=self._gateway.binding,
            tools=pool,
            skills=skills,
            citations=SqlCitationIndex(self._settings),
            sessions=functools.partial(build_sqlalchemy_session, engine=get_engine(self._settings)),
        )

    def _trace(
        self,
        request: TurnInput,
        events: list[Any],
        tool_calls: list[dict[str, Any]],
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        """轨迹载荷：事件流水 + 工具调用 + 装配事实。"""
        return {
            "system_id": self.system_id,
            "turn": request.turn,
            "runner": self._runner_label(request),
            "tool_calls": tool_calls,
            "events": [_event_to_dict(event) for event in events],
            **extra,
        }

    @staticmethod
    def _usage(usage: Any) -> dict[str, int] | None:
        """把基座 `RunUsage` 转成统一形状。"""
        if usage is None:
            return None
        return {
            "requests": int(getattr(usage, "requests", 0)),
            "input_tokens": int(getattr(usage, "input_tokens", 0)),
            "output_tokens": int(getattr(usage, "output_tokens", 0)),
            "total_tokens": int(getattr(usage, "total_tokens", 0)),
        }

    @staticmethod
    def _citation(record: Any) -> dict[str, Any]:
        """把引用记录转成统一形状。"""
        return {
            "source": getattr(record, "source", ""),
            "reference": getattr(record, "reference", ""),
            "summary": getattr(record, "summary", None),
        }


def _injected_search_tool(product_tool: Any, *, mode: str, hang_seconds: float = 420.0) -> Any:
    """按产品原工具造一个「故障替身」：只换 handler，其余逐项复用。

    为什么必须复用 `description` 与 `args_model`：工具说明会进模型上下文。替身若自带
    「本次由评测注入」之类的话，模型在调用前就知道检索是坏的——那测的是「模型会不会被
    一句话说服」，不是「系统在故障下是否如实披露」。而且说明漂移也会让模型的调用行为
    （什么时候调、传什么参数）与真产品不同，A/B/C 就不再是同题对比。

    故障只在 **handler 边界**显现，三种形态都走产品既有的产出形状：

    - ``empty``：返回产品「未找到相关资料」的同一句提示（`ToolResult`）；
    - ``unavailable``：返回产品真实故障时的同一句 `ToolFailure(tool_failed)`；
    - ``timeout``：挂住到产品自己的单轮预算耗尽（`run_finished.reason=timeout`）——
      必须比 `AGENT_RUN_TIMEOUT_SECONDS`（300 s）长，否则触发的是评测回合超时。
    """
    from campfire.agent.tools import ToolFailure, ToolResult, ToolSpec

    async def handler(_context: Any, _args: Any) -> Any:
        if mode == "empty":
            return ToolResult(
                text=("未找到相关资料。这**不等于**该做法不存在或没有风险——只能说本资料库当前没有可引用的依据。")
            )
        if mode == "unavailable":
            return ToolFailure(
                code="tool_failed",
                message=(
                    "检索服务暂时不可用，**没有**完成检索。"
                    "不得据此声称「没有相关资料」——请向使用者说明检索能力受限，或稍后重试。"
                ),
            )
        if mode == "timeout":
            # 只用可取消的 sleep：被评测回合取消时要能立刻退出，不留悬挂任务。
            import asyncio

            waited = 0.0
            while waited < hang_seconds:
                await asyncio.sleep(1.0)
                waited += 1.0
            raise TimeoutError(f"检索工具在 {hang_seconds:.0f}s 内没有返回")
        raise RuntimeError(f"未知的注入形态：{mode}")

    return ToolSpec(
        name=product_tool.name,
        description=product_tool.description,
        args_model=product_tool.args_model,
        handler=handler,
    )


__all__ = ["AgentSystem", "_injected_search_tool"]
