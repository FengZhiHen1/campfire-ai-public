"""只读评测尝试审计器：验证原始失败保留、计划分母与首轮组级分类。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.materials_evaluation_audit import analyze_run, main


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


def _record(
    case_id: str,
    system_id: str,
    turn: int,
    attempt: int,
    status: str,
    *,
    session: str | None = None,
    code: str | None = None,
    empty: bool = False,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "system_id": system_id,
        "turn": turn,
        "attempt": attempt,
        "completion_status": status,
        "session_id": session or f"{case_id}-{system_id}-attempt-{attempt}",
        "error": {"code": code} if code else None,
        "status_flags": {"empty_output": empty},
        "raw_output": "DO_NOT_COPY_MODEL_TEXT",
    }


def _run_dir(tmp_path: Path, records: list[dict[str, Any]]) -> Path:
    run = tmp_path / "formal-01"
    run.mkdir()
    (run / "manifest.json").write_text(
        json.dumps({"run_id": "formal-01", "code": {"commit": "tested123"}, "config": {"systems": ["A", "B"]}}),
        encoding="utf-8",
    )
    cases = [
        {"id": "CASE-001", "followup": None},
        {"id": "CASE-002", "followup": "第二轮"},
        {"id": "CASE-003", "followup": "第二轮"},
        {"id": "CASE-004", "followup": None},
    ]
    _write_jsonl(run / "cases.frozen.jsonl", cases)
    _write_jsonl(run / "outputs.jsonl", records)
    return run


def _scenario_records() -> list[dict[str, Any]]:
    return [
        _record("CASE-001", "A", 1, 1, "error", session="old-session", code="model_unavailable"),
        _record("CASE-001", "A", 1, 2, "completed", session="new-session"),
        _record("CASE-001", "B", 1, 1, "completed"),
        _record("CASE-002", "A", 1, 1, "completed"),
        _record("CASE-003", "A", 1, 1, "completed"),
        _record("CASE-003", "A", 2, 1, "completed"),
        _record("CASE-003", "B", 1, 1, "completed"),
        _record("CASE-003", "B", 2, 1, "completed"),
        _record("CASE-004", "A", 1, 1, "no_output", empty=True),
        _record("CASE-004", "B", 1, 1, "completed", empty=True),
    ]


def test_audit_counts_all_attempts_and_classifies_first_attempt_groups(tmp_path: Path) -> None:
    run = _run_dir(tmp_path, _scenario_records())
    originals = {
        name: hashlib.sha256((run / name).read_bytes()).hexdigest()
        for name in ("manifest.json", "cases.frozen.jsonl", "outputs.jsonl")
    }

    report = analyze_run(run)

    assert report["analysis"]["mode"] == "read_only_analysis"
    assert report["analysis"]["is_part_of_tested_run"] is False
    assert report["analysis"]["tool_version"] == "1.0.0"
    assert report["run"] == {"run_id": "formal-01", "tested_commit": "tested123"}
    assert {
        "manifest.json": report["raw_sources"]["manifest"]["sha256"],
        "cases.frozen.jsonl": report["raw_sources"]["cases"]["sha256"],
        "outputs.jsonl": report["raw_sources"]["outputs"]["sha256"],
    } == originals
    assert report["planned"] == {"case_count": 4, "system_count": 2, "case_groups": 8, "turns": 12}
    assert report["attempts"]["total"] == 10
    assert report["attempts"]["vs_planned_turns"] == {"attempts": 10, "planned_turns": 12, "difference": -2}
    assert report["attempts"]["status_counts"] == {
        "completed": 8,
        "no_output": 1,
        "timeout": 0,
        "error": 1,
    }
    assert report["attempts"]["by_system"]["A"]["status_counts"] == {
        "completed": 4,
        "no_output": 1,
        "timeout": 0,
        "error": 1,
    }
    assert report["attempts"]["error_code_counts"] == {"model_unavailable": 1}
    assert report["retry_groups"] == 1
    assert report["first_attempt_groups"]["denominator"] == 8
    assert report["first_attempt_groups"]["completed"] == 3
    assert report["first_attempt_groups"]["failed"] == 3
    assert report["first_attempt_groups"]["incomplete"] == 2
    assert "DO_NOT_COPY_MODEL_TEXT" not in json.dumps(report)
    assert {name: hashlib.sha256((run / name).read_bytes()).hexdigest() for name in originals} == originals


def test_zero_records_are_incomplete_not_a_pass(tmp_path: Path) -> None:
    report = analyze_run(_run_dir(tmp_path, []))

    assert report["attempts"]["total"] == 0
    assert report["attempts"]["vs_planned_turns"]["planned_turns"] == 12
    assert report["first_attempt_groups"] == {
        "denominator": 8,
        "completed": 0,
        "failed": 0,
        "incomplete": 8,
        "rule": report["first_attempt_groups"]["rule"],
    }


def test_cli_writes_only_the_requested_new_output(tmp_path: Path) -> None:
    run = _run_dir(tmp_path, _scenario_records())
    output = tmp_path / "audit.json"

    assert main(["--run", str(run), "--out", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["run"]["run_id"] == "formal-01"
    assert not (run / "summary.json").exists()
    assert main(["--run", str(run), "--out", str(output)]) == 2


def test_cli_refuses_summary_path_even_when_it_does_not_exist(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _run_dir(tmp_path, _scenario_records())

    assert main(["--run", str(run), "--out", str(run / "summary.json")]) == 2
    assert "不能指向输入原件或 summary" in capsys.readouterr().err
    assert not (run / "summary.json").exists()


def test_cli_rejects_missing_inputs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--run", str(tmp_path / "missing"), "--out", str(tmp_path / "audit.json")]) == 2
    assert "无法读取" in capsys.readouterr().err
