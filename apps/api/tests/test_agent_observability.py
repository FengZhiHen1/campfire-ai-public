"""运行记录：由事件派生的计量、失败与取消，以及写入端口的旁路语义。

对应 docs/技术设计/technical-details/通用基座.md 第 8 节。两组用例：

- **纯事件驱动**（多数）：直接喂事件，验证记录字段与 ``outcome`` 的五档映射；
- **端到端一条**：用真实运行编排 + 假 Chat Completions 服务跑一次，验证记录确实来自
  真实事件流（而不是只在手造事件上成立）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from agents import ModelSettings
from agents.items import TResponseInputItem
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from pydantic import BaseModel

from campfire.agent.context import CitationRecord, InjectionBatch, InjectionItem
from campfire.agent.model import ModelBinding
from campfire.agent.observability import RunRecord, RunRecorder, ToolCallRecord, record_stream
from campfire.agent.runtime import (
    AgentRunner,
    CandidateEvent,
    CitationEvent,
    RunFailedEvent,
    RunFinishedEvent,
    RunRequest,
    RunStartedEvent,
    RunUsage,
    TextDeltaEvent,
    ToolCallFinishedEvent,
)
from campfire.agent.skill_runtime import SkillRegistry
from campfire.agent.tools import Candidate, ToolPool, ToolResult, ToolSpec

STARTED_AT = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _citation(reference: str = "kb-1") -> CitationRecord:
    return CitationRecord(
        citation_id="cite-1",
        run_id="run-1",
        source="knowledge",
        reference=reference,
        recorded_at=STARTED_AT,
    )


def _started(*, activated: tuple[str, ...] = ("daily-consulting",)) -> RunStartedEvent:
    return RunStartedEvent(
        run_id="run-1",
        session_id="s-1",
        surface="consult",
        model="test-model",
        activated_skills=activated,
        injection_sources=("skill-catalog", "tool-availability", "retrieved"),
        appended_messages=3,
    )


# --- 纯事件驱动 -------------------------------------------------------------


def test_record_is_incomplete_until_a_terminal_event_arrives() -> None:
    """没有终态事件就是 ``incomplete``：不得把「没跑完」记成成功。"""
    recorder = RunRecorder(started_at=STARTED_AT)
    recorder.apply(_started())

    assert recorder.finish().outcome == "incomplete"


def test_completed_run_records_every_field_the_design_asks_for() -> None:
    recorder = RunRecorder(started_at=STARTED_AT)
    recorder.apply(_started())
    recorder.apply(TextDeltaEvent(delta="你"))
    recorder.apply(TextDeltaEvent(delta="好"))
    recorder.apply(
        ToolCallFinishedEvent(tool_name="search_knowledge", call_id="c1", ok=True, error_code=None, summary="摘要")
    )
    recorder.apply(CitationEvent(citation=_citation("kb-1")))
    recorder.apply(CandidateEvent(candidate=Candidate(reference="item-1", summary="待确认")))
    recorder.apply(
        RunFinishedEvent(
            reason="completed",
            citations=(_citation("kb-1"),),
            usage=RunUsage(requests=2, input_tokens=10, output_tokens=5, total_tokens=15),
            elapsed_seconds=1.5,
        )
    )

    record = recorder.finish()

    assert record.outcome == "completed"
    assert (record.model, record.surface, record.session_id) == ("test-model", "consult", "s-1")
    assert record.activated_skills == ("daily-consulting",)
    assert record.injection_sources == ("skill-catalog", "tool-availability", "retrieved")
    assert record.injection_count == 3
    assert record.appended_messages == 3
    assert record.tool_calls == [
        ToolCallRecord(tool_name="search_knowledge", call_id="c1", ok=True, error_code=None, summary="摘要")
    ]
    assert record.citation_references == ("kb-1",)
    assert record.usage.total_tokens == 15
    assert record.elapsed_seconds == 1.5
    assert record.text_deltas == 2
    assert record.candidate_count == 1


def test_finished_at_is_started_plus_elapsed() -> None:
    recorder = RunRecorder(started_at=STARTED_AT)
    recorder.apply(RunFinishedEvent(reason="completed", citations=(), usage=RunUsage(), elapsed_seconds=90.0))

    assert recorder.finish().finished_at == datetime(2026, 9, 29, 12, 1, 30, tzinfo=UTC)


def test_record_keeps_no_conversation_content() -> None:
    """记录只记计量与标识：使用者消息与模型输出不在这里存第二份（第 8 节 + 第 2 节单真源）。"""
    recorder = RunRecorder(started_at=STARTED_AT)
    recorder.apply(_started())
    recorder.apply(TextDeltaEvent(delta="使用者的敏感原话"))
    recorder.apply(RunFinishedEvent(reason="completed", citations=(), usage=RunUsage(), elapsed_seconds=0.1))

    record = recorder.finish()

    assert "使用者的敏感原话" not in repr(record)
    assert record.text_deltas == 1  # 只记条数，不记内容


@pytest.mark.parametrize(
    ("events", "cancelled", "expected"),
    [
        ([RunFinishedEvent(reason="completed", citations=(), usage=RunUsage(), elapsed_seconds=0)], False, "completed"),
        ([RunFinishedEvent(reason="timeout", citations=(), usage=RunUsage(), elapsed_seconds=0)], False, "timeout"),
        ([], True, "cancelled"),
        ([], False, "incomplete"),
    ],
)
def test_outcome_mapping(events: Sequence[object], cancelled: bool, expected: str) -> None:
    recorder = RunRecorder(started_at=STARTED_AT)
    for event in events:
        recorder.apply(event)  # type: ignore[arg-type]
    if cancelled:
        recorder.mark_cancelled()

    assert recorder.finish().outcome == expected


def test_failure_record_carries_code_and_model_reason() -> None:
    recorder = RunRecorder(started_at=STARTED_AT)
    recorder.apply(_started())
    recorder.apply(
        RunFailedEvent(
            code="model_unavailable",
            detail="模型调用失败（APITimeoutError）",
            citations=(_citation("kb-9"),),
            usage=RunUsage(requests=3, total_tokens=7),
            elapsed_seconds=45.0,
            model_reason="timeout",
        )
    )

    record = recorder.finish()

    assert record.outcome == "failed"
    assert record.failure_code == "model_unavailable"
    assert record.model_failure_reason == "timeout"
    assert record.citation_references == ("kb-9",)
    assert record.usage.requests == 3


def test_failed_tool_call_is_recorded_with_its_error_code() -> None:
    recorder = RunRecorder(started_at=STARTED_AT)
    recorder.apply(
        ToolCallFinishedEvent(
            tool_name="write_beta",
            call_id="c9",
            ok=False,
            error_code="tool_not_available",
            summary="此刻不可用",
        )
    )

    assert recorder.finish().tool_calls[0].error_code == "tool_not_available"


def test_cancellation_wins_over_a_missing_terminal_event() -> None:
    """取消不产出终态事件，所以「被取消」只能由消费方告知；否则会退化成 incomplete。"""
    recorder = RunRecorder(started_at=STARTED_AT)
    recorder.apply(_started())

    recorder.mark_cancelled()

    assert recorder.finish().outcome == "cancelled"


# --- 事件转发的旁路语义 -----------------------------------------------------


class _FakeWriter:
    """记录写入替身，可注入失败。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.records: list[RunRecord] = []
        self.fail = fail

    async def write(self, record: RunRecord) -> None:
        if self.fail:
            raise RuntimeError("postgresql://user:pw@host/db 写不进去")
        self.records.append(record)


