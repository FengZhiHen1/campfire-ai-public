"""故障注入必须穿过真实产品工具池和运行器装配，而非仅测试手工构造的替身。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from campfire.agent.runtime import AgentRunner
from campfire.agent.tools import ToolFailure, ToolResult
from campfire.core.config import Settings
from campfire.surfaces.consult import assembly, composition
from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan
from evaluation.carebench.systems.agent import AgentSystem
from evaluation.carebench.systems.base import TurnInput

from .conftest import load_cases, make_cases_file


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["empty", "unavailable", "timeout"])
async def test_fault_plan_builds_real_product_runner_and_invokes_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings_for_tests: Settings, mode: str
) -> None:
    settings = settings_for_tests.model_copy(
        update={"skill_root": str(Path(__file__).resolve().parents[3] / "apps/api/skills")}
    )
    monkeypatch.setattr("evaluation.carebench.systems.agent.get_engine", lambda _: None)
    case = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1)).cases[0]
    system = AgentSystem(
        settings=settings,
        config=RunConfig(label="calibration"),
        gateway=SimpleNamespace(model_name="test", binding=SimpleNamespace()),
        faults=FaultPlan({case.id: ((f"tool_search_{mode}", "config"),)}),
    )
    request = TurnInput(case=case, system_id="C", session_id="session", account_id="account", turn=1, attempt=1)
    product_pool = composition.build_tool_pool(assembly.get_skill_registry(settings))
    replacements = system._tool_replacements(request)
    replacement = replacements["search_knowledge"]
    product = product_pool.get("search_knowledge")
    assert replacement.description == product.description
    assert replacement.parameters == product.parameters
    assert isinstance(system._runner_for(request), AgentRunner)
    facts = system._override_facts(request)
    assert facts[0]["description_reused_from_product"] is True

    if mode == "timeout":
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(replacement.handler(None, None), timeout=0.01)
    else:
        result: Any = await replacement.handler(None, None)
        assert isinstance(result, ToolResult if mode == "empty" else ToolFailure)
        if mode == "unavailable":
            assert result.code == "tool_failed"
