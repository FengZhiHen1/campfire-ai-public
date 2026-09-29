"""运行记录：把一次运行的事件流变成一行可查的记录。

依据 docs/技术设计/technical-details/通用基座.md 第 8 节：

> 每次运行记录：模型、token、时延、激活的 skill、注入项来源与数量、工具调用、引用、错误、
> 结束原因。记录写在**我们自己的表**里，**不改写会话**。

## 为什么记录由**事件**派生，而不是由运行编排另行写一份

事件流是这次运行对外的唯一输出（第 7 节），运行编排已经把该记的事实都放在事件里了。
让记录再从事件里派生一次，得到的性质是：**记录必然与使用者看到的东西一致**。反过来，
若编排另写一份记录，两份就会各自演化——最终出现「记录说成功、界面说失败」这种无法排查的
分歧。

## 三条刻意的边界

1. **记录不含对话与业务正文**：它只记来源、数量、标识、长度与结果码，不记使用者消息、
   模型输出、工具结果全文与引用摘要。工具调用只留 ``summary_chars``（长度），引用只留
   标识——需要正文时去读会话真源（第 2 节：对话是唯一真源，**不另存副本**）。
   第一版把工具结果摘要与引用摘要原样存进记录，实测连一条含口令的连接串都会进记录；
   长度信息足以支撑排查，正文不值得再存一份。
2. **写的失败不影响运行，但绝不被静默吞掉**：记录是观测，不是对话。写失败必须记日志
   （「没写进去」不得被当作「写进去了」，技术栈设计第 5 节第 2 条），但不得把一次已经成功的
   对话变成失败。
3. **没有终态事件就不编造结束时间**：``elapsed_seconds`` 只在有可靠来源时才有值
   （终态事件，或记录器自己量的墙钟）；``finished_at`` 因此是 ``datetime | None``。
   第一版让取消的运行 ``elapsed=0.0``、``finished_at == started_at``，等于给审计表写了一个
   伪造的结束时间——外部实测那次运行其实跑了 0.203 秒。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
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
    ToolCallStartedEvent,
)

RunOutcome = Literal["completed", "timeout", "cancelled", "failed", "incomplete"]
"""一次运行的最终去向。

``incomplete`` 是**必须有**的一档：事件流可能在没有终态事件的情况下结束（进程被杀、
生成器被关闭）。把它记成 ``completed`` 就是「没写进去当成写进去了」，第 9 节禁止。
"""


@dataclass(frozen=True, slots=True)
class CitationRef:
    """记录里保留的引用**标识**（不含摘要正文，见模块 docstring 第 1 条）。"""

    citation_id: str
    reference: str
    source: str

    @classmethod
    def of(cls, record: CitationRecord) -> "CitationRef":
        """从事件里的引用记录取标识部分。"""
        return cls(citation_id=record.citation_id, reference=record.reference, source=record.source)


@dataclass(slots=True)
class ToolCallRecord:
    """一次工具调用的记录。

    ``ok is None`` 表示**没有收到结束事件**：运行触顶、失败或取消打断了这次调用。这不是
    罕见情形（实测触顶时事件序列是 ``run_started → tool_call_started → run_finished``），
    第一版只处理结束事件，于是记录里**完全没有**这次调用——与第 8 节「记录工具调用」不符。
    """

    tool_name: str
    call_id: str
    ok: bool | None
    error_code: str | None = None
    summary_chars: int = 0
    """工具结果的**长度**（不存正文，见模块 docstring 第 1 条）。"""


@dataclass(slots=True)
class RunRecord:
    """一次运行的记录。

    可变是为了让 :class:`RunRecorder` 逐步填充；对外交付用 :meth:`RunRecorder.finish`
    返回的**副本**，交付之后再改本对象不会影响已经写出去的那一份。
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
    citations: tuple[CitationRef, ...] = ()
    usage: RunUsage = field(default_factory=RunUsage)
    elapsed_seconds: float | None = None
    """墙钟耗时；``None`` 表示**没有可靠来源**（事件流没走到终态且记录器也没量到）。"""

    end_reason: Literal["completed", "timeout"] | None = None
    """终态事件给出的结束原因。

    刻意**不含** ``"cancelled"``：取消不产出终态事件（消费者取消了就收不到任何后续事件），
    取消的事实由 :attr:`cancelled` 表达。这样「终态原因」与「被取消」不会互相冒充。
    """

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
        """把「结束原因 / 失败码 / 取消 / 什么都没有」压成一档。

        终态事件优先于取消标志：只有终态事件才代表这次运行**确实**走完了某个终局，而取消标志
        可能来自终结时序（见 :meth:`RunRecorder.mark_cancelled` 的说明）。
        """
        if self.end_reason is not None:
            return self.end_reason
        if self.failure_code is not None:
            return "failed"
        if self.cancelled:
            return "cancelled"
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
    def unfinished_tool_calls(self) -> int:
        """被打断（没有结束事件）的工具调用条数。"""
        return sum(1 for call in self.tool_calls if call.ok is None)

    @property
    def finished_at(self) -> datetime | None:
        """结束时间；**没有可靠耗时来源时为 ``None``**，不编造。"""
        if self.elapsed_seconds is None:
            return None
        return self.started_at + timedelta(seconds=self.elapsed_seconds)


