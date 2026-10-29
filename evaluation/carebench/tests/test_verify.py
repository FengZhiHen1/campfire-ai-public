"""证据包校验的测试：篡改必须被抓住，正常批次必须通过。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio

from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan
from evaluation.carebench.review import export_packet
from evaluation.carebench.runner import execute
from evaluation.carebench.store import RunStore, create_run_dir
from evaluation.carebench.summarize import summarize_run
from evaluation.carebench.verify import verify_run

from .conftest import FakeAdapter, load_cases, make_cases_file, make_snapshot


async def _run(tmp_path: Path, *, settings: Any, faults: FaultPlan, count: int = 1) -> RunStore:
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=count))
    adapters = {
        system_id: FakeAdapter(
            system_id,
            outcome=lambda _request: TurnOutcome_factory(),
        )
        for system_id in ("A", "B", "C")
    }
    store = create_run_dir(tmp_path / "runs", "carebench-verify")
    await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults,
        settings=settings,
        adapters=adapters,
        log=lambda _message: None,
    )
    return store


def TurnOutcome_factory():  # noqa: N802 —— 测试内构造器，命名沿用其用途
    """一条正常的完成结果。"""
    from evaluation.carebench.systems.base import TurnOutcome

    return TurnOutcome(status="completed", raw_output="回复", latency_ms=10)


async def test_verify_passes_on_clean_run(tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan) -> None:
    """干净批次（含 summary 与评审包）应通过校验。"""
    store = await _run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    summarize_run(store, log=lambda _message: None)
    export_packet(store, log=lambda _message: None)
    report = verify_run(store, require_complete=True)
    assert report.ok, report.violations
    assert report.facts["progress"]["case_groups_complete"] == 3


async def test_verify_detects_tampered_output(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """改动原始输出（输入 hash 不再匹配）必须被抓住。"""
    store = await _run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    summarize_run(store, log=lambda _message: None)
    lines = store.outputs_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["raw_output"] = "偷偷改过的回复"
    lines[0] = json.dumps(first, ensure_ascii=False, sort_keys=True)
    store.outputs_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = verify_run(store)
    assert not report.ok
    # 记录自带的完整性 hash 会直接指认「被事后修改」
    assert any("内容 hash 不符" in item for item in report.violations)


async def test_verify_detects_input_asymmetry(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """某组输入 hash 与案例渲染不一致时报「信息不对称」。"""
    store = await _run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    summarize_run(store, log=lambda _message: None)
    lines = store.outputs_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["input_sha256"] = "f" * 64
    lines[0] = json.dumps(record, ensure_ascii=False, sort_keys=True)
    store.outputs_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = verify_run(store)
    assert not report.ok
    assert any("输入文本与案例渲染不一致" in item or "输入 hash 不一致" in item for item in report.violations)


async def test_verify_requires_complete_when_asked(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """`--require-complete` 下缺组必须报违反（正式批次不得用部分结果充当完整结果）。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=2))
    adapters = {system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")}
    store = create_run_dir(tmp_path / "runs", "carebench-partial")
    await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=settings_for_tests,
        adapters=adapters,
        case_ids=["CFB-C-001"],
        log=lambda _message: None,
    )
    summarize_run(store, log=lambda _message: None)
    relaxed = verify_run(store)
    assert relaxed.ok, relaxed.violations
    strict = verify_run(store, require_complete=True)
    assert not strict.ok
    assert any("要求跑满" in item for item in strict.violations)


async def test_verify_flags_scores_without_ratings(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """没人评审却出现 human_scores，必须判违反（程序不得生成质量分）。"""
    store = await _run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    summary = summarize_run(store, log=lambda _message: None)
    summary["human_scores"] = {"per_system": {}}
    (store.root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    report = verify_run(store)
    assert not report.ok
    assert any("绝不能由程序生成质量分" in item for item in report.violations)
