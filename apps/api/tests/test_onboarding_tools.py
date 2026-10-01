"""`tools/onboarding.py` 的单元测试：参数形状、账号校验与失败码映射。

对应契约：docs/技术设计/面/consult/tools/finish_onboarding.md。

不连库：状态机的幂等语义与「不代写 skipped」由
`test_onboarding_completion_integration.py` 在真实 PostgreSQL 上覆盖；
本文件只钉工具层自己的职责——参数形状（含「状态取值不该是参数」）、
缺账号时的明确失败、写入失败不回执 `completed`、状态透传到返回体。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from campfire.agent.context import CitationRecorder
from campfire.agent.tools import ActivationState, ToolContext, ToolFailure, ToolResult
from campfire.modules.accounts.errors import OnboardingWriteError
from campfire.tools.onboarding import (
    ACCOUNT_PAYLOAD_KEY,
    SKIPPED_SECTIONS,
    FinishOnboardingArgs,
    finish_onboarding,
)

_ACCOUNT = "tool_test_account"


class _FakeIndex:
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


def _accounted() -> ToolContext:
    return _context(payload={ACCOUNT_PAYLOAD_KEY: _ACCOUNT})


class _FakeSession:
    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_exc: object) -> None: ...


# ---------------------------------------------------------------------------
# 参数形状（契约第 2 节）
# ---------------------------------------------------------------------------


def test_parameter_names_match_the_contract() -> None:
    """参数名与契约逐字一致：只有 `skipped_sections`。"""
    assert set(FinishOnboardingArgs.model_fields) == {"skipped_sections"}


def test_does_not_accept_account_id_or_state() -> None:
    """不收 `account_id`，也不收 `state`（契约第 2 节）。

    判别性：加上 `state`，模型就有了选择 `skipped` 的通道，而契约第 1 节明写
    「本工具只写 `completed`，两条通道互不代写」——不设参数比「接受再拒绝」更强：
    不存在的通道无法被绕过。加上 `account_id` 则让属主可被指定（`RQ-ACC-01`）。
    """
    assert "account_id" not in FinishOnboardingArgs.model_fields
    assert "state" not in FinishOnboardingArgs.model_fields


def test_skipped_sections_defaults_to_empty() -> None:
    """`skipped_sections` 可省略（契约第 2 节未标必填）——全程没跳过时不必传。"""
    assert FinishOnboardingArgs.model_validate({}).skipped_sections == []


def test_skipped_sections_is_a_closed_vocabulary() -> None:
    """段名是闭词表（三个具名值），词表外的段名在解析期被拒。

    判别性：放开成 `list[str]`，模型可以塞任意字符串——那会变成一条没有消费者的
    自由文本，而契约第 2 节把它列成三个具名值。
    """
    assert SKIPPED_SECTIONS == {"onboarding", "profile_seed", "memory_seed"}
    for section in sorted(SKIPPED_SECTIONS):
        assert FinishOnboardingArgs.model_validate({"skipped_sections": [section]}).skipped_sections == [section]
    with pytest.raises(Exception):  # noqa: B017 —— pydantic 的 ValidationError
        FinishOnboardingArgs.model_validate({"skipped_sections": ["对象创建"]})


# ---------------------------------------------------------------------------
# 账号校验（未登录 → 明确失败）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fails_without_an_account_in_payload() -> None:
    """`payload` 里没有账号时明确失败，不猜一个默认账号（`RQ-ACC-01`）。

    猜默认会把引导状态写到别的账号上——使用者看不到异常，只是自己的引导一直没结束。
    """
    for payload in (None, {}, {ACCOUNT_PAYLOAD_KEY: ""}, {ACCOUNT_PAYLOAD_KEY: "   "}):
        outcome = await finish_onboarding(_context(payload=payload), FinishOnboardingArgs())
        assert isinstance(outcome, ToolFailure), "缺账号时不得成功"
        assert outcome.code == "tool_failed"
        assert ACCOUNT_PAYLOAD_KEY in outcome.message


# ---------------------------------------------------------------------------
# 返回与失败语义（契约第 3、5 节）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_the_state_written_by_the_use_case(monkeypatch: pytest.MonkeyPatch) -> None:
    """返回体是 `{"state": ...}`，取值来自用例层（契约第 3 节）。"""
    import campfire.tools.onboarding as tool_module

    async def _fake_complete(_session: object, **_kwargs: object) -> str:
        return "completed"

    monkeypatch.setattr(tool_module, "session_scope", lambda _s: _FakeSession())
    monkeypatch.setattr(tool_module, "complete_onboarding", _fake_complete)

    outcome = await finish_onboarding(_accounted(), FinishOnboardingArgs())

    assert isinstance(outcome, ToolResult)
    assert json.loads(outcome.text) == {"state": "completed"}


@pytest.mark.asyncio
async def test_returns_skipped_when_the_ui_already_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """此前已被 UI 跳过时返回 `skipped`，不报错也不改写（契约第 4 节第 2 条）。

    判别性：把用例层的「已 skipped 直接返回」改成覆盖写 `completed`，本用例失败
    ——那会抹掉使用者的显式决定（两条通道互不代写，认证与账号第 8 节）。
    """
    import campfire.tools.onboarding as tool_module

    async def _fake_complete(_session: object, **_kwargs: object) -> str:
        return "skipped"

    monkeypatch.setattr(tool_module, "session_scope", lambda _s: _FakeSession())
    monkeypatch.setattr(tool_module, "complete_onboarding", _fake_complete)

    outcome = await finish_onboarding(_accounted(), FinishOnboardingArgs())

    assert isinstance(outcome, ToolResult)
    assert json.loads(outcome.text) == {"state": "skipped"}


@pytest.mark.asyncio
async def test_write_failure_does_not_receipt_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    """状态表写入失败 → 明确失败，不回执 `completed`（契约第 5 节末行）。

    判别性：把 `except` 分支改成返回 `{"state": "completed"}`，本用例失败——
    模型会以为引导已收束，而下次会话仍会重新注入，两边都说自己是对的。
    """
    import campfire.tools.onboarding as tool_module

    async def _boom(_session: object, **_kwargs: object) -> str:
        raise OnboardingWriteError("连接中断")

    monkeypatch.setattr(tool_module, "session_scope", lambda _s: _FakeSession())
    monkeypatch.setattr(tool_module, "complete_onboarding", _boom)

    outcome = await finish_onboarding(_accounted(), FinishOnboardingArgs())

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_failed"
    assert "completed" not in outcome.message, "失败回执里不得出现 completed"
    assert "跳过入口" in outcome.message, "必须告知补救通道（UI 跳过入口）"


@pytest.mark.asyncio
async def test_failure_message_does_not_leak_details(monkeypatch: pytest.MonkeyPatch) -> None:
    """失败消息不复述底层细节（安全条款：可能含连接串）。"""
    import campfire.tools.onboarding as tool_module

    async def _boom(_session: object, **_kwargs: object) -> str:
        raise RuntimeError("postgresql://user:secret@host:5432/db 连接失败")

    monkeypatch.setattr(tool_module, "session_scope", lambda _s: _FakeSession())
    monkeypatch.setattr(tool_module, "complete_onboarding", _boom)

    outcome = await finish_onboarding(_accounted(), FinishOnboardingArgs())

    assert isinstance(outcome, ToolFailure)
    assert "secret" not in outcome.message
    assert "postgresql" not in outcome.message


@pytest.mark.asyncio
async def test_skipped_sections_do_not_change_the_returned_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """传了跳过段名也不改变状态取值（契约第 2 节末行「仅作记录」）。

    判别性：让 `skipped_sections` 影响 `state`（例如有跳过就写 skipped），本用例失败
    ——那就等于把 UI 通道的语义偷偷搬进了本工具。
    """
    import campfire.tools.onboarding as tool_module

    async def _fake_complete(_session: object, **_kwargs: object) -> str:
        return "completed"

    monkeypatch.setattr(tool_module, "session_scope", lambda _s: _FakeSession())
    monkeypatch.setattr(tool_module, "complete_onboarding", _fake_complete)

    args = FinishOnboardingArgs(skipped_sections=["profile_seed", "memory_seed"])
    outcome = await finish_onboarding(_accounted(), args)

    assert isinstance(outcome, ToolResult)
    assert json.loads(outcome.text) == {"state": "completed"}
