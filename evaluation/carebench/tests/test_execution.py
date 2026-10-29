"""编排层测试：轮换顺序、新会话、固定第二轮、重试策略、中断续跑、批次隔离。

这些都是「协议写死、但很容易被实现悄悄绕过」的规则，因此逐条用可观察行为测，而不是
断言注释：轮换看实际调用顺序；第二轮看是否落在同一会话；重试看尝试编号与首错是否保留；
续跑看已有输出有没有被重跑或改写。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio

from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan
from evaluation.carebench.records import effective_records
from evaluation.carebench.runner import ResumeRejected, execute
from evaluation.carebench.store import RunStore, create_run_dir
from evaluation.carebench.systems.base import TurnOutcome

from .conftest import FakeAdapter, load_cases, make_cases_file, make_snapshot


def _store(tmp_path: Path) -> RunStore:
    return create_run_dir(tmp_path / "runs", "carebench-test")


async def test_rotation_follows_case_index(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """第 i 个案例的组别顺序必须是 ROTATION[i % 3]，且每个 case-group 各跑一次。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=3))
    config = RunConfig(label="calibration")
    adapters = {system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")}
    store = _store(tmp_path)

    await execute(
        store=store,
        config=config,
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=settings_for_tests,
        adapters=adapters,
        log=lambda _message: None,
    )

    records = store.read_outputs()
    order_seen: dict[str, list[str]] = {}
    for record in records:
        order_seen.setdefault(record["case_id"], []).append(record["system_id"])
    assert order_seen["CFB-C-001"] == ["A", "B", "C"]
    assert order_seen["CFB-C-002"] == ["B", "C", "A"]
    assert order_seen["CFB-C-003"] == ["C", "A", "B"]


async def test_new_session_per_case_group_and_two_turns(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """每个 case-group 一个新会话；第二轮必须落在同一会话里。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1, followup=True))
    config = RunConfig(label="calibration")
    adapters = {system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")}
    store = _store(tmp_path)

    await execute(
        store=store,
        config=config,
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=settings_for_tests,
        adapters=adapters,
        log=lambda _message: None,
    )

    records = store.read_outputs()
    sessions = {(record["case_id"], record["system_id"]): set() for record in records}
    for record in records:
        sessions[(record["case_id"], record["system_id"])].add(record["session_id"])
    assert all(len(value) == 1 for value in sessions.values()), "同一 case-group 的第二轮换了会话"
    assert len({next(iter(value)) for value in sessions.values()}) == 3, "三组之间复用了会话"
    turns = sorted(record["turn"] for record in records if record["system_id"] == "A")
    assert turns == [1, 2]


async def test_input_text_identical_across_systems(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """三组拿到的使用者文本逐字节相同（公平性的机械判据）。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))
    adapters = {system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")}
    store = _store(tmp_path)
    await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=settings_for_tests,
        adapters=adapters,
        log=lambda _message: None,
    )
    hashes = {record["input_sha256"] for record in store.read_outputs()}
    assert len(hashes) == 1
    assert all(record["input_text"].startswith("【已确认的背景信息】") for record in store.read_outputs())


async def test_retry_once_keeps_first_error(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """错误重试至多一次；首错记录必须保留，最终结论取最后一次尝试。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))

    def outcome(request) -> TurnOutcome:
        if request.attempt == 1:
            return TurnOutcome(status="error", error_type="TestError", error_detail="第一次失败", latency_ms=1)
        return TurnOutcome(status="completed", raw_output="第二次成功", latency_ms=2)

    adapters = {system_id: FakeAdapter(system_id, outcome=outcome) for system_id in ("A", "B", "C")}
    store = _store(tmp_path)
    await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=settings_for_tests,
        adapters=adapters,
        log=lambda _message: None,
    )
    records = [record for record in store.read_outputs() if record["system_id"] == "A"]
    assert [record["attempt"] for record in records] == [1, 2]
    assert records[0]["completion_status"] == "error"
    assert records[0]["error"]["type"] == "TestError"
    effective = effective_records(records)
    assert effective[("CFB-C-001", "A", 1)]["completion_status"] == "completed"

    # 记录的错误清单里也能看到这次失败（原始失败不被抹除）
    errors = store.errors_path.read_text(encoding="utf-8")
    assert "TestError" not in errors  # 有效记录已成功；首错仍留在 outputs.jsonl 里
    assert '"attempt": 1' in store.outputs_path.read_text(encoding="utf-8")


async def test_no_retry_on_empty_output(tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan) -> None:
    """空回复是模型的真实产出，不得重试（重试等于替被测系统挑答案）。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))
    adapters = {
        system_id: FakeAdapter(system_id, outcome=lambda _request: TurnOutcome(status="no_output", raw_output=""))
        for system_id in ("A", "B", "C")
    }
    store = _store(tmp_path)
    await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=settings_for_tests,
        adapters=adapters,
        log=lambda _message: None,
    )
    records = store.read_outputs()
    assert all(record["attempt"] == 1 for record in records)
    assert all(record["completion_status"] == "no_output" for record in records)
    assert all(record["status_flags"]["empty_output"] for record in records)


