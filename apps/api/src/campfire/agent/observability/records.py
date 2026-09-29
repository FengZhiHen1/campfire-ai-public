"""运行记录：把一次运行的事件流变成一行可查的记录。

依据 docs/技术设计/technical-details/通用基座.md 第 8 节：

> 每次运行记录：模型、token、时延、激活的 skill、注入项来源与数量、工具调用、引用、错误、
> 结束原因。记录写在**我们自己的表**里，**不改写会话**。

## 为什么记录由**事件**派生，而不是由运行编排另行写一份

事件流是这次运行对外的唯一输出（第 7 节），运行编排已经把该记的事实都放在事件里了。
让记录再从事件里派生一次，得到的性质是：**记录必然与使用者看到的东西一致**。反过来，
若编排另写一份记录，两份就会各自演化——最终出现「记录说成功、界面说失败」这种无法排查的
分歧。

## 两条刻意的边界

1. **记录不含对话内容**：它记的是来源、数量、标识与结果码，不记使用者消息与模型输出。
   需要逐字对话时去读会话真源（第 2 节：应用读它做呈现与审计），不在这里存第二份。
   工具结果只留截断摘要（``SUMMARY_LIMIT``），它是给人看的「发生了什么」。
2. **写的失败不影响运行**：记录是观测，不是对话。写失败必须记日志并让调用方知道，
   但不得把一次已经成功的对话变成失败（第 9 节的失败语义全部关于对话与真源）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from campfire.agent.context import CitationRecord
from campfire.agent.runtime import (
    CandidateEvent,
    CitationEvent,
    CompactionFacts,
    RunEvent,
    RunFailedEvent,
    RunFinishedEvent,
    RunStartedEvent,
    RunUsage,
    TextDeltaEvent,
    ToolCallFinishedEvent,
)

RunOutcome = Literal["completed", "timeout", "cancelled", "failed", "incomplete"]
"""一次运行的最终去向。

``incomplete`` 是**必须有**的一档：事件流可能在没有终态事件的情况下结束（进程被杀、
生成器被关闭）。把它记成 ``completed`` 就是「没写进去当成写进去了」，第 9 节禁止。
"""


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """一次工具调用的记录。"""

    tool_name: str
    call_id: str
    ok: bool
    error_code: str | None
    summary: str


@dataclass(slots=True)
class RunRecord:
    """一次运行的记录（可变：由 :class:`RunRecorder` 逐步填充后冻结为快照）。

    所有字段都是**计量与标识**，没有对话内容——见模块 docstring 第 1 条。
    """

    started_at: datetime
    run_id: str | None = None
    session_id: str | None = None
    surface: str | None = None
    model: str | None = None
    activated_skills: tuple[str, ...] = ()
    injection_sources: tuple[str, ...] = ()
    appended_messages: int = 0
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    citations: tuple[CitationRecord, ...] = ()
    usage: RunUsage = field(default_factory=RunUsage)
    elapsed_seconds: float = 0.0
    end_reason: Literal["completed", "timeout"] | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    model_failure_reason: str | None = None
    cancelled: bool = False
    text_deltas: int = 0
    """文本增量的**条数**（不是内容）：用来判断这次运行到底有没有产出可见文本。"""

    candidate_count: int = 0
    """候选产出条数（内容进业务侧候选列表，不在这里存副本）。"""

    compactions: tuple[CompactionFacts, ...] = ()
    """本次运行做过的压缩计量（压缩策略第 9 节）。"""

    @property
    def outcome(self) -> RunOutcome:
        """把「结束原因 / 失败码 / 取消 / 什么都没有」压成一档。"""
        if self.failure_code is not None:
            return "failed"
        if self.cancelled:
            return "cancelled"
        if self.end_reason is not None:
            return self.end_reason
        return "incomplete"

    @property
    def injection_count(self) -> int:
        """注入项条数（第 8 节要求记「注入项来源与数量」）。"""
        return len(self.injection_sources)

    @property
    def citation_references(self) -> tuple[str, ...]:
        """引用指向的业务标识，便于按条目反查。"""
        return tuple(record.reference for record in self.citations)

    @property
    def released_tokens_by_compaction(self) -> int:
        """压缩累计释放的 token（第 9 节的「释放 token」）。"""
        return sum(item.released_tokens for item in self.compactions)

    @property
    def finished_at(self) -> datetime:
        """按起始时间与耗时推出的结束时间（供按时间范围查询）。"""
        from datetime import timedelta

        return self.started_at + timedelta(seconds=self.elapsed_seconds)


class RunRecorder:
    """把事件逐个累积成 :class:`RunRecord`。

    刻意与「转发事件」解耦：调用方一边把事件发给使用者，一边喂给本对象；同一个事件流
    有两个消费者，互不影响。
    """

    def __init__(self, *, started_at: datetime | None = None) -> None:
        """以运行开始时间初始化（默认取当前 UTC 时间）。"""
        self._record = RunRecord(started_at=started_at or datetime.now(UTC))

    @property
    def record(self) -> RunRecord:
        """当前的记录快照（同一个可变对象，便于流式观察）。"""
        return self._record

    def apply(self, event: RunEvent) -> None:
        """吃进一个事件。未知事件类型被忽略（**不是**静默丢字段：已知类型全在这里处理）。"""
        record = self._record
        if isinstance(event, RunStartedEvent):
            record.run_id = event.run_id
            record.session_id = event.session_id
            record.surface = event.surface
            record.model = event.model
            record.activated_skills = event.activated_skills
            record.injection_sources = event.injection_sources
            record.appended_messages = event.appended_messages
        elif isinstance(event, TextDeltaEvent):
            record.text_deltas += 1
        elif isinstance(event, ToolCallFinishedEvent):
            record.tool_calls.append(
                ToolCallRecord(
                    tool_name=event.tool_name,
                    call_id=event.call_id,
                    ok=event.ok,
                    error_code=event.error_code,
                    summary=event.summary,
                )
            )
        elif isinstance(event, CitationEvent):
            record.citations = (*record.citations, event.citation)
        elif isinstance(event, CandidateEvent):
            record.candidate_count += 1
        elif isinstance(event, RunFinishedEvent):
            record.end_reason = event.reason
            record.citations = event.citations
            record.usage = event.usage
            record.elapsed_seconds = event.elapsed_seconds
            record.compactions = event.compactions
        elif isinstance(event, RunFailedEvent):
            record.failure_code = event.code
            record.failure_detail = event.detail
            record.model_failure_reason = event.model_reason
            record.citations = event.citations
            record.usage = event.usage
            record.elapsed_seconds = event.elapsed_seconds
            record.compactions = event.compactions

    def mark_cancelled(self) -> None:
        """由消费方在捕获取消后调用。

        取消不产出终态事件（取消自己的消费者收不到任何后续事件），所以「这次运行是被取消的」
        这条事实只能由消费方告知——否则记录会退化成 ``incomplete``，与真实原因不符。
        """
        self._record.cancelled = True

    def finish(self) -> RunRecord:
        """返回最终记录。没有终态事件时 ``outcome`` 为 ``incomplete``，不假装成功。"""
        return self._record
