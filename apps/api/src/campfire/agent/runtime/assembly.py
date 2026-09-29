"""把基座的注册形状接到 SDK 上：agent、函数工具、运行配置。

依据 docs/技术设计/technical-details/通用基座.md 第 5 节与第 7 节，这里刻意只做**翻译**，
不做裁决：

- **声明保持稳定**：交给 SDK 的工具数组来自 ``ToolPool.declared()``（超集、按名字排序），
  一条对话内不变。可用性靠消息告知，可靠性靠 :class:`~campfire.agent.tools.ToolDispatcher`
  在执行前拒绝——**暴露范围不是安全边界**。
- **工具调用的事件归属**：``tool_call_started`` 由运行编排从 SDK 的事件流发出（那是模型
  提出请求的时刻），``tool_call_finished`` 由这里在调用边界发出（只有这里知道错误码与
  产出）。一件事只有一个发出点。
- 事件用**同步回调**交出去（编排侧只是缓冲），因为 SDK 的 ``on_invoke_tool`` 在流式循环
  内部被调用，而 Python 的异步生成器无法从嵌套回调里往外 yield。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from agents import Agent, FunctionTool, RunConfig
from agents.items import TResponseInputItem
from agents.models.interface import Model

from campfire.agent.model import ModelBinding
from campfire.agent.tools import Tool, ToolDispatcher, ToolFailure

from .events import (
    SUMMARY_LIMIT,
    CandidateEvent,
    CitationEvent,
    RunEvent,
    ToolCallFinishedEvent,
)

EventSink = Callable[[RunEvent], None]
"""事件的同步出口：编排侧把它接到缓冲区。"""

WindowCallback = Callable[[list[TResponseInputItem], list[TResponseInputItem]], list[TResponseInputItem]]
"""``RunConfig.session_input_callback`` 的形状：``(历史, 本轮新增) -> 本轮模型输入``。"""

WORKFLOW_NAME = "campfire"
"""SDK tracing 的工作流名；用于在追踪里区分本应用。"""


class ToolBridge:
    """把基座工具翻译成 SDK 的 ``FunctionTool``。"""

    def __init__(self, dispatcher: ToolDispatcher, *, sink: EventSink) -> None:
        """绑定权限门与事件出口。"""
        self._dispatcher = dispatcher
        self._sink = sink

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
) -> Agent:
    """构造 SDK 的 Agent。

    ``instructions`` 必须是**静态**字符串：技能目录、档案摘要、检索结果、时间、活跃技能
    一律不得进入系统提示（压缩策略第 8 节第 2 条），它们只能作为尾部消息注入。动态内容
    由 :class:`~campfire.agent.context.InjectionBatch` 负责，本函数不接受它。
    """
    return Agent(name=name, instructions=instructions, model=model, tools=list(tools))


def build_run_config(*, binding: ModelBinding, window: WindowCallback) -> RunConfig:
    """构造运行配置。

    ``tracing_disabled`` 保持默认（SDK 内置 tracing 是技术栈设计的选择），但
    ``trace_include_sensitive_data=False``：追踪默认会带上模型输入输出，而使用者资料属于
    外部数据处理范畴（``EVID-C`` 未关闭前只允许虚构样例，见技术栈设计第 3 节）。
    真正需要用户内容的观测走我们自己的运行记录（基座第 8 节）。
    """
    return RunConfig(
        model=binding.model,
        model_settings=binding.settings,
        session_input_callback=window,
        # 模型编出一个不存在的工具名时，SDK 默认直接抛错中断本次运行（ModelBehaviorError）。
        # 基座第 9 节的失败语义是「工具失败作为结果回给模型（可恢复）」，所以改成把错误
        # 交回模型——它可能只是记错了名字，换一个就能继续。
        tool_not_found_behavior="return_error_to_model",
        trace_include_sensitive_data=False,
        workflow_name=WORKFLOW_NAME,
    )
