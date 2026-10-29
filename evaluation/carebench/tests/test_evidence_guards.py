"""证据护栏：**重算记录 hash 之后**的篡改仍然必须被拒绝。

记录自带的 `record_sha256` 只能证明「这一行没被随手改过」。把所有内容改完再重算 hash，
它就不再有任何证明力——所以每条检查都必须与别处的独立事实对照（运行身份、原始载荷、
轨迹、评审包、配置预算）。这组用例逐条钉住这些对照关系：既证明篡改会被抓到，也证明
干净批次不会被这些断言误杀。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan, load_plan
from evaluation.carebench.freeze import FreezeError, freeze_cases
from evaluation.carebench.hashing import sha256_value
from evaluation.carebench.manifest import identity_fingerprint, runtime_identity
from evaluation.carebench.render import project
from evaluation.carebench.review import export_packet
from evaluation.carebench.runner import execute
from evaluation.carebench.store import RunStore, create_run_dir
from evaluation.carebench.summarize import summarize_run
from evaluation.carebench.systems.base import RETRY_NEW_SESSION, TurnOutcome
from evaluation.carebench.verify import verify_run

from .conftest import FakeAdapter, load_cases, make_cases_file, make_snapshot


def _fixtures_file(tmp_path: Path) -> Path:
    """B 组检索为空、C 组工具不可用的注入计划。"""
    path = tmp_path / "fixtures.json"
    path.write_text(
        json.dumps({"cases": {"CFB-C-001": ["tool_search_unavailable", "retrieval_empty"]}}),
        encoding="utf-8",
    )
    return path


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


async def _run(
    tmp_path: Path,
    *,
    settings: Any,
    faults: FaultPlan | None = None,
    outcome: Callable[[Any], TurnOutcome] | None = None,
    count: int = 1,
    run_id: str = "carebench-guards",
) -> RunStore:
    """跑一个最小批次（三组，可用脚本化结局）。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=count))
    adapters = {
        system_id: FakeAdapter(system_id, outcome=outcome) if outcome else FakeAdapter(system_id)
        for system_id in ("A", "B", "C")
    }
    store = create_run_dir(tmp_path / "runs", run_id)
    await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults or FaultPlan(requested={}),
        settings=settings,
        adapters=adapters,
        log=lambda _message: None,
    )
    return store


@pytest.mark.asyncio
async def test_clean_run_with_fixtures_passes_all_guards(tmp_path: Path, settings_for_tests: Any) -> None:
    """有故障注入的干净批次也必须能通过：护栏不能是「永远失败」的检查。"""
    plan = load_plan(_fixtures_file(tmp_path))
    store = await _run(tmp_path, settings=settings_for_tests, faults=plan, run_id="carebench-clean-fixtures")
    export_packet(store, log=lambda _message: None)
    summarize_run(store, log=lambda _message: None)
    report = verify_run(store, require_complete=True)
    assert report.ok, report.violations


@pytest.mark.asyncio
async def test_recomputed_hash_cannot_hide_projection_mismatch(tmp_path: Path, settings_for_tests: Any) -> None:
    """改投影（重算 hash）仍被拒：投影必须能由原始正文 + 结构化载荷重算出来。"""
    store = await _run(tmp_path, settings=settings_for_tests, run_id="carebench-projection")

    def mutate(records: list[dict[str, Any]]) -> None:
        records[0]["output_text"] = "偷偷改过的正文（评审只能看到这个）"

    _rewrite_records(store, mutate)
    report = verify_run(store)
    assert not report.ok
    assert any("规范文本投影" in item for item in report.violations), report.violations


@pytest.mark.asyncio
async def test_recomputed_hash_cannot_hide_packet_mismatch(tmp_path: Path, settings_for_tests: Any) -> None:
    """同时改原始载荷与投影（自洽且重算 hash）仍被拒：评审包里的内容对不上原始记录。"""
    store = await _run(tmp_path, settings=settings_for_tests, run_id="carebench-packet")
    export_packet(store, log=lambda _message: None)

    def mutate(records: list[dict[str, Any]]) -> None:
        for record in records:
            record["structured_output"] = [{"kind": "action_card", "card_id": "fake", "title": "事后补的卡"}]
            record["output_text"] = project(str(record.get("raw_output") or ""), record["structured_output"])

    _rewrite_records(store, mutate)
    report = verify_run(store)
    assert not report.ok
    packet_hits = [item for item in report.violations if "评审包" in item and "原始记录" in item]
    assert packet_hits, report.violations


