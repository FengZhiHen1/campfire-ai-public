"""`tools/library.py` 的单元测试：参数形状、返回契约映射、失败与空结果语义。

对应契约：[search_knowledge](../../../docs/技术设计/面/consult/tools/search_knowledge.md)
与[资料与案例检索](../../../docs/技术设计/technical-details/资料与案例检索.md)第 3、5 节。

**不连库**：检索链本身由 `test_library_retrieval*.py` 覆盖；本文件只钉**工具层自己的
职责**——参数上界、返回契约字段、降级与「未找到」的对外说法、失败不冒充空结果。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from campfire.agent.context import CitationRecorder
from campfire.agent.tools import ActivationState, ToolContext, ToolFailure, ToolResult
from campfire.modules.library.retrieval import RetrievedItem, SearchOutcome
from campfire.tools.library import (
    DEFAULT_RESULT_LIMIT,
    MAX_RESULT_LIMIT,
    SNIPPET_MAX_CHARS,
    SearchKnowledgeArgs,
    _degradation_note,
    _render_item,
    search_knowledge,
)


class _FakeIndex:
    def add(self, *_args: Any, **_kwargs: Any) -> None: ...


def _context() -> ToolContext:
    return ToolContext(
        run_id="run-1",
        session_id="session-1",
        surface="consult",
        activation_state=ActivationState(),
        citations=CitationRecorder(_FakeIndex(), run_id="run-1", clock=lambda: datetime.now(timezone.utc)),
    )


def _item(**overrides: Any) -> RetrievedItem:
    base: dict[str, Any] = {
        "item_id": "11111111-1111-4111-8111-111111111111",
        "library": "knowledge",
        "title": "视觉支持策略",
        "snippet": "使用图片日程表可以减少不确定性。",
        "source": "WHO 2024",
        "applicable_scope": "学龄前儿童",
        "status": "published",
        "locator": "/总则/",
        "ranking": {"fused_score": 0.5, "hit_paths": "both"},
    }
    base.update(overrides)
    return RetrievedItem(**base)


# ---------------------------------------------------------------------------
# 参数形状（契约第 2 节）
# ---------------------------------------------------------------------------


def test_query_is_required() -> None:
    """`query` 必填（契约第 2 节）。"""
    with pytest.raises(Exception):  # noqa: B017 —— pydantic 的 ValidationError
        SearchKnowledgeArgs.model_validate({})


def test_parameter_names_match_the_contract() -> None:
    """参数名与契约逐字一致——名字漂了模型就按错的 schema 调用。"""
    assert set(SearchKnowledgeArgs.model_fields) == {"query", "limit", "scope"}


def test_limit_has_a_server_side_cap() -> None:
    """`limit` 有服务端上界（CORE-11）：不设上界则 `limit=10**9` 会吃掉整个上下文预算。

    判别性：去掉 `le=MAX_RESULT_LIMIT`，超限值被接受，本用例失败。
    """
    with pytest.raises(Exception):  # noqa: B017
        SearchKnowledgeArgs.model_validate({"query": "孤独症", "limit": MAX_RESULT_LIMIT + 1})


def test_an_empty_query_is_rejected() -> None:
    """空查询在参数层拒绝——它无法构成检索，放行只会得到空结果并浪费一次调用。"""
    with pytest.raises(Exception):  # noqa: B017
        SearchKnowledgeArgs.model_validate({"query": ""})


# ---------------------------------------------------------------------------
# 返回契约映射（资料与案例检索第 3 节）
# ---------------------------------------------------------------------------


def test_render_item_carries_every_contract_field() -> None:
    """返回字段与第 3 节的 `KnowledgeResult` 逐字一致，且**不删减**。

    `source` 与 `applicable_scope` 是 `RQ-CON-03`（输出要能说明适用条件与局限）的
    前提，因此这里断言它们必须在场——将来有人为了省 context 删字段，本用例会拦下。
    """
    rendered = _render_item(_item())
    for field in (
        "item_id",
        "library",
        "title",
        "snippet",
        "source",
        "applicable_scope",
        "status",
        "locator",
        "ranking",
    ):
        assert field in rendered, f"返回契约字段 {field} 缺失"


def test_long_snippet_is_truncated_and_flagged() -> None:
    """超长 snippet 被截断，且**标注被截断**——静默截断会让模型以为看完了。

    判别性：去掉 `snippet_truncated` 的标记，本用例失败。
    """
    rendered = _render_item(_item(snippet="x" * (SNIPPET_MAX_CHARS + 500)))
    assert len(rendered["snippet"]) == SNIPPET_MAX_CHARS
    assert rendered["snippet_truncated"] is True


def test_short_snippet_is_not_flagged_as_truncated() -> None:
    """短 snippet 不得被标成截断（否则模型会怀疑内容不完整）。"""
    rendered = _render_item(_item(snippet="短"))
    assert rendered["snippet_truncated"] is False


# ---------------------------------------------------------------------------
# 降级与「未找到」的对外说法（失败语义第 5 节）
# ---------------------------------------------------------------------------


def test_degradation_note_forbids_claiming_no_material() -> None:
    """单路失败时必须**明确告知模型不得声称「没有相关资料」**。

    契约第 5 节原话：向量路失败 → 「只用字面路返回，并在结果中标注『语义检索不可用』」。
    光标注「不可用」不够——模型只有被明确要求，才不会把「检索不完整」说成
    「没有相关资料」。
    """
    note = _degradation_note(("vector",))
    assert note is not None
    assert "语义检索" in note
    assert "没有相关资料" in note


def test_no_degradation_note_when_both_paths_work() -> None:
    """两路都正常时不加降级说明——否则模型会平白怀疑结果不完整。"""
    assert _degradation_note(()) is None


@pytest.mark.asyncio
async def test_empty_result_says_not_found_without_overclaiming(monkeypatch: pytest.MonkeyPatch) -> None:
    """检索为空时明确「未找到」，且**不得**解释为「该做法不存在或没有风险」。

    判别性：去掉空结果分支的 `notice`，本用例失败。
    """

    async def _empty(*_args: object, **_kwargs: object) -> SearchOutcome:
        return SearchOutcome(items=[], degraded_paths=())

    monkeypatch.setattr("campfire.tools.library._run_search", _empty)

    outcome = await search_knowledge(_context(), SearchKnowledgeArgs(query="孤独症"))

    assert isinstance(outcome, ToolResult)
    payload = json.loads(outcome.text)
    assert payload["count"] == 0
    assert "未找到" in payload["notice"]
    assert "不存在" in payload["notice"]


@pytest.mark.asyncio
async def test_failure_does_not_pretend_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """两路都失败时返回 `ToolFailure`，**绝不返回空列表冒充「未找到」**（第 5 节）。

    判别性：把 `RetrievalError` 分支改成 `return ToolResult(text="[]")`，本用例失败。
    """
    from campfire.modules.library.retrieval import RetrievalError

    async def _boom(*_args: object, **_kwargs: object) -> SearchOutcome:
        raise RetrievalError("两路检索均失败：向量路 TimeoutError、字面路 OperationalError")

    monkeypatch.setattr("campfire.tools.library._run_search", _boom)

    outcome = await search_knowledge(_context(), SearchKnowledgeArgs(query="孤独症"))

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_failed"
    assert "没有相关资料" in outcome.message, "必须明确禁止把失败说成「没有相关资料」"


@pytest.mark.asyncio
async def test_failure_message_does_not_leak_details(monkeypatch: pytest.MonkeyPatch) -> None:
    """失败消息**不复述**底层细节（安全条款：可能含连接串/凭据）。"""

    async def _boom(*_args: object, **_kwargs: object) -> SearchOutcome:
        raise RuntimeError("postgresql://user:secret@host:5432/db 连接失败")

    monkeypatch.setattr("campfire.tools.library._run_search", _boom)

    outcome = await search_knowledge(_context(), SearchKnowledgeArgs(query="孤独症"))

    assert isinstance(outcome, ToolFailure)
    assert "secret" not in outcome.message
    assert "postgresql" not in outcome.message


@pytest.mark.asyncio
async def test_successful_result_reports_count_and_items(monkeypatch: pytest.MonkeyPatch) -> None:
    """命中时返回条目与条数，且**不带**降级标记。"""

    async def _hit(*_args: object, **_kwargs: object) -> SearchOutcome:
        return SearchOutcome(items=[_item()], degraded_paths=())

    monkeypatch.setattr("campfire.tools.library._run_search", _hit)

    outcome = await search_knowledge(_context(), SearchKnowledgeArgs(query="孤独症"))

    assert isinstance(outcome, ToolResult)
    payload = json.loads(outcome.text)
    assert payload["count"] == 1
    assert payload["results"][0]["title"] == "视觉支持策略"
    assert "degraded" not in payload
    assert "notice" not in payload


@pytest.mark.asyncio
async def test_degraded_result_is_flagged_in_the_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """单路失败的结果在 payload 里带 `degraded` 与说明。"""

    async def _degraded(*_args: object, **_kwargs: object) -> SearchOutcome:
        return SearchOutcome(items=[_item()], degraded_paths=("vector",))

    monkeypatch.setattr("campfire.tools.library._run_search", _degraded)

    outcome = await search_knowledge(_context(), SearchKnowledgeArgs(query="孤独症"))

    assert isinstance(outcome, ToolResult)
    payload = json.loads(outcome.text)
    assert payload["degraded"] is True
    assert payload["degraded_paths"] == ["vector"]
    assert "没有相关资料" in payload["notice"]


def test_default_limit_matches_the_retrieval_chain_default() -> None:
    """不给 `limit` 时与直接调检索链的默认值一致——避免两处默认值漂移。"""
    from campfire.modules.library.retrieval import FUSED_TOP_K

    assert DEFAULT_RESULT_LIMIT == FUSED_TOP_K
