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
    AgentRunner,
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
from .base import (
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_NO_OUTPUT,
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
        """驱动一次运行，翻译事件并返回原始产出。"""

        runner = self._runner_for(request)
        run_request = self._build_request(request)
        started = time.monotonic()
        events: list[Any] = []
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        terminal: Any = None
        activated_skills: list[str] = []

        try:
            async for event in runner.run(run_request):
                events.append(event)
                if isinstance(event, RunStartedEvent):
                    activated_skills = list(event.activated_skills)
                if isinstance(event, TextDeltaEvent):
                    text_parts.append(event.delta)
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
            return TurnOutcome(
                status=STATUS_ERROR,
                latency_ms=elapsed_ms,
                error_type=type(exc).__name__,
                error_detail=f"AgentRunner 运行抛出异常（{type(exc).__name__}）",
                tool_calls=tool_calls,
                trace=self._trace(
                    request,
                    events,
                    tool_calls,
                    {"exception": type(exc).__name__, "phase": "run"},
                ),
                meta={"model_id": self._gateway.model_name, "runner": self._runner_label(request)},
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        text = "".join(text_parts)
        usage = None
        error_type = None
        error_code = None
        error_detail = None
        if isinstance(terminal, RunFailedEvent):
            status = STATUS_ERROR
            error_code = terminal.code
            error_type = terminal.model_reason
            error_detail = terminal.detail
            citations = [self._citation(record) for record in terminal.citations] or citations
            usage = self._usage(terminal.usage)
        elif isinstance(terminal, RunFinishedEvent):
            status = STATUS_COMPLETED if text.strip() else STATUS_NO_OUTPUT
            citations = [self._citation(record) for record in terminal.citations] or citations
            usage = self._usage(terminal.usage)
        else:
            status = STATUS_ERROR
            error_type = "MissingTerminalEvent"
            error_detail = "事件流结束时没有 run_finished / run_failed（运行被中断）"

        return TurnOutcome(
            status=status,
            raw_output=text,
            latency_ms=latency_ms,
            usage=usage,
            citations=citations,
            tool_calls=tool_calls,
            error_type=error_type,
            error_code=error_code,
            error_detail=error_detail,
            trace=self._trace(
                request,
                events,
                tool_calls,
                {
                    "reasoning_chars": len("".join(reasoning_parts)),
                    "run_request": {
                        "surface": run_request.surface,
                        "instructions_sha256": sha256_text(run_request.instructions),
                        "activated": [skill.name for skill in run_request.activated],
                        "default_active_tools": list(run_request.default_active_tools),
                        "user_input_chars": len(run_request.user_input or ""),
                        "injections": 0,
                    },
                    "terminal": terminal.type if terminal is not None else None,
                },
            ),
            meta={
                "model_id": self._gateway.model_name,
                "runner": self._runner_label(request),
                "activated_skills": activated_skills,
            },
        )

    async def aclose(self) -> None:
        """不关闭网关（它的所有者是 runner，且 A/B 共用同一个客户端）。"""
        return None

    # --- 内部 ---
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
        """按 fixture 计划决定要替换哪些工具。"""
        replacements: dict[str, Any] = {}
        if self._faults.active(request.case.id, "C", "tool_search_empty"):
            replacements["search_knowledge"] = _empty_search_tool()
        if self._faults.active(request.case.id, "C", "tool_search_unavailable"):
            replacements["search_knowledge"] = _failing_search_tool()
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


def _empty_search_tool() -> Any:
    """返回「检索为空」的工具替身（参数模型与说明沿用产品定义）。"""
    from campfire.agent.tools import ToolResult, ToolSpec
    from campfire.tools.library import SearchKnowledgeArgs

    async def handler(_context: Any, _args: Any) -> Any:
        return ToolResult(
            text=(
                "本次检索没有返回任何条目（检索链正常，是库内没有匹配内容）。"
                "这**不等于**该做法不存在或没有风险——只能说当前知识库没有可引用的依据。"
            )
        )

    return ToolSpec(
        name="search_knowledge",
        description="在本项目的专业资料库里检索，为你的建议找依据（本次由评测注入空结果）。",
        args_model=SearchKnowledgeArgs,
        handler=handler,
    )


def _failing_search_tool() -> Any:
    """返回「检索不可用」的工具替身（走产品既有的 `tool_failed` 失败路径）。"""
    from campfire.agent.tools import ToolFailure, ToolSpec
    from campfire.tools.library import SearchKnowledgeArgs

    async def handler(_context: Any, _args: Any) -> Any:
        return ToolFailure(
            code="tool_failed",
            message=(
                "检索服务暂时不可用，**没有**完成检索。"
                "不得据此声称「没有相关资料」——请向使用者说明检索能力受限，或稍后重试。"
            ),
        )

    return ToolSpec(
        name="search_knowledge",
        description="在本项目的专业资料库里检索，为你的建议找依据（本次由评测注入失败）。",
        args_model=SearchKnowledgeArgs,
        handler=handler,
    )


__all__ = ["AgentSystem", "_empty_search_tool", "_failing_search_tool"]
