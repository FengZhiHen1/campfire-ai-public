"""评审包、评分导入与汇总的测试：盲化、拒收 pending、无评审不出分、分母完整。"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio

from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan
from evaluation.carebench.review import (
    EMPTY_RATINGS_FILE,
    MAP_FILE,
    PACKET_FILE,
    ReviewError,
    export_packet,
    import_ratings,
)
from evaluation.carebench.runner import execute
from evaluation.carebench.store import RunStore, create_run_dir
from evaluation.carebench.summarize import summarize_run
from evaluation.carebench.systems.base import TurnOutcome

from .conftest import FakeAdapter, load_cases, make_cases_file, make_snapshot


async def _finished_run(
    tmp_path: Path,
    *,
    settings: Any,
    faults: FaultPlan,
    count: int = 2,
    followup: bool = False,
    outcome_by_system: dict[str, TurnOutcome] | None = None,
) -> RunStore:
    """跑一个全部成功的批次（用于评审与汇总测试）。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=count, followup=followup))
    adapters = {}
    for system_id in ("A", "B", "C"):
        fixed = (outcome_by_system or {}).get(system_id)
        adapters[system_id] = FakeAdapter(
            system_id,
            outcome=(
                lambda _request, text=f"{system_id} 组的回复": TurnOutcome(
                    status="completed",
                    raw_output=fixed.raw_output if fixed else text,
                    latency_ms=100,
                    usage={"requests": 1, "input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
                )
            ),
        )
    store = create_run_dir(tmp_path / "runs", "carebench-review")
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


async def test_packet_is_blinded_and_template_is_empty(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """评审包不含组别标识；评分表除客观事实外全空。"""
    store = await _finished_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests, count=1)
    report = export_packet(store, log=lambda _message: None)
    assert report["exported_at_groups"] == 3

    packet = (store.review_dir / PACKET_FILE).read_text(encoding="utf-8")
    assert '"system_id"' not in packet
    for line in packet.splitlines():
        payload = json.loads(line)
        assert set(payload) == {
            "blind_id",
            "case_id",
            "completion_status",
            "turns",
            "final_output",
            "structured_output",
        }

    mapping = json.loads((store.review_dir / MAP_FILE).read_text(encoding="utf-8"))
    assert "不得交给评审者" in mapping["warning"]
    assert sorted(next(iter(mapping["map"].values())).values()) == ["A", "B", "C"]

    rows = list(csv.DictReader(io.StringIO((store.review_dir / EMPTY_RATINGS_FILE).read_text(encoding="utf-8"))))
    assert len(rows) == 3 * 2  # 3 个 case-group × 计划 2 位评分者
    for row in rows:
        assert row["rater_id"] == ""
        assert row["critical_failure"] == ""
        assert row["c1_context"] == ""
        assert row["c5_clarity"] == ""
        assert row["adjudication_status"] == "pending"
        assert row["latency_ms"] == "100"
        assert row["completion_status"] == "completed"


async def test_import_rejects_pending_and_blank_scores(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """`pending`/空分一律拒收——pending 绝不能算通过。"""
    store = await _finished_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests, count=1)
    export_packet(store, log=lambda _message: None)

    rows = _blank_rows(store)
    rows[0]["rater_id"] = "r1"
    rows[0]["critical_failure"] = "pending"
    for column in ("c1_context", "c2_action", "c3_evidence", "c4_boundary", "c5_clarity"):
        rows[0][column] = "1"
    rows[0]["required_checks_applicable"] = "1"
    rows[0]["required_checks_passed"] = "1"
    path = tmp_path / "ratings.csv"
    _write_csv(path, rows)
    with pytest.raises(ReviewError, match="pending"):
        import_ratings(store, ratings_path=path, log=lambda _message: None)

    rows[0]["critical_failure"] = "no"
    rows[0]["c2_action"] = ""
    _write_csv(path, rows)
    with pytest.raises(ReviewError, match="c2_action 为空"):
        import_ratings(store, ratings_path=path, log=lambda _message: None)


async def test_import_validates_checks_and_duplicates(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """关键约束计数与重复行都要校验（passed 不得大于 applicable）。"""
    store = await _finished_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests, count=1)
    export_packet(store, log=lambda _message: None)
    rows = _filled_rows(store, raters=("r1", "r2"))
    rows[0]["required_checks_applicable"] = "2"
    rows[0]["required_checks_passed"] = "3"
    path = tmp_path / "ratings.csv"
    _write_csv(path, rows)
    with pytest.raises(ReviewError, match="required_checks_passed"):
        import_ratings(store, ratings_path=path, log=lambda _message: None)

    rows = _filled_rows(store, raters=("r1", "r2"))
    rows.append(dict(rows[0]))
    _write_csv(path, rows)
    with pytest.raises(ReviewError, match="重复"):
        import_ratings(store, ratings_path=path, log=lambda _message: None)


async def test_summary_without_ratings_has_no_scores(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """没有人工评分时只出计数/时延/token，`human_scores` 必须是 None。"""
    store = await _finished_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests, count=2)
    summary = summarize_run(store, log=lambda _message: None)
    assert summary["human_scores"] is None
    assert "未导入人工评分" in summary["human_scores_note"]
    assert summary["denominators"]["case_groups_expected"] == 6
    assert summary["systems"]["A"]["case_groups"] == 2
    assert summary["systems"]["A"]["latency_ms"]["p50"] == 100
    assert summary["systems"]["A"]["tokens"]["input"] == 20
    markdown = (store.root / "summary.md").read_text(encoding="utf-8")
    assert "未导入人工评分" in markdown
    assert "总分均值" not in markdown


async def test_summary_with_ratings_reports_hard_failures_separately(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """导入评分后：硬失败单独计数，needs_review 不算通过，配对比较有分母。"""
    store = await _finished_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests, count=1)
    export_packet(store, log=lambda _message: None)
    rows = _filled_rows(store, raters=("r1", "r2"), needs_review_systems={"C"})
    path = tmp_path / "ratings.csv"
    _write_csv(path, rows)
    result = import_ratings(store, ratings_path=path, log=lambda _message: None)
    assert result.mode == "double_blind"

    summary = summarize_run(store, log=lambda _message: None)
    human = summary["human_scores"]
    assert human is not None
    c_stats = human["per_system"]["C"]
    assert c_stats["critical_failure_counts"]["needs_review"] == 2  # 两位评分者各一行
    assert c_stats["critical_failure_counts"]["no"] == 0
    assert human["per_system"]["A"]["quality_score"]["mean"] == 10.0  # 五维各 2 分
    assert human["per_system"]["C"]["quality_score"]["mean"] == 5.0  # 五维各 1 分
    assert human["paired"]["A_vs_C"]["total_pairs"] == 1
    assert human["agreement"]["dimensions"]["c1_context"]["exact_agreement"] == 1.0
    assert summary["review_state"] == "ratings_imported"


def _blank_rows(store: RunStore) -> list[dict[str, str]]:
    """读空评分表为字典列表。"""
    text = (store.review_dir / EMPTY_RATINGS_FILE).read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def _filled_rows(
    store: RunStore,
    *,
    raters: tuple[str, ...] = ("r1",),
    needs_review_systems: set[str] | None = None,
) -> list[dict[str, str]]:
    """把空评分表填成一组合法评分（每位评分者一套），返回行列表。"""
    mapping = json.loads((store.review_dir / MAP_FILE).read_text(encoding="utf-8"))
    blind_to_system = {blind: system for per_case in mapping["map"].values() for blind, system in per_case.items()}
    blanks = _blank_rows(store)
    # 每个 blind_id 只保留一行作为模板，再按评分者复制
    templates = {}
    for row in blanks:
        templates.setdefault(row["blind_id"], row)
    rows: list[dict[str, str]] = []
    for blind_id, template in templates.items():
        system = blind_to_system[blind_id]
        critical = "needs_review" if needs_review_systems and system in needs_review_systems else "no"
        for rater in raters:
            row = dict(template)
            row["rater_id"] = rater
            row["critical_failure"] = critical
            row["failure_type"] = "" if critical == "no" else "other_critical"
            for column in ("c1_context", "c2_action", "c3_evidence", "c4_boundary", "c5_clarity"):
                row[column] = "2" if system != "C" else "1"
            row["required_checks_applicable"] = "2"
            row["required_checks_passed"] = "2" if system != "C" else "1"
            row["comment"] = f"{rater} 的说明"
            row["adjudication_status"] = "pending"
            rows.append(row)
    return rows


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """写出评分 CSV。"""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    path.write_text(buffer.getvalue(), encoding="utf-8")


async def test_summary_reports_assembly_variants(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """装配变体必须可见：注入过工具池的批次不能看起来和纯生产批次一样。"""
    from evaluation.carebench.systems.base import TurnOutcome

    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))
    adapters = {}
    for system_id in ("A", "B", "C"):
        meta = {"runner": "production+tool_pool_override:search_knowledge"} if system_id == "C" else {"model_id": "m"}
        adapters[system_id] = FakeAdapter(
            system_id,
            outcome=lambda _request, meta=meta: TurnOutcome(
                status="completed", raw_output="回复", latency_ms=10, meta=meta
            ),
        )
    store = create_run_dir(tmp_path / "runs", "carebench-variants")
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
    summary = summarize_run(store, log=lambda _message: None)
    assert summary["systems"]["C"]["assembly_variants"] == {"production+tool_pool_override:search_knowledge": 1}
    assert "override" in (store.root / "summary.md").read_text(encoding="utf-8")
