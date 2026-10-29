"""检索工具的结果文本：降级说明与空结果提示必须**并存**（审查修正 2026-10-29）。

旧实现先设降级说明、再用空结果提示覆盖它，于是「单路检索失败 + 没有命中」这最危险的一格
只剩「未找到相关资料…」，丢掉了契约第 5 节要求「不得据此声称没有相关资料」的那句话。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone

import pytest

from campfire.agent.context import CitationRecord, CitationRecorder
from campfire.agent.tools import ActivationState, ToolContext
from campfire.modules.library.retrieval import SearchOutcome
from campfire.tools.library import SearchKnowledgeArgs, search_knowledge


class _FakeIndex:
    """最小引用索引替身：本文件的结果都不产生引用。"""

    async def add(self, _record: CitationRecord) -> None:
        return None

    async def list_for_run(self, _run_id: str) -> Sequence[CitationRecord]:
        return []


def _context() -> ToolContext:
    """工具上下文替身（与本仓 `test_library_tools` 同一装配）。"""
    return ToolContext(
        run_id="run-1",
        session_id="session-1",
        surface="consult",
        activation_state=ActivationState(),
        citations=CitationRecorder(_FakeIndex(), run_id="run-1", clock=lambda: datetime.now(timezone.utc)),
    )


@pytest.mark.asyncio
async def test_degraded_empty_result_keeps_the_no_such_material_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """「单路失败 + 没有命中」必须同时带：结果不完整的说明 + 不得声称没有资料的禁令。

    判别性（消融）：恢复 `payload["notice"] = empty_notice` 的覆盖写法，
    `"没有相关资料" in payload["notice"]` 立刻失败——而那正是模型会照做的方向。
    """

    async def _degraded_empty(*_args: object, **_kwargs: object) -> SearchOutcome:
        return SearchOutcome(items=[], degraded_paths=("vector",))

    monkeypatch.setattr("campfire.tools.library._run_search", _degraded_empty)

    outcome = await search_knowledge(_context(), SearchKnowledgeArgs(query="孤独症"))

    payload = json.loads(outcome.text)  # type: ignore[union-attr]  # ToolResult
    assert payload["degraded"] is True
    assert payload["degraded_paths"] == ["vector"]
    assert payload["count"] == 0
    notice = payload["notice"]
    assert "语义检索" in notice, "必须说明哪一路不可用"
    assert "不得" in notice and "没有相关资料" in notice, "必须保留「不得据此声称没有相关资料」"
    assert "未找到" in notice, "空结果仍要明确「未找到」"


@pytest.mark.asyncio
async def test_empty_result_without_degradation_has_only_the_empty_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正向控制：两路都正常但没有命中时，不得凭空出现降级字样。"""

    async def _empty(*_args: object, **_kwargs: object) -> SearchOutcome:
        return SearchOutcome(items=[], degraded_paths=())

    monkeypatch.setattr("campfire.tools.library._run_search", _empty)

    outcome = await search_knowledge(_context(), SearchKnowledgeArgs(query="孤独症"))

    payload = json.loads(outcome.text)  # type: ignore[union-attr]
    assert "degraded" not in payload
    assert "语义检索" not in payload["notice"]
    assert "未找到" in payload["notice"]
