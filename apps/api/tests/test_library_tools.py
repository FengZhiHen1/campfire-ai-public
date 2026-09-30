"""`tools/library.py` 的单元测试：参数形状、返回契约映射、失败与空结果语义。

对应契约：[search_knowledge](../../../docs/技术设计/面/consult/tools/search_knowledge.md)、
[search_cases](../../../docs/技术设计/面/consult/tools/search_cases.md)
与[资料与案例检索](../../../docs/技术设计/technical-details/资料与案例检索.md)第 3、5 节。

**不连库**：检索链本身由 `test_library_retrieval*.py` 覆盖；本文件只钉**工具层自己的
职责**——参数上界、返回契约字段、降级与「未找到」的对外说法、失败不冒充空结果、
库别不混。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from campfire.agent.context import CitationRecorder
from campfire.agent.tools import ActivationState, ToolContext, ToolFailure, ToolResult
from campfire.modules.library.retrieval import LIBRARY_CASE, LIBRARY_KNOWLEDGE, RetrievedItem, SearchOutcome
from campfire.tools.library import (
    DEFAULT_RESULT_LIMIT,
    MAX_RESULT_LIMIT,
    SNIPPET_MAX_CHARS,
    SearchCasesArgs,
    SearchKnowledgeArgs,
    _degradation_note,
    _render_case_item,
    _render_item,
    search_cases,
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


def _case_item(**overrides: Any) -> RetrievedItem:
    """一条带全部案例专属字段的命中（契约第 3 节 + 公共案例库第 8 节）。"""
    base: dict[str, Any] = {
        "item_id": "22222222-2222-4222-8222-222222222222",
        "library": "case",
        "title": "把日程表贴在冰箱上后出门前的崩溃减少",
        "snippet": "出门前十分钟开始预告，并把图片日程表贴在他够得到的位置。",
        "source": "专家访谈转写 · 2026-03",
        "applicable_scope": "学龄前 · 语言理解尚可",
        "status": "published",
        "locator": "/案例/日程/",
        "ranking": {"fused_score": 0.7, "hit_paths": "both"},
        "authorization": "已授权",
        "source_type": "expert_interview",
        "evidence_level": "OBSERVATIONAL",
        "review_status": "professional",
        "interview_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        "makes_claims_high_risk": False,
        "inferred_fields": ["age_range"],
    }
    base.update(overrides)
    return RetrievedItem(**base)


# ---------------------------------------------------------------------------
# search_cases：参数形状与返回契约（search_cases 契约第 2、3 节）
# ---------------------------------------------------------------------------


def test_search_cases_parameter_names_match_the_contract() -> None:
    """参数名与契约逐字一致：`query` / `limit` / `authorization`。

    判别性：多写一个 `scope`（资料侧的过滤维度）或漏掉 `authorization`，本用例失败
    ——契约第 2 节明确只暴露这三个，一期不向模型暴露卡片级过滤维度。
    """
    assert set(SearchCasesArgs.model_fields) == {"query", "limit", "authorization"}


def test_search_cases_has_no_library_parameter() -> None:
    """**没有**库别参数：库别由工具写死（契约第 4 节「只查案例库，不混入专业资料」）。

    判别性：谁将来加一个 `library` 参数，本用例失败——那会让模型把这条硬约束
    改成「查资料库」，「不混库」就不再是机械保证。
    """
    assert "library" not in SearchCasesArgs.model_fields


def test_search_cases_limit_has_the_same_server_side_cap() -> None:
    """`limit` 上界与资料侧同值（CORE-11）。"""
    with pytest.raises(Exception):  # noqa: B017
        SearchCasesArgs.model_validate({"query": "日程表", "limit": MAX_RESULT_LIMIT + 1})


def test_render_case_item_carries_every_shared_and_case_field() -> None:
    """案例返回 = 共用字段 + 七个案例专属字段，**一个都不能省**（契约第 3 节）。

    `authorization` 与 `status` 是「真实案例与虚构样例可辨」（`AC-06`）的全部依据；
    `review_status`/`evidence_level`/`interview_at` 是「谁说的、多可信、什么时候」；
    `makes_claims_high_risk`/`inferred_fields` 是高风险主张与被推断字段的标注。

    判别性：删掉任一字段，本用例失败。
    """
    rendered = _render_case_item(_case_item())
    for field in (
        # 共用（资料与案例检索第 3 节）
        "item_id",
        "library",
        "title",
        "snippet",
        "source",
        "applicable_scope",
        "status",
        "locator",
        "ranking",
        # 案例专属七字段
        "authorization",
        "source_type",
        "evidence_level",
        "review_status",
        "interview_at",
        "makes_claims_high_risk",
        "inferred_fields",
    ):
        assert field in rendered, f"案例返回契约字段 {field} 缺失"


def test_render_case_item_keeps_missing_case_fields_as_none() -> None:
    """案例字段缺失时如实保留 `None`，不补默认值（不变量：不补默认值）。

    判别性：把 `None` 换成空串或 `False`，本用例失败——那会让「未记录」看起来
    像「已记录为否」，例如 `makes_claims_high_risk=False` 会被读成「已核实无高风险主张」。
    """
    rendered = _render_case_item(
        _case_item(
            authorization=None,
            evidence_level=None,
            review_status=None,
            interview_at=None,
            makes_claims_high_risk=None,
            inferred_fields=[],
        )
    )
    assert rendered["authorization"] is None
    assert rendered["evidence_level"] is None
    assert rendered["review_status"] is None
    assert rendered["interview_at"] is None
    assert rendered["makes_claims_high_risk"] is None
    assert rendered["inferred_fields"] == []


def test_render_case_item_serializes_interview_at() -> None:
    """`interview_at` 转成 ISO 8601 字符串——返回要走 `json.dumps`，`datetime` 会抛 `TypeError`。

    判别性：直接透传 `datetime`，本用例（以及任何真实调用）在序列化时失败。
    """
    rendered = _render_case_item(_case_item())
    assert rendered["interview_at"] == "2026-03-01T12:00:00+00:00"
    json.dumps(rendered)  # 不抛错 = 可序列化


@pytest.mark.asyncio
async def test_search_cases_asks_the_case_library_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """`search_cases` 传的库别是 `case`（契约第 4 节「只查案例库」的机械落点）。

    判别性：把 `LIBRARY_CASE` 改成 `LIBRARY_KNOWLEDGE`，本用例失败——那会让
    「不混库」失效，而这是契约第 6 节的验证项之一。
    """
    seen: dict[str, Any] = {}

    async def _capture(_settings: object, **kwargs: Any) -> SearchOutcome:
        seen.update(kwargs)
        return SearchOutcome(items=[_case_item()], degraded_paths=())

    monkeypatch.setattr("campfire.tools.library._run_search", _capture)

    outcome = await search_cases(_context(), SearchCasesArgs(query="出门前崩溃"))

    assert isinstance(outcome, ToolResult)
    assert seen["library"] == LIBRARY_CASE, "案例工具必须只查案例库"
    assert seen["library"] != LIBRARY_KNOWLEDGE


@pytest.mark.asyncio
async def test_search_cases_passes_authorization_filter_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """`authorization` 透传到检索链（契约第 2 节；过滤在 SQL 层用绑定参数完成）。"""
    seen: dict[str, Any] = {}

    async def _capture(_settings: object, **kwargs: Any) -> SearchOutcome:
        seen.update(kwargs)
        return SearchOutcome(items=[_case_item()], degraded_paths=())

    monkeypatch.setattr("campfire.tools.library._run_search", _capture)

    await search_cases(_context(), SearchCasesArgs(query="日程表", authorization="已授权"))

    assert seen["authorization"] == "已授权"


@pytest.mark.asyncio
async def test_search_cases_does_not_pass_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """`scope` 不是案例侧参数，因此**不传**（传了等于把资料侧的过滤维度偷渡进来）。"""
    seen: dict[str, Any] = {}

    async def _capture(_settings: object, **kwargs: Any) -> SearchOutcome:
        seen.update(kwargs)
        return SearchOutcome(items=[], degraded_paths=())

    monkeypatch.setattr("campfire.tools.library._run_search", _capture)

    await search_cases(_context(), SearchCasesArgs(query="日程表"))

    assert seen.get("scope") is None
    assert seen["library"] == LIBRARY_CASE


@pytest.mark.asyncio
async def test_search_cases_empty_result_does_not_overclaim(monkeypatch: pytest.MonkeyPatch) -> None:
    """案例检索为空时明确「未找到」，且不得升级成「没有这种情形」（契约第 5 节同源纪律）。"""

    async def _empty(*_args: object, **_kwargs: object) -> SearchOutcome:
        return SearchOutcome(items=[], degraded_paths=())

    monkeypatch.setattr("campfire.tools.library._run_search", _empty)

    outcome = await search_cases(_context(), SearchCasesArgs(query="日程表"))

    assert isinstance(outcome, ToolResult)
    payload = json.loads(outcome.text)
    assert payload["count"] == 0
    assert "未找到" in payload["notice"]
    assert "不等于" in payload["notice"]


@pytest.mark.asyncio
async def test_search_cases_failure_does_not_pretend_no_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    """两路都失败时返回 `ToolFailure`，**绝不**返回空列表冒充「没有相关案例」。

    判别性：把失败分支改成 `ToolResult(text="[]")`，本用例失败。
    """
    from campfire.modules.library.retrieval import RetrievalError

    async def _boom(*_args: object, **_kwargs: object) -> SearchOutcome:
        raise RetrievalError("两路检索均失败")

    monkeypatch.setattr("campfire.tools.library._run_search", _boom)

    outcome = await search_cases(_context(), SearchCasesArgs(query="日程表"))

    assert isinstance(outcome, ToolFailure)
    assert outcome.code == "tool_failed"
    assert "没有相关案例" in outcome.message, "必须明确禁止把失败说成「没有相关案例」"


@pytest.mark.asyncio
async def test_search_cases_failure_message_does_not_leak_details(monkeypatch: pytest.MonkeyPatch) -> None:
    """失败消息不复述底层细节（安全条款）。"""

    async def _boom(*_args: object, **_kwargs: object) -> SearchOutcome:
        raise RuntimeError("postgresql://user:secret@host:5432/db 连接失败")

    monkeypatch.setattr("campfire.tools.library._run_search", _boom)

    outcome = await search_cases(_context(), SearchCasesArgs(query="日程表"))

    assert isinstance(outcome, ToolFailure)
    assert "secret" not in outcome.message
    assert "postgresql" not in outcome.message


def test_default_limit_matches_the_retrieval_chain_default() -> None:
    """不给 `limit` 时与直接调检索链的默认值一致——避免两处默认值漂移。"""
    from campfire.modules.library.retrieval import FUSED_TOP_K

    assert DEFAULT_RESULT_LIMIT == FUSED_TOP_K