@pytest.mark.asyncio
async def test_recomputed_hash_cannot_hide_uncalled_fixture(tmp_path: Path, settings_for_tests: Any) -> None:
    """把「装上但没被调用」写成「观察到」（重算 hash）会被 tool_calls/轨迹复算抓住。"""
    plan = load_plan(_fixtures_file(tmp_path))
    store = await _run(tmp_path, settings=settings_for_tests, faults=plan, run_id="carebench-fixture-lie")

    def mutate(records: list[dict[str, Any]]) -> None:
        for record in records:
            if record["system_id"] != "C":
                continue
            for item in record["fixtures"]:
                if item["name"] == "tool_search_unavailable":
                    item["observed"] = True
                    item["observed_calls"] = 1

    _rewrite_records(store, mutate)
    report = verify_run(store)
    assert not report.ok
    assert any("observed_calls" in item or "「装上」不等于「观察到」" in item for item in report.violations), (
        report.violations
    )


@pytest.mark.asyncio
async def test_recomputed_hash_cannot_hide_retry_budget_overflow(tmp_path: Path, settings_for_tests: Any) -> None:
    """把一次尝试改成第 3 次（重算 hash）会被预算与连续性检查抓住。"""

    def outcome(request: Any) -> TurnOutcome:
        if request.attempt == 1:
            return TurnOutcome(status="error", error_type="TestError", latency_ms=1)
        return TurnOutcome(status="completed", raw_output="成功", latency_ms=2)

    store = await _run(tmp_path, settings=settings_for_tests, outcome=outcome, run_id="carebench-budget")

    def mutate(records: list[dict[str, Any]]) -> None:
        for record in records:
            if record["system_id"] == "A" and record["attempt"] == 2:
                record["attempt"] = 3
                record["retry"]["attempt"] = 3

    _rewrite_records(store, mutate)
    report = verify_run(store)
    assert not report.ok
    assert any("尝试序号" in item or "超过预算" in item for item in report.violations), report.violations


@pytest.mark.asyncio
async def test_recomputed_hash_cannot_hide_in_place_retry_on_dirty_session(
    tmp_path: Path, settings_for_tests: Any
) -> None:
    """把换会话的重试改成原地重试（重算 hash）会被「同轮输入重复」检查抓住。"""

    def outcome(request: Any) -> TurnOutcome:
        if request.attempt == 1:
            return TurnOutcome(
                status="error",
                error_type="SessionWriteFailure",
                latency_ms=1,
                retry_safety=RETRY_NEW_SESSION,
            )
        return TurnOutcome(status="completed", raw_output="成功", latency_ms=2)

    store = await _run(tmp_path, settings=settings_for_tests, outcome=outcome, run_id="carebench-session")
    records = [record for record in store.read_outputs() if record["system_id"] == "A"]
    first_session = records[0]["session_id"]

    def mutate(payloads: list[dict[str, Any]]) -> None:
        for payload in payloads:
            if payload["system_id"] == "A" and payload["attempt"] == 2:
                payload["session_id"] = first_session

    _rewrite_records(store, mutate)
    report = verify_run(store)
    assert not report.ok
    assert any("重复发送了同一轮使用者输入" in item for item in report.violations), report.violations


@pytest.mark.asyncio
async def test_recomputed_identity_cannot_hide_model_swap(tmp_path: Path, settings_for_tests: Any) -> None:
    """把身份段与记录绑定一起改并重算（hash 自洽）仍被拒：与 manifest 其它事实对不上。"""
    store = await _run(tmp_path, settings=settings_for_tests, run_id="carebench-identity-swap")
    manifest = store.read_manifest()
    manifest["run_identity"]["model_id"] = "another-model"
    new_sha = identity_fingerprint(manifest["run_identity"])
    manifest["run_identity_sha256"] = new_sha
    store.write_manifest(manifest)

    def mutate(records: list[dict[str, Any]]) -> None:
        for record in records:
            record["run_identity_sha256"] = new_sha

    _rewrite_records(store, mutate)
    report = verify_run(store)
    assert not report.ok
    assert any("运行身份与 inference.model_id 不一致" in item for item in report.violations), report.violations
    assert any("装配模型" in item for item in report.violations), report.violations


