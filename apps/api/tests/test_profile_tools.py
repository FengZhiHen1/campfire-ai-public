"""`tools/profile.py` 的单元测试：参数形状、账号校验、错误码映射与返回契约字段。

对应契约：docs/技术设计/面/consult/tools/read_profile_summary.md、
docs/技术设计/面/consult/tools/read_profile_items.md、
docs/技术设计/面/consult/tools/propose_profile_item.md、
docs/技术设计/面/consult/tools/create_support_object.md。

不连库：真正的取数、落层与授权判定在 `modules/profile`（由
`test_profile_items_integration.py` 等覆盖）。本文件只钉工具层自己的职责——
参数形状（含「哪些参数不该存在」）、账号缺失时的明确失败、异常到错误码的映射、
返回体的契约字段。落层分流与「拒绝且未落库」的库侧断言见
`test_profile_tools_integration.py`。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import get_args

import pytest
from pydantic import BaseModel

from campfire.agent.context import CitationRecord, CitationRecorder
from campfire.agent.tools import ActivationState, ToolContext, ToolFailure, ToolResult
from campfire.core.authz import (
    OBJECT_ARCHIVED_MESSAGE,
    OBJECT_NOT_ACCESSIBLE_MESSAGE,
    AuthorizationError,
    ObjectArchivedError,
)
from campfire.core.pending_write import KIND_PROFILE_ITEM, ORIGINS
from campfire.modules.profile import (
    DOMAINS,
    MAX_DISPLAY_NAME_LENGTH,
    GroupedItems,
    ItemView,
    ProfileDataError,
    ProfileSummary,
    SummaryEntry,
    SummaryField,
)
from campfire.tools.profile import (
    ACCOUNT_PAYLOAD_KEY,
    DEFAULT_ITEMS_LIMIT,
    MAX_ITEMS_LIMIT,
    CreateSupportObjectArgs,
    Domain,
    Origin,
    ProposeProfileItemArgs,
    ReadProfileItemsArgs,
    ReadProfileSummaryArgs,
    create_support_object,
    propose_profile_item,
    read_profile_items,
    read_profile_summary,
)

_ACCOUNT = "tool_test_account"
_OBJECT = "11111111-1111-4111-8111-111111111111"


class _FakeIndex:
    """引用索引替身：本文件只关心工具层的参数形状与错误码映射。

    形状与 `CitationIndex` 端口逐字一致，因此 `CitationRecorder` 的构造真的接受它——
    写成宽口径的 `*_args` 会绕过端口契约，`CitationRecorder` 的写入路径就没被替身掉。
    """

    async def add(self, record: CitationRecord) -> None:
        """不落任何东西。"""
        return None

    async def list_for_run(self, run_id: str) -> Sequence[CitationRecord]:
        """空列表。"""
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


#: 工具处理器的收口签名：四个工具的参数模型各不相同，用 `...` 取它们的公共形状
#: （与 `agent.tools.spec.ToolHandler` 同一写法）。
_Handler = Callable[..., Awaitable[ToolResult | ToolFailure]]


def _accounted() -> ToolContext:
    return _context(payload={ACCOUNT_PAYLOAD_KEY: _ACCOUNT})


def _propose_args(**overrides: object) -> ProposeProfileItemArgs:
    base: dict[str, object] = {
        "support_object_id": _OBJECT,
        "domain": "communication",
        "topic": "表达需求的方式",
        "description": "口渴时会拉大人的手走向水杯",
        "origin": "guardian_observation",
        "source": {"session_id": "session-1"},
    }
    base.update(overrides)
    return ProposeProfileItemArgs.model_validate(base)


def _summary_result(**overrides: object) -> ProfileSummary:
    base: dict[str, object] = {
        "support_object_id": _OBJECT,
        "has_profile": True,
        "fields": [
            SummaryField(
                key="how_i_communicate",
                label="我怎么沟通",
                items=[
                    SummaryEntry(
                        item_id="22222222-2222-4222-8222-222222222222",
                        origin="guardian_observation",
                        last_confirmed_at=datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc),
                        description="口渴时会拉大人的手走向水杯",
                        freshness="current",
                    )
                ],
            )
        ],
        "item_count": 1,
        "generated_at": datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc),
        "possibly_stale": False,
    }
    base.update(overrides)
    return ProfileSummary(**base)  # type: ignore[arg-type]  # 夹具以 object 组合再交给 dataclass，静态类型看不出这层收敛


def _item_view(**overrides: object) -> ItemView:
    base: dict[str, object] = {
        "item_id": "22222222-2222-4222-8222-222222222222",
        "domain": "communication",
        "topic": "表达需求的方式",
        "description": "口渴时会拉大人的手走向水杯",
        "origin": "guardian_observation",
        "confirmation": "confirmed",
        "freshness": "current",
        "contexts": ["在家里"],
        "manifestations": [],
        "helpful_support": ["把水杯放在够得到的位置"],
        "unhelpful_support": [],
        "person_report": None,
        "probable_need": None,
        "source": {"session_id": "session-1", "tool": "propose_profile_item"},
        "first_recorded_at": datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc),
        "last_confirmed_at": datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc),
        "superseded_by": None,
        "supersedes": None,
    }
    base.update(overrides)
    return ItemView(**base)  # type: ignore[arg-type]  # 夹具以 object 组合再交给 dataclass，静态类型看不出这层收敛


class _FakeSession:
    """最小的会话替身：本文件不落库，只需满足 `async with`。"""

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_exc: object) -> None: ...


def _patch(monkeypatch: pytest.MonkeyPatch, module: str, **replacements: object) -> None:
    """把工具模块里的装配点换成替身（会话与用例函数）。"""
    import importlib

    tool_module = importlib.import_module(module)
    for name, value in replacements.items():
        monkeypatch.setattr(tool_module, name, value)


# ---------------------------------------------------------------------------
# 参数形状（四份契约各自的第 2 节）
# ---------------------------------------------------------------------------


def test_parameter_names_match_the_contracts() -> None:
    """四个参数模型的字段名与契约逐字一致——名字漂了模型就按错的 schema 调用。"""
    assert set(ReadProfileSummaryArgs.model_fields) == {"support_object_id"}
    assert set(ReadProfileItemsArgs.model_fields) == {
        "support_object_id",
        "domains",
        "include_candidates",
        "limit",
    }
    assert set(CreateSupportObjectArgs.model_fields) == {"display_name"}
    assert set(ProposeProfileItemArgs.model_fields) == {
        "support_object_id",
        "domain",
        "topic",
        "description",
        "origin",
        "source",
        "contexts",
        "manifestations",
        "person_report",
        "probable_need",
        "helpful_support",
        "unhelpful_support",
    }


def test_no_profile_tool_accepts_an_account_id() -> None:
    """四个工具都不收 `account_id`：属主取登录态（支持对象第 4 节不变量）。

    判别性：谁将来为了「方便」加一个 `account_id` 参数，本用例失败——那会让模型
    有通道把档案写到别的账号或从别的账号读。
    """
    for model in (
        ReadProfileSummaryArgs,
        ReadProfileItemsArgs,
        ProposeProfileItemArgs,
        CreateSupportObjectArgs,
    ):
        assert "account_id" not in model.model_fields, f"{model.__name__} 不得收 account_id"


def test_propose_has_no_confirmation_parameter() -> None:
    """没有 `confirmation` 参数：确认状态由 `origin` 决定（个性化档案第 3、7 节）。

    判别性：加上这个参数，模型就能把推断标成已确认——契约第 4 节第 2 条要拒绝的正是
    这件事。不设参数比「接受再拒绝」更强：不存在的通道无法被绕过。
    """
    assert "confirmation" not in ProposeProfileItemArgs.model_fields


def test_domain_enum_rejects_values_outside_the_vocabulary() -> None:
    """领域名落参数枚举：词表外的值在解析期被拒（契约第 5 节：不静默归入「其他」）。

    判别性：把 `domain` 从 `Literal` 改回 `str`，本用例失败。
    """
    with pytest.raises(Exception):  # noqa: B017 —— pydantic 的 ValidationError
        _propose_args(domain="感官")

    # 词表内的值必须全部通过，且与模块侧词表同源（不是在这里另抄一份）。
    for domain in DOMAINS:
        assert _propose_args(domain=domain).domain == domain


def test_domain_enum_mirrors_the_module_vocabulary_exactly() -> None:
    """工具层的 `Domain` 枚举与 `modules.profile.DOMAINS` 双向相等。

    工具层把词表写成字面量 `Literal` 而不是从 `DOMAINS` 派生：`Literal` 只接受字面量
    表达式，`Literal[*tuple(sorted(DOMAINS))]` 会被 mypy 判 `valid-type`（`Final` 常量
    同样不行，实测 mypy 2.1.0）。派生写法的好处是「不可能漂移」，改成镜像后这份好处
    必须由本用例接管——所以断言取集合相等而不是子集：

    - 少一个 → 模块侧新增了领域而工具层收不到，模型无法表达它；
    - 多一个 → 工具层放行了一个模块侧不认的值，解析通过但落库被 CHECK 拒。

    判别性：任改一侧一个取值，本用例失败。
    """
    assert set(get_args(Domain)) == set(DOMAINS)


def test_origin_enum_mirrors_the_module_vocabulary_exactly() -> None:
    """工具层的 `Origin` 枚举与 `core.pending_write.ORIGINS` 双向相等。

    理由与上一条完全相同（同为「派生改镜像 + 由用例接管不漂移」）。
    """
    assert set(get_args(Origin)) == set(ORIGINS)


def test_origin_enum_covers_the_six_generation_methods() -> None:
    """`origin` 六值全部可表达，第七种表达不出来（词表的所有者是写入路径第 3 节）。"""
    for origin in (
        "user_statement",
        "guardian_observation",
        "third_party_report",
        "document",
        "system_observation",
        "ai_inference",
    ):
        assert _propose_args(origin=origin).origin == origin
    with pytest.raises(Exception):  # noqa: B017
        _propose_args(origin="hearsay")


def test_items_limit_has_a_server_side_cap() -> None:
    """`limit` 有服务端上界（CORE-11），且上界与模块侧仓储常量同源。

    判别性：去掉 `le=MAX_ITEMS_LIMIT`，`limit=10**9` 会被接受。
    """
    with pytest.raises(Exception):  # noqa: B017
        ReadProfileItemsArgs.model_validate({"support_object_id": _OBJECT, "limit": MAX_ITEMS_LIMIT + 1})
    assert ReadProfileItemsArgs.model_validate({"support_object_id": _OBJECT}).limit is None


def test_empty_display_name_is_rejected_by_the_parameter_model() -> None:
    """空名在参数层就被拒（`min_length=1`），存储层 CHECK 仍是兜底（契约第 4 节第 1 条）。"""
    with pytest.raises(Exception):  # noqa: B017
        CreateSupportObjectArgs.model_validate({"display_name": ""})


def test_display_name_has_the_module_side_length_cap() -> None:
    """对象名上界与模块侧常量同源（不另写数字——抄一份必然漂移）。"""
    assert CreateSupportObjectArgs.model_fields["display_name"].metadata
    with pytest.raises(Exception):  # noqa: B017
        CreateSupportObjectArgs.model_validate({"display_name": "名" * (MAX_DISPLAY_NAME_LENGTH + 1)})


def test_source_rejects_unknown_keys() -> None:
    """来源定位是固定形状（`extra="forbid"`）——来源要被使用者复核，形状固定才能复核。

    判别性：把 `_Source` 换成 `dict[str, Any]`，本用例失败；而放开还会让 SDK 的
    严格模式在注册期失败（开放对象不被支持）。
    """
    with pytest.raises(Exception):  # noqa: B017
        _propose_args(source={"session_id": "s1", "随便一个键": "x"})


# ---------------------------------------------------------------------------
# 账号校验（未登录 → 明确失败，四④号质量地板校验点）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_tool_fails_without_an_account_in_payload() -> None:
    """`payload` 里没有账号时明确失败，而不是猜一个默认账号。

    猜默认会把档案写到错误的账号下——使用者看不到异常，只是数据不在自己名下。
    四个工具都要有这条守卫（质量地板校验点④「未登录/无 account → 明确失败」）。
    """
    # 工具名单列一列而不是取 `handler.__name__`：四者的参数模型不同，收口成 `_Handler`
    # 之后 `__name__` 不在 Callable 的静态形状里（真跑时在，静态上看不出）。
    cases: tuple[tuple[str, _Handler, BaseModel], ...] = (
        ("read_profile_summary", read_profile_summary, ReadProfileSummaryArgs(support_object_id=_OBJECT)),
        ("read_profile_items", read_profile_items, ReadProfileItemsArgs(support_object_id=_OBJECT)),
        ("propose_profile_item", propose_profile_item, _propose_args()),
        ("create_support_object", create_support_object, CreateSupportObjectArgs(display_name="小宝")),
    )
    for name, handler, args in cases:
        for payload in (None, {}, {ACCOUNT_PAYLOAD_KEY: ""}, {ACCOUNT_PAYLOAD_KEY: "   "}):
            outcome = await handler(_context(payload=payload), args)
            assert isinstance(outcome, ToolFailure), f"{name} 缺账号时不得成功"
            assert outcome.code == "tool_failed"
            assert ACCOUNT_PAYLOAD_KEY in outcome.message


# ---------------------------------------------------------------------------
# read_profile_summary（契约第 3、4、5 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_returns_the_four_contract_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """返回体含契约第 3 节的四个字段，且 `generated_at` 是可序列化的 ISO 8601。"""

    async def _fake_summary(_session: object, **_kwargs: object) -> ProfileSummary:
        return _summary_result()

    _patch(monkeypatch, "campfire.tools.profile", session_scope=lambda _s: _FakeSession(), summary=_fake_summary)

    outcome = await read_profile_summary(_accounted(), ReadProfileSummaryArgs(support_object_id=_OBJECT))

    assert isinstance(outcome, ToolResult)
    payload = json.loads(outcome.text)
    for field in ("summary", "item_count", "generated_at", "possibly_stale"):
        assert field in payload, f"契约字段 {field} 缺失"
    assert payload["item_count"] == 1
    assert payload["possibly_stale"] is False
    assert payload["summary"].strip(), "有档案时摘要不得为空"


@pytest.mark.asyncio
async def test_summary_without_a_profile_is_explicit_not_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """无档案时返回明确的「无档案」结果，而不是空对象（契约第 4 节末行、`AC-02`）。

    判别性：把 `_render_summary_text` 的 `has_profile=False` 分支改成返回空串，
    本用例失败——空串会让模型分不清「没有档案」与「取数没成功」。
    """

    async def _fake_summary(_session: object, **_kwargs: object) -> ProfileSummary:
        return _summary_result(has_profile=False, fields=[], item_count=0)

    _patch(monkeypatch, "campfire.tools.profile", session_scope=lambda _s: _FakeSession(), summary=_fake_summary)

    outcome = await read_profile_summary(_accounted(), ReadProfileSummaryArgs(support_object_id=_OBJECT))

    assert isinstance(outcome, ToolResult)
    payload = json.loads(outcome.text)
    assert payload["has_profile"] is False
    assert payload["item_count"] == 0
    assert "没有档案" in payload["summary"]
    assert "未使用个性化档案" in payload["summary"], "必须提示调用方标注未使用档案"


@pytest.mark.asyncio
async def test_summary_flags_possibly_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """有未完成的待处理记录时 `possibly_stale` 为真，且带一句话说明（契约第 4 节末行）。

    判别性：去掉 `notice`，模型只看到一个布尔值——它未必会用，而「摘要可能滞后」
    必须出现在输出里才可能被如实转述。
    """

    async def _fake_summary(_session: object, **_kwargs: object) -> ProfileSummary:
        return _summary_result(possibly_stale=True)

    _patch(monkeypatch, "campfire.tools.profile", session_scope=lambda _s: _FakeSession(), summary=_fake_summary)

    outcome = await read_profile_summary(_accounted(), ReadProfileSummaryArgs(support_object_id=_OBJECT))

    assert isinstance(outcome, ToolResult)
    payload = json.loads(outcome.text)
    assert payload["possibly_stale"] is True
    assert "notice" in payload


@pytest.mark.asyncio
async def test_summary_maps_cross_account_denial_to_the_shared_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """越权（对象不存在或不属于当前账号）映射成同一句文案，且不冒充「没有档案」。

    判别性：把两种情形分开成不同文案，本用例失败——区分二者等于提供对象枚举通道。
    """

    async def _deny(_session: object, **_kwargs: object) -> ProfileSummary:
        raise AuthorizationError(OBJECT_NOT_ACCESSIBLE_MESSAGE)

    _patch(monkeypatch, "campfire.tools.profile", session_scope=lambda _s: _FakeSession(), summary=_deny)

    outcome = await read_profile_summary(_accounted(), ReadProfileSummaryArgs(support_object_id=_OBJECT))

    assert isinstance(outcome, ToolFailure)
    assert outcome.message == OBJECT_NOT_ACCESSIBLE_MESSAGE


@pytest.mark.asyncio
async def test_summary_failure_does_not_pretend_no_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """取数失败时明确失败，不得静默当作没有档案（契约第 5 节末行）。

    判别性：把 `except Exception` 分支改成返回 `has_profile=False` 的正常结果，
    本用例失败——那会让模型对使用者说「没有你的档案」。
    """

    async def _boom(_session: object, **_kwargs: object) -> ProfileSummary:
        raise RuntimeError("postgresql://user:secret@host/db 连接失败")

    _patch(monkeypatch, "campfire.tools.profile", session_scope=lambda _s: _FakeSession(), summary=_boom)

    outcome = await read_profile_summary(_accounted(), ReadProfileSummaryArgs(support_object_id=_OBJECT))

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_failed"
    assert "未使用个性化档案" in outcome.message
    assert "secret" not in outcome.message and "postgresql" not in outcome.message


# ---------------------------------------------------------------------------
# read_profile_items（契约第 3、4、5 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_items_carry_origin_confirmation_and_freshness(monkeypatch: pytest.MonkeyPatch) -> None:
    """每条返回都含 `origin` / `confirmation` / `freshness`（契约第 4 节逐字要求）。

    判别性：为了让输出「干净」省掉其中任一，本用例失败。
    """

    async def _fake_read(_session: object, **_kwargs: object) -> GroupedItems:
        return GroupedItems(items=[_item_view()], candidates=[])

    _patch(monkeypatch, "campfire.tools.profile", session_scope=lambda _s: _FakeSession(), read_items=_fake_read)

    outcome = await read_profile_items(_accounted(), ReadProfileItemsArgs(support_object_id=_OBJECT))

    assert isinstance(outcome, ToolResult)
    payload = json.loads(outcome.text)
    assert payload["count"] == 1
    for field in ("origin", "confirmation", "freshness"):
        assert field in payload["items"][0], f"条目必须带 {field}"


@pytest.mark.asyncio
async def test_items_keep_candidates_in_a_separate_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """候选不混进 `items`，且自带 `layer` 标记与一句不可当事实的说明（契约第 4 节第 1 条）。

    判别性：把候选并进 `items` 数组，本用例失败——`AC-18` 的候选层不变量靠返回结构保证，
    不靠调用方按 `confirmation` 自己分。
    """

    async def _fake_read(_session: object, **_kwargs: object) -> GroupedItems:
        return GroupedItems(
            items=[_item_view()],
            candidates=[_item_view(origin="ai_inference", confirmation="unconfirmed")],
        )

    _patch(monkeypatch, "campfire.tools.profile", session_scope=lambda _s: _FakeSession(), read_items=_fake_read)

    outcome = await read_profile_items(_accounted(), ReadProfileItemsArgs(support_object_id=_OBJECT))

    assert isinstance(outcome, ToolResult)
    payload = json.loads(outcome.text)
    assert [row["layer"] for row in payload["items"]] == ["stable"]
    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["layer"] == "candidate"
    assert payload["candidates"][0]["confirmation"] == "unconfirmed"
    assert "不得" in payload["notice"]


@pytest.mark.asyncio
async def test_items_hide_candidates_when_not_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    """`include_candidates=false` 时返回里没有候选（用例层不再返回它们）。"""
    seen: dict[str, object] = {}

    async def _fake_read(_session: object, **kwargs: object) -> GroupedItems:
        seen.update(kwargs)
        return GroupedItems(items=[_item_view()], candidates=[])

    _patch(monkeypatch, "campfire.tools.profile", session_scope=lambda _s: _FakeSession(), read_items=_fake_read)

    outcome = await read_profile_items(_accounted(), ReadProfileItemsArgs(support_object_id=_OBJECT))

    assert isinstance(outcome, ToolResult)
    assert seen["include_candidates"] is False
    assert json.loads(outcome.text)["candidates"] == []


@pytest.mark.asyncio
async def test_items_unknown_domain_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """领域词表外的值明确失败，不静默忽略条件（契约第 5 节）。

    参数枚举是第一道（模型侧），用例层的 `ProfileDataError` 是第二道——覆盖绕过
    参数模型直接调用本函数的情形。这里直接构造 `ReadProfileItemsArgs` 会先被枚举拒绝，
    因此用 `model_construct` 模拟「绕过参数模型」。
    """

    async def _fake_read(_session: object, **_kwargs: object) -> GroupedItems:
        raise ProfileDataError("领域过滤含词表外的取值", operation="list_items", detail="合法取值=…")

    _patch(monkeypatch, "campfire.tools.profile", session_scope=lambda _s: _FakeSession(), read_items=_fake_read)

    args = ReadProfileItemsArgs.model_construct(support_object_id=_OBJECT, domains=["不存在的领域"], limit=None)

    outcome = await read_profile_items(_accounted(), args)

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_invalid_arguments"


@pytest.mark.asyncio
async def test_items_failure_does_not_return_partial_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """取数失败明确失败，不返回部分结果冒充完整结果（契约第 5 节末行）。"""

    async def _boom(_session: object, **_kwargs: object) -> GroupedItems:
        raise RuntimeError("连接中断")

    _patch(monkeypatch, "campfire.tools.profile", session_scope=lambda _s: _FakeSession(), read_items=_boom)

    outcome = await read_profile_items(_accounted(), ReadProfileItemsArgs(support_object_id=_OBJECT))

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_failed"


@pytest.mark.asyncio
async def test_items_limit_defaults_to_the_module_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """不给 `limit` 时用模块侧默认值（与仓储同源，不另写一份数字）。"""
    seen: dict[str, object] = {}

    async def _fake_read(_session: object, **kwargs: object) -> GroupedItems:
        seen.update(kwargs)
        return GroupedItems(items=[], candidates=[])

    _patch(monkeypatch, "campfire.tools.profile", session_scope=lambda _s: _FakeSession(), read_items=_fake_read)

    await read_profile_items(_accounted(), ReadProfileItemsArgs(support_object_id=_OBJECT))

    assert seen["limit"] == DEFAULT_ITEMS_LIMIT


# ---------------------------------------------------------------------------
# propose_profile_item（契约第 4、5 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_submits_a_pending_record_and_says_submitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """回执只承诺 `submitted`（契约第 3 节），且落的是待处理记录而不是条目。

    判别性：把回执改成 `saved`（或直接调 `propose_item` 同步写），本用例失败。
    """
    from campfire.core.jobs import set_dispatch_hook

    dispatched: list[tuple[str, str]] = []

    async def _record(pending_id: str, kind: str) -> None:
        dispatched.append((pending_id, kind))

    seen: dict[str, object] = {}

    class _FakeRecord:
        id = "33333333-3333-4333-8333-333333333333"

    async def _fake_enqueue(_session: object, **kwargs: object) -> _FakeRecord:
        seen.update(kwargs)
        return _FakeRecord()

    async def _allow(_account: object, _object: object) -> None: ...

    _patch(
        monkeypatch,
        "campfire.tools.profile",
        session_scope=lambda _s: _FakeSession(),
        enqueue=_fake_enqueue,
        require_writable=_allow,
    )

    set_dispatch_hook(_record)
    try:
        outcome = await propose_profile_item(_accounted(), _propose_args())
    finally:
        set_dispatch_hook(None)

    assert isinstance(outcome, ToolResult)
    assert json.loads(outcome.text) == {"pending_id": _FakeRecord.id, "state": "submitted"}
    # kind 必须随投递一起给出（写入路径第 4 节第 3 条：按 kind 分派）。
    assert dispatched == [(_FakeRecord.id, KIND_PROFILE_ITEM)], "落库后必须按 kind 投递（否则要等兜底扫描）"
    assert seen["kind"] == "profile_item"
    assert seen["support_object_id"] == _OBJECT
    assert seen["origin"] == "guardian_observation"


@pytest.mark.asyncio
async def test_propose_payload_never_carries_a_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    """载荷里没有 `confirmation`：确认状态由 `origin` 推导（个性化档案第 3、7 节）。

    判别性：把 `confirmation` 放进载荷，本用例失败——那等于让一个可构造的载荷指定落层，
    正是契约第 4 节第 2 条要拒绝的事（Worker 侧还会再拒一次，这里是不制造它的第一道）。
    """
    seen: dict[str, object] = {}

    class _FakeRecord:
        id = "33333333-3333-4333-8333-333333333333"

    async def _fake_enqueue(_session: object, **kwargs: object) -> _FakeRecord:
        seen.update(kwargs)
        return _FakeRecord()

    async def _allow(_account: object, _object: object) -> None: ...

    _patch(
        monkeypatch,
        "campfire.tools.profile",
        session_scope=lambda _s: _FakeSession(),
        enqueue=_fake_enqueue,
        require_writable=_allow,
    )

    await propose_profile_item(_accounted(), _propose_args(origin="ai_inference"))

    # `seen` 的值是 `object`（真实载荷在运行时才成形），断言前先收窄成映射。
    payload = seen["payload"]
    assert isinstance(payload, Mapping)
    assert "confirmation" not in payload


@pytest.mark.asyncio
async def test_propose_carries_the_source_with_the_server_side_tool_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """来源带会话、消息序号、转述者，且工具名由服务端补（不让模型自报）。

    判别性：把 `tool` 改成取模型的输入，本用例失败——工具名是服务端事实，
    让模型自报会得到一个可以撒谎的来源定位。
    """
    seen: dict[str, object] = {}

    class _FakeRecord:
        id = "33333333-3333-4333-8333-333333333333"

    async def _fake_enqueue(_session: object, **kwargs: object) -> _FakeRecord:
        seen.update(kwargs)
        return _FakeRecord()

    async def _allow(_account: object, _object: object) -> None: ...

    _patch(
        monkeypatch,
        "campfire.tools.profile",
        session_scope=lambda _s: _FakeSession(),
        enqueue=_fake_enqueue,
        require_writable=_allow,
    )

    await propose_profile_item(
        _accounted(),
        _propose_args(source={"session_id": "s1", "message_seq": 7, "relayed_by": "妈妈"}),
    )

    source = seen["source"]
    assert isinstance(source, Mapping)
    assert source["session_id"] == "s1"
    assert source["message_seq"] == 7
    assert source["relayed_by"] == "妈妈"
    assert source["tool"] == "propose_profile_item"


@pytest.mark.asyncio
async def test_propose_omits_optional_keys_it_was_not_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """未给的可选字段不进载荷：空数组与「没提到」语义不同，补默认值会制造假事实。"""
    seen: dict[str, object] = {}

    class _FakeRecord:
        id = "33333333-3333-4333-8333-333333333333"

    async def _fake_enqueue(_session: object, **kwargs: object) -> _FakeRecord:
        seen.update(kwargs)
        return _FakeRecord()

    async def _allow(_account: object, _object: object) -> None: ...

    _patch(
        monkeypatch,
        "campfire.tools.profile",
        session_scope=lambda _s: _FakeSession(),
        enqueue=_fake_enqueue,
        require_writable=_allow,
    )

    await propose_profile_item(_accounted(), _propose_args())

    payload = seen["payload"]
    assert isinstance(payload, Mapping)
    assert set(payload) == {"domain", "topic", "description"}


@pytest.mark.asyncio
async def test_propose_maps_archived_object_to_a_distinct_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """归档对象明确失败，且文案区分于越权（支持对象第 5.3 节）。

    判别性：把两个分支的文案合成一句，本用例失败——属主自己的对象，告知归档状态
    不泄露信息，而使用者需要知道原因才能去恢复。
    """

    async def _archived(_account: object, _object: object) -> None:
        raise ObjectArchivedError(OBJECT_ARCHIVED_MESSAGE)

    _patch(monkeypatch, "campfire.tools.profile", require_writable=_archived)

    outcome = await propose_profile_item(_accounted(), _propose_args())

    assert isinstance(outcome, ToolFailure)
    assert outcome.message == OBJECT_ARCHIVED_MESSAGE
    assert outcome.message != OBJECT_NOT_ACCESSIBLE_MESSAGE
    assert "归档" in outcome.message


@pytest.mark.asyncio
async def test_propose_denies_cross_account_with_the_shared_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """越权与「对象不存在」文案相同（不提供对象枚举通道）。"""

    async def _deny(_account: object, _object: object) -> None:
        raise AuthorizationError(OBJECT_NOT_ACCESSIBLE_MESSAGE)

    _patch(monkeypatch, "campfire.tools.profile", require_writable=_deny)

    outcome = await propose_profile_item(_accounted(), _propose_args())

    assert isinstance(outcome, ToolFailure)
    assert outcome.message == OBJECT_NOT_ACCESSIBLE_MESSAGE


@pytest.mark.asyncio
async def test_propose_write_failure_does_not_receipt_submitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """待处理记录写入失败 → 明确失败，不回执 submitted（契约第 5 节）。

    判别性：把 `except Exception` 分支改成返回 `state="submitted"`，本用例失败。
    """

    async def _allow(_account: object, _object: object) -> None: ...

    async def _boom(_session: object, **_kwargs: object) -> object:
        raise RuntimeError("postgresql://user:secret@host/db 连接失败")

    _patch(
        monkeypatch,
        "campfire.tools.profile",
        session_scope=lambda _s: _FakeSession(),
        enqueue=_boom,
        require_writable=_allow,
    )

    outcome = await propose_profile_item(_accounted(), _propose_args())

    assert isinstance(outcome, ToolFailure)
    assert "submitted" not in outcome.message
    assert "secret" not in outcome.message and "postgresql" not in outcome.message


@pytest.mark.asyncio
async def test_propose_checks_the_object_before_writing(monkeypatch: pytest.MonkeyPatch) -> None:
    """权限判定发生在写入之前：归档对象不得先收到一次「已受理」再异步失败。

    判别性：把 `require_writable` 从 handler 里去掉，本用例失败（`enqueue` 会被调用）。
    """
    called: list[str] = []

    async def _deny(_account: object, _object: object) -> None:
        called.append("authz")
        raise ObjectArchivedError(OBJECT_ARCHIVED_MESSAGE)

    async def _enqueue(_session: object, **_kwargs: object) -> object:
        called.append("enqueue")
        raise AssertionError("越权的写入不得到达 enqueue")

    _patch(
        monkeypatch,
        "campfire.tools.profile",
        session_scope=lambda _s: _FakeSession(),
        enqueue=_enqueue,
        require_writable=_deny,
    )

    outcome = await propose_profile_item(_accounted(), _propose_args())

    assert isinstance(outcome, ToolFailure)
    assert called == ["authz"], "必须先判定权限再落记录"


# ---------------------------------------------------------------------------
# create_support_object（契约第 4、6 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_object_returns_the_persisted_name_and_binds_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """返回落库的对象名与标识，并在同一次会话里补建绑定（契约第 3、6 节）。

    判别性：去掉补绑调用，本用例失败——首对象补绑是引导期的组成部分（支持对象第 6 节）。
    """
    bound: list[dict[str, object]] = []

    class _FakeObject:
        id = "44444444-4444-4444-8444-444444444444"
        display_name = "  小宝  ".strip()

    async def _fake_create(_session: object, **_kwargs: object) -> _FakeObject:
        return _FakeObject()

    async def _fake_bind(_session: object, **kwargs: object) -> bool:
        bound.append(kwargs)
        return True

    _patch(
        monkeypatch,
        "campfire.tools.profile",
        session_scope=lambda _s: _FakeSession(),
        create_object=_fake_create,
        bind_first_object=_fake_bind,
    )

    outcome = await create_support_object(_accounted(), CreateSupportObjectArgs(display_name="小宝"))

    assert isinstance(outcome, ToolResult)
    assert json.loads(outcome.text) == {
        "support_object_id": _FakeObject.id,
        "display_name": _FakeObject.display_name,
    }
    assert bound == [{"session_id": "session-1", "account_id": _ACCOUNT, "support_object_id": _FakeObject.id}]


@pytest.mark.asyncio
async def test_create_object_uses_the_login_account_not_a_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    """属主取登录态（支持对象第 4 节）：用例收到的 `account_id` 来自 payload。"""
    seen: dict[str, object] = {}

    class _FakeObject:
        id = "44444444-4444-4444-8444-444444444444"
        display_name = "小宝"

    async def _fake_create(_session: object, **kwargs: object) -> _FakeObject:
        seen.update(kwargs)
        return _FakeObject()

    async def _fake_bind(_session: object, **_kwargs: object) -> bool:
        return True

    _patch(
        monkeypatch,
        "campfire.tools.profile",
        session_scope=lambda _s: _FakeSession(),
        create_object=_fake_create,
        bind_first_object=_fake_bind,
    )

    await create_support_object(_accounted(), CreateSupportObjectArgs(display_name="小宝"))

    assert seen["account_id"] == _ACCOUNT
    assert seen["display_name"] == "小宝"


@pytest.mark.asyncio
async def test_create_object_rejects_a_blank_name_without_substituting(monkeypatch: pytest.MonkeyPatch) -> None:
    """空白名明确失败，不静默填默认名（契约第 4 节第 1 条、存储层 CHECK 兜底）。

    这里构造「绕过参数模型」的调用（`model_construct`）以覆盖用例层判据：
    `min_length=1` 挡不住 `"   "`（长度 3 但去空白为空），那条由
    `normalize_display_name` 与 CHECK 拒。
    """

    async def _blank(_session: object, **_kwargs: object) -> object:
        raise ProfileDataError("对象名不得为空", operation="normalize_display_name", detail="去空白后长度为 0")

    _patch(monkeypatch, "campfire.tools.profile", session_scope=lambda _s: _FakeSession(), create_object=_blank)

    outcome = await create_support_object(_accounted(), CreateSupportObjectArgs.model_construct(display_name="   "))

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_invalid_arguments"


@pytest.mark.asyncio
async def test_create_object_failure_does_not_receipt_an_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """创建失败明确失败，不回执一个标识——回执了模型会把它当成已建成的对象用。"""

    async def _boom(_session: object, **_kwargs: object) -> object:
        raise RuntimeError("连接中断")

    _patch(monkeypatch, "campfire.tools.profile", session_scope=lambda _s: _FakeSession(), create_object=_boom)

    outcome = await create_support_object(_accounted(), CreateSupportObjectArgs(display_name="小宝"))

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_failed"
