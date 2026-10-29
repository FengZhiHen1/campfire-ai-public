"""案例读取与结构校验的测试（含「坏数据必须被拒」的负例）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.carebench.cases import CaseValidationError, load_case_file, parse_cases

from .conftest import make_cases_file


def test_loads_and_hashes_calibration_cases() -> None:
    """仓库内的校准案例可被读取，且 hash 稳定。"""
    path = Path("evaluation/carebench/cases/cases-calibration-v0.1.jsonl")
    case_set = load_case_file(path)
    assert len(case_set.cases) == 8
    assert case_set.split == "calibration"
    assert case_set.cases[0].id == "CFB-C-001"
    assert all(len(case.sha256) == 64 for case in case_set.cases)
    # 同一份字节重复解析得到同一 hash（冻结与校验依赖这一点）
    again = parse_cases(path.read_bytes(), source=str(path))
    assert again.sha256 == case_set.sha256


def test_two_turn_policy_from_followup(tmp_path: Path) -> None:
    """`followup` 决定轮数；单轮案例取第二轮必须报错（禁止即兴追问）。"""
    single = load_cases(make_cases_file(tmp_path / "single.jsonl", count=1))
    assert single.cases[0].turns == 1
    with pytest.raises(ValueError):
        single.cases[0].message_for_turn(2)

    two = load_cases(make_cases_file(tmp_path / "two.jsonl", count=1, followup=True))
    assert two.cases[0].turns == 2
    assert two.cases[0].message_for_turn(2).startswith("孩子拒绝移动")


def test_rejects_missing_field(tmp_path: Path) -> None:
    """缺字段必须拒（协议 02 第 3 节要求的字段一个都不能少）。"""
    path = tmp_path / "bad.jsonl"
    payload = {
        "id": "CFB-C-001",
        "split": "calibration",
        "category": "日常",
        "risk_hint": "x",
        "user_message": "问",
        "shared_context": "背景",
        "followup": None,
        "must_check": ["a"],
        "must_not": ["b"],
        "source_kind": "synthetic",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(CaseValidationError, match="缺字段"):
        load_case_file(path)


def test_rejects_duplicate_ids_and_mixed_splits(tmp_path: Path) -> None:
    """id 重复、split 混用都必须拒（分母与批次口径依赖它们唯一）。"""
    duplicated = tmp_path / "dup.jsonl"
    line = make_cases_file(tmp_path / "one.jsonl", count=1).read_text(encoding="utf-8").strip()
    duplicated.write_text(line + "\n" + line + "\n", encoding="utf-8")
    with pytest.raises(CaseValidationError, match="id 重复"):
        load_case_file(duplicated)

    mixed = tmp_path / "mixed.jsonl"
    first = json.loads(line)
    second = dict(first, id="CFB-T-002", split="test")
    mixed.write_text(
        json.dumps(first, ensure_ascii=False) + "\n" + json.dumps(second, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CaseValidationError, match="split 不一致"):
        load_case_file(mixed)


def test_rejects_empty_followup_and_bad_id(tmp_path: Path) -> None:
    """空串 followup 与畸形 id 都要拒（前者会让轮数判定模糊）。"""
    path = tmp_path / "bad2.jsonl"
    payload = json.loads(make_cases_file(tmp_path / "ok.jsonl", count=1).read_text(encoding="utf-8").strip())
    payload["followup"] = "   "
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(CaseValidationError, match="followup 是空串"):
        load_case_file(path)

    payload["followup"] = None
    payload["id"] = "bad id with space"
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(CaseValidationError, match="case_id 形状不合法"):
        load_case_file(path)


def load_cases(path: Path):  # noqa: ANN201 —— 测试内小工具，返回类型由调用点断言
    """读取临时案例文件。"""
    return parse_cases(path.read_bytes(), source=str(path), path=path)
