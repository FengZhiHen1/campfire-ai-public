"""运行追踪与评测钩子。

归属（见 docs/项目结构设计.md 第 3 节）：基座拥有流式输出与可观测钩子；
面向用户的输出结构与呈现不归基座。

关键约束（见 docs/技术设计/technical-details/通用基座.md 第 8 节）：

- 每次运行记录：模型、token、时延、激活的 skill、注入项来源与数量、工具调用、
  引用、错误、结束原因。记录写在我们自己的表里，不改写会话。
- 触发准确性与输出质量分开测：前者用「应为／不应为触发」的提示集测触发率，
  后者用对齐 `AC-11` 的独立评价判定。

一期可观测（见 docs/技术栈设计.md 第 2 节）：OpenAI Agents SDK 内置 tracing +
结构化日志；不引入 Langfuse 一类平台。

模块分工：:mod:`~campfire.agent.observability.records` 是记录形状与由事件派生的累积器，
:mod:`~campfire.agent.observability.writer` 是写入端口与「顺带记录」的事件转发。

两处尚未落地，都不是遗漏：

- 记录的持久化由装配处实现（基座只声明 :class:`RunTraceWriter` 端口）：表要由 Alembic
  迁移创建，而迁移与 `core/db` 同批落地（技术栈设计第 1 节记着「迁移命令仍缺失」）。
- 评测集（触发准确性与输出质量）依赖尚不存在的 skill 内容与
  「应为／不应为触发」提示集，因此与第一份 `SKILL.md` 同批落地——和
  `skills-ref validate` 的接入条件完全相同（该条件登记于 `docs/TODO.md` 第四节
  「基座已确认要求尚未落地」第 ① 项）。
"""

from .records import CitationRef, RunOutcome, RunRecord, RunRecorder, ToolCallRecord
from .writer import RunTraceWriter, record_stream

__all__ = [
    "CitationRef",
    "RunOutcome",
    "RunRecord",
    "RunRecorder",
    "RunTraceWriter",
    "ToolCallRecord",
    "record_stream",
]
