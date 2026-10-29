"""AI 盲评通道的独立终审用例：三条「证据锚」不变量（只读产出目录、不联网）。

每条都先跑通干净链路做正控，再构造只补 hash 的篡改，断言篡改必须被拒：

1. `response_text`（被评分、被重新解析的正文）必须来自 `raw_response`——两者各自
   hash，但从未互相对照；只改正文 + parsed + hash 就能让「原始响应」与「评分正文」
   互相矛盾而校验仍通过。
2. `require_complete=True` 时，评审包组数少于 manifest 的「案例 × 组别」必须判违反，
   不能只留 warning（`summarize_ai_review` 对同一情形已判 pending、拒出结论）。
3. `resume` 重写 manifest 不得抹掉 `review.ai`（身份锚）与 `review.packet_sha256`
   （评审包锚）；锚一丢，身份与评审包就退回「只靠自证」。
4. 正式批次（`label=test`）的 AI 身份必须是 `stage=formal`：`calibration` 允许在看到
   尝试之后再冻结，用它给正式批次背书就绕过了「正式身份必须在评分开始前冻结」。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio

from evaluation.carebench.ai_review import (
    DIMENSION_KEYS,
    AiReviewError,
    build_scoring_inputs,
    default_judges,
    freeze_judges,
    load_frozen_cases,
    load_identity,
    parse_judge_output,
    summarize_ai_review,
    verify_ai_review_report,
)
from evaluation.carebench.ai_runner import score_run
from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan
from evaluation.carebench.hashing import sha256_value
from evaluation.carebench.review import export_packet
from evaluation.carebench.runner import execute
from evaluation.carebench.store import RunStore, create_run_dir, read_json
from evaluation.carebench.systems.base import TurnOutcome

from .conftest import FakeAdapter, load_cases, make_cases_file, make_snapshot


class _Response:
    """脚本化 chat.completions 响应（`raw_response` 与正文同源）。"""

    def __init__(self, text: str) -> None:
        self.id = "resp-test"
        self.model = "stub-model"
        self.choices = [type("Choice", (), {"message": type("Message", (), {"content": text})()})()]

    def model_dump(self) -> dict[str, Any]:
        """SDK 形状的原始响应。"""
        return {
            "id": self.id,
            "model": self.model,
            "choices": [{"message": {"content": self.choices[0].message.content}}],
        }


class _Client:
    """按 (pass, blind) 返回预设正文的最小异步客户端。"""

    def __init__(self, store: RunStore, handler: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        completions = self

        class _Chat:
            @staticmethod
            async def create(**kwargs: Any) -> _Response:
                completions.calls.append(kwargs)
                identity = load_identity(store)
                pass_no = 1 if kwargs["messages"][0]["content"] == identity["judges"]["1"]["prompt_text"] else 2
                blind = re.search(r'"blind_id": "([^"]+)"', kwargs["messages"][1]["content"])
                assert blind is not None
                return _Response(handler(pass_no, blind.group(1)))

        self.chat = type("Chat", (), {"completions": _Chat()})()


async def _exported_run(
    tmp_path: Path,
    *,
    settings: Any,
    count: int = 1,
    case_ids: list[str] | None = None,
    label: str = "calibration",
) -> RunStore:
    """跑一个批次并导出盲化评审包（可选只跑部分案例，模拟评审包少于期望组数）。"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=count))
    adapters = {
        system_id: FakeAdapter(
            system_id,
            outcome=lambda _request, text=f"{system_id} 组的回复": TurnOutcome(status="completed", raw_output=text),
        )
        for system_id in ("A", "B", "C")
    }
    store = create_run_dir(tmp_path / "runs", "carebench-ai-acceptance")
    await execute(
        store=store,
        config=RunConfig(label=label),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=FaultPlan(requested={}),
        settings=settings,
        adapters=adapters,
        case_ids=case_ids,
        log=lambda _message: None,
    )
    export_packet(store, log=lambda _message: None)
    return store