async def _events(*items: object) -> AsyncIterator[Any]:
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_record_stream_forwards_events_unchanged_and_writes_one_record() -> None:
    writer = _FakeWriter()
    incoming = [
        _started(),
        TextDeltaEvent(delta="a"),
        RunFinishedEvent(reason="completed", citations=(), usage=RunUsage(), elapsed_seconds=0.2),
    ]

    forwarded = [event async for event in record_stream(_events(*incoming), writer=writer)]

    assert forwarded == incoming
    assert len(writer.records) == 1
    assert writer.records[0].outcome == "completed"


@pytest.mark.asyncio
async def test_writer_failure_does_not_break_the_stream_and_does_not_leak_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """观测写失败只记日志：一次已成功的对话不该因为记录写不进去而变成失败。"""
    writer = _FakeWriter(fail=True)

    with caplog.at_level(logging.WARNING):
        forwarded = [
            event
            async for event in record_stream(
                _events(
                    _started(), RunFinishedEvent(reason="completed", citations=(), usage=RunUsage(), elapsed_seconds=0)
                ),
                writer=writer,
            )
        ]

    assert len(forwarded) == 2  # 事件照常转发
    assert writer.records == []  # 没写进去就是没写进去
    assert "运行记录写入失败" in caplog.text
    assert "pw@" not in caplog.text  # 只记异常类型名


@pytest.mark.asyncio
async def test_cancellation_is_marked_on_the_record_and_re_raised() -> None:
    """取消自己的消费者收不到终态事件，所以「被取消」由消费方告知（mark_cancelled）。"""
    writer = _FakeWriter()

    async def slow() -> AsyncIterator[Any]:
        yield _started()
        await asyncio.sleep(5)

    async def consume() -> None:
        async for _event in record_stream(slow(), writer=writer):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.02)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(writer.records) == 1
    assert writer.records[0].outcome == "cancelled"


