"""证据保真：结构化产出、规范文本投影、注入工具的说明复用、重试隔离与故障观察。

这些用例针对的都是「记录看起来没问题、其实丢了事实」的那类缺陷——每一条都对应一次
主 agent 的审查意见，因此断言写到**可观察的行为**，不写实现细节。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel


from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan, load_plan
from evaluation.carebench.render import NO_TEXT_MARK, project
from evaluation.carebench.runner import execute
from evaluation.carebench.store import create_run_dir
from evaluation.carebench.systems.agent import _injected_search_tool
from evaluation.carebench.systems.base import RETRY_NEW_SESSION, RETRY_SAME_SESSION, STATUS_COMPLETED, TurnOutcome

from .conftest import FakeAdapter, load_cases, make_cases_file, make_snapshot


class _StrictArgs(BaseModel):
    """严格模式可接受的参数模型（产品 ToolSpec 会校验 JSON schema）。"""

    query: str


def _card() -> dict[str, Any]:
    """一张最小行动卡（字段名与产品 ActionCardEvent 一致）。"""
    return {
        "kind": "action_card",
        "card_id": "c1",
        "title": "现场应急",
        "sections": [
            {"key": "do_now", "heading": "现在做什么", "lines": ["先确认孩子呼吸是否平稳", "把人群疏散到 3 米外"]}
        ],
        "states": [{"key": "call_emergency", "value": "yes"}],
        "annotations": [{"target": "2", "kind": "escalation"}],
    }


def test_projection_keeps_text_verbatim() -> None:
    """纯正文时投影等于原文（不做任何包装）。"""
    assert project("第一行\n第二行", []) == "第一行\n第二行"


def test_projection_renders_card_without_rewriting() -> None:
    """纯卡片输出：正文标记为「没有正文」，卡片逐行原样呈现。"""
    text = project("", [_card()])
    assert NO_TEXT_MARK in text
    assert "【行动卡】1｜现场应急（card_id=c1）" in text
    assert "1. 先确认孩子呼吸是否平稳" in text
    assert "2. 把人群疏散到 3 米外" in text
    assert "call_emergency = yes" in text
    assert "第 2 行 — escalation" in text


def test_projection_renders_questions() -> None:
    """结构化提问：题干、选项、是否可跳过都出现在投影里。"""
    payload = {
        "kind": "question",
        "batch_id": "b1",
        "items": [
            {
                "id": "q1",
                "prompt": "孩子现在能正常说话吗？",
                "options": [{"label": "能", "value": "yes"}, {"label": "不能", "value": "no"}],
                "allow_skip": True,
            }
        ],
    }
    text = project("", [payload])
    assert "【结构化提问】1｜batch_id=b1" in text
    assert "题1（id=q1）：孩子现在能正常说话吗？" in text
    assert "能（value=yes） / 不能（value=no）" in text
    assert "允许跳过：是" in text


def test_projection_keeps_unknown_structure() -> None:
    """不认识的结构化类型也要原样留下（宁可丑，不可丢）。"""
    text = project("正文", [{"kind": "mystery", "payload": {"a": 1}}])
    assert "未识别的结构化产出：mystery" in text
    assert '"a": 1' in text


def test_injected_tool_reuses_product_description_and_args() -> None:
    """注入替身只换 handler：说明与参数模型必须与产品原工具逐字相同，且不得泄漏注入。"""
    from campfire.agent.tools import ToolFailure, ToolResult, ToolSpec

    product = ToolSpec(
        name="search_knowledge",
        description="在本项目的专业资料库里检索，为你的建议找依据。",
        args_model=_StrictArgs,
        handler=lambda _c, _a: None,
    )
    for mode in ("empty", "unavailable", "timeout"):
        stand_in = _injected_search_tool(product, mode=mode, hang_seconds=0.01)
        assert stand_in.name == product.name
        assert stand_in.description == product.description, f"{mode} 改了工具说明：模型会提前看到故障"
        assert stand_in.args_model is product.args_model

    empty = _injected_search_tool(product, mode="empty")
    unavailable = _injected_search_tool(product, mode="unavailable")
    import asyncio

    assert isinstance(asyncio.run(empty.handler(None, None)), ToolResult)
    assert isinstance(asyncio.run(unavailable.handler(None, None)), ToolFailure)
    # 主 agent 审查的那句：「本次评测注入」不得出现在模型可见的说明里
    assert "评测" not in empty.description and "注入" not in empty.description


@pytest.mark.asyncio
async def test_structured_only_turn_is_recorded_as_completed_output(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """纯卡片输出必须落成「有产出」：结构化载荷、投影、状态标记三样都在。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))
    card = _card()

    def outcome(_request) -> TurnOutcome:
        return TurnOutcome(
            status=STATUS_COMPLETED,
            raw_output="",
            structured=[card],
            output_text=project("", [card]),
            latency_ms=5,
        )

    adapters = {system_id: FakeAdapter(system_id, outcome=outcome) for system_id in ("A", "B", "C")}
    store = create_run_dir(tmp_path / "runs", "carebench-structured")
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
    record = store.read_outputs()[0]
    assert record["raw_output"] == ""
    assert record["structured_output"][0]["card_id"] == "c1"
    assert "现在做什么" in record["output_text"]
    assert record["status_flags"]["structured_only"] is True
    assert record["status_flags"]["empty_output"] is False


