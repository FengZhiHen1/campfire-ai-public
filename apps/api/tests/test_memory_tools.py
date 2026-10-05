"""`tools/memory.py` 的单元测试：参数形状、归属校验、失败语义与投递纪律。

对应契约：docs/技术设计/面/consult/tools/write_memory.md、
docs/技术设计/面/consult/tools/read_memory.md。

不连库、不连图库：这两个工具的实现把真正的读写委托给 `modules/memory` 与
`core/pending_write`，因此本文件只钉住工具层自己的职责——参数解析、账号校验、
失败码、投递调用。读写语义本身由 `test_memory_*` 的集成测试覆盖。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import pytest

from campfire.agent.context import CitationRecord, CitationRecorder
from campfire.agent.tools import ActivationState, ToolContext, ToolFailure, ToolResult
from campfire.core.pending_write import KIND_MEMORY_EPISODE
from campfire.tools.memory import (
    ACCOUNT_PAYLOAD_KEY,
    DEFAULT_READ_LIMIT,
    ReadMemoryArgs,
    WriteMemoryArgs,
    _resolve_occurred_at,
    _Source,
    read_memory,
    write_memory,
)

_ACCOUNT = "tool_test_account"


class _FakeIndex:
    """最小引用索引；本文件不产生引用，只需满足构造。

    显式实现 `CitationIndex` 协议的两个成员（`add` / `list_for_run`）：协议是
    `runtime_checkable` 的 `Protocol`，只实现半数成员会被静态检查拒绝，而那正是
    「这个替身够不够格当索引」的真实判据——不能靠 ignore 抹掉。
    写入本文件的用例从不产生引用，因此两者都是空实现。
    """

    async def add(self, record: CitationRecord) -> None:
        """接受写入但不落任何地方：本文件不产生引用。"""
        del record  # 显式声明未使用：替身只需形状正确

    async def list_for_run(self, run_id: str) -> Sequence[CitationRecord]:
        """永远返回空：没有写入，就没有可读回的记录。"""
        del run_id
        return []


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
        # `source` 里不再有 `session_id`（2026-10-06 起由服务端填，见 `_Source`）。
        "source": {"message_seq": 1},
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
    """词表外的 `origin` 在参数层就被拒（与存储层 CHECK 同一份取值）。"""
    with pytest.raises(Exception):  # noqa: B017
        _write_args(origin="made_up_origin")


def test_write_memory_source_requires_the_object_but_not_a_session_id() -> None:
    """`source` 不再要求任何字段：会话标识由服务端填，`message_seq` 可选。

    旧断言（`source={}` 必须报错）已被本包**有意推翻**：它钉住的是「模型必须给出会话
    标识」这条正是缺陷的约束。取而代之的判据在
    :func:`test_write_memory_fills_session_id_from_the_run_context`（模型值到不了落库）。

    判别性：`source` 改回必填（无 `default_factory`）时，本用例第一行失败。
    """
    assert _write_args(source={}).source.message_seq is None


def test_write_memory_does_not_accept_a_model_supplied_session_id() -> None:
    """`source_session_id` 必须由服务端填：模型不得在参数里表达会话标识。

    与 `ask_user` 的 `batch_id` 同一原则（`runtime/ask_user_tool.py:52-58`「不信任模型传
    标识」）：模型既不知道当前会话，写进去的值就只可能是编的。实测（T24 §6-⑦）模型
    传了 `"current-session"`，而真实会话是 `4993067c8ae34f3db0feb8e9031b44b0`。

    判别性：参数模型里保留 `source.session_id` 时本用例失败（那条通道存在即会被使用）。
    """
    assert "session_id" not in _Source.model_fields


def test_occurred_at_is_optional_and_defaults_to_none() -> None:
    """`occurred_at` 改为可选，缺省 `None` 由工具层补当前时间。

    根因（T27 §3）：原设计让模型**必须**提供 `occurred_at`，而模型没有时钟——实测它
    传了 `2025-06-10`（真实时间 `2026-10-05`），并在自己的 reasoning 里写着
    "That's fabricating." 然后还是编了。字段必填就等于要求模型编一个它拿不到的事实。

    判别性：把 `occurred_at` 改回必填（`min_length=1` 无默认值），本用例失败。
    """
    args = WriteMemoryArgs.model_validate({"content": "他今天主动说了想喝水", "origin": "user_statement"})

    assert args.occurred_at is None, "缺省应是 None（由工具层补当前时间），而不是模型填的字符串"
    # `source` 也整体可选：模型连来源都不用给（会话标识由服务端填）。
    assert args.source.message_seq is None


def test_occurred_at_rejects_a_value_far_in_the_future() -> None:
    """`occurred_at` 不得是「还没发生」的时间（判据 `_occurred_at_problem`，解析期拒）。

    这是**反空断言的第一半**：喂一个明显越界的值必须被拒——否则这条约束只是一道
    恒真的空闸门。下一条用例是对照组（合理值必须被接受），只有拒绝没有接受时
    「一切都被拒」也能让本用例通过。
    """
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    with pytest.raises(Exception, match="晚于现在"):  # noqa: B017 —— pydantic 的 ValidationError
        _write_args(occurred_at=future)


def test_occurred_at_accepts_a_recent_and_a_naive_value_is_rejected() -> None:
    """对照组：刚发生的时刻被接受；朴素时间（无时区）被拒。

    与上一条成对。朴素时间这一半与消费侧 `_parse_occurred_at` 同一立场——没有时区的
    时间会被解释成不同瞬间，污染时间线顺序。
    """
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert _write_args(occurred_at=recent).occurred_at == recent

    with pytest.raises(Exception, match="必须带时区"):  # noqa: B017
        _write_args(occurred_at="2026-10-06T10:00:00")

    with pytest.raises(Exception, match="不是合法的 ISO 8601"):  # noqa: B017
        _write_args(occurred_at="昨天")


def test_write_memory_fills_session_id_from_the_run_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 端到端判据：模型传的会话标识**到不了**落库的 `source`，服务端用自己的。

    做法是捕获 `enqueue` 的关键字参数（与 `test_write_memory_returns_submitted_not_saved`
    同一种替身方式），断言 `source["session_id"]` 等于 `ToolContext.session_id`。

    判别性（三重，各自独立可红）：
    1. 把 `source["session_id"]` 改回 `args.source.session_id` ⇒ 本用例红（模型值进库）；
    2. 把 `_resolve_occurred_at` 的缺省分支去掉 ⇒ `occurred_at` 为 None 会一路走到
       `enqueue`，断言「是带时区的 ISO 8601」失败；
    3. 把 `context.session_id` 换成常量 ⇒ 与 `_context()` 的 "session-1" 不符，断言失败。
    """
    import asyncio

    from campfire.core.jobs import set_dispatch_hook

    captured: list[dict[str, object]] = []

    async def _capture(*_args: object, **kwargs: object) -> object:
        captured.append(dict(kwargs))

        class _Record:
            id = "00000000-0000-4000-8000-000000000002"

        return _Record()

    async def _no_dispatch(_pending_id: str, _kind: str) -> None: ...

    set_dispatch_hook(_no_dispatch)
    try:
        import campfire.tools.memory as tool_module

        class _FakeSession:
            async def __aenter__(self) -> "_FakeSession":
                return self

            async def __aexit__(self, *_exc: object) -> None: ...

        monkeypatch.setattr(tool_module, "enqueue", _capture)
        monkeypatch.setattr(tool_module, "session_scope", lambda _s: _FakeSession())
        # 模型仍多传一个 session_id：它必须被忽略（参数模型里已无该字段，会被拒）；
        # 这里改为只传 message_seq，另有一条用例专门钉住「多传即拒」。
        outcome = asyncio.run(
            write_memory(
                _context(payload={ACCOUNT_PAYLOAD_KEY: _ACCOUNT}),
                WriteMemoryArgs.model_validate(
                    {
                        "content": "他今天主动说了想喝水",
                        "origin": "user_statement",
                        "source": {"message_seq": 3},
                    }
                ),
            )
        )
    finally:
        set_dispatch_hook(None)

    assert isinstance(outcome, ToolResult)
    assert len(captured) == 1
    source = captured[0]["source"]
    assert isinstance(source, dict)
    assert source["session_id"] == "session-1", "会话标识必须取自运行上下文，不是模型给的值"
    assert source["message_seq"] == 3, "消息序号是模型能如实给出的信息，照常采用"

    payload = captured[0]["payload"]
    assert isinstance(payload, dict)
    occurred_at = payload["occurred_at"]
    assert isinstance(occurred_at, str)
    # 缺省取当前时间：必须是带时区的 ISO 8601（消费侧拒绝朴素时间）。
    assert datetime.fromisoformat(occurred_at).tzinfo is not None
    assert abs((datetime.now(timezone.utc) - datetime.fromisoformat(occurred_at)).total_seconds()) < 60


