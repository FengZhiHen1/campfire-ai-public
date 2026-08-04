"""py-agent-kernel 工具集装配——AgentTool → pydantic-ai Toolset 桥接 + 面白名单。

职责：
- KernelToolset：持有内核注册的 AgentTool，桥接为 pydantic-ai FunctionToolset
- set_active_tools：面白名单（按工具名寻址，pi 语义——跨扩展来源一视同仁）
- 错误语义：工具抛异常 → ToolReturn(is_error?) —— pydantic-ai 原生把异常
  转为 retry prompt 回传模型；内核保留完整错误文本，禁止伪装正常 content

桥接说明（pydantic-ai 2.23）：
- 每个 AgentTool 动态生成带显式签名的 async 函数（字段级 JSON Schema 由
  parameters 模型注解生成），ctx 注入 RunContext；
- execution_mode="sequential" 映射 per-tool sequential=True 屏障。
"""

from __future__ import annotations

import inspect
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import FilteredToolset, FunctionToolset

from py_agent_kernel.tools.types import (
    AgentTool,
    CancellationToken,
    ImageContent,
    TextContent,
    ToolContext,
    ToolResult,
)


def _result_to_model_text(result: ToolResult) -> str:
    """ToolResult content blocks → 模型可读文本（image 块以占位说明呈现）。"""
    parts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        elif isinstance(block, ImageContent):
            parts.append(f"[image:{block.mime_type}]")
    return "\n".join(parts)


class KernelToolset:
    """内核工具集——注册、桥接与白名单装配。

    宿主/扩展经 register() 注册 AgentTool；build() 产出 pydantic-ai
    Toolset（可经 set_active_tools 施加面白名单后使用）。
    """

    def __init__(self, session_id: str, cwd: str | None = None) -> None:
        self._tools: dict[str, AgentTool] = {}
        self._session_id = session_id
        self._cwd = cwd

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register(self, tool: AgentTool) -> None:
        """注册工具（重名拒绝——工具名全局唯一寻址）。"""
        if tool.name in self._tools:
            raise ValueError(f"工具名重复注册: {tool.name}")
        self._tools[tool.name] = tool

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get(self, name: str) -> AgentTool | None:
        return self._tools.get(name)

    # ------------------------------------------------------------------
    # 桥接
    # ------------------------------------------------------------------

    def build(self, active_tools: list[str] | None = None) -> Any:
        """构建 pydantic-ai Toolset。

        Args:
            active_tools: 面白名单（工具名列表）；None 表示全量。
        """
        toolset: FunctionToolset[Any] = FunctionToolset()
        for tool in self._tools.values():
            toolset.add_function(
                self._make_runner(tool),
                name=tool.name,
                description=tool.description,
                sequential=tool.execution_mode == "sequential",
            )

        if active_tools is None:
            return toolset
        active = set(active_tools)
        return FilteredToolset(toolset, filter_func=lambda _ctx, tool_def: tool_def.name in active)

    def _make_runner(self, tool: AgentTool) -> Any:
        """为 AgentTool 生成带显式签名的 async 函数（pydantic-ai 桥接）。

        显式签名使 pydantic-ai 能从字段注解生成字段级 JSON Schema。
        """
        tool_ref = tool
        session_id = self._session_id
        cwd = self._cwd

        async def runner(ctx: RunContext[Any], /, **kwargs: Any) -> str:
            params = tool_ref.parameters.model_validate(kwargs)
            signal = CancellationToken()
            tool_ctx = ToolContext(session_id=session_id, cwd=cwd)
            # RunContext 携带 tool_call_id（pydantic-ai 2.23）
            tool_call_id = getattr(ctx, "tool_call_id", None) or ""
            result = await tool_ref.execute(
                tool_call_id=tool_call_id,
                params=params,
                signal=signal,
                on_update=None,
                ctx=tool_ctx,
            )
            return _result_to_model_text(result)

        # 动态签名：ctx + parameters 模型字段；
        # pydantic-ai 经 get_type_hints 读取 __annotations__ 生成字段级 JSON Schema
        sig_params: list[inspect.Parameter] = [
            inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_ONLY, annotation=RunContext),
        ]
        annotations: dict[str, Any] = {"ctx": RunContext, "return": str}
        for field_name, field_info in tool.parameters.model_fields.items():
            default = field_info.default if not field_info.is_required() else inspect.Parameter.empty
            sig_params.append(
                inspect.Parameter(
                    field_name,
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=field_info.annotation,
                    default=default,
                )
            )
            annotations[field_name] = field_info.annotation
        runner.__signature__ = inspect.Signature(sig_params, return_annotation=str)  # type: ignore[attr-defined]
        runner.__annotations__ = annotations
        runner.__name__ = tool.name
        runner.__doc__ = tool.description
        return runner


def set_active_tools(toolset: Any, tool_names: list[str]) -> Any:
    """面白名单施加（宿主为不同执行面配置可用工具子集）。

    按工具名寻址（pi 语义）：白名单不感知工具归属扩展。
    """
    active = set(tool_names)
    return FilteredToolset(toolset, filter_func=lambda _ctx, tool_def: tool_def.name in active)


__all__ = ["KernelToolset", "set_active_tools", "ToolDefinition"]
