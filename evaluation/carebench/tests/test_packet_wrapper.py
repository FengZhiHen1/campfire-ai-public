"""盲化只检查评审包包装字段，原始产出与用户可见内容保持原样。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from campfire.agent.runtime import ActionCardEvent, QuestionEvent
from campfire.agent.tools.payloads import (
    ActionCardAnnotation,
    ActionCardSection,
    ActionCardState,
    QuestionItem,
    QuestionOption,
)
from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan
from evaluation.carebench.hashing import sha256_value
from evaluation.carebench.render import project
from evaluation.carebench.review import PACKET_FILE, export_packet
from evaluation.carebench.runner import execute
from evaluation.carebench.store import RunStore, create_run_dir
from evaluation.carebench.summarize import summarize_run
from evaluation.carebench.verify import verify_run

from .conftest import FakeAdapter, load_cases, make_cases_file, make_snapshot


def _product_payload(event: QuestionEvent | ActionCardEvent) -> dict[str, Any]:
    """转成 Agent 适配器落盘的 kind + 产品事件载荷形状。"""
    payload = asdict(event)
    kind = payload.pop("type")
    return {"kind": kind, **payload}


def _product_outputs() -> list[dict[str, Any]]:
    question = QuestionEvent(
        batch_id="question-batch",
        items=(
            QuestionItem(
                id="q1",
                prompt="孩子现在最在意什么？",
                options=(QuestionOption(label="声音"), QuestionOption(label="人群")),
                allow_skip=True,
            ),
        ),
    )
    card = ActionCardEvent(
        card_id="card-1",
        title="先照顾当下",
        sections=(ActionCardSection("now", "现在", ("留在孩子身边",)),),
        states=(ActionCardState("support_needed", "unknown"),),
        annotations=(ActionCardAnnotation("1", "boundary"),),
    )
    return [_product_payload(question), _product_payload(card)]


async def _exported_run(tmp_path: Path, settings: Any, faults: FaultPlan) -> RunStore:
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=1, followup=True))
    structured = _product_outputs()

    def outcome(_request: Any):
        from evaluation.carebench.systems.base import TurnOutcome

        raw = '原文保留 "label"、system_id 和用户措辞。'
        return TurnOutcome(
            status="completed",
            raw_output=raw,
            structured=structured,
            output_text=project(raw, structured),
            latency_ms=10,
        )

    adapters = {system_id: FakeAdapter(system_id, outcome=outcome) for system_id in ("A", "B", "C")}
    store = create_run_dir(tmp_path / "runs", "packet-wrapper")
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
    export_packet(store, log=lambda _message: None)
    summarize_run(store, log=lambda _message: None)
    return store


def _rewrite_packet(store: RunStore, entries: list[dict[str, Any]]) -> None:
    packet_text = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in entries)
    (store.review_dir / PACKET_FILE).write_text(packet_text, encoding="utf-8")
    manifest = store.read_manifest()
    manifest["review"]["packet_sha256"] = hashlib.sha256(packet_text.encode("utf-8")).hexdigest()
    store.write_manifest(manifest)


@pytest.mark.asyncio
async def test_exported_product_question_and_action_card_shapes_pass_verification(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    store = await _exported_run(tmp_path, settings_for_tests, faults_for_tests)

    packet_text = (store.review_dir / PACKET_FILE).read_text(encoding="utf-8")
    packet = json.loads(packet_text.splitlines()[0])
    assert packet["turns"][0]["structured_output"][0]["items"][0]["options"][0]["label"] == "声音"
    assert packet["structured_output"][1]["sections"][0]["lines"] == ["留在孩子身边"]
    assert '"label"、system_id' in packet["final_output"]
    report = verify_run(store, require_complete=True)
    assert report.ok, report.violations


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("level", "key"),
    [
        ("packet", "system_id"),
        ("packet", "system"),
        ("packet", "model_id"),
        ("packet", "label"),
        ("packet", "assembly"),
        ("turn", "system_id"),
        ("turn", "system"),
        ("turn", "model_id"),
        ("turn", "label"),
        ("turn", "assembly"),
    ],
)
async def test_forbidden_packet_wrapper_fields_are_rejected(
    tmp_path: Path,
    settings_for_tests: Any,
    faults_for_tests: FaultPlan,
    level: str,
    key: str,
) -> None:
    store = await _exported_run(tmp_path, settings_for_tests, faults_for_tests)
    packet_path = store.review_dir / PACKET_FILE
    entries = [json.loads(line) for line in packet_path.read_text(encoding="utf-8").splitlines()]
    if level == "packet":
        entries[0][key] = "leaked"
    else:
        entries[0]["turns"][0][key] = "leaked"
    _rewrite_packet(store, entries)

    report = verify_run(store)
    assert not report.ok
    assert any(f"组别标识字段 `{key}`" in item for item in report.violations), report.violations


@pytest.mark.asyncio
async def test_raw_output_change_with_recomputed_record_hash_fails_packet_fidelity(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    store = await _exported_run(tmp_path, settings_for_tests, faults_for_tests)
    lines = store.outputs_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["raw_output"] = "事后改写的原始输出"
    record["record_sha256"] = sha256_value({key: value for key, value in record.items() if key != "record_sha256"})
    lines[0] = json.dumps(record, ensure_ascii=False, sort_keys=True)
    store.outputs_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = verify_run(store)
    assert not report.ok
    assert any("规范文本投影与原始载荷重算结果不一致" in item for item in report.violations), report.violations
