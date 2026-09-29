"""运行编排：一次运行的全部行为与失败语义。

依据 docs/技术设计/technical-details/通用基座.md 第 2、3、4、5、7、9 节。这个模块把前面
几步的零件装成一次运行，形状如下：

```text
读历史 ──► 决定要追加哪些注入消息（目录/激活/可用性：与历史里最后一条同名消息不同才追加）
        ──► 渲染注入项（写引用索引）──► 派生本轮模型窗口 ──► 交给 SDK 流式运行
        ──► 把 SDK 事件翻译成基座事件 ──► 结束（含原因与引用清单）
```

## 六条刻意写清楚的边界

1. **注入项就是消息，而且只加在末尾**（压缩策略第 8 节第 1 条：只在末尾追加）。目录、
   激活内容、工具可用性都在「与历史里最后一条同名消息不同」时才追加——这条判断只依赖
   会话历史本身，因此不需要另存「窗口配方」或「上次注入集合」这类第二真相。
2. **注入失败分两类，处置相反**：取数失败由面用 ``UnavailableSource`` 表达，基座**标注该
   来源不可用并继续**（第 9 节）；而**渲染或引用索引写入失败**是持久化失败，基座以
   ``injection_failed`` 结束本次运行——索引里可能已有记录而窗口里没有，继续下去会让
   ``run_finished`` 报出模型从未看到的依据。
3. **窗口只裁模型输入，不动落库**：裁剪经 ``RunConfig.session_input_callback`` 表达，
   会话里仍是完整历史（第 2 节）。
4. **上界只有 180 秒**（第 2 节）：用**每次拉取流事件的剩余预算**实现，而不是给整个
   生成器套一层超时——后者的定时器会在生成器把事件交给消费方（例如慢速 SSE 客户端）时
   继续走，最后取消的是**消费方的任务**，那是错误的处置对象。触顶按第 9 节以
   ``run_finished(reason="timeout")`` 结束并保留已产生的引用。
5. **取消不发事件**：消费者取消自己的任务后收不到任何后续事件，发了也是空的。取消路径
   只做两件事——停掉 SDK 侧的运行、把 ``CancelledError`` 继续抛出去（第 9 节：
   运行被取消 → 立即停止调用）。
6. **模型失败与内部失败分开报码**：模型侧的异常（超时、限流、供应商错误、认证）归
   ``model_unavailable`` 并带上细分原因；其余归 ``internal``。分类器在
   :mod:`campfire.agent.model`，判定顺序在那里有说明。

## 已知缺口（登记于 docs/TODO.md）

- **基座不做工具级重试**：第 9 节写「工具失败 → 作为结果回给模型；重试耗尽则以明确失败
  结束本次运行」，但一期没有任何工具级重试策略——重试的循环是**模型自己**（它会看到
  ``tool_failed`` 再决定要不要换个参数重试）。真的反复失败会一直走到 180 秒上限，
  以 ``timeout`` 结束。接入真实工具后再评估是否要加重试策略。
- **会话写入失败靠异常检出**：SDK 会 ``await`` 会话写入，写入抛错即本次运行失败；但一个
  「不抛错也不写」的会话实现不会被发现。这条已登记为待验证事实（TECH-16）。

## 为什么不调用 SDK 的压缩能力

第 2 节明确不使用 ``OpenAIResponsesCompactionSession``：它会清空并重写历史，在单真源下
等于改写用户可见的历史。上下文压力只由窗口与（尚未实现的）压缩机制处理。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass, field

from agents import Runner
from agents.items import TResponseInputItem
from agents.result import RunResultStreaming
from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent

from campfire.agent.context import (
    CitationIndex,
    CitationRecorder,
    InjectionBatch,
    InjectionItem,
    InjectionMessage,
    InjectionPriority,
    InjectionRenderError,
    derive_window,
    message_text,
)
from campfire.agent.limits import AGENT_RUN_TIMEOUT_SECONDS
from campfire.agent.model import ModelBinding, ModelFailureReason, classify_model_failure
from campfire.agent.skill_runtime import Skill, SkillRegistry, render_activation
from campfire.agent.tools import ToolContext, ToolDispatcher, ToolPool, ToolScope, resolve_scope

from .assembly import ToolBridge, WindowCallback, build_agent, build_run_config
from .errors import RuntimeAssemblyError
from .events import (
    SUMMARY_LIMIT,
    CitationEvent,
    RunEvent,
    RunFailedEvent,
    RunFailureCode,
    RunFinishedEvent,
    RunStartedEvent,
    RunUsage,
    TextDeltaEvent,
    ToolCallFinishedEvent,
    ToolCallStartedEvent,
)
from .session import SessionFactory
from .skill_tool import SKILL_TOOL_NAME

logger = logging.getLogger("campfire.agent.runtime")

_CATALOG_PREFIX = "<available_skills>"
_ACTIVATION_PREFIX_TEMPLATE = '<skill_content name="{name}">'
_AVAILABILITY_PREFIX = "<tool_availability>"

SESSION_IO_DETAIL = "对话真源不可用（读取或写入会话失败）"
"""会话读写失败的说明。表名沿用设计里的「会话写入失败」：读写同属一类——对话真源不可用。"""


@dataclass(frozen=True, slots=True)
class RunRequest:
    """一次运行的输入：由面构造（见基座第 2 节「入口」行）。"""

    session_id: str
    """对话标识；与 SDK 会话一一对应。"""

    surface: str | None
    """当前面，用于按面收窄技能目录。"""

    instructions: str
    """**静态**系统提示（压缩策略第 8 节第 2 条）。"""

    injections: InjectionBatch = field(default_factory=InjectionBatch)
    """本轮的业务注入项（档案摘要、检索结果…）与取数失败的来源。"""

    activated: tuple[Skill, ...] = ()
    """程序注入的激活集合（例如应急卡片直接激活指定 skill）。"""

    default_active_tools: tuple[str, ...] = ()
    """未激活任何 skill 时面配置的默认可用工具集（一期只含只读类）。"""

    user_input: str | None = None
    """本轮使用者输入；纯注入（无用户消息）时可为 ``None``。"""

    context_payload: object | None = None
    """透传给产品侧工具的领域事实；基座不解读。"""

    def __post_init__(self) -> None:
        """校验形状。

        Raises:
            RuntimeAssemblyError: 会话标识为空，或静态提示为空。
        """
        if not self.session_id:
            raise RuntimeAssemblyError("RunRequest.session_id 不能为空")
        if not self.instructions.strip():
            raise RuntimeAssemblyError("RunRequest.instructions 不能为空：模型需要静态系统提示")


class AgentRunner:
    """把一次运行跑完，并只产出基座事件。"""

    def __init__(
        self,
        *,
        binding: ModelBinding,
        tools: ToolPool,
        skills: SkillRegistry,
        citations: CitationIndex,
        sessions: SessionFactory,
        timeout_seconds: float = AGENT_RUN_TIMEOUT_SECONDS,
        agent_name: str = "campfire",
    ) -> None:
        """绑定协作者。会话工厂与引用索引由装配处提供（基座不拥有连接池与表）。

        Raises:
            RuntimeAssemblyError: 配置自相矛盾——存在可按 ``description`` 自动匹配的 skill，
                但工具池里没有模型侧激活工具（``skill``），模型将无法激活任何 skill。
        """
        self._binding = binding
        self._tools = tools
        self._skills = skills
        self._citations = citations
        self._sessions = sessions
        self._timeout_seconds = timeout_seconds
        self._agent_name = agent_name

        has_candidates = bool(skills.activation_candidates())
        has_activation_tool = SKILL_TOOL_NAME in tools.names()
        if has_candidates and not has_activation_tool:
            raise RuntimeAssemblyError(
                f"工具池缺少模型侧激活工具 {SKILL_TOOL_NAME}：存在可选 skill 时模型将无法激活它们。"
                "请在装配处用 build_skill_tool(skill_registry) 注册（ToolPool.register_base）"
            )
        # 激活工具是机制本身，必须恒可用；不参与 allowed-tools 的并集。
        self._always_active: tuple[str, ...] = (SKILL_TOOL_NAME,) if has_activation_tool else ()

    def _resolve_scope(self, request: RunRequest) -> ToolScope:
        """按请求解析工具范围（唯一入口，避免两处各算一次而分叉）。"""
        return resolve_scope(
            self._tools,
            activated=request.activated,
            default_active=request.default_active_tools,
            always_active=self._always_active,
        )

    async def run(self, request: RunRequest) -> AsyncIterator[RunEvent]:
        """执行一次运行，逐个产出事件。

        生成器结束即运行结束；正常情况下最后一个事件是 ``run_finished`` 或 ``run_failed``。
        消费者取消自己的任务时不会收到结束事件（取消以 ``CancelledError`` 表达）。
        """
        started = time.monotonic()
        run_id = uuid.uuid4().hex
        session = self._sessions(request.session_id)
        recorder = CitationRecorder(self._citations, run_id=run_id)

        try:
            history = await session.get_items()
        except Exception as exc:  # noqa: BLE001 —— 会话不可用必须以明确失败结束
            logger.warning("读取会话失败 run=%s error=%s", run_id, type(exc).__name__)
            yield _failure("session_write_failed", SESSION_IO_DETAIL, recorder, RunUsage(), started, None)
            return

        scope = self._resolve_scope(request)
        batch = InjectionBatch(
            [*self._pending_injections(history, request, scope), *request.injections.items],
            request.injections.unavailable,
        )

        try:
            rendered = await batch.render(recorder)
        except InjectionRenderError as exc:
            # 索引里可能已有记录而窗口里没有：不得当作「没有注入」继续。
            logger.warning("注入渲染失败 run=%s error=%s", run_id, type(exc).__name__)
            yield _failure(
                "injection_failed",
                f"注入渲染失败（{type(exc).__name__}）",
                recorder,
                RunUsage(),
                started,
                None,
            )
            return

        new_items: list[TResponseInputItem] = [_as_input_item(message) for message in rendered]
        if request.user_input is not None:
            new_items.append({"role": "user", "content": request.user_input})

        yield RunStartedEvent(
            run_id=run_id,
            session_id=request.session_id,
            surface=request.surface,
            model=self._binding.name,
            activated_skills=tuple(skill.name for skill in request.activated),
            injection_sources=tuple(item.source for item in batch.ordered()),
            appended_messages=len(new_items),
        )
        for record in recorder.issued:
            yield CitationEvent(citation=record)

        buffer: list[RunEvent] = []
        dispatcher = ToolDispatcher(
            self._tools,
            scope,
            context=ToolContext(
                run_id=run_id,
                session_id=request.session_id,
                surface=request.surface,
                activated_skills=scope.activated_skills,
                citations=recorder,
                payload=request.context_payload,
            ),
        )
        bridge = ToolBridge(dispatcher, sink=buffer.append)
        agent = build_agent(
            name=self._agent_name,
            instructions=request.instructions,
            model=self._binding.model,
            tools=bridge.function_tools(),
        )
        run_config = build_run_config(binding=self._binding, window=_window_callback())
        # max_turns=None：基座第 2 节不设步数上限，SDK 默认的 10 轮就是一条步数上限。
        result = Runner.run_streamed(agent, input=new_items, session=session, max_turns=None, run_config=run_config)

        async for event in self._stream(result=result, recorder=recorder, buffer=buffer, started=started):
            yield event

    async def _stream(
        self,
        *,
        result: RunResultStreaming,
        recorder: CitationRecorder,
        buffer: list[RunEvent],
        started: float,
    ) -> AsyncIterator[RunEvent]:
        """消费 SDK 的事件流，翻译成基座事件，直到结束、触顶或失败。

        与 :meth:`run` 分开是为了让「准备」和「流式消费」各自可读：前者是装配与注入，
        后者是事件循环与失败处置，混在一个函数里既难读也难改。

        Raises:
            asyncio.CancelledError: 消费者取消时原样抛出（第 9 节：立即停止调用）；
                此时不产出结束事件，因为取消自己的消费者收不到任何后续事件。
        """
        run_id = recorder.run_id
        usage = RunUsage()
        deadline = started + self._timeout_seconds
        tracker = _ToolCallTracker()

        try:
            async for event in _drain(result, deadline):
                if isinstance(event, _SdkEvent):
                    mapped, delta = _translate(event.value)
                    usage = usage + delta
                    for item in mapped:
                        tracker.note_started(item)
                        yield item
                else:  # _TimedOut
                    _cancel_quietly(result, run_id)
                    for item in tracker.flush(buffer):
                        yield item
                    yield RunFinishedEvent(
                        reason="timeout",
                        citations=recorder.issued,
                        usage=usage,
                        elapsed_seconds=time.monotonic() - started,
                    )
                    return

                for item in tracker.flush(buffer):
                    yield item

                orphan = tracker.orphan_finish(event.value) if isinstance(event, _SdkEvent) else None
                if orphan is not None:
                    yield orphan
        except asyncio.CancelledError:
            _cancel_quietly(result, run_id)
            raise
        except Exception as exc:  # noqa: BLE001 —— 任何未归类异常都要变成带码的失败
            logger.warning("运行失败 run=%s error=%s", run_id, type(exc).__name__)
            for item in tracker.flush(buffer):
                yield item
            yield _failed_from_exception(exc, recorder, usage, started)
            return

        for item in tracker.flush(buffer):
            yield item
        yield RunFinishedEvent(
            reason="completed",
            citations=recorder.issued,
            usage=usage,
            elapsed_seconds=time.monotonic() - started,
        )

    def _pending_injections(
        self,
        history: Sequence[object],
        request: RunRequest,
        scope: ToolScope,
    ) -> list[InjectionItem]:
        """决定本轮要追加哪些基座自己生成的注入消息。

        只追加「与历史里最后一条同名消息不同」的那些（压缩策略第 8 节第 1 条：只在末尾追加，
        不原地替换）。判断完全由会话历史推导，不依赖进程内记忆。
        """
        pending: list[InjectionItem] = []

        if self._skills.activation_candidates():  # 没有任何可选 skill 时，空目录是噪音
            catalog = self._skills.catalog(surface=request.surface)
            if _last_content(history, _CATALOG_PREFIX) != catalog:
                pending.append(
                    InjectionItem(
                        source="skill-catalog",
                        content=catalog,
                        priority=InjectionPriority.SKILL_CATALOG,
                    )
                )

        for skill in request.activated:
            payload = render_activation(skill)
            prefix = _ACTIVATION_PREFIX_TEMPLATE.format(name=skill.name)
            if _last_content(history, prefix) != payload:
                pending.append(
                    InjectionItem(
                        source=f"skill-activation:{skill.name}",
                        content=payload,
                        priority=InjectionPriority.SKILL_ACTIVATION,
                    )
                )

        if scope.declared:  # 没有任何已声明工具时，可用性告知是噪音
            availability = scope.availability_item()
            if _last_content(history, _AVAILABILITY_PREFIX) != availability.content:
                pending.append(availability)

        return pending


# --- SDK 事件翻译 -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _SdkEvent:
    """包一层，避免把 SDK 的事件类型与 ``_TimedOut`` 混在一起判断。"""

    value: object


@dataclass(frozen=True, slots=True)
class _TimedOut:
    """到达时间上限。"""


async def _drain(result: RunResultStreaming, deadline: float) -> AsyncIterator[_SdkEvent | _TimedOut]:
    """按**剩余预算**逐次拉取 SDK 事件。

    每次拉取单独设超时，而不是把整个循环套进一个超时上下文：生成器把事件交给消费方时可能
    长时间挂起（慢速 SSE 客户端），那不是模型或工具在耗时，不该计入运行预算，更不该因此
    取消消费方的任务。
    """
    stream = result.stream_events()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            yield _TimedOut()
            return
        try:
            event = await asyncio.wait_for(anext(stream), timeout=remaining)
        except StopAsyncIteration:
            return
        except TimeoutError:
            yield _TimedOut()
            return
        yield _SdkEvent(event)


def _translate(event: object) -> tuple[list[RunEvent], RunUsage]:
    """把一个 SDK 事件翻译成零个或多个基座事件（外加可能的用量增量）。"""
    if isinstance(event, RawResponsesStreamEvent):
        raw = event.data
        kind = getattr(raw, "type", "")
        if kind == "response.output_text.delta":
            delta = getattr(raw, "delta", "")
            return ([TextDeltaEvent(delta=str(delta))] if delta else []), RunUsage()
        if kind == "response.completed":
            return [], _usage_of(raw)
        return [], RunUsage()

    if isinstance(event, RunItemStreamEvent) and event.name == "tool_called":
        name, call_id = _tool_call_identity(event.item)
        return [ToolCallStartedEvent(tool_name=name, call_id=call_id)], RunUsage()

    return [], RunUsage()


def _tool_call_identity(item: object) -> tuple[str, str]:
    """取工具调用的名字与调用标识；SDK 可能给对象也可能给映射。"""
    raw = getattr(item, "raw_item", None)
    if isinstance(raw, dict):
        return str(raw.get("name", "")), str(raw.get("call_id", ""))
    return str(getattr(raw, "name", "")), str(getattr(raw, "call_id", ""))


def _usage_of(raw: object) -> RunUsage:
    """从 ``response.completed`` 事件里取提供方返回的用量（不折算字符）。"""
    usage = getattr(getattr(raw, "response", None), "usage", None)
    if usage is None:
        return RunUsage(requests=1)
    return RunUsage(
        requests=1,
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
    )


class _ToolCallTracker:
    """跟踪工具调用的开始与结束，保证事件成对。

    单独成类是因为它是一份**跨事件的状态**：``tool_call_started`` 来自 SDK 的事件流，
    ``tool_call_finished`` 来自工具桥的缓冲；两者要在运行编排里对齐，而模型编出不存在的
    工具名时 SDK 会自己处置那次调用（不经过基座的权限门），需要补一条失败结束事件。
    """

    def __init__(self) -> None:
        """初始状态：没有进行中的调用，也没有已结束的调用。"""
        self._pending: dict[str, str] = {}
        self._finished: set[str] = set()

    def note_started(self, event: RunEvent) -> None:
        """记下一次已发出的工具调用开始。"""
        if isinstance(event, ToolCallStartedEvent):
            self._pending[event.call_id] = event.tool_name

    def flush(self, buffer: list[RunEvent]) -> Iterator[RunEvent]:
        """交出工具桥缓冲的事件，并记下哪些调用已经结束。"""
        while buffer:
            item = buffer.pop(0)
            if isinstance(item, ToolCallFinishedEvent):
                self._finished.add(item.call_id)
                self._pending.pop(item.call_id, None)
            yield item

    def orphan_finish(self, event: object) -> ToolCallFinishedEvent | None:
        """为「SDK 自己处置、没经过基座权限门」的调用补一条失败结束事件。

        目前唯一的来路是模型编出不存在的工具名：``RunConfig.tool_not_found_behavior``
        设成 ``return_error_to_model``，SDK 直接把错误交回模型继续跑。若不补，面会看到
        一次只有开始没有结束的调用。
        """
        call_id = _tool_output_call_id(event)
        if call_id is None or call_id not in self._pending or call_id in self._finished:
            return None
        self._finished.add(call_id)
        output = getattr(getattr(event, "item", None), "output", "")
        return ToolCallFinishedEvent(
            tool_name=self._pending.pop(call_id),
            call_id=call_id,
            ok=False,
            # 错误码与基座自己的 tool_not_registered 对齐，面看到的词汇只有一套。
            error_code="tool_not_registered",
            summary=str(output)[:SUMMARY_LIMIT],
        )


def _tool_output_call_id(event: object) -> str | None:
    """取 ``tool_output`` 事件对应的调用标识；不是这类事件时返回 ``None``。"""
    if not isinstance(event, RunItemStreamEvent) or event.name != "tool_output":
        return None
    raw = getattr(event.item, "raw_item", None)
    call_id = raw.get("call_id") if isinstance(raw, dict) else getattr(raw, "call_id", None)
    return str(call_id) if call_id else None


# --- 小工具 -----------------------------------------------------------------


def _window_callback() -> WindowCallback:
    """构造 ``session_input_callback``：窗口 = 由会话历史派生的裁剪 + 本轮新增项。"""

    def window(history: list[TResponseInputItem], new_items: list[TResponseInputItem]) -> list[TResponseInputItem]:
        """把 SDK 给的历史与本轮新增项按窗口策略合成模型输入。"""
        return derive_window(history, appended=new_items)

    return window


def _as_input_item(message: InjectionMessage) -> TResponseInputItem:
    """把注入消息转成 SDK 的输入项（形状一致，只是补齐 SDK 的联合类型）。"""
    if message["role"] == "assistant":
        return {"role": "assistant", "content": message["content"]}
    return {"role": "user", "content": message["content"]}


def _last_content(history: Sequence[object], prefix: str) -> str | None:
    """取历史里最后一条以 ``prefix`` 开头的消息内容；没有返回 ``None``。

    靠内容而不是靠位置：SDK 未把 ``limit=None`` 的读回顺序写成硬保证（基座文档「已知偏差」）。
    """
    found: str | None = None
    for item in history:
        content = message_text(item)
        if content is not None and content.lstrip().startswith(prefix):
            found = content
    return found


def _cancel_quietly(result: RunResultStreaming, run_id: str) -> None:
    """停掉 SDK 侧的运行；取消失败只记日志，不得掩盖触顶/取消本身的原因。"""
    try:
        result.cancel()
    except Exception as exc:  # noqa: BLE001 —— 见 docstring
        logger.warning("取消运行结果失败 run=%s error=%s", run_id, type(exc).__name__)


def _failed_from_exception(
    error: BaseException,
    recorder: CitationRecorder,
    usage: RunUsage,
    started: float,
) -> RunFailedEvent:
    """把一次未捕获的异常变成 ``run_failed``：模型侧问题与内部问题分开报码。"""
    reason = classify_model_failure(error)
    if reason == "unknown":
        return _failure("internal", f"运行内部错误（{type(error).__name__}）", recorder, usage, started, None)
    return _failure("model_unavailable", f"模型调用失败（{type(error).__name__}）", recorder, usage, started, error)


def _failure(
    code: RunFailureCode,
    detail: str,
    recorder: CitationRecorder,
    usage: RunUsage,
    started: float,
    cause: BaseException | None,
) -> RunFailedEvent:
    """造一个 ``run_failed`` 事件；模型失败额外带上细分原因。"""
    reason: ModelFailureReason | None = None
    if code == "model_unavailable" and cause is not None:
        reason = classify_model_failure(cause)
    return RunFailedEvent(
        code=code,
        detail=detail,
        citations=recorder.issued,
        usage=usage,
        elapsed_seconds=time.monotonic() - started,
        model_reason=reason,
    )


__all__ = ["SESSION_IO_DETAIL", "AgentRunner", "RunRequest"]