@pytest.mark.asyncio
async def test_closing_the_stream_mid_way_records_incomplete_not_completed() -> None:
    """生成器被关闭（消费者提前断开）时，记录是 ``incomplete``——不假装成功。"""
    writer = _FakeWriter()

    async def gated() -> AsyncIterator[Any]:
        yield _started()
        await asyncio.sleep(60)

    stream = record_stream(gated(), writer=writer)
    assert isinstance(await anext(stream), RunStartedEvent)

    await stream.aclose()

    assert len(writer.records) == 1
    assert writer.records[0].outcome == "incomplete"


# --- 端到端：记录确实来自真实事件流 -----------------------------------------


class _FakeSession:
    """会话替身。"""

    def __init__(self) -> None:
        self.session_id = "s-1"
        self.session_settings = None
        self.items: list[TResponseInputItem] = []

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
        return list(self.items)

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        self.items.extend(items)

    async def pop_item(self) -> TResponseInputItem | None:
        return self.items.pop() if self.items else None

    async def clear_session(self) -> None:
        self.items.clear()


class _FakeIndex:
    """引用索引替身。"""

    def __init__(self) -> None:
        self.records: list[CitationRecord] = []

    async def add(self, record: CitationRecord) -> None:
        self.records.append(record)

    async def list_for_run(self, run_id: str) -> Sequence[CitationRecord]:
        return [record for record in self.records if record.run_id == run_id]


class _Args(BaseModel):
    """检索参数。"""

    query: str


def _text_reply(text: str, usage: dict[str, int] | None = None) -> bytes:
    def chunk(delta: dict[str, Any], finish: str | None = None) -> str:
        payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "test-model",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload)}\n\n"

    body = chunk({"role": "assistant", "content": ""}) + chunk({"content": text}) + chunk({}, "stop")
    if usage is not None:
        body += f"data: {json.dumps({'choices': [], 'usage': usage})}\n\n"
    return (body + "data: [DONE]\n\n").encode()


def _empty_skills() -> SkillRegistry:
    import tempfile

    return SkillRegistry.discover(Path(tempfile.mkdtemp(prefix="campfire-obs-skills-")))


def _search_tool(index: _FakeIndex) -> ToolSpec[_Args]:
    """一个产出引用的检索工具。"""

    async def handler(context: Any, args: _Args) -> ToolResult:
        record = await context.citations.record(source="knowledge", reference="kb-42")
        return ToolResult(text=f"找到 {args.query}", citations=(record,))

    return ToolSpec(name="search_knowledge", description="检索", args_model=_Args, handler=handler)


@pytest.mark.asyncio
async def test_record_reflects_a_real_run(tmp_path: Path) -> None:
    """跑一次真实运行（假 HTTP 出口），确认记录里的字段确实来自事件流。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_text_reply("答", usage={"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}),
        )

    from openai import AsyncOpenAI

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    binding = ModelBinding(
        name="test-model",
        model=OpenAIChatCompletionsModel(
            model="test-model",
            openai_client=AsyncOpenAI(
                api_key="k", base_url="https://tokenhub.test/v1", max_retries=0, http_client=client
            ),
        ),
        settings=ModelSettings(),
    )
    index = _FakeIndex()
    runner = AgentRunner(
        binding=binding,
        tools=ToolPool([_search_tool(index)]),
        skills=_empty_skills(),
        citations=index,
        sessions=lambda session_id: _FakeSession(),
    )
    request = RunRequest(
        session_id="s-1",
        surface="consult",
        instructions="静态系统提示",
        user_input="你好",
        injections=InjectionBatch([InjectionItem(source="retrieved", content="资料", reference="kb-1")]),
        default_active_tools=("search_knowledge",),
    )
    writer = _FakeWriter()

    forwarded = [event async for event in record_stream(runner.run(request), writer=writer)]

    record = writer.records[0]
    assert record.outcome == "completed"
    assert record.model == "test-model"
    assert record.surface == "consult"
    assert record.usage.total_tokens >= 13
    # 注入项来源既有本轮业务注入，也有基座自己生成的可用性告知
    assert "retrieved" in record.injection_sources
    assert any(source.startswith("tool-availability") for source in record.injection_sources)
    # 引用来自注入项，且能回指业务标识
    assert record.citation_references == ("kb-1",)
    assert [event for event in forwarded if isinstance(event, CitationEvent)]
