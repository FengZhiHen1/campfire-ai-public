"""证据核对负例：摘要、冻结配置与状态标记的篡改须被拒绝；每条先验证干净批次。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio

from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan
from evaluation.carebench.hashing import batch_fingerprint, sha256_value
from evaluation.carebench.runner import execute
from evaluation.carebench.store import RunStore, create_run_dir
from evaluation.carebench.summarize import summarize_run
from evaluation.carebench.verify import verify_run

from .conftest import FakeAdapter, load_cases, make_cases_file, make_snapshot


async def _complete_run(tmp_path: Path, *, run_id: str, settings: Any) -> RunStore:
    """跑一个最小但完整的批次（三组、单轮、无注入），并生成 summary。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))
    store = create_run_dir(tmp_path / "runs", run_id)
    await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=FaultPlan(requested={}),
        settings=settings,
        adapters={system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")},
        log=lambda _message: None,
    )
    summarize_run(store, log=lambda _message: None)
    return store


def _rewrite_records(store: RunStore, mutate: Callable[[list[dict[str, Any]]], None]) -> None:
    """改写记录并**重算** `record_sha256`（模拟「改完再补 hash」的篡改）。"""
    payloads = [
        json.loads(line) for line in store.outputs_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    mutate(payloads)
    for payload in payloads:
        payload["record_sha256"] = sha256_value(
            {key: value for key, value in payload.items() if key != "record_sha256"}
        )
    store.outputs_path.write_text(
        "\n".join(json.dumps(payload, ensure_ascii=False, sort_keys=True) for payload in payloads) + "\n",
        encoding="utf-8",
    )


async def test_tampered_summary_status_counts_must_be_rejected(tmp_path: Path, settings_for_tests: Any) -> None:
    """摘要中的状态、拒答和工具调用数必须与原始记录复算一致。"""
    store = await _complete_run(tmp_path, run_id="carebench-unchecked-summary", settings=settings_for_tests)
    assert verify_run(store, require_complete=True).ok, "正控：干净批次必须通过"

    summary = json.loads((store.root / "summary.json").read_text(encoding="utf-8"))
    assert summary["systems"]["A"]["completion_status_counts"] == {"completed": 1}, "前置条件：A 组已完成"
    summary["systems"]["A"]["completion_status_counts"] = {"error": 99}
    summary["systems"]["A"]["refusal_suspected_heuristic"] = 99
    summary["systems"]["A"]["tool_calls"] = 999
    (store.root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")

    report = verify_run(store, require_complete=True)
    assert not report.ok, (
        "summary 的状态计数/拒答计数/工具调用数与记录复算不符，verify 仍判通过：报告的头条数字没有任何独立对照"
    )
    assert any("summary" in item for item in report.violations), report.violations


async def test_config_tamper_with_recomputed_hashes_must_be_caught_by_the_frozen_copy(
    tmp_path: Path, settings_for_tests: Any
) -> None:
    """重算派生 hash 仍不能掩盖配置与冻结副本的漂移。"""
    store = await _complete_run(tmp_path, run_id="carebench-unchecked-freeze-binding", settings=settings_for_tests)
    assert verify_run(store, require_complete=True).ok, "正控：干净批次必须通过"
    frozen_before = json.loads((store.freeze_path).read_text(encoding="utf-8"))

    manifest = store.read_manifest()
    manifest["config"]["max_outer_retries"] = 5
    new_config_sha = sha256_value(manifest["config"])
    manifest["config_sha256"] = new_config_sha
    new_batch_id = batch_fingerprint(
        dataset_sha256=manifest["dataset"]["sha256"],
        config_sha256=new_config_sha,
        code_commit=manifest["code"]["commit"],
    )
    manifest["batch_id"] = new_batch_id
    store.write_manifest(manifest)

    def _retag(records: list[dict[str, Any]]) -> None:
        for record in records:
            record["batch_id"] = new_batch_id

    _rewrite_records(store, _retag)

    report = verify_run(store, require_complete=True)
    assert not report.ok, (
        "配置（max_outer_retries 1→5）被改并补齐 config_sha256/batch_id 后 verify 仍判通过："
        f"run 目录的 freeze.json 仍记着原配置 {frozen_before['config_sha256'][:12]}…，"
        "但没有任何检查使用它作为独立对照"
    )
    assert any("config" in item or "freeze" in item for item in report.violations), report.violations


async def test_emptied_status_flags_must_be_rejected(tmp_path: Path, settings_for_tests: Any) -> None:
    """删除状态标记也必须失败，不能因缺键绕过一致性核验。"""
    store = await _complete_run(tmp_path, run_id="carebench-unchecked-flags", settings=settings_for_tests)
    assert verify_run(store, require_complete=True).ok, "正控：干净批次必须通过"

    def _blank(records: list[dict[str, Any]]) -> None:
        for record in records:
            record["status_flags"] = {}

    _rewrite_records(store, _blank)

    report = verify_run(store, require_complete=True)
    assert not report.ok, (
        "status_flags 被清空后 verify 仍判通过：自洽核对只在键存在时才执行，"
        "删键即可让「四处口径同一」失效（summary 的拒答/空输出计数也随之归零）"
    )
    assert any("status_flags" in item for item in report.violations), report.violations
