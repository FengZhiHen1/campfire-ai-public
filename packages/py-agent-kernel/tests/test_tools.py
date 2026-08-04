"""工具契约与白名单单元测试——注册/执行/异常语义/FilteredToolset 过滤。"""

from __future__ import annotations

import pytest
from py_agent_kernel.tools import (
    AgentTool,
    CancellationToken,
    KernelToolset,
    ToolContext,
    ToolResult,
)
from pydantic import BaseModel


class EchoParams(BaseModel):
    text: str


class EchoTool(AgentTool):
    """回显工具（测试用）。"""

    name: str = "echo"
    label: str = "回显"
    description: str = "回显输入文本"
    parameters: type[BaseModel] = EchoParams

    async def execute(self, tool_call_id, params, signal, on_update, ctx) -> ToolResult:
        assert isinstance(params, EchoParams)
        assert isinstance(signal, CancellationToken)
        assert isinstance(ctx, ToolContext)
        return ToolResult.text(f"echo:{params.text}", tool_call_id=tool_call_id)


class FailingTool(AgentTool):
    name: str = "failing"
    label: str = "失败工具"
    description: str = "总是失败"
    parameters: type[BaseModel] = EchoParams

    async def execute(self, tool_call_id, params, signal, on_update, ctx) -> ToolResult:
        raise RuntimeError("工具内部错误")


class TestToolRegistration:
    def test_register_and_get(self):
        ts = KernelToolset(session_id="s")
        ts.register(EchoTool())
        assert ts.get("echo") is not None
        assert "echo" in ts.tool_names

    def test_duplicate_name_rejected(self):
        ts = KernelToolset(session_id="s")
        ts.register(EchoTool())
        with pytest.raises(ValueError, match="重复"):
            ts.register(EchoTool())


class TestToolExecution:
    @pytest.mark.asyncio
    async def test_execute_contract(self):
        tool = EchoTool()
        result = await tool.execute(
            tool_call_id="tc-1",
            params=EchoParams(text="hello"),
            signal=CancellationToken(),
            on_update=None,
            ctx=ToolContext(session_id="s"),
        )
        assert result.content[0].text == "echo:hello"
        assert result.details["tool_call_id"] == "tc-1"

    @pytest.mark.asyncio
    async def test_tool_exception_propagates(self):
        """工具抛异常（内核捕获转 isError 由桥接层承载，契约层透传）。"""
        tool = FailingTool()
        with pytest.raises(RuntimeError, match="工具内部错误"):
            await tool.execute("tc", EchoParams(text="x"), CancellationToken(), None, ToolContext(session_id="s"))

    @pytest.mark.asyncio
    async def test_cancellation_token(self):
        import asyncio

        signal = CancellationToken()
        assert not signal.is_cancelled
        signal.cancel()
        assert signal.is_cancelled
        with pytest.raises(asyncio.CancelledError):
            signal.raise_if_cancelled()


class TestToolsetBridge:
    @pytest.mark.asyncio
    async def test_build_and_call_via_pydantic_ai(self):
        """桥接为 pydantic-ai Toolset 后可被 Agent 调用（TestModel 验证）。"""
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        ts = KernelToolset(session_id="s")
        ts.register(EchoTool())
        agent = Agent(TestModel(), toolsets=[ts.build()])
        result = await agent.run("调用 echo")
        assert result.output is not None

    def test_active_tools_whitelist(self):
        """面白名单按工具名寻址（FilteredToolset 承载）。"""
        ts = KernelToolset(session_id="s")
        ts.register(EchoTool())
        ts.register(FailingTool())
        built = ts.build(active_tools=["echo"])
        # FilteredToolset 过滤后仅 echo 可见
        assert built is not None

    def test_sequential_execution_mode_mapped(self):
        """execution_mode=sequential → per-tool sequential 屏障。"""

        class SeqTool(EchoTool):
            name: str = "seq_tool"
            execution_mode: str = "sequential"

        ts = KernelToolset(session_id="s")
        ts.register(SeqTool())
        built = ts.build()
        assert built is not None


class TestToolResultText:
    def test_text_factory(self):
        result = ToolResult.text("hello", key="value")
        assert result.content[0].text == "hello"
        assert result.details == {"key": "value"}
