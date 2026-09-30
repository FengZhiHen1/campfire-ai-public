"""把基座的注册形状接到 SDK 上：agent、函数工具、运行配置。

职责：只做「基座形状 → SDK 对象」的翻译（见 :class:`ToolBridge`、:func:`build_agent`、
:func:`build_run_config`）。
边界：不做裁决（可用性与权限由 dispatcher 在执行前判定），不拥有会话与引用索引。
参考：docs/技术设计/technical-details/通用基座.md 第 5 节与第 7 节。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from agents import (
    Agent,
    FunctionTool,
    FunctionToolResult,
    RunConfig,
    RunContextWrapper,
    ToolsToFinalOutputResult,
)
from agents.items import TResponseInputItem
from agents.models.interface import Model

from campfire.agent.model import ModelBinding
from campfire.agent.tools import Tool, ToolDispatcher, ToolFailure

from .events import (
    SUMMARY_LIMIT,
    ActionCardEvent,
    CandidateEvent,
    CitationEvent,
    QuestionEvent,
    RunEvent,
    ToolCallFinishedEvent,
)

EventSink = Callable[[RunEvent], None]
"""事件的同步出口：编排侧把它接到缓冲区。

事件用同步回调交出去（编排侧只是缓冲），因为 SDK 的 `on_invoke_tool` 在流式循环
内部被调用，而 Python 的异步生成器无法从嵌套回调里往外 yield。
"""

WindowCallback = Callable[[list[TResponseInputItem], list[TResponseInputItem]], list[TResponseInputItem]]
"""`RunConfig.session_input_callback` 的形状：`(历史, 本轮新增) -> 本轮模型输入`。"""

WORKFLOW_NAME = "campfire"
"""SDK tracing 的工作流名；用于在追踪里区分本应用。"""


class QuestionGate:
    """「本次运行问出问题了没有」的唯一事实来源。

    为什么需要它，而不直接用 SDK 现成的机制：让运行结束在提问处要给 SDK 一个
    `tool_use_behavior` 回调，而回调只能拿到工具结果的字符串，字符串里分不出
    「问成了」与「参数不合法的工具错误」。文档里更省事的
    `tool_use_behavior={"stop_at_tool_names": ["ask_user"]}` 有更严重的缺陷：它只看工具名，
    失败也停——实测模型给一组不合法参数（`items` 为空）时该机制照样结束运行，
    而没有任何 `question` 事件发出，使用者的表现是「回复突然断掉，界面上什么都没有」。
    因此判据只能来自「这次调用是否真的产出了提问」，而那件事只有工具桥知道。
    """

    def __init__(self) -> None:
        """初始状态：本次运行还没有问出问题，运行照常继续。"""
        self._asked_text: str | None = None

    def note_question(self, *, text: str) -> None:
        """记下「一次提问成功产出」以及它回给模型的那句话。

        `text` 同时用作运行结束时的 `final_output`：提问之后不再有模型轮次，`final_output`
        就是这次运行的最终产出，用它自己给模型的话比另编一句更诚实（SDK 不会把它写成
        单独的助手消息，实测会话里只有 function_call 与 function_call_output 两项）。
        """
        self._asked_text = text

    def final_output(self) -> str | None:
        """运行应结束在提问处时返回最终产出；`None` 表示本次工具批次要照常回到模型。"""
        return self._asked_text


def stop_after_question(
    gate: QuestionGate,
) -> Callable[[RunContextWrapper[object], list[FunctionToolResult]], ToolsToFinalOutputResult]:
    """构造 `Agent.tool_use_behavior`：真的问出问题就结束本次运行。

    依据基座第 7.2 节「模型调用它即结束本次运行并发出该事件」。判据取自
    :class:`QuestionGate`（见该类的说明：按工具名停会在参数不合法时静默截断运行）。
    没有问出问题时返回 `is_final_output=False`，SDK 的行为与默认的 `run_llm_again` 相同
    （工具结果照常回到模型，它可据错误提示改一次参数）。
    """

    def behavior(
        _context: RunContextWrapper[object],
        tool_results: list[FunctionToolResult],
    ) -> ToolsToFinalOutputResult:
        """只看「有没有真的产出提问」，不看工具名、不看字符串。"""
        text = gate.final_output() if tool_results else None
        if text is None:
            return ToolsToFinalOutputResult(is_final_output=False, final_output=None)
        return ToolsToFinalOutputResult(is_final_output=True, final_output=text)

    return behavior


class ToolBridge:
    """把基座工具翻译成 SDK 的 `FunctionTool`。

    依据第 5 节与第 7 节，这里刻意只做翻译，不做裁决：

    - 声明保持稳定：交给 SDK 的工具数组来自 `ToolPool.declared()`（超集、按名字排序），
      一条对话内不变。可用性靠消息告知，可靠性靠 :class:`~campfire.agent.tools.ToolDispatcher`
      在执行前拒绝——暴露范围不是安全边界。
    - 工具调用的事件归属：`tool_call_started` 由运行编排从 SDK 的事件流发出（那是模型
      提出请求的时刻），`tool_call_finished` 由这里在调用边界发出（只有这里知道错误码与
      产出）。一件事只有一个发出点。
    """

    def __init__(self, dispatcher: ToolDispatcher, *, sink: EventSink, gate: QuestionGate | None = None) -> None:
        """绑定权限门、事件出口与提问闸门。

        `gate` 不传时提问仍会产出 `question` 事件，只是运行不会停在提问处（照常回到模型）——
        便于单测只验证事件翻译；真实运行由 :class:`~campfire.agent.runtime.runner.AgentRunner`
        传入闸门，使「结束本次运行」与「发出事件」两件事由同一个事实触发。
        """
        self._dispatcher = dispatcher
        self._sink = sink
        self._gate = gate

    def function_tools(self) -> list[FunctionTool]:
        """按稳定声明顺序构造 SDK 工具。"""
        return [self._build(tool) for tool in self._dispatcher.declared]

    def _build(self, tool: Tool) -> FunctionTool:
        """为一个基座工具造出 SDK 工具。"""
        name = tool.name

        async def on_invoke(tool_context: object, arguments_json: str) -> str:
            """SDK 的调用入口：转交给权限门与事件桥。"""
            return await self._invoke(name, tool_context, arguments_json)

        return FunctionTool(
            name=name,
            description=tool.description,
            params_json_schema=tool.parameters,
            # 严格模式让模型更可能给对参数。已核实：pydantic 导出的 schema（含默认值）
            # 能通过 SDK 的 ensure_strict_json_schema 归一。
            strict_json_schema=True,
            on_invoke_tool=on_invoke,
        )

    async def _invoke(self, name: str, tool_context: object, arguments_json: str) -> str:
        """执行一次工具调用并把结果翻译成模型可见文本。"""
        call_id = str(getattr(tool_context, "tool_call_id", ""))
        outcome = await self._dispatcher.dispatch(name, arguments_json)

        if isinstance(outcome, ToolFailure):
            self._sink(
                ToolCallFinishedEvent(
                    tool_name=name,
                    call_id=call_id,
                    ok=False,
                    error_code=outcome.code,
                    summary=outcome.message[:SUMMARY_LIMIT],
                )
            )
            return outcome.as_model_text()

        for record in outcome.citations:
            self._sink(CitationEvent(citation=record))
        for candidate in outcome.candidates:
            self._sink(CandidateEvent(candidate=candidate))
        for card in outcome.cards:
            self._sink(
                ActionCardEvent(
                    card_id=card.card_id,
                    title=card.title,
                    sections=card.sections,
                    states=card.states,
                    annotations=card.annotations,
                )
            )
        if outcome.question is not None:
            # 事件的字段名与载荷逐字一致（基座 7.2 节），所以这里是平铺搬运，不是重新命名。
            self._sink(QuestionEvent(batch_id=outcome.question.batch_id, items=outcome.question.items))
            if self._gate is not None:
                # 与事件同源：闸门只在「确实产出了提问」时被打开，因此运行不会因为一次参数
                # 不合法的调用而静默截断（见 QuestionGate 的说明）。
                self._gate.note_question(text=outcome.text)

        self._sink(
            ToolCallFinishedEvent(
                tool_name=name,
                call_id=call_id,
                ok=True,
                error_code=None,
                summary=outcome.text[:SUMMARY_LIMIT],
            )
        )
        return outcome.text


def build_agent(
    *,
    name: str,
    instructions: str,
    model: Model,
    tools: Sequence[FunctionTool],
    tool_use_behavior: Callable[[RunContextWrapper[object], list[FunctionToolResult]], ToolsToFinalOutputResult]
    | None = None,
) -> Agent:
    """构造 SDK 的 Agent。

    `instructions` 必须是静态字符串：技能目录、产品侧注入的业务上下文、时间、活跃技能
    一律不得进入系统提示（压缩策略第 8 节第 2 条），它们只能作为尾部消息注入。动态内容
    由 :class:`~campfire.agent.context.InjectionBatch` 负责，本函数不接受它。

    `tool_use_behavior` 不传即 SDK 默认的 `run_llm_again`（工具结果回到模型继续跑）；
    运行编排传入 :func:`stop_after_question` 以支持「运行结束于提问」（基座第 7.2 节）。
    """
    return Agent(
        name=name,
        instructions=instructions,
        model=model,
        tools=list(tools),
        tool_use_behavior=tool_use_behavior or "run_llm_again",
    )


def build_run_config(*, binding: ModelBinding, window: WindowCallback) -> RunConfig:
    """构造运行配置。

    `tracing_disabled` 保持默认（SDK 内置 tracing 是技术栈设计的选择），但
    `trace_include_sensitive_data=False`：追踪默认会带上模型输入输出，而使用者数据属于
    外部数据处理范畴（`EVID-C` 未关闭前只允许虚构样例，见技术栈设计第 3 节）。
    真正需要用户内容的观测走我们自己的运行记录（基座第 8 节）。
    """
    return RunConfig(
        model=binding.model,
        model_settings=binding.settings,
        session_input_callback=window,
        # 模型编出一个不存在的工具名时，SDK 默认直接抛错中断本次运行（ModelBehaviorError）。
        # 基座第 9 节的失败语义是「工具失败作为结果回给模型（可恢复）」，所以把错误
        # 交回模型——它可能只是记错了名字，换一个就能继续。
        tool_not_found_behavior="return_error_to_model",
        trace_include_sensitive_data=False,
        workflow_name=WORKFLOW_NAME,
    )