def test_write_memory_rejects_a_model_supplied_session_id_in_arguments() -> None:
    """模型若仍按旧 schema 传 `session_id`，参数层直接拒（`extra="forbid"`）。

    为什么必须显式拒绝而不是静默忽略：静默忽略会让「模型以为自己指明了一条来源」这件
    事在日志里查不到，而 reject 会让它在下一轮改对。严格模式（SDK 的
    `ensure_strict_json_schema` + pydantic）本来就把多给的字段变成
    `tool_invalid_arguments`——本用例钉住这条行为不被关掉。
    """
    with pytest.raises(Exception, match="session_id"):  # noqa: B017
        WriteMemoryArgs.model_validate(
            {
                "content": "x",
                "occurred_at": "2026-09-30T08:00:00+00:00",
                "origin": "user_statement",
                "source": {"session_id": "current-session"},
            }
        )


def test_read_memory_limit_has_a_server_side_cap() -> None:
    """`limit` 有服务端上界（契约第 4 节：不设上界会让「回看全部历史」无界拉取）。

    判别性：把 `le=DEFAULT_READ_LIMIT` 去掉，超限值会被接受，本用例失败。
    """
    with pytest.raises(Exception):  # noqa: B017
        ReadMemoryArgs.model_validate({"limit": DEFAULT_READ_LIMIT + 1})


