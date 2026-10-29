"""评测装配在预检、装配失败、取消和落盘失败时都必须释放自有资源。"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from evaluation.carebench import systems
from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan
from evaluation.carebench.runner import execute
from evaluation.carebench.store import create_run_dir

from .conftest import FakeAdapter, load_cases, make_cases_file, make_snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["none", "prepare", "cancel", "manifest"])
async def test_owned_bundle_is_closed_on_every_pre_execution_exit(
    tmp_path: Path, settings_for_tests: Any, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))
    store = create_run_dir(tmp_path / "runs", "lifecycle")
    adapters = {system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")}
    bundle = SimpleNamespace(adapters=adapters, aclose=AsyncMock())
    monkeypatch.setattr(systems, "build_adapters", lambda **kwargs: bundle)
    if failure in {"prepare", "cancel"}:
        error = RuntimeError("prepare") if failure == "prepare" else asyncio.CancelledError()
        monkeypatch.setattr(adapters["A"], "prepare", AsyncMock(side_effect=error))
    if failure == "manifest":
        monkeypatch.setattr(type(store), "write_manifest", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    call = execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=FaultPlan(requested={}),
        settings=settings_for_tests,
        dry_run=True,
        log=lambda message: None,
    )
    if failure == "none":
        assert (await call).status == "dry_run"
    else:
        expected = {"prepare": RuntimeError, "cancel": asyncio.CancelledError, "manifest": OSError}[failure]
        with pytest.raises(expected):
            await call
    bundle.aclose.assert_awaited_once()
    assert all(not adapter.calls for adapter in adapters.values())