class RunRecorder:
    """把事件逐个累积成 :class:`RunRecord`。

    刻意与「转发事件」解耦：调用方一边把事件发给使用者，一边喂给本对象；同一个事件流
    有两个消费者，互不影响。
    """

    def __init__(self, *, started_at: datetime | None = None) -> None:
        """以运行开始时间初始化（默认取当前 UTC 时间），并记下单调时钟起点。"""
        self._record = RunRecord(started_at=started_at or datetime.now(UTC))
        self._monotonic_start = time.monotonic()
        self._sealed = False

    @property
    def record(self) -> RunRecord:
        """当前记录（同一个可变对象，便于流式观察）；交付请用 :meth:`finish`。"""
        return self._record

    def apply(self, event: RunEvent) -> None:
        """吃进一个事件。

        终止事件之后不再吃任何事件（记录已定稿）：否则「写下之后又被改」会让批式写入器
        落盘到后来的状态，而调用方以为写的是当时那份。

        ``RunEvent`` 联合里每一种类型都在这里有明确处置——包括 :class:`ToolCallStartedEvent`
        与 :class:`ProgressEvent`：前者是「工具调用被打断」这条事实的唯一来源，后者确实不带
        第 8 节要求的字段（不计入记录是**有意的**，不是漏了）。
        """
        if self._sealed:
            return
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
        elif isinstance(event, ToolCallStartedEvent):
            record.tool_calls.append(ToolCallRecord(tool_name=event.tool_name, call_id=event.call_id, ok=None))
        elif isinstance(event, ToolCallFinishedEvent):
            self._complete_tool_call(event)
        elif isinstance(event, CitationEvent):
            record.citations = _merged_citations(record.citations, (CitationRef.of(event.citation),))
        elif isinstance(event, CandidateEvent):
            record.candidate_count += 1
        elif isinstance(event, RunFinishedEvent):
            record.end_reason = event.reason
            record.citations = _merged_citations(record.citations, _refs(event.citations))
            record.usage = event.usage
            record.elapsed_seconds = event.elapsed_seconds
            record.compactions = event.compactions
            self._sealed = True
        elif isinstance(event, RunFailedEvent):
            record.failure_code = event.code
            record.failure_detail = event.detail
            record.model_failure_reason = event.model_reason
            record.citations = _merged_citations(record.citations, _refs(event.citations))
            record.usage = event.usage
            record.elapsed_seconds = event.elapsed_seconds
            record.compactions = event.compactions
            self._sealed = True

    def _complete_tool_call(self, event: ToolCallFinishedEvent) -> None:
        """把结束事件补到对应的调用上；没有对应的开始事件时补一条完整记录（防御性）。"""
        for call in reversed(self._record.tool_calls):
            if call.call_id == event.call_id and call.ok is None:
                call.ok = event.ok
                call.error_code = event.error_code
                call.summary_chars = len(event.summary)
                return
        self._record.tool_calls.append(
            ToolCallRecord(
                tool_name=event.tool_name,
                call_id=event.call_id,
                ok=event.ok,
                error_code=event.error_code,
                summary_chars=len(event.summary),
            )
        )

    def mark_cancelled(self) -> None:
        """由消费方在捕获取消后调用。

        取消不产出终态事件（取消自己的消费者收不到任何后续事件），所以「这次运行是被取消的」
        这条事实只能由消费方告知——否则记录会退化成 ``incomplete``，与真实原因不符。

        **只在还没有终态事实时生效**：已经跑完的运行不该因为随后的一次取消被改判成
        ``cancelled``（实测：终态事件之后再 ``mark_cancelled()``，记录会写成自相矛盾的
        「outcome=cancelled 且 end_reason=completed」）。

        残留的不确定性：事件循环关闭时，``aclose()`` 会被排成任务并被取消，那条
        ``CancelledError`` 与「消费者主动取消」在生成器里长得一样，因此终结时序可能被记成
        ``cancelled``（换一个时序又会记成 ``incomplete``）。这里不猜，只保证不覆盖终态；
        已知偏差登记在 docs/TODO.md。
        """
        if self._record.end_reason is None and self._record.failure_code is None:
            self._record.cancelled = True
        self._measure_elapsed()

    def finish(self) -> RunRecord:
        """返回最终记录的**副本**（没有终态事件时 ``outcome`` 为 ``incomplete``，不假装成功）。

        返回副本而不是内部对象：写出去的那一份不该再被后续事件或外部代码改动。
        列表字段也复制，否则副本与内部对象仍共享同一个 ``tool_calls``。
        """
        self._measure_elapsed()
        self._sealed = True
        return replace(self._record, tool_calls=list(self._record.tool_calls))

    def _measure_elapsed(self) -> None:
        """没有终态事件提供的耗时时，用记录器自己的单调时钟补一个**真实测量值**。"""
        if self._record.elapsed_seconds is None:
            self._record.elapsed_seconds = time.monotonic() - self._monotonic_start


def _refs(citations: tuple[CitationRecord, ...]) -> tuple[CitationRef, ...]:
    """把事件里的引用记录压成记录侧的标识。"""
    return tuple(CitationRef.of(record) for record in citations)


def _merged_citations(
    existing: tuple[CitationRef, ...],
    incoming: tuple[CitationRef, ...],
) -> tuple[CitationRef, ...]:
    """按 ``citation_id`` 合并，而不是整体覆盖。

    第一版的终态事件直接整体赋值：一个空清单会把先到的引用连同摘要一起抹掉（当前运行编排传的
    是全量清单，所以真实链路没暴露；形状上仍是隐患）。
    """
    known = {ref.citation_id for ref in existing}
    merged = list(existing)
    for ref in incoming:
        if ref.citation_id not in known:
            known.add(ref.citation_id)
            merged.append(ref)
    return tuple(merged)
