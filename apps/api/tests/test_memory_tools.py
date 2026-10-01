"""`tools/memory.py` 的单元测试：参数形状、归属校验、失败语义与投递纪律。

对应契约：[write_memory](../../../../docs/技术设计/面/consult/tools/write_memory.md)、
[read_memory](../../../../docs/技术设计/面/consult/tools/read_memory.md)。

**不连库、不连图库**：这两个工具的实现把真正的读写委托给 `modules/memory` 与
`core/pending_write`，因此本文件只钉住**工具层自己的职责**——参数解析、账号校验、
失败码、投递调用。读写语义本身由 `test_memory_*` 的集成测试覆盖。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from campfire.agent.context import CitationRecorder
from campfire.agent.tools import ActivationState, ToolContext, ToolFailure, ToolResult
from campfire.core.pending_write import KIND_MEMORY_EPISODE
from campfire.tools.memory import (
    ACCOUNT_PAYLOAD_KEY,
    DEFAULT_READ_LIMIT,
    ReadMemoryArgs,
    WriteMemoryArgs,
    read_memory,
    write_memory,
)

_ACCOUNT = "tool_test_account"


class _FakeIndex:
    """最小引用索引；本文件不产生引用，只需满足构造。"""

    def add(self, *_args: object, **_kwargs: object) -> None: ...


def _context(payload: object | None = None) -> ToolContext:
    return ToolContext(
        run_id="run-1",
        session_id="session-1",
        surface="consult",
        activation_state=ActivationState(),
        citations=CitationRecorder(_FakeIndex(), run_id="run-1", clock=lambda: datetime.now(timezone.utc)),
        payload=payload,
    )


def _write_args(**overrides: object) -> WriteMemoryArgs:
    base: dict[str, object] = {
        "content": "他今天主动说了想喝水",
        "occurred_at": "2026-09-30T08:00:00+00:00",
        "origin": "user_statement",
        "source": {"session_id": "s1"},
    }
    base.update(overrides)
    return WriteMemoryArgs.model_validate(base)


# ---------------------------------------------------------------------------
# 参数形状（契约第 2 节）
# ---------------------------------------------------------------------------


def test_write_memory_requires_origin() -> None:
    """`origin` 必填（2026-09-30 补）：`AC-07` 要求条目带生成方式，存储层也是 NOT NULL。

    判别性：去掉参数模型里的 `origin` 字段，本用例失败（缺字段不再报错）。
    """
    with pytest.raises(Exception):  # noqa: B017 —— pydantic 的 ValidationError
        WriteMemoryArgs.model_validate(
            {
                "content": "x",
                "occurred_at": "2026-09-30T08:00:00+00:00",
                "source": {"session_id": "s1"},
            }
        )


def test_write_memory_rejects_an_origin_outside_the_vocabulary() -> None:
    """词表外的 `origin` 在**参数层**就被拒（与存储层 CHECK 同一份取值）。"""
    with pytest.raises(Exception):  # noqa: B017
        _write_args(origin="made_up_origin")


def test_write_memory_source_requires_a_session_id() -> None:
    """来源必填：`AC-07` 要求可核对，来源无法从其他参数还原。"""
    with pytest.raises(Exception):  # noqa: B017
        _write_args(source={})


def test_read_memory_limit_has_a_server_side_cap() -> None:
    """`limit` 有服务端上界（契约第 4 节：不设上界会让「回看全部历史」无界拉取）。

    判别性：把 `le=DEFAULT_READ_LIMIT` 去掉，超限值会被接受，本用例失败。
    """
    with pytest.raises(Exception):  # noqa: B017
        ReadMemoryArgs.model_validate({"limit": DEFAULT_READ_LIMIT + 1})


# ---------------------------------------------------------------------------
# 归属校验（记忆属账号；分区键由装配处给，模型不能指定）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_fail_without_an_account_in_payload() -> None:
    """`payload` 里没有账号时**明确失败**，而不是猜一个默认账号。

    猜默认会把记忆写到错误的图里（`group_id` 就是图名），属静默错分。
    两个工具都要有这条守卫。
    """
    for handler, args in ((write_memory, _write_args()), (read_memory, ReadMemoryArgs())):
        outcome = await handler(_context(payload=None), args)
        assert isinstance(outcome, ToolFailure), f"{handler.__name__} 缺账号时不得成功"
        assert outcome.code == "tool_failed"
        assert ACCOUNT_PAYLOAD_KEY in outcome.message


@pytest.mark.asyncio
async def test_tools_fail_on_an_illegal_account_id() -> None:
    """非法账号标识（含空白、空串）明确失败，**不复述原始值**（安全条款）。

    空串与「缺账号」走同一条分支（都不是有效账号），因此只对**非空**的非法值断言
    「不回显」——`'' in msg` 恒真，断言它没有意义（第一版就写错在这里）。
    """
    for bad in ("", "bad account", "acct\n"):
        outcome = await write_memory(_context(payload={ACCOUNT_PAYLOAD_KEY: bad}), _write_args())
        assert isinstance(outcome, ToolFailure), f"非法账号 {bad!r} 不得成功"
        assert outcome.code == "tool_failed"
        if bad:
            assert bad not in outcome.message, "错误消息不得回显原始账号值"


@pytest.mark.asyncio
async def test_read_memory_rejects_a_naive_datetime() -> None:
    """朴素时间**明确拒绝**：它会被解释成不同瞬间，破坏区间比较。

    与 `consumer` 对 `occurred_at` 的严格立场一致（那边也拒绝朴素时间）。
    判别性：去掉 `value.tzinfo is None` 的检查，本用例失败（会被静默按本地时区接受）。
    """
    outcome = await read_memory(
        _context(payload={ACCOUNT_PAYLOAD_KEY: _ACCOUNT}),
        ReadMemoryArgs(since="2026-09-30T08:00:00"),
    )
    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_invalid_arguments"
    assert "时区" in outcome.message


@pytest.mark.asyncio
async def test_read_memory_rejects_an_unparseable_time() -> None:
    """非空但无法解析的时间**明确失败**，不静默当成「没传」。"""
    outcome = await read_memory(
        _context(payload={ACCOUNT_PAYLOAD_KEY: _ACCOUNT}),
        ReadMemoryArgs(until="昨天"),
    )
    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_invalid_arguments"


# ---------------------------------------------------------------------------
# 投递纪律（写入路径第 4 节）
# ---------------------------------------------------------------------------


def test_write_memory_contract_shape_matches_the_document() -> None:
    """工具的参数名与契约文档逐字一致——名字漂了模型就按错的 schema 调用。"""
    assert set(WriteMemoryArgs.model_fields) == {"content", "occurred_at", "origin", "source"}
    assert set(ReadMemoryArgs.model_fields) == {"since", "until", "query", "limit"}


def test_write_memory_returns_submitted_not_saved() -> None:
    """回执只承诺 `submitted`（契约第 3 节）——不得让模型以为已经保存。

    这里只断言**渲染形状与投递被调用**：真正的落库由集成测试覆盖。
    """
    # ToolResult 的 text 是给模型看的 JSON；键名与契约第 3 节一致。
    import asyncio

    from campfire.core.jobs import set_dispatch_hook

    dispatched: list[tuple[str, str]] = []

    async def _record(pending_id: str, kind: str) -> None:
        dispatched.append((pending_id, kind))

    set_dispatch_hook(_record)
    try:
        # 用替身替换数据库会话：本用例只关心「投递被调用 + 回执形状」。
        import campfire.tools.memory as tool_module

        class _FakeRecord:
            id = "00000000-0000-4000-8000-000000000001"

        class _FakeSession:
            async def __aenter__(self) -> "_FakeSession":
                return self

            async def __aexit__(self, *_exc: object) -> None: ...

        async def _fake_enqueue(*_args: object, **_kwargs: object) -> _FakeRecord:
            return _FakeRecord()

        original_enqueue, original_scope = tool_module.enqueue, tool_module.session_scope
        tool_module.enqueue, tool_module.session_scope = _fake_enqueue, lambda _s: _FakeSession()
        try:
            outcome = asyncio.run(write_memory(_context(payload={ACCOUNT_PAYLOAD_KEY: _ACCOUNT}), _write_args()))
        finally:
            tool_module.enqueue, tool_module.session_scope = original_enqueue, original_scope
    finally:
        set_dispatch_hook(None)

    assert isinstance(outcome, ToolResult)
    payload = json.loads(outcome.text)
    assert payload == {"pending_id": _FakeRecord.id, "state": "submitted"}
    # kind 必须随投递一起给出（写入路径第 4 节第 3 条：按 kind 分派）——
    # 少了它，投递方只能一律投给同一个消费者。
    assert dispatched == [(_FakeRecord.id, KIND_MEMORY_EPISODE)], "写入后必须按 kind 投递（否则记录要等兜底扫描）"


def test_dispatch_failure_does_not_fail_the_call() -> None:
    """**投递失败不让本次调用失败**（第 4 节）：记录已落库，由兜底扫描重投。

    判别性：把 `dispatch_pending_write` 里的 `except Exception` 去掉，
    钩子抛错会冒泡成工具失败，本用例失败。
    """
    import asyncio

    from campfire.core.jobs import dispatch_pending_write, set_dispatch_hook

    async def _explode(_pending_id: str, _kind: str) -> None:
        raise RuntimeError("Redis 不可达")

    set_dispatch_hook(_explode)
    try:
        # 不抛异常即为通过（异常消息可能带连接串，实现里只记 warning）。
        asyncio.run(dispatch_pending_write("some-pending-id", KIND_MEMORY_EPISODE))
    finally:
        set_dispatch_hook(None)


def test_dispatch_without_a_hook_is_not_an_error() -> None:
    """未设置钩子时**不抛异常**：记录留给兜底扫描，回执仍然成立。"""
    import asyncio

    from campfire.core.jobs import dispatch_pending_write, set_dispatch_hook

    set_dispatch_hook(None)
    asyncio.run(dispatch_pending_write("some-pending-id", KIND_MEMORY_EPISODE))