def _system_of(store: RunStore, blind_id: str) -> str:
    """从盲化映射取组别（只用于造真实引用）。"""
    for per_case in (read_json(store.review_dir / "blind-map.json")["map"]).values():
        if blind_id in per_case:
            return str(per_case[blind_id])
    raise AssertionError(blind_id)


def _score_payload(quote: str, *, hard: str = "no") -> dict[str, Any]:
    """一份 schema 合法的评分输出。"""
    evidence = {"quote": quote, "missing": False, "turn": 1, "note": ""}
    return {
        "hard_failure": {
            "value": hard,
            "reason": "硬失败" if hard == "yes" else "无硬失败",
            "failure_types": ["other_critical"] if hard == "yes" else [],
        },
        "dimensions": {key: {"score": 2, "reason": "理由", "evidence": dict(evidence)} for key in DIMENSION_KEYS},
        "must_check": [{"id": "MC-1", "status": "pass", "evidence": dict(evidence)}],
        "must_not": [{"id": "MN-1", "status": "respected", "evidence": dict(evidence)}],
    }


async def _frozen_and_scored(store: RunStore, *, hard: str = "no") -> None:
    """冻结两位评分者并跑完两 pass（正文随引用走，schema 合法）。"""
    freeze_judges(store, judges=default_judges("stub-model"), stage="calibration", log=lambda _message: None)

    def handler(_pass_no: int, blind_id: str) -> str:
        return json.dumps(_score_payload(f"{_system_of(store, blind_id)} 组的回复", hard=hard), ensure_ascii=False)

    await score_run(store, client=_Client(store, handler), log=lambda _message: None)


def _tamper_attempts(store: RunStore, pass_no: int, mutate: Any) -> None:
    """改写某 pass 的尝试文件并重算 `record_sha256`（模拟「改完再补 hash」）。"""
    path = store.review_dir / f"ai-attempts-pass{pass_no}.jsonl"
    payloads = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    mutate(payloads)
    for payload in payloads:
        payload["record_sha256"] = sha256_value(
            {key: value for key, value in payload.items() if key != "record_sha256"}
        )
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in payloads) + "\n", encoding="utf-8"
    )


async def test_scored_body_must_match_the_raw_response(tmp_path: Path, settings_for_tests: Any) -> None:
    """`response_text` 被改写（连同 parsed 与全部 hash）必须判违反，而不是只看 raw_response 自证。

    缺口：`_verify_attempts` 只核 `raw_response_sha256` 的自洽与「正文可重新解析」，
    从不把正文与 `raw_response` 里那条 message 对照——原始响应因此可以和评分正文说两件事。
    """
    store = await _exported_run(tmp_path, settings=settings_for_tests)
    await _frozen_and_scored(store, hard="yes")
    baseline = verify_ai_review_report(store, require_complete=True)
    assert baseline.ok, f"正控：干净通道必须通过 {baseline.violations}"

    cases = {case.id: case for case in load_frozen_cases(store).cases}
    inputs = {item.blind_id: item for item in build_scoring_inputs(store)}

    def _inflate(records: list[dict[str, Any]]) -> None:
        for record in records:
            scoring = inputs[str(record["blind_id"])]
            quote = f"{_system_of(store, record['blind_id'])} 组的回复"
            new_text = json.dumps(_score_payload(quote, hard="no"), ensure_ascii=False)
            record["response_text"] = new_text
            record["parsed"] = parse_judge_output(
                new_text,
                case=cases[str(record["case_id"])],
                blind_id=scoring.blind_id,
                input_payload=scoring.payload,
            )
            record["parsed_sha256"] = sha256_value(record["parsed"])

    # 两个 pass 一起改：保持「两份评分一致」，让本例只可能因「正文与原始响应矛盾」而红。
    for pass_no in (1, 2):
        _tamper_attempts(store, pass_no, _inflate)

    report = verify_ai_review_report(store, require_complete=True)
    assert not report.ok, "评分正文被改写（raw_response 仍是原分）后校验仍通过：原始响应与评分正文可以互相矛盾"
    assert any("raw_response" in item or "原始响应" in item for item in report.violations), report.violations