def test_resolve_occurred_at_bounds() -> None:
    """补值函数的边界各自可判定：缺省补当前时间、合法值透传、未来值拒、朴素值拒。

    这一条与参数模型上的校验器**成对**（后者见
    `test_occurred_at_rejects_a_value_far_in_the_future`）：参数模型是正常路径上的闸门，
    `_resolve_occurred_at` 是 `model_construct` 之类绕开校验时的兜底。两条分开写，
    一路失效时另一路不会替它顶绿。
    """
    given = "2026-09-30T08:00:00+00:00"

    assert _resolve_occurred_at(given) == given
    resolved = _resolve_occurred_at(None)
    assert isinstance(resolved, str)
    # 缺省必须补一个**带时区**的时间（消费侧拒绝朴素时间）。
    assert datetime.fromisoformat(resolved).tzinfo is not None
    assert abs((datetime.now(timezone.utc) - datetime.fromisoformat(resolved)).total_seconds()) < 60

    far_future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    assert isinstance(_resolve_occurred_at(far_future), ToolFailure)
    assert isinstance(_resolve_occurred_at("2026-09-30T08:00:00"), ToolFailure)
    assert isinstance(_resolve_occurred_at("昨天"), ToolFailure)


# ---------------------------------------------------------------------------
# 归属校验（记忆属账号；分区键由装配处给，模型不能指定）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_fail_without_an_account_in_payload() -> None:
    """`payload` 里没有账号时明确失败，而不是猜一个默认账号。

    猜默认会把记忆写到错误的图里（`group_id` 就是图名），属静默错分。
    两个工具都要有这条守卫——因此两个都断言，不用同构循环：两个 handler 的
    参数类型本就不同（`WriteMemoryArgs` / `ReadMemoryArgs`），把它们塞进一个
    `(handler, args)` 序列会退化成联合类型，反而看不出「各自都被覆盖」。
    """
    write_outcome = await write_memory(_context(payload=None), _write_args())
    read_outcome = await read_memory(_context(payload=None), ReadMemoryArgs())

    for label, outcome in (("write_memory", write_outcome), ("read_memory", read_outcome)):
        assert isinstance(outcome, ToolFailure), f"{label} 缺账号时不得成功"
        assert outcome.code == "tool_failed"
        assert ACCOUNT_PAYLOAD_KEY in outcome.message


@pytest.mark.asyncio
async def test_tools_fail_on_an_illegal_account_id() -> None:
    """非法账号标识（含空白、空串）明确失败，不复述原始值（安全条款）。

    空串与「缺账号」走同一条分支（都不是有效账号），因此只对非空的非法值断言
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
    """朴素时间明确拒绝：它会被解释成不同瞬间，破坏区间比较。

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
    """非空但无法解析的时间明确失败，不静默当成「没传」。"""
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


def test_write_memory_returns_submitted_not_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    """回执只承诺 `submitted`（契约第 3 节）——不得让模型以为已经保存。

    这里只断言渲染形状与投递被调用：真正的落库由集成测试覆盖。

    替身经 `monkeypatch.setattr` 的字符串形态挂上：直接赋值会把 `enqueue` /
    `session_scope` 换成签名不同的可调用体，静态检查判的是「形状是否还是那个
    API」（`assignment` / `return-value`），而本用例要测的是「投递被调用 + 回执形状」，
    替身换了形状是刻意的；走 monkeypatch 还免掉了手工还原（原写法靠 `finally`）。
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

        monkeypatch.setattr(tool_module, "enqueue", _fake_enqueue)
        monkeypatch.setattr(tool_module, "session_scope", lambda _s: _FakeSession())
        outcome = asyncio.run(write_memory(_context(payload={ACCOUNT_PAYLOAD_KEY: _ACCOUNT}), _write_args()))
    finally:
        set_dispatch_hook(None)

    assert isinstance(outcome, ToolResult)
    payload = json.loads(outcome.text)
    assert payload == {"pending_id": _FakeRecord.id, "state": "submitted"}
    # kind 必须随投递一起给出（写入路径第 4 节第 3 条：按 kind 分派）——
    # 少了它，投递方只能一律投给同一个消费者。
    assert dispatched == [(_FakeRecord.id, KIND_MEMORY_EPISODE)], "写入后必须按 kind 投递（否则记录要等兜底扫描）"


def test_dispatch_failure_does_not_fail_the_call() -> None:
    """投递失败不让本次调用失败（第 4 节）：记录已落库，由兜底扫描重投。

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
    """未设置钩子时不抛异常：记录留给兜底扫描，回执仍然成立。"""
    import asyncio

    from campfire.core.jobs import dispatch_pending_write, set_dispatch_hook

    set_dispatch_hook(None)
    asyncio.run(dispatch_pending_write("some-pending-id", KIND_MEMORY_EPISODE))