@pytest.mark.asyncio
async def test_hand_edited_blind_map_is_rejected(tmp_path: Path, settings_for_tests: Any) -> None:
    """盲化映射必须由 review_seed 派生：手工交换两个组别会让评分记到别的系统上。"""
    store = await _run(tmp_path, settings=settings_for_tests, run_id="carebench-blindmap")
    export_packet(store, log=lambda _message: None)
    map_path = store.review_dir / "blind-map.json"
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    per_case = next(iter(mapping["map"].values()))
    blind_ids = sorted(per_case)
    per_case[blind_ids[0]], per_case[blind_ids[1]] = per_case[blind_ids[1]], per_case[blind_ids[0]]
    map_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    report = verify_run(store)
    assert not report.ok
    assert any("不是由 review_seed 派生" in item for item in report.violations), report.violations


@pytest.mark.asyncio
async def test_manifest_fault_counts_must_match_records(tmp_path: Path, settings_for_tests: Any) -> None:
    """跑满的批次里，manifest 的注入统计被改大就会被复算抓住。"""
    plan = load_plan(_fixtures_file(tmp_path))
    store = await _run(tmp_path, settings=settings_for_tests, faults=plan, run_id="carebench-counts")
    manifest = store.read_manifest()
    manifest["fault_injection"]["applied_counts"]["tool_search_unavailable"] = 3
    store.write_manifest(manifest)
    report = verify_run(store)
    assert not report.ok
    assert any("manifest.fault_injection 与记录复算不一致" in item for item in report.violations), report.violations


@pytest.mark.asyncio
async def test_summary_distinguishes_installed_from_observed(tmp_path: Path, settings_for_tests: Any) -> None:
    """汇总必须分开「装上替身」与「真的观察到」：C 组不调用工具时计入 installed_but_uncalled。"""
    plan = load_plan(_fixtures_file(tmp_path))
    store = await _run(tmp_path, settings=settings_for_tests, faults=plan, run_id="carebench-observed-summary")
    summary = summarize_run(store, log=lambda _message: None)
    bucket = summary["fault_injection_observation"]["by_fixture"]["tool_search_unavailable"]
    assert bucket["applied"] == 1
    assert bucket["observed"] == 0
    assert bucket["installed_but_uncalled"] == 1
    markdown = (store.root / "summary.md").read_text(encoding="utf-8")
    assert "装上但没被调用" in markdown
    assert verify_run(store).ok, verify_run(store).violations