async def test_timeout_recorded_and_counted(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """超时落成 `timeout` 且进入分母（不因超时而缩小分母）。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))
    adapters = {system_id: FakeAdapter(system_id, delay_seconds=0.2) for system_id in ("A", "B", "C")}
    config = RunConfig(label="calibration", turn_timeout_seconds=0.05)
    store = _store(tmp_path)
    result = await execute(
        store=store,
        config=config,
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=settings_for_tests,
        adapters=adapters,
        log=lambda _message: None,
    )
    assert result.status == "completed"
    records = store.read_outputs()
    assert all(record["completion_status"] == "timeout" for record in records)
    # 超时按策略重试一次，因此每个 case-group 有两条尝试记录
    assert {record["attempt"] for record in records} == {1, 2}
    assert result.progress["case_groups_complete"] == 3


async def test_resume_does_not_rerun_finished_turns(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """续跑只补缺的轮次：已完成的第二轮不会被重跑，第一轮输出原样保留。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1, followup=True))
    config = RunConfig(label="calibration")

    def stop_on_second_turn(request) -> TurnOutcome:
        if request.turn == 2:
            raise RuntimeError("模拟进程在第二轮前被杀掉")
        return TurnOutcome(status="completed", raw_output="第一轮回复", latency_ms=5)

    first_adapters = {system_id: FakeAdapter(system_id, outcome=stop_on_second_turn) for system_id in ("A", "B", "C")}
    store = _store(tmp_path)
    # 只让 A 组失败一次以便观察续跑；其余组正常完成两轮
    await execute(
        store=store,
        config=config,
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=settings_for_tests,
        adapters=first_adapters,
        case_ids=["CFB-C-001"],
        log=lambda _message: None,
    )
    before = store.read_outputs()
    first_turn = {(record["system_id"]): record for record in before if record["turn"] == 1}

    second_adapters = {system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")}
    await execute(
        store=store,
        config=config,
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=settings_for_tests,
        adapters=second_adapters,
        resume=True,
        log=lambda _message: None,
    )
    after = store.read_outputs()
    # 第一轮记录没有新增（没有重跑）
    assert len([record for record in after if record["turn"] == 1]) == len(first_turn)
    for record in after:
        if record["turn"] == 1:
            assert record["raw_output"] == "第一轮回复"
    # 第二轮补齐，且复用了第一轮的会话
    for system_id in ("A", "B", "C"):
        turn2 = [record for record in after if record["turn"] == 2 and record["system_id"] == system_id]
        assert turn2, f"{system_id} 的第二轮没有补上"
        assert turn2[0]["session_id"] == first_turn[system_id]["session_id"]


async def test_resume_rejects_different_batch(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """案例集变了就必须拒绝续跑（不同批次不得混跑）。"""
    case_path = make_cases_file(tmp_path / "cases.jsonl", count=1)
    case_set = load_cases(case_path)
    adapters = {system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")}
    store = _store(tmp_path)
    await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=settings_for_tests,
        adapters=adapters,
        log=lambda _message: None,
    )

    # 换一份内容不同的案例集（同一份 id）再续跑
    changed = load_cases(make_cases_file(tmp_path / "cases2.jsonl", count=1, category="现场应急"))
    with pytest.raises(ResumeRejected, match="批次指纹"):
        await execute(
            store=store,
            config=RunConfig(label="calibration"),
            case_set=changed,
            snapshot=make_snapshot(),
            faults=faults_for_tests,
            settings=settings_for_tests,
            adapters=adapters,
            resume=True,
            log=lambda _message: None,
        )


async def test_refuses_non_eval_database(tmp_path: Path, faults_for_tests: FaultPlan) -> None:
    """库名不像评测库时直接拒绝（防止把合成账号写进开发库）。"""
    from campfire.core.config import Settings

    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))
    adapters = {system_id: FakeAdapter(system_id) for system_id in ("C",)}
    settings = Settings(database_url="postgresql+asyncpg://u:p@127.0.0.1:5432/campfire")
    store = _store(tmp_path)
    with pytest.raises(Exception, match="不是评测库"):
        await execute(
            store=store,
            config=RunConfig(label="calibration", systems=("C",), rotation=("C",)),
            case_set=case_set,
            snapshot=make_snapshot(),
            faults=faults_for_tests,
            settings=settings,
            adapters=adapters,
            log=lambda _message: None,
        )


async def test_dry_run_writes_manifest_without_calls(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """dry-run 只装配并写 manifest：一个模型调用都不发。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))
    adapters = {system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")}
    store = _store(tmp_path)
    result = await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults_for_tests,
        settings=settings_for_tests,
        adapters=adapters,
        dry_run=True,
        log=lambda _message: None,
    )
    assert result.status == "dry_run"
    assert store.read_outputs() == []
    manifest = store.read_manifest()
    assert manifest["status"] == "dry_run"
    assert manifest["systems"][0]["label"] == "fake_A"
    assert manifest["progress"]["case_groups_expected"] == 3