@pytest.mark.asyncio
async def test_retry_on_dirty_session_restarts_with_new_session(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """失败尝试已落库时必须换会话重开：同一轮出现两条记录、两个会话，且只重试一次。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))

    def outcome(request) -> TurnOutcome:
        if request.attempt == 1:
            return TurnOutcome(
                status="error",
                error_type="SessionWriteFailure",
                error_detail="第一次失败（已落库一半）",
                latency_ms=3,
                retry_safety=RETRY_NEW_SESSION,
            )
        return TurnOutcome(status="completed", raw_output="第二次成功", latency_ms=4)

    adapters = {system_id: FakeAdapter(system_id, outcome=outcome) for system_id in ("A", "B", "C")}
    store = create_run_dir(tmp_path / "runs", "carebench-retry-new")
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
    assert records[0]["session_id"] != records[1]["session_id"], "已落库的失败被原地重试了"
    assert records[1]["raw_output"] == "第二次成功"
    assert records[1]["retry"]["retry_safety"] == RETRY_SAME_SESSION


@pytest.mark.asyncio
async def test_retry_budget_is_per_group_not_per_turn(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """整组只允许一次外层重试：第 1 轮用过额度后，第 2 轮失败不得再重试。"""
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1, followup=True))

    def outcome(request) -> TurnOutcome:
        if request.attempt == 1:
            return TurnOutcome(status="timeout", latency_ms=1, error_type="TimeoutError")
        return TurnOutcome(status="completed", raw_output="成功", latency_ms=1)

    adapters = {system_id: FakeAdapter(system_id, outcome=outcome) for system_id in ("A", "B", "C")}
    store = create_run_dir(tmp_path / "runs", "carebench-retry-budget")
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
    a_records = [record for record in store.read_outputs() if record["system_id"] == "A"]
    # 第 1 轮：attempt 1 超时 → attempt 2 成功；第 2 轮：attempt 1 超时 → 额度已尽，不再重试
    assert [(r["turn"], r["attempt"]) for r in a_records] == [(1, 1), (1, 2), (2, 1)]
    assert a_records[-1]["completion_status"] == "timeout"


@pytest.mark.asyncio
async def test_fixture_observation_marks_uncalled_tool(tmp_path: Path, settings_for_tests: Any) -> None:
    """替身装上了但模型没调用 → `observed=false`，不能算「系统在故障下的表现」。"""
    fixtures = tmp_path / "fixtures.json"
    fixtures.write_text('{"cases": {"CFB-C-001": ["tool_search_unavailable", "retrieval_empty"]}}', encoding="utf-8")
    plan = load_plan(fixtures)
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1))
    adapters = {
        "A": FakeAdapter("A"),
        "B": FakeAdapter("B"),
        "C": FakeAdapter(
            "C",
            outcome=lambda _request: TurnOutcome(
                status=STATUS_COMPLETED,
                raw_output="没查资料直接回答",
                latency_ms=2,
                tool_calls=[],
                trace={},
            ),
        ),
    }
    store = create_run_dir(tmp_path / "runs", "carebench-observed")
    await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=plan,
        settings=settings_for_tests,
        adapters=adapters,
        log=lambda _message: None,
    )
    c_record = next(record for record in store.read_outputs() if record["system_id"] == "C")
    tool_fixture = next(item for item in c_record["fixtures"] if item["name"] == "tool_search_unavailable")
    assert tool_fixture["applied"] is True
    assert tool_fixture["observed"] is False
    assert "没有观察到该故障被触发" in tool_fixture["note"]

    # 检索类注入（B 组）：轨迹里有检索记录才算观察到
    b_record = next(record for record in store.read_outputs() if record["system_id"] == "B")
    retrieval_fixture = next(item for item in b_record["fixtures"] if item["name"] == "retrieval_empty")
    assert retrieval_fixture["applied"] is True
    assert retrieval_fixture["observed"] is False  # FakeAdapter 没有检索轨迹


@pytest.mark.parametrize("mode", ["empty", "unavailable"])
def test_injected_tool_never_leaks_injection(mode: str) -> None:
    """替身说明里不得出现「评测 / 注入 / 故障」这类会提示模型的字眼。"""
    from campfire.agent.tools import ToolSpec

    product = ToolSpec(
        name="search_knowledge",
        description="在本项目的专业资料库里检索，为你的建议找依据。",
        args_model=_StrictArgs,
        handler=lambda _c, _a: None,
    )
    stand_in = _injected_search_tool(product, mode=mode)
    for word in ("评测", "注入", "故障", "本次由"):
        assert word not in stand_in.description