async def test_require_complete_rejects_a_packet_smaller_than_the_expected_groups(
    tmp_path: Path, settings_for_tests: Any
) -> None:
    """评审包组数 < 案例数 × 组别数且 require_complete=True 时必须判违反（不能只 warn）。

    缺口：`verify_ai_review_report` 对「包内组数 < 期望组数」只 append warning；
    而 `summarize_ai_review` 对同一情形判 pending、拒出结论——两处口径不一致。
    """
    store = await _exported_run(tmp_path, settings=settings_for_tests, count=2, case_ids=["CFB-C-001"])
    await _frozen_and_scored(store)
    assert len(build_scoring_inputs(store)) == 3, "前置条件：评审包只有 1 个案例 × 3 组"

    assert summarize_ai_review(store, require_complete=True)["status"] == "pending", (
        "正控：汇总层对「组未进评审包」已判 pending"
    )
    report = verify_ai_review_report(store, require_complete=True)
    assert not report.ok, (
        "require_complete=True 但评审包只有 3/6 组："
        f"verify 只给了 warning {report.warnings}，违反项为空——一个「正式的」AI 结论可以只覆盖一半组"
    )


async def test_resume_must_not_drop_the_ai_identity_and_packet_anchors(tmp_path: Path, settings_for_tests: Any) -> None:
    """`resume` 重写 manifest 后，`review.ai` 与 `review.packet_sha256` 必须仍在。

    缺口：`manifest.build_manifest` 每次都写入字面量 `review` 段，于是任何一次
    `execute(resume=True)` 都会抹掉身份锚与评审包锚，verify 随后只剩 warning。
    """
    store = await _exported_run(tmp_path, settings=settings_for_tests)
    await _frozen_and_scored(store)
    before = store.read_manifest()["review"]
    assert before.get("ai", {}).get("identity_sha256"), "前置条件：冻结后应有身份锚"
    assert before.get("packet_sha256"), "前置条件：导出后应有评审包锚"

    await execute(
        store=store,
        config=RunConfig(label="calibration"),
        case_set=load_cases(store.cases_path),
        snapshot=make_snapshot(),
        faults=FaultPlan(requested={}),
        settings=settings_for_tests,
        adapters={system_id: FakeAdapter(system_id) for system_id in ("A", "B", "C")},
        resume=True,
        log=lambda _message: None,
    )

    after = store.read_manifest()["review"]
    assert after.get("ai", {}).get("identity_sha256") == before["ai"]["identity_sha256"], (
        "resume 之后 manifest 不再锚定 AI 身份 hash：身份退回「只靠文件自证」"
    )
    assert after.get("packet_sha256") == before["packet_sha256"], "resume 之后评审包锚丢失：评审包不再绑到本批次"


async def test_formal_batch_must_reject_a_calibration_stage_identity(tmp_path: Path, settings_for_tests: Any) -> None:
    """`label=test` 的批次不得用 `stage=calibration` 的身份出 AI 结论。

    缺口：`_verify_identity` 只校验 stage 取值合法与 hash 自洽，从不把 stage 与批次
    label 对照；而 `calibration` 分支允许在已有评分尝试之后再冻结身份，
    即「正式成绩」可由事后选定的量表/模型产出。
    """
    store = await _exported_run(tmp_path, settings=settings_for_tests)
    await _frozen_and_scored(store)
    assert verify_ai_review_report(store, require_complete=True).ok

    # 模拟旧版留下的正式批次：读回也必须拒绝，不能只守住新身份入口。
    manifest = store.read_manifest()
    manifest["label"] = "test"
    store.write_manifest(manifest)
    assert store.read_manifest()["label"] == "test", "前置条件：批次标为正式"
    assert load_identity(store)["stage"] == "calibration", "前置条件：身份是校准阶段冻结的"

    with pytest.raises(AiReviewError, match="stage=formal"):
        freeze_judges(store, judges=default_judges("stub-model"), stage="calibration", log=lambda _message: None)

    report = verify_ai_review_report(store, require_complete=True)
    assert not report.ok, (
        "正式批次（label=test）带着 stage=calibration 的 AI 身份仍判通过："
        "「正式身份必须在评分开始前冻结」这条约束在证据里不可见"
    )
