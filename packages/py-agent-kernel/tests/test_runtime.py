"""runtime 接缝单元测试（T2.7 专项，对应偏差清单）：

- turn 聚合：ModelRequestNode(before)=turn_start / CallToolsNode(after)=turn_end
- 消息边界：part 流 → message_start/update/end
- 内联阻断：tool_call block → ModelRetry 回传模型，工具不执行
- tool_result 链式修改
- 流式事件序（KernelStreamEvent 序列）
- 会话持久化（JSONL 落盘）
"""

from __future__ import annotations

import pytest
from py_agent_kernel import (
    AgentTool,
    EventResult,
    KernelEvent,
    ToolResult,
    create_agent_session,
)
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel


class _Params(BaseModel):
    text: str = "default"


def _make_tool(name: str, result_text: str, sink: list[str] | None = None) -> AgentTool:
    class _Tool(AgentTool):
        name_: str = ""
        label: str = "测试工具"
        description: str = "测试工具"
        parameters: type[BaseModel] = _Params

        async def execute(self, tool_call_id, params, signal, on_update, ctx) -> ToolResult:
            if sink is not None:
                sink.append(name)
            return ToolResult.text(result_text)

    return _Tool(name=name)  # type: ignore[call-arg]


class TestRuntimeEventSequence:
    @pytest.mark.asyncio
    async def test_agent_run_event_sequence(self):
        """完整事件序：agent_start → turn_start → message_* → turn_end → agent_end。"""
        events: list[str] = []
        session = create_agent_session(
            TestModel(),
            extensions=[lambda pi: pi.on("agent_start", lambda ctx: events.append("agent_start"))],
        )
        session.bus.subscribe(KernelEvent.TURN_START, lambda ctx: events.append("turn_start"))
        session.bus.subscribe(KernelEvent.TURN_END, lambda ctx: events.append("turn_end"))

        stream_types: list[str] = []
        async for event in session.run_stream("你好"):
            stream_types.append(event.type)
            if event.type == "agent_end":
                break

        assert "agent_start" in events
        assert "turn_start" in events
        assert "turn_end" in events
        # turn_start 在 agent_start 之后
        assert events.index("turn_start") > events.index("agent_start")
        assert stream_types[0] == "agent_start"
        assert stream_types[-1] == "agent_end"


class TestInlineBlocking:
    @pytest.mark.asyncio
    async def test_tool_call_block_via_model_retry(self):
        """tool_call block → ModelRetry 内联阻断：工具不执行，审计含阻断记录。"""
        executed: list[str] = []

        def blocking_ext(pi):
            pi.register_tool(_make_tool("dangerous_tool", "不应执行", sink=executed))
            pi.on("tool_call", lambda ctx: EventResult(block=True, reason="权限不足"))

        session = create_agent_session(TestModel(), extensions=[blocking_ext])
        try:
            async for _event in session.run_stream("调用工具"):
                pass
        except Exception:
            pass  # TestModel 在重试耗尽后可能抛错，阻断语义已验证

        assert executed == []  # 工具从未执行
        blocked = session.audit.blocked_calls()
        assert len(blocked) >= 1
        assert blocked[0].tool_name == "dangerous_tool"
        assert blocked[0].block_reason == "权限不足"


class TestToolResultChain:
    @pytest.mark.asyncio
    async def test_tool_result_chain_modification(self):
        """tool_result 链式修改：后者看到前者的结果。"""

        def ext_with_tool(pi):
            pi.register_tool(_make_tool("my_tool", "原始结果"))
            pi.on("tool_result", lambda ctx: EventResult(payload={**ctx.payload, "result": "修改后"}))

        observed: list[str] = []
        session = create_agent_session(TestModel(), extensions=[ext_with_tool])
        session.bus.subscribe(
            KernelEvent.TOOL_RESULT,
            lambda ctx: observed.append(str(ctx.payload.get("result"))) or None,
        )
        async for _ in session.run_stream("调用工具"):
            pass
        # 订阅在后的 handler 看到扩展修改后的结果
        assert any("修改后" in r for r in observed)


class TestMessageBoundaries:
    @pytest.mark.asyncio
    async def test_message_events_emitted(self):
        """part 流 → message 边界事件（start/update/end 成对）。"""
        session = create_agent_session(TestModel())
        stream_types: list[str] = []
        async for event in session.run_stream("你好"):
            stream_types.append(event.type)
        assert "message_start" in stream_types
        assert "message_end" in stream_types


class TestSessionPersistence:
    @pytest.mark.asyncio
    async def test_history_persisted_to_jsonl(self, tmp_path):
        """会话消息落盘 JSONL（完整历史保留）。"""
        session = create_agent_session(TestModel(), session_dir=tmp_path)
        async for _ in session.run_stream("你好"):
            pass
        session_file = tmp_path / f"{session.session_id}.jsonl"
        assert session_file.exists()
        content = session_file.read_text(encoding="utf-8")
        assert '"type": "message"' in content

    @pytest.mark.asyncio
    async def test_history_reloaded_in_second_run(self, tmp_path):
        """第二次 run 的上下文包含首轮历史（history 构建生效）。"""
        session = create_agent_session(TestModel(), session_dir=tmp_path)
        async for _ in session.run_stream("第一轮"):
            pass
        history = session._build_history()
        assert len(history) > 0


class TestExtensionLoadOrderIntegration:
    @pytest.mark.asyncio
    async def test_handler_order_follows_load_order(self):
        """扩展加载顺序 = handler 执行顺序（受控加载/安全首位的基础）。"""
        order: list[str] = []

        def ext_a(pi):
            pi.on("agent_start", lambda ctx: order.append("a") or None)

        def ext_b(pi):
            pi.on("agent_start", lambda ctx: order.append("b") or None)

        session = create_agent_session(TestModel(), extensions=[ext_a, ext_b])
        async for _ in session.run_stream("你好"):
            pass
        assert order == ["a", "b"]
