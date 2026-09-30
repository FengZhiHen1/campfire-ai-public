"""`campfire.agent.runtime`：通用 Agent 基座的运行装配面（对外只暴露这里列出的名字）。

职责：拥有 agent loop、会话与运行状态，并导出事件形状、装配、运行编排与机制工具。
边界：只做再导出，不含实现；产品入口与业务侧工具不在本包。
参考：docs/项目结构设计.md 第 3 节；docs/技术设计/technical-details/通用基座.md 第 2 节。
"""

from .ask_user_tool import ASK_USER_TOOL_NAME, AskUserArgs, build_ask_user_tool
from .assembly import QuestionGate, ToolBridge, build_agent, build_run_config, stop_after_question
from .errors import RuntimeAssemblyError, SessionConfigurationError
from .events import (
    ActionCardEvent,
    CandidateEvent,
    CitationEvent,
    CompactionFacts,
    ProgressEvent,
    QuestionEvent,
    ReasoningDeltaEvent,
    RunEndReason,
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
from .resource_tool import (
    READ_SKILL_RESOURCE_TOOL_NAME,
    ReadSkillResourceArgs,
    build_read_skill_resource_tool,
)
from .runner import SESSION_IO_DETAIL, AgentRunner, CompactionWiring, RunRequest
from .session import SessionFactory, build_sqlalchemy_session
from .skill_tool import SKILL_TOOL_NAME, ActivateSkillArgs, build_skill_tool
from .summarizer import ModelSummarizer

# 归属（见 docs/项目结构设计.md 第 3 节）：基座拥有 agent loop、会话与运行状态。
#
# 关键约束（见 docs/技术设计/technical-details/通用基座.md 第 2 节）：
#
# - 对话的唯一真源是 SDK 的会话存储，不另存副本；应用读它做呈现与审计。
# - 模型当轮看到的上下文是由对话真源派生的窗口；窗口裁剪只影响本轮模型输入，
#   不影响落库。
# - 不使用 SDK 的压缩重写（它会清空并重写历史，等于改写用户可见的历史）。
# - 上限只设一条通用响应上限 180 秒，不另设步数或 token 上限。
#
# 模块分工：:mod:`~campfire.agent.runtime.events` 是唯一对外的事件形状（名称对齐 AG-UI），
# :mod:`~campfire.agent.runtime.session` 只做会话装配，
# :mod:`~campfire.agent.runtime.assembly` 只做「基座形状 → SDK 对象」的翻译，
# :mod:`~campfire.agent.runtime.runner` 是运行编排本身。
#
# 三个机制工具（`skill` / `read_skill_resource` / `ask_user`）都放在本包，而不是
# `agent/tools`：它们都要用到运行编排的知识（激活状态、提问即结束运行），而
# `agent/tools` 只承载与产品侧共用的注册形状。

__all__ = [
    "SESSION_IO_DETAIL",
    "SKILL_TOOL_NAME",
    "READ_SKILL_RESOURCE_TOOL_NAME",
    "ASK_USER_TOOL_NAME",
    "ActivateSkillArgs",
    "ActionCardEvent",
    "AgentRunner",
    "AskUserArgs",
    "CandidateEvent",
    "CitationEvent",
    "CompactionFacts",
    "CompactionWiring",
    "ModelSummarizer",
    "ProgressEvent",
    "QuestionEvent",
    "QuestionGate",
    "ReadSkillResourceArgs",
    "ReasoningDeltaEvent",
    "RunEndReason",
    "RunEvent",
    "RunFailedEvent",
    "RunFailureCode",
    "RunFinishedEvent",
    "RunRequest",
    "RunStartedEvent",
    "RunUsage",
    "RuntimeAssemblyError",
    "SessionConfigurationError",
    "SessionFactory",
    "TextDeltaEvent",
    "ToolBridge",
    "ToolCallFinishedEvent",
    "ToolCallStartedEvent",
    "build_agent",
    "build_ask_user_tool",
    "build_read_skill_resource_tool",
    "build_run_config",
    "build_skill_tool",
    "build_sqlalchemy_session",
    "stop_after_question",
]
