"""AI 评分入口与恢复流程的纯替身验收，不调用模型或数据服务。"""

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from evaluation.carebench import ai_runner, cli
from evaluation.carebench.ai_review import load_identity
from evaluation.carebench.ai_runner import ScoreRunResult
from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan
from evaluation.carebench.review import export_packet
from evaluation.carebench.runner import execute
from evaluation.carebench.store import RunStore, create_run_dir
from evaluation.carebench.summarize import summarize_run
from evaluation.carebench.verify import verify_run

from .conftest import FakeAdapter, load_cases, make_cases_file, make_snapshot


@pytest.fixture
def dry_run(tmp_path: Path, settings_for_tests: Any) -> RunStore:
    store = create_run_dir(tmp_path / "runs", "cli-ai")
    asyncio.run(
        execute(
            store=store,
            config=RunConfig(label="calibration"),
            case_set=load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1)),
            snapshot=make_snapshot(),
            faults=FaultPlan(requested={}),
            settings=settings_for_tests,
            adapters={name: FakeAdapter(name) for name in ("A", "B", "C")},
            dry_run=True,
            log=lambda message: None,
        )
    )
    return store


def _resume(store: RunStore, settings: Any) -> None:
    asyncio.run(
        execute(
            store=store,
            config=RunConfig.from_dict(store.read_manifest()["config"]),
            case_set=load_cases(store.cases_path),
            snapshot=make_snapshot(),
            faults=FaultPlan(requested={}),
            settings=settings,
            adapters={name: FakeAdapter(name) for name in ("A", "B", "C")},
            resume=True,
            log=lambda message: None,
        )
    )


def test_ai_prepare_before_generation_keeps_identity_across_resume(dry_run: RunStore, settings_for_tests: Any) -> None:
    assert not dry_run.read_outputs()
    assert cli.main(["ai-prepare", "--run", str(dry_run.root), "--model", "stub-model"]) == 0
    identity = load_identity(dry_run)
    anchor = dry_run.read_manifest()["review"]["ai"]
    _resume(dry_run, settings_for_tests)
    assert dry_run.read_outputs()
    assert dry_run.read_manifest()["review"]["ai"] == anchor
    assert load_identity(dry_run) == identity
    export_packet(dry_run, log=lambda message: None)
    summary = summarize_run(dry_run, log=lambda message: None)
    assert summary["human_scores"] is None
    assert summary["ai_review_status"] == "pending"
    assert "hard_failure" not in summary["ai_scores"]
    assert verify_run(dry_run).ok
    assert not verify_run(dry_run, require_complete=True).ok


@pytest.mark.parametrize("invalid", [0, 1])
def test_ai_score_cli_passes_explicit_scope_and_reports_invalid_attempts(
    dry_run: RunStore, settings_for_tests: Any, monkeypatch: pytest.MonkeyPatch, invalid: int
) -> None:
    _resume(dry_run, settings_for_tests)
    export_packet(dry_run, log=lambda message: None)
    assert cli.main(["ai-prepare", "--run", str(dry_run.root), "--model", "stub-model"]) == 0
    runner = AsyncMock(return_value=ScoreRunResult(total=1, ok=1 - invalid, invalid=invalid, error=0, skipped=0))
    monkeypatch.setattr(ai_runner, "score_run", runner)
    monkeypatch.setattr(cli, "_settings", lambda: settings_for_tests)
    code = cli.main(
        ["ai-score", "--run", str(dry_run.root), "--pass", "2", "--blind-ids", "X1", "--max-concurrency", "1"]
    )
    assert code == (1 if invalid else 0)
    assert runner.await_args.kwargs == {"passes": (2,), "blind_ids": ["X1"], "max_concurrency": 1}


def test_formal_cli_refuses_posthoc_review_identity(dry_run: RunStore, settings_for_tests: Any) -> None:
    _resume(dry_run, settings_for_tests)
    manifest = dry_run.read_manifest()
    manifest["label"] = "test"
    dry_run.write_manifest(manifest)
    assert cli.main(["ai-prepare", "--run", str(dry_run.root), "--model", "stub-model"]) == 2
    report = verify_run(dry_run, require_complete=True)
    assert any("缺独立 AI 评审" in issue for issue in report.violations)
