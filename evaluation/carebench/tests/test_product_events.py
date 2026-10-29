"""真实产品事件形状必须贯穿适配器、文本投影和 JSON 证据，不能只用手写字典代替。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from campfire.agent.runtime import ActionCardEvent, QuestionEvent, RunFinishedEvent
from campfire.agent.runtime.events import RunUsage
from campfire.agent.tools.payloads import (
    ActionCardAnnotation,
    ActionCardSection,
    ActionCardState,
    QuestionItem,
    QuestionOption,
)
from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan
from evaluation.carebench.systems.agent import AgentSystem
from evaluation.carebench.systems.base import TurnInput

from .conftest import load_cases, make_cases_file


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["question", "action_card"])
async def test_product_nested_event_survives_adapter_projection_and_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings_for_tests: Any, kind: str
) -> None:
    question = QuestionEvent(
        batch_id="batch-real",
        items=(QuestionItem(id="q1", prompt="当前最在意什么？", options=(QuestionOption("声音"),), allow_skip=True),),
    )
    card = ActionCardEvent(
        card_id="card-real",
        title="下一步",
        sections=(ActionCardSection("now", "现在", ("保持陪伴",)),),
        states=(ActionCardState("status", "unknown"),),
        annotations=(ActionCardAnnotation("1", "boundary"),),
    )
    event = question if kind == "question" else card

    class EventRunner:
        async def run(self, _request: Any):
            yield event
            yield RunFinishedEvent(reason="completed", citations=(), usage=RunUsage(), elapsed_seconds=0.01)

    system = AgentSystem(
        settings=settings_for_tests,
        config=RunConfig(label="calibration"),
        gateway=SimpleNamespace(model_name="test"),
        faults=FaultPlan({}),
    )
    system._constants = {
        "surface": "consult",
        "instructions": "test",
        "default_active_tools": (),
        "account_payload_key": "account_id",
    }
    monkeypatch.setattr(system, "_runner_for", lambda _request: EventRunner())
    monkeypatch.setattr(system, "_session_item_count", AsyncMock(side_effect=[0, 13]))
    case = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1)).cases[0]
    request = TurnInput(case=case, system_id="C", session_id="session", account_id="account", turn=1, attempt=1)
    outcome = await system.run_turn(request)
    assert outcome.status == "completed"
    assert outcome.raw_output == ""
    assert outcome.retry_safety == "new_session"
    saved = json.loads(json.dumps(outcome.structured, ensure_ascii=False))[0]
    assert saved["kind"] == kind
    assert "type" not in saved
    if kind == "question":
        assert saved["items"][0]["options"] == [{"label": "声音", "description": None}]
        assert "当前最在意什么？" in outcome.output_text
        assert "选项：声音" in outcome.output_text
        assert "允许跳过：是" in outcome.output_text
    else:
        assert saved["sections"][0]["lines"] == ["保持陪伴"]
        assert saved["states"] == [{"key": "status", "value": "unknown"}]
        assert saved["annotations"] == [{"target": "1", "kind": "boundary"}]
        assert "1. 保持陪伴" in outcome.output_text
        assert "status = unknown" in outcome.output_text
        assert "第 1 行 — boundary" in outcome.output_text
    assert json.loads(json.dumps(outcome.trace))["events"][0]["type"] == kind
