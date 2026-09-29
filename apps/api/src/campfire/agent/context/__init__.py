"""注入项的组织与引用索引：以消息形式进入对话。

归属（见 docs/项目结构设计.md 第 3 节）：基座拥有注入项的组织与引用索引；
**记忆、档案、检索的语义与生命周期**不归基座。

关键约束（见 docs/技术设计/technical-details/通用基座.md 第 4 节）：

- 注入项**就是消息**，没有单独的装配端口。
- 每条注入消息在引用索引表留一条记录（来源、时间、指向的业务标识），
  输出里的引用靠它回指。
- **不变量**：没有索引记录的注入消息不得成为「可引用依据」；注入失败必须显式
  标注该来源不可用，不得静默当作没有该信息。

本模块另含**模型窗口的派生**（:mod:`~campfire.agent.context.window`）：窗口是由对话
真源派生的视图，只裁模型输入、不影响落库；规则由压缩策略文档第 5、8 节拥有。

模块分工：:mod:`~campfire.agent.context.citations` 是引用索引与唯一的引用凭据来源，
:mod:`~campfire.agent.context.injection` 负责排序、索引记录与失败告知，
:mod:`~campfire.agent.context.window` 是纯函数式的窗口派生。
"""

from .citations import CitationIndex, CitationRecord, CitationRecorder
from .compaction import (
    CompactionError,
    CompactionJournal,
    CompactionOutcome,
    CompactionSettings,
    CompactionSummarizer,
    Item,
    RangeSelection,
    SkipReason,
    SummaryRequest,
    SummaryResult,
    appended_items,
    build_checkpoint,
    compact,
    estimate_window_tokens,
    is_context_overflow,
    is_tool_call,
    is_tool_output,
    item_text,
    previous_summary_text,
    retained_after_last_checkpoint,
    select_range,
    settings_from_config,
    window_tokens,
)
from .errors import CitationError, ContextError, InjectionError, InjectionRenderError
from .injection import (
    InjectionBatch,
    InjectionItem,
    InjectionMessage,
    InjectionPriority,
    InjectionRole,
    UnavailableSource,
)
from .window import (
    COMPACTED_SUMMARY_CLOSE_TAG,
    COMPACTED_SUMMARY_TAG,
    derive_window,
    is_compacted_summary,
    is_system_message,
    last_checkpoint_index,
    leading_system_count,
    message_text,
)

__all__ = [
    "COMPACTED_SUMMARY_CLOSE_TAG",
    "COMPACTED_SUMMARY_TAG",
    "CitationError",
    "CitationIndex",
    "CitationRecord",
    "CitationRecorder",
    "CompactionError",
    "CompactionJournal",
    "CompactionOutcome",
    "CompactionSettings",
    "CompactionSummarizer",
    "ContextError",
    "InjectionBatch",
    "InjectionError",
    "InjectionItem",
    "InjectionMessage",
    "InjectionPriority",
    "InjectionRenderError",
    "InjectionRole",
    "Item",
    "RangeSelection",
    "SkipReason",
    "SummaryRequest",
    "SummaryResult",
    "UnavailableSource",
    "appended_items",
    "build_checkpoint",
    "compact",
    "derive_window",
    "estimate_window_tokens",
    "is_compacted_summary",
    "is_context_overflow",
    "is_system_message",
    "is_tool_call",
    "is_tool_output",
    "item_text",
    "last_checkpoint_index",
    "leading_system_count",
    "message_text",
    "previous_summary_text",
    "retained_after_last_checkpoint",
    "select_range",
    "settings_from_config",
    "window_tokens",
]
