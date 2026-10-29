"""故障注入与提示词边界的测试：注入必须标实施状态，未实现必须如实标未支持。"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.carebench import prompts
from evaluation.carebench.cases import parse_cases
from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import (
    REGISTRY_VERSION,
    SUPPORTED,
    UNSUPPORTED,
    empty_plan,
    load_plan,
    merge,
    plan_from_cases,
)
from evaluation.carebench.systems.rag import build_retrieval_query, render_evidence

from .conftest import make_cases_file


def test_supported_matrix_is_per_system() -> None:
    """注册表里每个已实现 fixture 都写明适用组别与实现方式。"""
    for name, (systems, impl) in SUPPORTED.items():
        assert systems, f"{name} 没有声明适用组别"
        assert impl.strip(), f"{name} 没有实现说明"
        assert set(systems) <= {"A", "B", "C"}


def test_unsupported_fixtures_reported_as_not_applied(tmp_path: Path) -> None:
    """未实现的 fixture 必须 `applied=False` 且带原因，不能留下「看起来测过」的记录。"""
    path = tmp_path / "fixtures.json"
    path.write_text(json.dumps({"cases": {"CFB-C-001": ["tool_timeout"]}}), encoding="utf-8")
    plan = load_plan(path)
    for system_id in ("A", "B", "C"):
        applications = plan.plan_for("CFB-C-001", system_id)
        assert len(applications) == 1
        assert applications[0].applied is False
        assert applications[0].note == UNSUPPORTED["tool_timeout"]
    summary = plan.summary(("A", "B", "C"))
    assert summary["applied_counts"] == {}
    assert "tool_timeout" in summary["unsupported"]


def test_unknown_fixture_is_flagged(tmp_path: Path) -> None:
    """未注册的名字按未实施处理，并进 `unknown` 清单（不静默通过）。"""
    path = tmp_path / "fixtures.json"
    path.write_text(json.dumps({"cases": {"CFB-C-002": ["no_such_thing"]}}), encoding="utf-8")
    plan = load_plan(path)
    application = plan.plan_for("CFB-C-002", "B")[0]
    assert application.applied is False
    assert "未知 fixture" in application.note
    assert plan.summary(("A", "B", "C"))["unknown"] == ["no_such_thing"]


def test_fixture_on_other_system_is_not_applicable(tmp_path: Path) -> None:
    """只在 B 实施的 fixture 在 C 上必须记成「无对等注入点」。"""
    path = tmp_path / "fixtures.json"
    path.write_text(json.dumps({"cases": {"CFB-C-003": ["retrieval_empty"]}}), encoding="utf-8")
    plan = load_plan(path)
    assert plan.active("CFB-C-003", "B", "retrieval_empty") is True
    assert plan.active("CFB-C-003", "C", "retrieval_empty") is False
    application = plan.plan_for("CFB-C-003", "C")[0]
    assert application.applied is False
    assert "无对等注入点" in application.note


def test_registry_hash_changes_with_content() -> None:
    """注册表 hash 参与 config hash：改注册表就等于改配置。"""
    assert len(empty_plan().registry_sha256) == 64
    assert empty_plan().registry_sha256 == empty_plan().registry_sha256
    assert REGISTRY_VERSION in RunConfig().to_dict()["fault_registry_version"]


def test_plan_merge_keeps_both_sources(tmp_path: Path) -> None:
    """案例自带 fixtures 与命令行 fixtures 合并去重。"""
    case_path = make_cases_file(tmp_path / "cases.jsonl", count=1, fixtures=["tool_search_empty"])
    case_set = parse_cases(case_path.read_bytes(), source=str(case_path), path=case_path)
    config_path = tmp_path / "fixtures.json"
    config_path.write_text(
        json.dumps({"cases": {"CFB-C-001": ["tool_search_empty", "retrieval_empty"]}}), encoding="utf-8"
    )
    plan = merge(plan_from_cases(list(case_set.cases)), load_plan(config_path))
    names = [name for name, _ in plan.requested["CFB-C-001"]]
    assert names == ["tool_search_empty", "retrieval_empty"]
    assert plan.active("CFB-C-001", "C", "tool_search_empty") is True
    assert plan.active("CFB-C-001", "B", "retrieval_empty") is True


def test_render_user_turn_same_for_all_groups() -> None:
    """三组共用的渲染函数：同一输入 → 同一文本（公平性的实现方式）。"""
    text_a = prompts.render_user_turn(shared_context="背景", message="问题", is_followup=False)
    text_b = prompts.render_user_turn(shared_context="背景", message="问题", is_followup=False)
    assert text_a == text_b
    assert text_a.startswith(prompts.CONTEXT_HEADING)
    assert prompts.QUESTION_HEADING in text_a
    followup = prompts.render_user_turn(shared_context="背景", message="补充", is_followup=True)
    assert prompts.FOLLOWUP_HEADING in followup


def test_refusal_marker_is_heuristic_only() -> None:
    """拒答标记只是线索：长文本里的边界说明不算拒答。"""
    assert prompts.refusal_suspected("抱歉，我无法回答这个问题。")
    long_text = "我先说明边界：我不能提供医疗诊断。" + "后续步骤：" + "先确认现场安全。" * 100
    assert not prompts.refusal_suspected(long_text)
    assert not prompts.refusal_suspected("")


def test_evidence_rendering_marks_missing_and_degraded() -> None:
    """证据块必须显式写出「没有材料」与「检索降级」。"""
    empty = render_evidence([], ())
    assert prompts.EVIDENCE_EMPTY in empty
    degraded = render_evidence([], ("vector",))
    assert "不完整" in degraded
    assert prompts.EVIDENCE_EMPTY in degraded


def test_retrieval_query_capped(tmp_path: Path) -> None:
    """检索词截到契约上限（500 字符）。"""
    case_path = make_cases_file(tmp_path / "cases.jsonl", count=1)
    case_set = parse_cases(case_path.read_bytes(), source=str(case_path), path=case_path)
    query = build_retrieval_query(case_set.cases[0], 1)
    assert len(query) <= 500
    assert case_set.cases[0].user_message in query