@pytest.mark.asyncio
async def test_verify_rejects_tampered_summary_observation(tmp_path: Path, settings_for_tests: Any) -> None:
    """summary 把「没观察到」改成「观察到」必须判违反（不得由程序补出观察结果）。"""
    plan = load_plan(_fixtures_file(tmp_path))
    store = await _run(tmp_path, settings=settings_for_tests, faults=plan, run_id="carebench-summary-lie")
    summary = summarize_run(store, log=lambda _message: None)
    bucket = summary["fault_injection_observation"]["by_fixture"]["tool_search_unavailable"]
    bucket["observed"] = 1
    bucket["installed_but_uncalled"] = 0
    (store.root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    report = verify_run(store)
    assert not report.ok
    assert any("故障观察统计" in item for item in report.violations), report.violations


@pytest.mark.asyncio
async def test_summary_separates_unsupported_and_out_of_harness(tmp_path: Path, settings_for_tests: Any) -> None:
    """未支持与越界必须各自成桶：不能都写成「因该组没有注入点而未实施」。"""
    path = tmp_path / "fixtures.json"
    path.write_text(
        json.dumps({"cases": {"CFB-C-001": ["tool_timeout", "client_render_fault"]}}),
        encoding="utf-8",
    )
    plan = load_plan(path)
    store = await _run(tmp_path, settings=settings_for_tests, faults=plan, run_id="carebench-unsupported")
    summary = summarize_run(store, log=lambda _message: None)
    injection = summary["fault_injection"]
    assert injection["unsupported_counts"] == {"tool_timeout": 3}
    assert injection["out_of_harness_counts"] == {"client_render_fault": 3}
    assert injection["not_applicable_counts"] == {}
    buckets = summary["fault_injection_observation"]["by_fixture"]
    assert buckets["tool_timeout"]["unsupported"] == 3
    assert buckets["client_render_fault"]["out_of_harness"] == 3
    markdown = (store.root / "summary.md").read_text(encoding="utf-8")
    assert "未支持" in markdown and "这一类没测成" in markdown
    report = verify_run(store)
    assert report.ok, report.violations


@pytest.mark.asyncio
async def test_run_refuses_identity_that_differs_from_freeze(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """冻结时锁定的身份与当前环境不同 → 拒绝运行（不是「照跑并记一笔」）。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))
    frozen_identity = runtime_identity(settings_for_tests, make_snapshot(), RunConfig())
    frozen_identity["model_id"] = "model-from-freeze"
    store = create_run_dir(tmp_path / "runs", "carebench-freeze-identity")
    with pytest.raises(ValueError, match="冻结时锁定的身份"):
        await execute(
            store=store,
            config=RunConfig(label="calibration"),
            case_set=case_set,
            snapshot=make_snapshot(),
            faults=faults_for_tests,
            settings=settings_for_tests,
            adapters={system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")},
            expected_identity=frozen_identity,
            log=lambda _message: None,
        )
    assert store.read_outputs() == []


@pytest.mark.asyncio
async def test_resume_keeps_freeze_binding(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """续跑不得把「跑在锁定身份上」这条证据洗掉（补齐轮次后仍需可核对）。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=2))
    identity = runtime_identity(settings_for_tests, make_snapshot(), RunConfig(label="calibration"))
    store = create_run_dir(tmp_path / "runs", "carebench-resume-binding")

    def adapters() -> dict[str, FakeAdapter]:
        return {system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")}

    await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=settings_for_tests,
        adapters=adapters(),
        case_ids=["CFB-C-001"],
        expected_identity=identity,
        log=lambda _message: None,
    )
    await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=settings_for_tests,
        adapters=adapters(),
        resume=True,
        log=lambda _message: None,
    )
    manifest = store.read_manifest()
    assert manifest["freeze_binding"]["identity_locked"] is True
    assert manifest["freeze_binding"]["frozen_identity_sha256"] == identity_fingerprint(identity)
    assert manifest["run_identity_sha256"] == identity_fingerprint(identity)
    summarize_run(store, log=lambda _message: None)
    assert verify_run(store, require_complete=True).ok


def test_formal_freeze_requires_locked_identity(tmp_path: Path) -> None:
    """正式冻结必须锁定运行身份：只绑案例与配置时，formal 成绩无法证明跑的是计划里的模型。"""
    cases = make_cases_file(tmp_path / "cases.jsonl", count=1)
    with pytest.raises(FreezeError, match="锁定运行身份"):
        freeze_cases(cases_path=cases, label="test", out_dir=tmp_path / "frozen", config=RunConfig())
    with pytest.raises(FreezeError, match="身份指纹"):
        freeze_cases(
            cases_path=cases,
            label="calibration",
            out_dir=tmp_path / "frozen-cal",
            config=RunConfig(),
            identity={"model_id": "m"},
            identity_sha256="0" * 64,
        )


def test_refreeze_with_other_identity_is_refused(tmp_path: Path, settings_for_tests: Any) -> None:
    """身份属于冻结条件：同一目录换一份身份再冻结必须拒绝，不改写原记录。"""
    cases = make_cases_file(tmp_path / "cases.jsonl", count=1)
    identity = runtime_identity(settings_for_tests, make_snapshot(), RunConfig(label="calibration"))
    out = tmp_path / "frozen-identity"
    frozen = freeze_cases(
        cases_path=cases,
        label="calibration",
        out_dir=out,
        config=RunConfig(),
        identity=identity,
        identity_sha256=identity_fingerprint(identity),
    )
    assert frozen.run_identity_sha256 == identity_fingerprint(identity)

    other = {**identity, "model_id": "another-model"}
    with pytest.raises(FreezeError, match="另一组实验条件"):
        freeze_cases(
            cases_path=cases,
            label="calibration",
            out_dir=out,
            config=RunConfig(),
            identity=other,
            identity_sha256=identity_fingerprint(other),
        )
    record = json.loads((out / "freeze.json").read_text(encoding="utf-8"))
    assert record["run_identity_sha256"] == identity_fingerprint(identity)
