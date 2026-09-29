"""工具池与权限系统（工具实现由产品侧注册在 ``campfire.tools``）。

归属（见 docs/项目结构设计.md 第 3 节）：基座拥有工具池与权限系统；**具体工具
的实现**由产品侧拥有。工具注册在装配处（``main.py`` / ``worker.py``）完成，
因此 ``agent/*`` 不需要 import ``tools/*``。

关键约束（见 docs/技术设计/technical-details/通用基座.md 第 5 节）：

- **权限在执行前校验，不靠隐藏 schema；工具可见性不是安全边界。**
- skill 的 ``allowed-tools`` 是**预授权**，不限制工具池本身。
- 请求里的 ``tools`` 数组在一条对话内**不变**（超集，缓存纪律）；激活集合变化
  用消息告知模型，越界调用由服务端拒绝。
- 延后加载（``ToolSearchTool``、``tool_namespace``、``defer_loading``）属
  OpenAI Responses-only，本项目走 TokenHub 兼容端点，**整条路已排除**。
- 一期无高风险动作（risk 全为 low），不实现人工审批。

模块分工：:mod:`~campfire.agent.tools.spec` 是注册形状与参数边界，
:mod:`~campfire.agent.tools.pool` 管注册与稳定声明，
:mod:`~campfire.agent.tools.scope` 管可用集合与告知，
:mod:`~campfire.agent.tools.dispatch` 是执行前的权限门。

**与 SDK 的接线不在这里**：把 :class:`ToolSpec` 转成 SDK 的 ``FunctionTool`` 属于运行
编排的装配细节；基座的注册形状不依赖任何 SDK 版本。
"""

from .dispatch import ToolDispatcher
from .errors import ToolError, ToolNotRegisteredError, ToolRegistrationError, ToolSpecError
from .pool import ToolPool
from .results import Candidate, ToolErrorCode, ToolFailure, ToolOutcome, ToolResult
from .scope import AVAILABILITY_SOURCE, ToolScope, resolve_scope
from .spec import TOOL_NAME_PATTERN, RiskLevel, Tool, ToolContext, ToolHandler, ToolSpec

__all__ = [
    "AVAILABILITY_SOURCE",
    "Candidate",
    "RiskLevel",
    "TOOL_NAME_PATTERN",
    "Tool",
    "ToolContext",
    "ToolDispatcher",
    "ToolError",
    "ToolErrorCode",
    "ToolFailure",
    "ToolHandler",
    "ToolNotRegisteredError",
    "ToolOutcome",
    "ToolPool",
    "ToolRegistrationError",
    "ToolResult",
    "ToolScope",
    "ToolSpec",
    "ToolSpecError",
    "resolve_scope",
]
