"""py-agent-kernel runtime——AgentSession（宿主装配主类）。

职责（Agent内核框架 §二/§四/§十）：
- 组装：EventBus + KernelToolset + 扩展加载 + SkillLoader + SessionTree
- Hooks 翻译：pydantic-ai Hooks/Capabilities → 内核统一事件面
- turn 聚合：ModelRequestNode(before) = turn_start；CallToolsNode(after) = turn_end
- 内联阻断：tool_call block → before_tool_execute 抛 ModelRetry（reason 回传模型）
- 流式装配：AgentStreamEvent → KernelStreamEvent（供宿主 SSE）
- steering/follow-up：asap（下个 LLM 调用前注入）/ when_idle（run 结束前注入）

偏差清单落地（§十）：
- 并行工具事件序按 pydantic-ai 原生语义（不重排）
- 会话字节不兼容 pi，仅结构同构
- HITL（DeferredToolRequests）不经本层混用——仅人工审批流（宿主显式装配）
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from pydantic_ai import Agent, ModelRetry
from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import ModelRequest, UserPromptPart

from py_agent_kernel.events.bus import EventBus
from py_agent_kernel.events.types import EventContext, KernelEvent
from py_agent_kernel.extension_api import (
    LoadedExtension,
    load_extensions,
)
from py_agent_kernel.runtime.audit import AuditRecorder, ToolCallRecord, UsageTracker
from py_agent_kernel.runtime.streaming import KernelStreamEvent, translate_stream_event
from py_agent_kernel.session.messages import (
    PendingMessageQueue,
    deserialize_messages,
    serialize_messages,
)
from py_agent_kernel.session.store import SessionTree
from py_agent_kernel.skills.loader import SkillLoader
from py_agent_kernel.tools.toolset import KernelToolset


class AgentSession:
    """Agent 会话——宿主装配与运行入口。

    宿主用法（§三 接口契约）：
        session = create_agent_session(model=..., extensions=[...], ...)
        result = await session.run("用户输入")
        async for event in session.run_stream("用户输入"): ...
        await session.close()
    """

    def __init__(
        self,
        model: Any,
        *,
        system_prompt: str = "",
        output_type: Any = None,
        extensions: list[Any] | None = None,
        skills_dirs: list[str | Path] | None = None,
        session_dir: str | Path | None = None,
        active_tools: list[str] | None = None,
        session_id: str | None = None,
        audit_sink: Callable[[ToolCallRecord], None] | None = None,
        compaction_threshold: int = 40,
    ) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self.bus = EventBus()
        self.toolset = KernelToolset(session_id=self.session_id, cwd=str(session_dir) if session_dir else None)
        self.audit = AuditRecorder(sink=audit_sink)
        self.usage = UsageTracker()
        self.pending = PendingMessageQueue()
        self._compaction_threshold = compaction_threshold

        # 扩展加载（加载顺序即优先级）
        self.loaded_extensions: list[LoadedExtension] = load_extensions(extensions or [], self.bus, self.toolset)

        # Skill 发现（扩展 skills/ 目录 + 宿主额外目录 + resources_discover 贡献）
        skill_roots: list[Path] = []
        for ext in self.loaded_extensions:
            skill_roots.extend(ext.skill_dirs)
        for d in skills_dirs or []:
            skill_roots.append(Path(d))
        self.skill_loader = SkillLoader()
        self.skill_loader.discover(skill_roots)

        # 会话存储（JSONL 树）
        self.tree: SessionTree | None = None
        if session_dir is not None:
            self.tree = SessionTree(Path(session_dir) / f"{self.session_id}.jsonl")

        # 基础系统提示 + Skill 目录（渐进披露第一层）
        base_prompt = system_prompt
        catalog = self.skill_loader.system_prompt_catalog()
        if catalog:
            base_prompt = f"{base_prompt}\n\n{catalog}" if base_prompt else catalog
        self._system_prompt = base_prompt

        # pydantic-ai Agent 组装
        agent_kwargs: dict[str, Any] = {
            "instructions": base_prompt,
            "capabilities": [self._make_hooks()],
            "toolsets": [self.toolset.build(active_tools)],
        }
        if output_type is not None:
            agent_kwargs["output_type"] = output_type
        self._agent = Agent(model, **agent_kwargs)

        self._session_started = False
        self._turn_index = 0

    # ==================================================================
    # 公共运行面
    # ==================================================================

    async def run(self, user_input: str) -> Any:
        """一次性运行（聚合全部输出）。"""
        final_result: Any = None
        async for event in self.run_stream(user_input):
            if event.type == "agent_end":
                final_result = event.data.get("result")
        return final_result

    async def run_stream(self, user_input: str) -> AsyncIterator[KernelStreamEvent]:
        """流式运行——内核流事件序列（宿主 SSE 消费）。

        事件序：input → before_agent_start → agent_start →
                [turn_start → message_*/tool_execution_* → turn_end] × N → agent_end
        """
        queue: asyncio.Queue[KernelStreamEvent] = asyncio.Queue()
        self._stream_queue = queue

        async def _run() -> None:
            try:
                result = await self._run_inner(user_input)
                await queue.put(KernelStreamEvent(type="agent_end", data={"result": result}))
            except Exception as exc:
                await queue.put(KernelStreamEvent(type="agent_end", data={"result": None, "error": str(exc)}))

        task = asyncio.create_task(_run())
        try:
            while True:
                event = await queue.get()
                yield event
                if event.type == "agent_end":
                    break
        finally:
            self._stream_queue = None
            if not task.done():
                task.cancel()

    async def close(self) -> None:
        """会话卸载——session_shutdown 通知与资源清理（扩展在此释放会话级资源）。"""
        if self._session_started:
            await self.bus.emit(EventContext(KernelEvent.SESSION_SHUTDOWN, self.session_id, {}))
            self._session_started = False

    # ==================================================================
    # 运行主流程（编排——代码持有控制流）
    # ==================================================================

    async def _run_inner(self, user_input: str) -> Any:
        # 会话生命周期：首次 run 建立会话
        if not self._session_started:
            await self.bus.emit(EventContext(KernelEvent.SESSION_START, self.session_id, {}))
            self._session_started = True

        # input 事件（可 transform / handled）
        input_result = await self.bus.emit(
            EventContext(KernelEvent.INPUT, self.session_id, {"text": user_input})
        )
        if input_result.handled:
            return None
        effective_input = str((input_result.payload or {}).get("text", user_input))

        await self.bus.emit(EventContext(KernelEvent.AGENT_START, self.session_id, {"input": effective_input}))
        await self._emit_stream(KernelStreamEvent(type="agent_start", data={}))

        # before_agent_start（可改系统提示 / 注入消息）
        before_result = await self.bus.emit(
            EventContext(
                KernelEvent.BEFORE_AGENT_START,
                self.session_id,
                {"system_prompt": self._system_prompt, "inject_messages": []},
            )
        )
        before_payload = before_result.payload or {}
        instructions = str(before_payload.get("system_prompt", self._system_prompt))
        inject_messages: list[str] = list(before_payload.get("inject_messages", []))

        # 注入消息拼入用户输入前部（before_agent_start 语义承载）
        if inject_messages:
            effective_input = "\n".join([*inject_messages, effective_input])

        # 上下文窗口构建（含 compaction 检查）
        history = self._build_history()

        # pydantic-ai 运行
        result = await self._agent.run(
            effective_input,
            message_history=history,
            instructions=instructions,
        )

        # 用量追踪
        try:
            self.usage.track_run(result.usage(), tool_call_count=0)
        except Exception:
            pass

        # 历史持久化（完整历史始终保留）
        self._persist_messages(result.new_messages())

        # follow-up（when_idle）：agent 将终止时注入——非空则继续一轮
        idle_messages = self.pending.drain_when_idle()
        if idle_messages:
            follow_up_input = "\n".join(idle_messages)
            return await self._run_inner(follow_up_input)

        await self.bus.emit(
            EventContext(KernelEvent.AGENT_END, self.session_id, {"output": str(result.output)[:200]})
        )
        return result.output

    # ==================================================================
    # Hooks 翻译层（pydantic-ai 接缝 → 内核事件面）
    # ==================================================================

    def _make_hooks(self) -> Hooks:
        session = self

        async def before_run(ctx: Any) -> None:
            return None

        async def after_run(ctx: Any, *, result: Any) -> Any:
            return result

        async def before_node_run(ctx: Any, *, node: Any) -> Any:
            # turn 聚合：ModelRequestNode 开始 = turn_start（§十 接缝规则）
            from pydantic_ai import ModelRequestNode

            if isinstance(node, ModelRequestNode):
                session._turn_index += 1
                await session.bus.emit(
                    EventContext(KernelEvent.TURN_START, session.session_id, {"turn_index": session._turn_index})
                )
                await session._emit_stream(
                    KernelStreamEvent(type="turn_start", data={"turn_index": session._turn_index})
                )
            return node

        async def after_node_run(ctx: Any, *, node: Any, result: Any) -> Any:
            # turn 聚合：CallToolsNode 结束 = turn_end（§十 接缝规则）
            from pydantic_ai import CallToolsNode

            if isinstance(node, CallToolsNode):
                await session.bus.emit(
                    EventContext(KernelEvent.TURN_END, session.session_id, {"turn_index": session._turn_index})
                )
                await session._emit_stream(
                    KernelStreamEvent(type="turn_end", data={"turn_index": session._turn_index})
                )
            return result

        async def on_event(ctx: Any, event: Any, /) -> Any:
            # 流式事件翻译 + message_* 内核事件
            kernel_event = translate_stream_event(event)
            if kernel_event is not None:
                await session._translate_message_events(kernel_event)
                await session._emit_stream(kernel_event)
            return event

        async def before_tool_execute(ctx: Any, *, call: Any, tool_def: Any, args: Any) -> Any:
            # tool_call 可阻断事件——block → ModelRetry（内联阻断承载，§十）
            result = await session.bus.emit(
                EventContext(
                    KernelEvent.TOOL_CALL,
                    session.session_id,
                    {
                        "tool_name": tool_def.name,
                        "tool_call_id": call.tool_call_id,
                        "params": dict(args),
                    },
                )
            )
            session._record_tool_call(
                tool_name=tool_def.name,
                tool_call_id=call.tool_call_id,
                params=dict(args),
                blocked=result.block,
                block_reason=result.reason,
            )
            if result.block:
                raise ModelRetry(result.reason or "工具调用被阻断")
            return args

        async def after_tool_execute(ctx: Any, *, call: Any, tool_def: Any, args: Any, result: Any) -> Any:
            # tool_result 可干预事件——链式修改（补丁语义）
            emit_result = await session.bus.emit(
                EventContext(
                    KernelEvent.TOOL_RESULT,
                    session.session_id,
                    {
                        "tool_name": tool_def.name,
                        "tool_call_id": call.tool_call_id,
                        "result": result,
                        "is_error": False,
                    },
                )
            )
            modified = (emit_result.payload or {}).get("result", result)
            return modified

        async def before_model_request(ctx: Any, request_context: Any, /) -> Any:
            # context 事件（每次 LLM 调用前，可修改消息列表——非破坏）
            messages = list(getattr(request_context, "messages", []) or [])
            emit_result = await session.bus.emit(
                EventContext(KernelEvent.CONTEXT, session.session_id, {"messages": messages})
            )
            modified = (emit_result.payload or {}).get("messages", messages)
            if modified is not messages and hasattr(request_context, "messages"):
                try:
                    request_context.messages = modified
                except Exception:
                    pass
            # steering（asap）：当前 turn 工具执行完后、下个 LLM 调用前注入
            asap = session.pending.drain_asap()
            if asap and hasattr(request_context, "messages"):
                inject = ModelRequest(parts=[UserPromptPart(content="\n".join(asap))])
                try:
                    request_context.messages = list(request_context.messages) + [inject]
                except Exception:
                    pass
            return request_context

        return Hooks(
            before_run=before_run,
            after_run=after_run,
            before_node_run=before_node_run,
            after_node_run=after_node_run,
            event=on_event,
            before_tool_execute=before_tool_execute,
            after_tool_execute=after_tool_execute,
            before_model_request=before_model_request,
        )

    async def _translate_message_events(self, kernel_event: KernelStreamEvent) -> None:
        """流事件 → message_* / tool_execution_* 内核事件（事件总线侧）。"""
        event_map = {
            "message_start": KernelEvent.MESSAGE_START,
            "message_update": KernelEvent.MESSAGE_UPDATE,
            "message_end": KernelEvent.MESSAGE_END,
            "tool_execution_start": KernelEvent.TOOL_EXECUTION_START,
            "tool_execution_update": KernelEvent.TOOL_EXECUTION_UPDATE,
            "tool_execution_end": KernelEvent.TOOL_EXECUTION_END,
        }
        kernel_evt = event_map.get(kernel_event.type)
        if kernel_evt is None:
            return
        ctx = EventContext(kernel_evt, self.session_id, dict(kernel_event.data))
        result = await self.bus.emit(ctx)
        # message_end 可干预（替换消息）——替换结果回流到流事件
        if kernel_evt == KernelEvent.MESSAGE_END and result.payload is not None:
            kernel_event.data.update(result.payload)

    async def _emit_stream(self, event: KernelStreamEvent) -> None:
        """向当前流式队列投递事件（非流式运行时静默跳过）。"""
        queue = getattr(self, "_stream_queue", None)
        if queue is not None:
            await queue.put(event)

    def _record_tool_call(
        self,
        tool_name: str,
        tool_call_id: str,
        params: dict[str, Any],
        blocked: bool,
        block_reason: str | None,
    ) -> None:
        self.audit.record(
            ToolCallRecord(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                params=params,
                blocked=blocked,
                block_reason=block_reason,
                is_error=False,
            )
        )

    # ==================================================================
    # 上下文窗口与持久化
    # ==================================================================

    def _build_history(self) -> list[Any]:
        """从会话树构建上下文窗口（当前分支 message 条目，含 compaction 窗口）。"""
        if self.tree is None:
            return []
        branch = self.tree.current_branch()
        message_payloads: list[dict[str, Any]] = []
        for entry in branch:
            if entry.type == "message":
                message_payloads.extend(entry.payload.get("messages", []))
            elif entry.type == "compaction":
                # compaction：摘要替换其覆盖范围（只影响上下文窗口，历史保留）
                message_payloads = [entry.payload.get("summary", {})]
        if not message_payloads:
            return []
        try:
            return deserialize_messages(message_payloads)
        except Exception:
            return []

    def _persist_messages(self, new_messages: list[Any]) -> None:
        """新增消息落 JSONL（完整历史始终保留）。"""
        if self.tree is None or not new_messages:
            return
        payload = {"messages": serialize_messages(list(new_messages))}
        self.tree.append("message", payload)

    async def maybe_compact(self) -> bool:
        """阈值触发 compaction（手动/阈值策略；完整历史保留，仅影响上下文窗口）。

        session_before_compact 事件：handler 可取消（payload compact=False）
        或提供自定义摘要（payload summary）。
        """
        if self.tree is None:
            return False
        branch = self.tree.current_branch()
        message_entries = [e for e in branch if e.type == "message"]
        if len(message_entries) < self._compaction_threshold:
            return False

        emit_result = await self.bus.emit(
            EventContext(
                KernelEvent.SESSION_BEFORE_COMPACT,
                self.session_id,
                {"compact": True, "summary": None},
            )
        )
        payload = emit_result.payload or {}
        if payload.get("compact") is False:
            return False

        summary_messages = payload.get("summary")
        if summary_messages is None:
            # 内核生成摘要（模型摘要路径；provider CompactionPart 优先策略由宿主
            # 模型能力决定，本期简化为截断式摘要占位——S3 应急面不接 compaction）
            summary_messages = [{"kind": "request", "parts": [{"part_kind": "user-prompt", "content": "[历史摘要：早期对话已压缩]"}]}]

        self.tree.append("compaction", {"summary": summary_messages})
        return True


# ===========================================================================
# 宿主装配入口（§三 接口契约）
# ===========================================================================


def create_agent_session(
    model: Any,
    *,
    extensions: list[Any] | None = None,
    system_prompt: str = "",
    output_type: Any = None,
    skills_dirs: list[str | Path] | None = None,
    session_dir: str | Path | None = None,
    active_tools: list[str] | None = None,
    session_id: str | None = None,
    audit_sink: Callable[[ToolCallRecord], None] | None = None,
) -> AgentSession:
    """创建 Agent 会话（宿主装配唯一入口）。

    Args:
        model: pydantic-ai 模型（如 'deepseek:deepseek-v4-pro' 或 TestModel）。
        extensions: 扩展清单（目录路径/单文件/工厂函数；加载顺序即优先级，
            安全扩展必须首位——宿主启动断言）。
        system_prompt: 基础系统提示（Skill 目录自动追加）。
        output_type: 结构化输出契约（Pydantic 模型，pydantic-ai 原生校验）。
        skills_dirs: 额外 Skill 目录（扩展 skills/ 之外的宿主目录）。
        session_dir: 会话 JSONL 存储目录（None = 纯内存会话）。
        active_tools: 面白名单（工具名列表，None = 全量）。
        session_id: 会话标识（缺省生成 UUID）。
        audit_sink: 工具调用审计外送回调（trace_id 透传宿主日志）。
    """
    return AgentSession(
        model,
        system_prompt=system_prompt,
        output_type=output_type,
        extensions=extensions,
        skills_dirs=skills_dirs,
        session_dir=session_dir,
        active_tools=active_tools,
        session_id=session_id,
        audit_sink=audit_sink,
    )


__all__ = ["AgentSession", "create_agent_session"]
