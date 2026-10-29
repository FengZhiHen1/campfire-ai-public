"""独立终审（2026-10-29）发现的证据核对缺口：**当前预期为红**。

三个缺口都属同一形态——`verify` 的注释/文档宣称核对了某项，实现里却没有与
「别处的独立事实」对照，于是「改完再补 hash」的篡改一路通过：

1. `summary.json` 的 `completion_status_counts` / `refusal_suspected_heuristic` /
   `tool_calls` 从不与记录复算对照（`verify._check_summary` 的文档写明核「状态计数」）；
2. run 目录里 `freeze.json` 的 `config_sha256`（以及 `code`）从不与 `manifest` 对照，
   于是把配置（例如 `max_outer_retries` 1→5）改大并补齐派生 hash 后仍判通过，
   而重试预算检查正是读这份被改过的配置；
3. `verify._check_status_consistency` 只在 `status_flags` **缺键时静默跳过**
   （`if name in flags`），把 `status_flags` 清空即绕过「四处口径同一」的核对。

这些用例断言的是「篡改必须被拒」，因此**修复前必红**；它们不是永远失败的检查：
每条都先断言干净批次通过（正控），失败只可能来自篡改未被识别。
"""

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
    """summary 的完成/失败计数被改，verify 必须判违反（它是报告里的头条数字）。

    缺口：`verify._check_summary` 只核对分母、`case_groups` 与故障观察统计，
    `completion_status_counts` / `refusal_suspected_heuristic` / `tool_calls` 一律不看，
    尽管函数文档写明核「状态计数」。影响：把全成功改写成全失败（或反之）不需要动任何
    记录就能让证据包判「通过」。
    """
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
    """配置被改大（重试预算 1→5）并补齐派生 hash 后，必须由 run 目录的 freeze.json 认出。

    缺口：`verify._check_cases` 只把 run 目录 `freeze.json` 的 `dataset_sha256` /
    `cases_sha256` 与案例文件对照，从不把 `freeze.json.config_sha256`（以及 `code`）
    与 `manifest.config_sha256` 对照。而 `manifest.config` 的 hash 是**自证**的
    （`config_sha256 = sha256(config)`），`batch_id` 又由它派生，记录里的 `batch_id`
    同样可以重算——于是「预算 1→5」这一步不留痕迹。

    影响：`verify._check_retry_and_sessions` 的预算取自这份配置，
    `budget = 1 + config.max_outer_retries`；抬高它之后，超出真实预算的尝试记录全部合法。
    """
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
    """把 `status_flags` 清空（重算记录 hash）必须判违反，而不是静默跳过。

    缺口：`verify._check_status_consistency` 的判据写成
    `if name in flags and bool(flags[name]) is not bool(expected)`——**缺键不报**。
    于是「raw / structured / output_text / flags 四处口径同一」这条承诺可以用删键绕过；
    而 `summarize._system_stats` 的拒答数与空输出数正是从这份 flags 读的。
    """
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
