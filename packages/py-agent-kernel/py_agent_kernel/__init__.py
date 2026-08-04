"""py-agent-kernel — 通用 Agent 内核框架。

内核+扩展架构（ADR-011）：harness 层契约仿 pi（ExtensionAPI/事件总线/
工具契约/Session JSONL 树/skill-loader），LLM 层委托 pydantic-ai。

零 Campfire 依赖——内核不得 import 任何宿主/领域包（启动断言由 CI grep 保证）。

Usage:
    from py_agent_kernel import create_agent_session, AgentTool, ToolResult

    session = create_agent_session(model=..., extensions=[security_ext, ...])
    result = await session.run("用户输入")
"""

from py_agent_kernel.events import (
    BLOCKABLE_EVENTS,
    TRANSFORMABLE_EVENTS,
    EventBus,
    EventContext,
    EventHandler,
    EventResult,
    KernelEvent,
)
from py_agent_kernel.extension_api import (
    KERNEL_VERSION,
    ExtensionAPI,
    ExtensionLoadError,
    ExtensionMeta,
    LoadedExtension,
    load_extension,
    load_extensions,
)
from py_agent_kernel.runtime import (
    AgentSession,
    AuditRecorder,
    KernelStreamEvent,
    PreloadedExtensions,
    ToolCallRecord,
    UsageTracker,
    create_agent_session,
    translate_stream_event,
)
from py_agent_kernel.session import (
    InjectionMode,
    PendingMessageQueue,
    SessionEntry,
    SessionTree,
    deserialize_messages,
    serialize_messages,
)
from py_agent_kernel.skills import Skill, SkillLoader, SkillLoadError
from py_agent_kernel.tools import (
    AgentTool,
    CancellationToken,
    ContentBlock,
    ImageContent,
    KernelToolset,
    TextContent,
    ToolContext,
    ToolResult,
    set_active_tools,
)

__version__ = KERNEL_VERSION

__all__ = [
    # 版本
    "__version__",
    "KERNEL_VERSION",
    # 扩展
    "ExtensionAPI",
    "ExtensionMeta",
    "LoadedExtension",
    "ExtensionLoadError",
    "load_extension",
    "load_extensions",
    # 事件
    "KernelEvent",
    "EventContext",
    "EventResult",
    "EventBus",
    "EventHandler",
    "TRANSFORMABLE_EVENTS",
    "BLOCKABLE_EVENTS",
    # 工具
    "AgentTool",
    "ToolResult",
    "TextContent",
    "ImageContent",
    "ContentBlock",
    "CancellationToken",
    "ToolContext",
    "KernelToolset",
    "set_active_tools",
    # 会话
    "SessionEntry",
    "SessionTree",
    "serialize_messages",
    "deserialize_messages",
    "InjectionMode",
    "PendingMessageQueue",
    # Skill
    "Skill",
    "SkillLoader",
    "SkillLoadError",
    # 运行时
    "AgentSession",
    "PreloadedExtensions",
    "create_agent_session",
    "KernelStreamEvent",
    "translate_stream_event",
    "AuditRecorder",
    "ToolCallRecord",
    "UsageTracker",
]
