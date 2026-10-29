#!/usr/bin/env python3
"""只读汇总 CareBench 原始生成尝试，补充展示首轮失败与重试历史。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ANALYZER_VERSION = "1.0.0"
STATUSES = ("completed", "no_output", "timeout", "error")
ERROR_CODE_STATUSES = frozenset({"timeout", "error"})
MISSING_ERROR_CODE = "(missing)"


class AuditError(ValueError):
    """输入证据缺失或结构无法安全解释。"""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path, data: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"{path.name} 不是有效 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise AuditError(f"{path.name} 顶层必须是 JSON 对象")
    return payload


def _read_jsonl(path: Path, data: bytes) -> tuple[list[dict[str, Any]], bool]:
    records: list[dict[str, Any]] = []
    lines = data.splitlines(keepends=True)
    partial_last_line = bool(data and not data.endswith(b"\n"))
    for index, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if partial_last_line and index == len(lines):
                break
            raise AuditError(f"{path.name}:{index} 不是有效 JSONL 记录：{exc}") from exc
        if not isinstance(record, dict):
            raise AuditError(f"{path.name}:{index} 顶层必须是 JSON 对象")
        records.append(record)
    return records, partial_last_line


def _planned_cases(data: bytes, path: Path) -> list[tuple[str, int]]:
    cases: list[tuple[str, int]] = []
    seen: set[str] = set()
    records, partial_line = _read_jsonl(path, data)
    if partial_line:
        raise AuditError(f"{path.name} 冻结案例文件末尾有不完整行")
    for index, record in enumerate(records, start=1):
        case_id = record.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise AuditError(f"{path.name}:{index} 缺少有效 id")
        if case_id in seen:
            raise AuditError(f"{path.name}:{index} case id 重复：{case_id}")
        followup = record.get("followup")
        if followup is not None and not isinstance(followup, str):
            raise AuditError(f"{path.name}:{index} followup 必须是字符串或 null")
        seen.add(case_id)
        cases.append((case_id, 2 if followup else 1))
    return cases


def _counter_with_statuses(counter: Counter[str]) -> dict[str, int]:
    return {
        **{status: counter.get(status, 0) for status in STATUSES},
        **{status: count for status, count in sorted(counter.items()) if status not in STATUSES},
    }


def analyze_run(run_dir: Path) -> dict[str, Any]:
    """按单次读取的文件快照分析，不导入评测运行代码或暴露输出文本。"""
    run_dir = run_dir.expanduser().resolve()
    input_paths = {
        "manifest": run_dir / "manifest.json",
        "cases": run_dir / "cases.frozen.jsonl",
        "outputs": run_dir / "outputs.jsonl",
    }
    snapshots: dict[str, bytes] = {}
    for name, path in input_paths.items():
        try:
            snapshots[name] = path.read_bytes()
        except OSError as exc:
            raise AuditError(f"无法读取 {path}: {exc}") from exc

    manifest = _read_json(input_paths["manifest"], snapshots["manifest"])
    cases = _planned_cases(snapshots["cases"], input_paths["cases"])
    records, partial_last_line = _read_jsonl(input_paths["outputs"], snapshots["outputs"])

    run_id = manifest.get("run_id")
    code = manifest.get("code")
    config = manifest.get("config")
    tested_commit = code.get("commit") if isinstance(code, dict) else None
    systems = config.get("systems") if isinstance(config, dict) else None
    if not isinstance(run_id, str) or not run_id:
        raise AuditError("manifest.json 缺少有效 run_id")
    if not isinstance(tested_commit, str) or not tested_commit:
        raise AuditError("manifest.json 缺少 code.commit")
    if not isinstance(systems, list) or not systems or not all(isinstance(item, str) for item in systems):
        raise AuditError("manifest.json 缺少有效 config.systems")
    if len(set(systems)) != len(systems):
        raise AuditError("manifest.json config.systems 含重复组别")

    expected_groups = [(case_id, system_id, turns) for case_id, turns in cases for system_id in systems]
    expected_keys = {(case_id, system_id) for case_id, system_id, _turns in expected_groups}
    turns_by_key = {(case_id, system_id): turns for case_id, system_id, turns in expected_groups}
    planned_turns = sum(turns for _case_id, turns in cases) * len(systems)

    status_counts: Counter[str] = Counter()
    system_status_counts: dict[str, Counter[str]] = defaultdict(Counter)
    error_code_counts: Counter[str] = Counter()
    system_error_code_counts: dict[str, Counter[str]] = defaultdict(Counter)
    retries: set[tuple[str, str]] = set()
    first_attempt_records: dict[tuple[str, str], dict[int, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for line_number, record in enumerate(records, start=1):
        case_id = record.get("case_id")
        system_id = record.get("system_id")
        turn = record.get("turn")
        attempt = record.get("attempt")
        status = record.get("completion_status")
        if not isinstance(case_id, str) or not isinstance(system_id, str):
            raise AuditError(f"outputs.jsonl:{line_number} 缺少 case_id/system_id")
        if system_id not in systems:
            raise AuditError(f"outputs.jsonl:{line_number} 出现未知 system_id：{system_id}")
        if not isinstance(turn, int) or isinstance(turn, bool) or turn < 1:
            raise AuditError(f"outputs.jsonl:{line_number} turn 必须是正整数")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            raise AuditError(f"outputs.jsonl:{line_number} attempt 必须是正整数")
        if not isinstance(status, str) or not status:
            raise AuditError(f"outputs.jsonl:{line_number} 缺少 completion_status")
        key = (case_id, system_id)
        if key not in expected_keys:
            raise AuditError(f"outputs.jsonl:{line_number} 不属于冻结案例与系统组合")
        expected_turns = turns_by_key[key]
        if turn > expected_turns:
            raise AuditError(f"outputs.jsonl:{line_number} turn 超出冻结案例计划")

        status_counts[status] += 1
        system_status_counts[system_id][status] += 1
        if attempt > 1:
            retries.add(key)
        if attempt == 1:
            first_attempt_records[key][turn].append(record)

        error = record.get("error")
        error_code = error.get("code") if isinstance(error, dict) else None
        if status in ERROR_CODE_STATUSES:
            normalized_code = error_code if isinstance(error_code, str) and error_code else MISSING_ERROR_CODE
            error_code_counts[normalized_code] += 1
            system_error_code_counts[system_id][normalized_code] += 1

    first_attempt_groups = {"completed": 0, "failed": 0, "incomplete": 0}
    for case_id, system_id, turns in expected_groups:
        key = (case_id, system_id)
        turn_records = first_attempt_records.get(key, {})
        has_failure = any(
            record.get("completion_status") != "completed"
            or (record.get("status_flags") or {}).get("empty_output") is True
            for rows in turn_records.values()
            for record in rows
        )
        if has_failure:
            first_attempt_groups["failed"] += 1
            continue
        complete = all(
            turn in turn_records
            and all(
                record.get("completion_status") == "completed"
                and (record.get("status_flags") or {}).get("empty_output") is not True
                for record in turn_records[turn]
            )
            for turn in range(1, turns + 1)
        )
        first_attempt_groups["completed" if complete else "incomplete"] += 1

    analyzer_sha = _sha256(Path(__file__).read_bytes())
    return {
        "analysis": {
            "mode": "read_only_analysis",
            "tool": "materials_evaluation_audit",
            "tool_version": ANALYZER_VERSION,
            "tool_source_sha256": analyzer_sha,
            "is_part_of_tested_run": False,
            "note": "补充分析器；不属于被测运行，不修改 manifest、summary 或原始输出。",
        },
        "run": {"run_id": run_id, "tested_commit": tested_commit},
        "raw_sources": {
            name: {"path": str(path), "sha256": _sha256(snapshots[name])} for name, path in input_paths.items()
        },
        "planned": {
            "case_count": len(cases),
            "system_count": len(systems),
            "case_groups": len(expected_groups),
            "turns": planned_turns,
        },
        "attempts": {
            "total": len(records),
            "vs_planned_turns": {
                "attempts": len(records),
                "planned_turns": planned_turns,
                "difference": len(records) - planned_turns,
            },
            "status_counts": _counter_with_statuses(status_counts),
            "by_system": {
                system_id: {
                    "attempts": sum(system_status_counts[system_id].values()),
                    "status_counts": _counter_with_statuses(system_status_counts[system_id]),
                    "error_code_counts": dict(sorted(system_error_code_counts[system_id].items())),
                }
                for system_id in systems
            },
            "error_code_counts": dict(sorted(error_code_counts.items())),
        },
        "first_attempt_groups": {
            "denominator": len(expected_groups),
            **first_attempt_groups,
            "rule": (
                "按冻结案例计划轮数逐组判定；首轮任一 error/timeout/no_output 或 empty_output 标为 failed，"
                "计划轮次 attempt=1 全部 completed 才标为 completed，其余标为 incomplete。"
            ),
        },
        "retry_groups": len(retries),
        "outputs_trailing_partial_line": partial_last_line,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读补充统计 CareBench 原始生成尝试")
    parser.add_argument(
        "--run", required=True, type=Path, help="包含 manifest.json、cases.frozen.jsonl、outputs.jsonl 的运行目录"
    )
    parser.add_argument("--out", required=True, type=Path, help="新建审计 JSON 的输出路径；拒绝覆盖现有文件")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run_dir = args.run.expanduser().resolve()
    out_path = args.out.expanduser().resolve()
    protected_paths = {
        (run_dir / name).resolve()
        for name in ("manifest.json", "cases.frozen.jsonl", "outputs.jsonl", "summary.json", "summary.md")
    }
    if out_path in protected_paths:
        print("错误：--out 不能指向输入原件或 summary", file=sys.stderr)
        return 2
    if out_path.exists() or out_path.is_symlink():
        print(f"错误：拒绝覆盖已有输出文件：{out_path}", file=sys.stderr)
        return 2
    try:
        result = analyze_run(run_dir)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (AuditError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print(f"只读评测尝试审计已写出：{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
