"""AI 独立评分通道的确定性测试：盲化输入、严格 schema、只追加、汇总与校验。

不联网、不连库：评分调用走注入的客户端替身，其余链路都是真的。
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio

from evaluation.carebench.ai_review import (
    ADJUDICATION_ATTEMPTS_FILE,
    ATTEMPTS_FILES,
    DIMENSION_KEYS,
    AiReviewError,
    JudgeIdentity,
    ScoreSchemaError,
    append_attempt,
    build_scoring_inputs,
    default_adjudicator,
    default_judges,
    freeze_judges,
    load_adjudication_attempts,
    load_adjudications,
    load_attempts,
    load_frozen_cases,
    load_identity,
    parse_judge_output,
    prepare_ai_review,
    record_adjudication,
    summarize_ai_review,
    summary_ai,
    verify_ai_review,
    verify_ai_review_report,
)
from evaluation.carebench.ai_runner import adjudicate_run, score_run
from evaluation.carebench.config import RunConfig
from evaluation.carebench.faults import FaultPlan
from evaluation.carebench.review import PACKET_FILE, export_packet
from evaluation.carebench.runner import execute
from evaluation.carebench.store import RunStore, create_run_dir, read_json, write_json, write_jsonl
from evaluation.carebench.systems.base import TurnOutcome

from .conftest import FakeAdapter, load_cases, make_cases_file, make_snapshot


async def _exported_run(
    tmp_path: Path,
    *,
    settings: Any,
    faults: FaultPlan,
    count: int = 1,
    structured: bool = False,
    case_ids: list[str] | None = None,
    label: str = "calibration",
) -> RunStore:
    """跑满一个批次并导出盲化评审包（评分包不含组别）。"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    case_set = load_cases(make_cases_file(tmp_path / "cases.jsonl", count=count))
    adapters = {
        system_id: FakeAdapter(
            system_id,
            outcome=lambda _request, text=f"{system_id} 组的回复": TurnOutcome(
                status="completed",
                raw_output=text,
                structured=(
                    [{"kind": "action_card", "label": "确认选项", "system": "模型自述", "model_id": "x"}]
                    if structured
                    else []
                ),
                latency_ms=100,
            ),
        )
        for system_id in ("A", "B", "C")
    }
    store = create_run_dir(tmp_path / "runs", "carebench-ai")
    await execute(
        store=store,
        config=RunConfig(label=label),
        case_set=case_set,
        snapshot=make_snapshot(),
        faults=faults,
        settings=settings,
        adapters=adapters,
        case_ids=case_ids,
        log=lambda _message: None,
    )
    export_packet(store, log=lambda _message: None)
    return store


def _system_of(store: RunStore, blind_id: str) -> str:
    """从盲化映射取组别（只给测试造引用用）。"""
    mapping = read_json(store.review_dir / "blind-map.json")["map"]
    for per_case in mapping.values():
        if blind_id in per_case:
            return per_case[blind_id]
    raise AssertionError(blind_id)


def _quote_of(store: RunStore, blind_id: str) -> str:
    """该 blind 的真实输出片段（引用必须逐字存在）。"""
    return f"{_system_of(store, blind_id)} 组的回复"


def _evidence(quote: str | None, *, turn: int | None = 1, note: str = "") -> dict[str, Any]:
    """证据对象（缺省为真实引用；None 表示明确缺失）。"""
    if quote is None:
        return {"quote": None, "missing": True, "turn": None, "note": note or "输出没有对应表述"}
    return {"quote": quote, "missing": False, "turn": turn, "note": note}


def _judge_payload(
    *,
    quote: str | None,
    hard: str = "no",
    scores: tuple[int, int, int, int, int] = (2, 2, 2, 2, 2),
    must_check: str = "pass",
    must_not: str = "respected",
    reason: str = "测试理由",
) -> dict[str, Any]:
    """一份 schema 合法的评分输出。"""
    return {
        "hard_failure": {
            "value": hard,
            "reason": reason,
            "failure_types": ["other_critical"] if hard == "yes" else [],
        },
        "dimensions": {
            key: {"score": score, "reason": "理由", "evidence": _evidence(quote)}
            for key, score in zip(DIMENSION_KEYS, scores, strict=True)
        },
        "must_check": [{"id": "MC-1", "status": must_check, "evidence": _evidence(quote)}],
        "must_not": [{"id": "MN-1", "status": must_not, "evidence": _evidence(quote)}],
    }


class _Response:
    """脚本化 chat.completions 响应。"""

    def __init__(self, text: str) -> None:
        self.id = "resp-test"
        self.model = "stub-model"
        self.choices = [type("Choice", (), {"message": type("Message", (), {"content": text})()})()]

    def model_dump(self) -> dict[str, Any]:
        """SDK 形状的原始响应。"""
        return {
            "id": self.id,
            "model": self.model,
            "choices": [{"message": {"role": "assistant", "content": self.choices[0].message.content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }


class _Completions:
    """按 (pass, blind) 返回预设正文。"""

    def __init__(self, store: RunStore, handler: Any) -> None:
        self.store = store
        self.handler = handler
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _Response:
        """记录请求并返回替身响应。"""
        self.calls.append(kwargs)
        identity = load_identity(self.store)
        pass_no = 1 if kwargs["messages"][0]["content"] == identity["judges"]["1"]["prompt_text"] else 2
        match = re.search(r'"blind_id": "([^"]+)"', kwargs["messages"][1]["content"])
        assert match is not None
        outcome = self.handler(pass_no, match.group(1))
        if isinstance(outcome, BaseException):
            raise outcome
        return _Response(outcome)


class _Client:
    """最小异步客户端。"""

    def __init__(self, store: RunStore, handler: Any) -> None:
        self.chat = type("Chat", (), {"completions": _Completions(store, handler)})()

    @property
    def calls(self) -> list[dict[str, Any]]:
        """透传调用记录。"""
        return self.chat.completions.calls


def _freeze(store: RunStore, *, model_id: str = "stub-model") -> tuple[JudgeIdentity, JudgeIdentity]:
    """冻结默认两位评分者（不冻结裁定者）。"""
    judges = default_judges(model_id)
    freeze_judges(store, judges=judges, stage="calibration", log=lambda _message: None)
    return judges


def _freeze_with_adjudicator(store: RunStore) -> JudgeIdentity:
    """冻结两位评分者与一位独立裁定者。"""
    judges = default_judges("stub-model")
    adjudicator = default_adjudicator("adjudicator-model")
    freeze_judges(store, judges=judges, adjudicator=adjudicator, stage="calibration", log=lambda _message: None)
    return adjudicator


async def _score_all(store: RunStore, handler: Any) -> tuple[Any, _Client]:
    """跑两套评分（注入客户端）。"""
    client = _Client(store, handler)
    result = await score_run(store, client=client, log=lambda _message: None)
    return result, client


def _cases(store: RunStore) -> dict[str, Any]:
    """测试辅助：冻结案例按 id 索引。"""
    return {case.id: case for case in load_frozen_cases(store).cases}


def _set_first_output_start(store: RunStore, value: str) -> None:
    """把全部系统输出的开始时间改成指定值（只用于测试时间门禁）。"""
    records = store.read_outputs()
    for record in records:
        record["started_at"] = value
    write_jsonl(store.outputs_path, records)


# ---------------------------------------------------------------------------
# 输入与解析
# ---------------------------------------------------------------------------


async def test_scoring_input_is_blinded_and_complete(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """输入含背景/约束/逐轮原文，不含组别、映射或轨迹。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    inputs = build_scoring_inputs(store)
    assert len(inputs) == 3
    for item in inputs:
        assert set(item.payload) == {
            "blind_id",
            "case_id",
            "shared_context",
            "turns",
            "must_check",
            "must_not",
        }
        assert item.payload["shared_context"]
        assert item.payload["must_check"][0]["id"] == "MC-1"
        assert item.payload["must_not"][0]["id"] == "MN-1"
        assert item.payload["turns"][0]["output"] == _quote_of(store, item.blind_id)
        dumped = json.dumps(item.payload, ensure_ascii=False)
        assert "system_id" not in dumped
        assert "blind-map" not in dumped
        assert '"trace' not in dumped
    assert [item.sha256 for item in inputs] == [item.sha256 for item in build_scoring_inputs(store)]


async def test_business_structured_fields_are_not_rejected(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """卡片/提问里的 label/system/model_id 等业务字段原样保留，不按包装键误拒。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests, structured=True)
    inputs = build_scoring_inputs(store)
    assert any(item.payload["turns"][0]["structured_output"] for item in inputs)
    for item in inputs:
        structured_payload = item.payload["turns"][0]["structured_output"]
        assert structured_payload == [
            {"kind": "action_card", "label": "确认选项", "system": "模型自述", "model_id": "x"}
        ]


async def test_parse_rejects_missing_items_and_bad_values(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """严格 schema：缺条目、越界分、pending、假引用都不通过。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    scoring = build_scoring_inputs(store)[0]
    case = _cases(store)[scoring.case_id]
    quote = _quote_of(store, scoring.blind_id)

    valid = parse_judge_output(
        json.dumps(_judge_payload(quote=quote)),
        case=case,
        blind_id=scoring.blind_id,
        input_payload=scoring.payload,
    )
    assert valid["hard_failure"]["value"] == "no"
    assert valid["dimensions"]["c1_context"]["evidence"]["quote_present"] is True

    payload = _judge_payload(quote=quote)
    payload["must_check"] = []
    with pytest.raises(ScoreSchemaError, match="条目数"):
        parse_judge_output(json.dumps(payload), case=case, blind_id=scoring.blind_id, input_payload=scoring.payload)

    payload = _judge_payload(quote=quote, scores=(3, 2, 2, 2, 2))
    with pytest.raises(ScoreSchemaError, match="score"):
        parse_judge_output(json.dumps(payload), case=case, blind_id=scoring.blind_id, input_payload=scoring.payload)

    payload = _judge_payload(quote=quote)
    payload["hard_failure"]["value"] = "pending"
    with pytest.raises(ScoreSchemaError, match="hard_failure.value"):
        parse_judge_output(json.dumps(payload), case=case, blind_id=scoring.blind_id, input_payload=scoring.payload)

    payload = _judge_payload(quote="这句话不在输出里")
    with pytest.raises(ScoreSchemaError, match="不在指定轮次"):
        parse_judge_output(json.dumps(payload), case=case, blind_id=scoring.blind_id, input_payload=scoring.payload)

    payload = _judge_payload(quote=None)
    assert (
        parse_judge_output(json.dumps(payload), case=case, blind_id=scoring.blind_id, input_payload=scoring.payload)[
            "dimensions"
        ]["c1_context"]["evidence"]["missing"]
        is True
    )

    payload["dimensions"]["c1_context"]["evidence"]["note"] = ""
    with pytest.raises(ScoreSchemaError, match="note"):
        parse_judge_output(json.dumps(payload), case=case, blind_id=scoring.blind_id, input_payload=scoring.payload)


# ---------------------------------------------------------------------------
# 身份冻结
# ---------------------------------------------------------------------------


async def test_freeze_requires_distinct_prompts_and_precedes_scoring(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """同提示不是两次独立评分；正式身份必须在评分前冻结且不可替换。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    first, second = default_judges("stub-model")
    duplicated = JudgeIdentity(
        pass_no=2,
        rater_id="other",
        model_id="stub-model",
        prompt_version=first.prompt_version,
        prompt_text=first.prompt_text,
    )
    with pytest.raises(AiReviewError, match="提示必须不同"):
        freeze_judges(store, judges=(first, duplicated), stage="calibration", log=lambda _message: None)

    frozen = freeze_judges(store, judges=(first, second), stage="calibration", log=lambda _message: None)
    assert frozen["identity_sha256"] == load_identity(store)["identity_sha256"]
    assert read_json(store.review_dir / "ai-review-identity.json")["judges"]["1"]["pass"] == 1
    assert store.read_manifest()["review"]["ai"]["identity_sha256"] == frozen["identity_sha256"]

    assert freeze_judges(store, judges=(first, second), stage="calibration", log=lambda _message: None) == frozen
    changed = default_judges("another-model")
    with pytest.raises(AiReviewError, match="已冻结"):
        freeze_judges(store, judges=changed, stage="calibration", log=lambda _message: None)

    other = await _exported_run(tmp_path / "second", settings=settings_for_tests, faults=faults_for_tests)
    append_attempt(other, 1, {"blind_id": "x", "status": "ok", "case_id": "CFB-C-001"})
    with pytest.raises(AiReviewError, match="评分开始前"):
        freeze_judges(other, judges=default_judges("stub-model"), stage="formal", log=lambda _message: None)


async def test_formal_identity_must_precede_first_system_output(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """正式身份晚于首次系统输出即违规；校准不套这条门禁；同秒不算晚。"""
    calibration = await _exported_run(tmp_path / "calibration", settings=settings_for_tests, faults=faults_for_tests)
    _set_first_output_start(calibration, "2000-01-01T00:00:00+00:00")
    _freeze(calibration)
    assert not any("晚于首次系统输出" in item for item in verify_ai_review_report(calibration).violations)

    late = await _exported_run(tmp_path / "late", settings=settings_for_tests, faults=faults_for_tests)
    _set_first_output_start(late, "2000-01-01T00:00:00+00:00")
    freeze_judges(
        late,
        judges=default_judges("stub-model"),
        adjudicator=default_adjudicator("stub-model"),
        stage="formal",
        log=lambda _message: None,
    )
    assert any("晚于首次系统输出" in item for item in verify_ai_review_report(late).violations)

    early = await _exported_run(tmp_path / "early", settings=settings_for_tests, faults=faults_for_tests)
    _set_first_output_start(early, "2999-01-01T00:00:00+00:00")
    freeze_judges(
        early,
        judges=default_judges("stub-model"),
        adjudicator=default_adjudicator("stub-model"),
        stage="formal",
        log=lambda _message: None,
    )
    assert not any("晚于首次系统输出" in item for item in verify_ai_review_report(early).violations)


# ---------------------------------------------------------------------------
# 执行器：只追加、失败保留
# ---------------------------------------------------------------------------


async def test_score_run_records_raw_attempts_and_never_overwrites(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """成功/无效/失败都落原始请求与响应；成功分不覆盖，重评只追加。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    _freeze(store)

    def handler(pass_no: int, blind: str) -> Any:
        if pass_no == 1:
            return json.dumps(_judge_payload(quote=_quote_of(store, blind)))
        return "这不是 JSON"

    result, _client = await _score_all(store, handler)
    assert result.ok == 3
    assert result.invalid == 3

    pass1 = load_attempts(store, 1)
    pass2 = load_attempts(store, 2)
    assert len(pass1) == 3 and len(pass2) == 3
    for record in pass1:
        assert record["status"] == "ok"
        assert record["request"]["messages"][0]["role"] == "system"
        assert record["request_sha256"]
        assert record["raw_response"]["choices"][0]["message"]["content"]
        assert record["identity"]["prompt_sha256"] == load_identity(store)["judges"]["1"]["prompt_sha256"]
    for record in pass2:
        assert record["status"] == "invalid"
        assert record["parsed"] is None
        assert record["errors"]

    result, _client = await _score_all(store, handler)
    assert result.skipped == 3
    assert result.invalid == 3
    assert [record["attempt"] for record in load_attempts(store, 2)] == [1, 1, 1, 2, 2, 2]
    assert all(record["status"] == "invalid" for record in load_attempts(store, 2)[:3])

    def failing(_pass_no: int, _blind: str) -> Any:
        return RuntimeError("endpoint down")

    result, _client = await _score_all(store, failing)
    assert result.error == 3
    latest = load_attempts(store, 2)[-3:]
    assert [record["status"] for record in latest] == ["error", "error", "error"]
    assert latest[0]["errors"] == ["RuntimeError"]
    assert latest[0]["raw_response"] is None

    with pytest.raises(AiReviewError, match="已有成功评分"):
        append_attempt(store, 1, {"blind_id": pass1[0]["blind_id"], "status": "ok"})


async def test_two_passes_are_stateless_and_independent(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """两 pass 各自一份 system 提示，单轮、无共享上下文。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    _freeze(store)
    _result, client = await _score_all(
        store, lambda _pass, blind: json.dumps(_judge_payload(quote=_quote_of(store, blind)))
    )

    identity = load_identity(store)
    assert len(client.calls) == 6
    systems: dict[str, set[str]] = {}
    users: dict[str, set[str]] = {}
    for call in client.calls:
        assert [message["role"] for message in call["messages"]] == ["system", "user"]
        systems.setdefault(call["messages"][1]["content"], set()).add(call["messages"][0]["content"])
        users.setdefault(call["messages"][0]["content"], set()).add(call["messages"][1]["content"])
    assert identity["judges"]["1"]["prompt_text"] in users
    assert identity["judges"]["2"]["prompt_text"] in users
    for value in systems.values():
        assert len(value) == 2
    for value in users.values():
        assert len(value) == 3


async def test_runner_accepts_gateway_with_only_client(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """外部 gateway 只提供 .client 时也能用，且不被 runner 关闭。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    _freeze(store)
    client = _Client(store, lambda _pass, blind: json.dumps(_judge_payload(quote=_quote_of(store, blind))))
    gateway = type("GatewayOnlyClient", (), {"client": client})()
    result = await score_run(store, gateway=gateway, log=lambda _message: None)
    assert result.ok == 6


# ---------------------------------------------------------------------------
# 汇总（不碰人工字段）
# ---------------------------------------------------------------------------


async def test_summary_ai_never_counts_invalid_or_needs_review_as_pass(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """无成功评分/未裁定分歧/needs_review 都进 unresolved，不算通过。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    adjudicator = _freeze_with_adjudicator(store)

    def handler(pass_no: int, blind: str) -> Any:
        hard = "no" if pass_no == 1 else "needs_review"
        return json.dumps(_judge_payload(quote=_quote_of(store, blind), hard=hard))

    await _score_all(store, handler)
    summary = summary_ai(store)["ai_scores"]
    assert summary["counts"]["pass1"]["ok"] == 3
    assert summary["counts"]["pass2"]["ok"] == 3
    assert summary["disagreements"] and summary["adjudication"]["missing"] == 3
    assert summary["hard_failure"]["resolved"]["unresolved"] == 3
    assert summary["safety_gate"]["pass"] == 0
    assert summary["paired"]["A-B"]["unresolved"] == 1

    blind = sorted(summary["disagreements"], key=lambda item: item["blind_id"])[0]["blind_id"]
    record_adjudication(
        store,
        blind_id=blind,
        adjudicator=adjudicator,
        raw_text=json.dumps(
            _judge_payload(quote=_quote_of(store, blind), hard="needs_review") | {"reason": "证据不足"}
        ),
        log=lambda _message: None,
    )
    summary = summary_ai(store)["ai_scores"]
    assert summary["hard_failure"]["resolved"]["needs_review"] == 1
    assert summary["hard_failure"]["resolved"]["unresolved"] == 2
    assert summary["safety_gate"]["pass"] == 0
    assert summary["adjudication"]["present"] == 1
    assert summary["adjudication"]["missing"] == 2

    assert not (store.review_dir / "ratings.imported.csv").exists()
    assert store.read_manifest()["review"]["human_scores_available"] is False
    assert "human_scores" not in summary


async def test_summary_ai_agreement_and_paired_safety_prior(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """原始一致率、逐条分母与配对的安全先决都要可复算。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    adjudicator = _freeze_with_adjudicator(store)
    inputs = build_scoring_inputs(store)
    system_by_blind = {item.blind_id: _system_of(store, item.blind_id) for item in inputs}
    c_blind = next(blind for blind, system in system_by_blind.items() if system == "C")

    def handler(pass_no: int, blind: str) -> Any:
        if blind == c_blind:
            return json.dumps(_judge_payload(quote=_quote_of(store, blind), hard="yes"))
        scores = (2, 2, 2, 2, 2) if pass_no == 1 else (1, 1, 1, 1, 1)
        return json.dumps(_judge_payload(quote=_quote_of(store, blind), scores=scores))

    await _score_all(store, handler)
    summary = summary_ai(store)["ai_scores"]
    assert summary["agreement"]["hard_failure"] == {"agree": 3, "total": 3, "rate": 1.0}
    assert summary["agreement"]["dimensions"]["c1_context"] == {"agree": 1, "total": 3, "rate": 0.3333}
    assert summary["agreement"]["must_check"]["total"] == 3

    for disagreement in summary["disagreements"]:
        record_adjudication(
            store,
            blind_id=disagreement["blind_id"],
            adjudicator=adjudicator,
            raw_text=json.dumps(
                _judge_payload(quote=_quote_of(store, disagreement["blind_id"]), scores=(2, 2, 2, 2, 2))
                | {"reason": "证据支持 2 分"}
            ),
            log=lambda _message: None,
        )

    summary = summary_ai(store)["ai_scores"]
    assert summary["hard_failure"]["resolved"]["yes"] == 1
    assert summary["hard_failure"]["resolved"]["no"] == 2
    assert summary["paired"]["A-C"]["blocked_by_safety"] == 1
    assert summary["paired"]["B-C"]["blocked_by_safety"] == 1
    assert summary["paired"]["A-B"]["tie"] == 1
    assert summary["must_check"]["resolved"]["denominator"] == 3
    assert summary["must_check"]["expected_denominator"] == 3
    assert summary["dimensions"]["resolved"]["c1_context"]["mean"] == 2.0


async def test_summary_ai_per_system_and_category_breakdown(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """per_system / category×system 能区分 A/B/C 的五维、硬失败与约束覆盖。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    _freeze_with_adjudicator(store)
    levels = {"A": 2, "B": 1, "C": 0}
    checks = {"A": "pass", "B": "fail", "C": "unclear"}
    not_checks = {"A": "respected", "B": "violated", "C": "unclear"}

    def handler(_pass: int, blind: str) -> Any:
        system = _system_of(store, blind)
        score = levels[system]
        return json.dumps(
            _judge_payload(
                quote=_quote_of(store, blind),
                scores=(score, score, score, score, score),
                must_check=checks[system],
                must_not=not_checks[system],
            )
        )

    await _score_all(store, handler)
    summary = summary_ai(store)["ai_scores"]
    assert summary["per_system"]["A"]["dimensions"]["c1_context"] == {
        "groups": 1,
        "mean": 2.0,
        "median": 2.0,
    }
    assert summary["per_system"]["B"]["dimensions"]["c1_context"]["mean"] == 1.0
    assert summary["per_system"]["C"]["dimensions"]["c1_context"]["mean"] == 0.0
    assert summary["per_system"]["A"]["hard_failure"] == {
        "yes": 0,
        "no": 1,
        "needs_review": 0,
        "unresolved": 0,
    }
    assert summary["per_system"]["A"]["must_check"]["passed"] == 1
    assert summary["per_system"]["B"]["must_check"]["failed"] == 1
    assert summary["per_system"]["C"]["must_check"]["unclear"] == 1
    assert summary["per_system"]["B"]["must_not"]["violated"] == 1
    assert summary["bycategory_system"]["日常照护"]["C"]["must_check"]["denominator"] == 1
    assert summary["bycategory_system"]["日常照护"]["C"]["dimensions"]["c2_action"]["mean"] == 0.0
    assert summary["safety_gate"]["hard_failure_no"] == 3
    assert summary["safety_gate"]["strict_pass"] == 1
    assert summary["safety_gate"]["pass"] == 1
    assert summary["safety_gate"]["failed_checks"] == 1
    assert summary["safety_gate"]["violated_checks"] == 1


async def test_summary_ai_per_system_keeps_missing_denominator(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """缺组不缩分母：未评的 B/C 仍是 unresolved，条目分母保留，summary 保持 pending。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    _freeze_with_adjudicator(store)
    a_blind = next(item.blind_id for item in build_scoring_inputs(store) if _system_of(store, item.blind_id) == "A")
    client = _Client(store, lambda _pass, blind: json.dumps(_judge_payload(quote=_quote_of(store, blind))))
    await score_run(store, client=client, blind_ids=[a_blind], log=lambda _message: None)

    pending = summarize_ai_review(store)
    assert pending is not None and pending["status"] == "pending"
    summary = summary_ai(store)["ai_scores"]
    assert summary["per_system"]["A"]["scored_groups"] == 1
    assert summary["per_system"]["B"]["expected_groups"] == 1
    assert summary["per_system"]["B"]["scored_groups"] == 0
    assert summary["per_system"]["B"]["hard_failure"]["unresolved"] == 1
    assert summary["per_system"]["B"]["must_check"] == {
        "passed": 0,
        "failed": 0,
        "unclear": 0,
        "denominator": 1,
        "scored_denominator": 0,
    }
    assert summary["per_system"]["B"]["dimensions"]["c1_context"] == {
        "groups": 0,
        "mean": None,
        "median": None,
    }


# ---------------------------------------------------------------------------
# 分歧裁定执行器（只追加尝试）
# ---------------------------------------------------------------------------


async def _disagree_store(tmp_path: Path, *, settings: Any, faults: FaultPlan) -> tuple[RunStore, JudgeIdentity]:
    """构造一个两份评分都在五维上有分歧的批次。"""
    store = await _exported_run(tmp_path, settings=settings, faults=faults)
    adjudicator = _freeze_with_adjudicator(store)
    await _score_all(
        store,
        lambda pass_no, blind: json.dumps(
            _judge_payload(
                quote=_quote_of(store, blind),
                scores=(2, 2, 2, 2, 2) if pass_no == 1 else (1, 1, 1, 1, 1),
            )
        ),
    )
    return store, adjudicator


def _adjudication_text(store: RunStore, blind: str, *, hard: str = "no") -> str:
    """合法裁定输出（含总体理由）。"""
    return json.dumps(
        _judge_payload(quote=_quote_of(store, blind), hard=hard, scores=(2, 2, 2, 2, 2))
        | {"reason": "逐条证据支持 2 分"}
    )


async def test_adjudicate_run_appends_attempts_and_skips_finalized(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """成功裁定写尝试+记录并互相链接；已裁定跳过、不重复打模型。"""
    store, _adjudicator = await _disagree_store(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    client = _Client(store, lambda _pass, blind: _adjudication_text(store, blind))
    result = await adjudicate_run(store, client=client, log=lambda _message: None)
    assert result.total == 3 and result.ok == 3
    attempts = load_adjudication_attempts(store)
    assert [record["status"] for record in attempts] == ["ok", "ok", "ok"]
    finals = load_adjudications(store)
    assert len(finals) == 3
    for final in finals:
        assert final["attempt_record_sha256"] in {record["record_sha256"] for record in attempts}
    report = verify_ai_review_report(store, require_complete=True)
    assert report.ok, report.violations

    second_client = _Client(store, lambda _pass, _blind: "不应调用模型")
    skipped = await adjudicate_run(store, client=second_client, log=lambda _message: None)
    assert skipped.skipped == 3 and skipped.ok == 0
    assert second_client.calls == []


async def test_adjudicate_run_keeps_invalid_and_error_attempts(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """无效/异常裁定尝试原样保留；重跑追加 attempt，不覆盖。"""
    store, _adjudicator = await _disagree_store(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    invalid = await adjudicate_run(
        store, client=_Client(store, lambda _pass, _blind: "不是 JSON"), log=lambda _message: None
    )
    assert invalid.invalid == 3
    assert len(load_adjudications(store)) == 0

    error = await adjudicate_run(
        store, client=_Client(store, lambda _pass, _blind: RuntimeError("down")), log=lambda _message: None
    )
    assert error.error == 3
    attempts = load_adjudication_attempts(store)
    assert [record["status"] for record in attempts] == ["invalid"] * 3 + ["error"] * 3
    assert [record["attempt"] for record in attempts] == [1, 1, 1, 2, 2, 2]

    ok = await adjudicate_run(
        store,
        client=_Client(store, lambda _pass, blind: _adjudication_text(store, blind)),
        log=lambda _message: None,
    )
    assert ok.ok == 3
    attempts = load_adjudication_attempts(store)
    assert len(attempts) == 9
    assert [record["attempt"] for record in attempts[-3:]] == [3, 3, 3]
    assert {record["status"] for record in attempts} == {"invalid", "error", "ok"}
    assert verify_ai_review_report(store, require_complete=True).ok


async def test_adjudicate_run_propagates_cancelled_error(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """CancelledError 不当作普通错误吞掉。"""
    store, _adjudicator = await _disagree_store(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    with pytest.raises(asyncio.CancelledError):
        await adjudicate_run(
            store,
            client=_Client(store, lambda _pass, _blind: asyncio.CancelledError()),
            log=lambda _message: None,
        )
    assert load_adjudication_attempts(store) == []


async def test_adjudicate_run_recovers_orphan_ok_attempt(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan, monkeypatch: Any
) -> None:
    """成功尝试已落盘但裁定记录中断时，下次直接用尝试补记录，不重打模型。"""
    from evaluation.carebench import ai_runner as ai_runner_module

    store, _adjudicator = await _disagree_store(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    real = ai_runner_module.record_adjudication

    def crash(*_args: Any, **_kwargs: Any) -> Any:
        raise AiReviewError("模拟中断")

    monkeypatch.setattr(ai_runner_module, "record_adjudication", crash)
    with pytest.raises(AiReviewError, match="模拟中断"):
        await adjudicate_run(
            store,
            client=_Client(store, lambda _pass, blind: _adjudication_text(store, blind)),
            log=lambda _message: None,
        )
    assert len(load_adjudications(store)) == 0
    assert [record["status"] for record in load_adjudication_attempts(store)] == ["ok", "ok", "ok"]

    monkeypatch.setattr(ai_runner_module, "record_adjudication", real)
    client = _Client(store, lambda _pass, _blind: "不应调用模型")
    result = await adjudicate_run(store, client=client, log=lambda _message: None)
    assert result.ok == 3
    assert client.calls == []
    assert len(load_adjudications(store)) == 3


# ---------------------------------------------------------------------------
# 校验：篡改必须被抓住
# ---------------------------------------------------------------------------


async def _scored_agreed(store: RunStore) -> None:
    """两 pass 完全一致的一批评分。"""
    _freeze_with_adjudicator(store)
    await _score_all(store, lambda _pass, blind: json.dumps(_judge_payload(quote=_quote_of(store, blind))))


def _rewrite(path: Path, mutate: Any) -> None:
    """改写 JSONL 并重算记录 hash（模拟「连 hash 一起改」的篡改）。"""
    from evaluation.carebench.hashing import sha256_value

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    mutate(lines)
    for record in lines:
        if "record_sha256" in record:
            record["record_sha256"] = sha256_value(
                {key: value for key, value in record.items() if key != "record_sha256"}
            )
    path.write_text("".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in lines), "utf-8")


async def test_verify_passes_and_recomputes_hashes(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """干净批次通过；校验给出可复核事实。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    await _scored_agreed(store)
    report = verify_ai_review_report(store, require_complete=True)
    assert report.ok, report.violations
    assert report.facts["pass1_ok"] == 3 and report.facts["pass2_ok"] == 3
    assert report.facts["case_groups_expected"] == 3


async def test_verify_detects_parsed_and_input_tampering(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """即使重算 record hash，原始响应与输入重建仍能发现评分/输入不一致。"""
    from evaluation.carebench.hashing import sha256_value

    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    await _scored_agreed(store)

    def tamper_parsed(lines: list[dict[str, Any]]) -> None:
        lines[0]["parsed"]["dimensions"]["c1_context"]["score"] = 0
        lines[0]["parsed_sha256"] = sha256_value(lines[0]["parsed"])

    _rewrite(store.review_dir / ATTEMPTS_FILES[1], tamper_parsed)
    report = verify_ai_review_report(store)
    assert any("重新解析的结果不一致" in item for item in report.violations), report.violations

    store2 = await _exported_run(tmp_path / "second", settings=settings_for_tests, faults=faults_for_tests)
    await _scored_agreed(store2)

    def tamper_input(lines: list[dict[str, Any]]) -> None:
        lines[0]["input"]["shared_context"] = "被改过的背景"
        lines[0]["input_sha256"] = sha256_value(lines[0]["input"])

    _rewrite(store2.review_dir / ATTEMPTS_FILES[1], tamper_input)
    report = verify_ai_review_report(store2)
    assert any("输入与评审包+冻结案例重建的结果不一致" in item for item in report.violations), report.violations


async def test_verify_rejects_response_text_disagreeing_with_raw_response(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """只改正文/parsed/hash、保留原始响应时，必须报出两者矛盾。"""
    from evaluation.carebench.hashing import sha256_value

    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    _freeze_with_adjudicator(store)
    await _score_all(store, lambda _pass, blind: json.dumps(_judge_payload(quote=_quote_of(store, blind), hard="yes")))
    assert verify_ai_review_report(store, require_complete=True).ok
    inputs = {item.blind_id: item for item in build_scoring_inputs(store)}
    cases = _cases(store)

    def inflate(lines: list[dict[str, Any]]) -> None:
        for record in lines:
            scoring = inputs[str(record["blind_id"])]
            text = json.dumps(_judge_payload(quote=_quote_of(store, str(record["blind_id"])), hard="no"))
            record["response_text"] = text
            record["parsed"] = parse_judge_output(
                text,
                case=cases[str(record["case_id"])],
                blind_id=scoring.blind_id,
                input_payload=scoring.payload,
            )
            record["parsed_sha256"] = sha256_value(record["parsed"])

    for pass_no in (1, 2):
        _rewrite(store.review_dir / ATTEMPTS_FILES[pass_no], inflate)
    report = verify_ai_review_report(store, require_complete=True)
    assert any("response_text 与 raw_response 正文不一致" in item for item in report.violations), report.violations


async def test_verify_rejects_adjudication_body_disagreeing_with_raw_response(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """裁定尝试也核 raw_response 正文；只改正文/decision/hash 必须被拒。"""
    from evaluation.carebench.hashing import sha256_value

    store, _adjudicator = await _disagree_store(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    await adjudicate_run(
        store,
        client=_Client(store, lambda _pass, blind: _adjudication_text(store, blind)),
        log=lambda _message: None,
    )
    assert verify_ai_review_report(store, require_complete=True).ok
    inputs = {item.blind_id: item for item in build_scoring_inputs(store)}
    cases = _cases(store)

    def tamper(lines: list[dict[str, Any]]) -> None:
        record = lines[0]
        scoring = inputs[str(record["blind_id"])]
        text = json.dumps(
            _judge_payload(quote=_quote_of(store, str(record["blind_id"])), hard="yes", scores=(1, 1, 1, 1, 1))
            | {"reason": "改过的裁定"}
        )
        record["response_text"] = text
        record["decision"] = parse_judge_output(
            text,
            case=cases[str(record["case_id"])],
            blind_id=scoring.blind_id,
            input_payload=scoring.payload,
            allow_overall_reason=True,
        )
        record["decision_sha256"] = sha256_value(record["decision"])

    _rewrite(store.review_dir / ADJUDICATION_ATTEMPTS_FILE, tamper)
    report = verify_ai_review_report(store, require_complete=True)
    assert any("response_text 与 raw_response 正文不一致" in item for item in report.violations), report.violations


async def test_verify_rejects_final_adjudication_body_disagreeing_with_raw_response(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """裁定记录本身也必须让 response_text 等于 raw_response 正文（text fallback）。"""
    from evaluation.carebench.hashing import sha256_value

    store, _adjudicator = await _disagree_store(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    await adjudicate_run(
        store,
        client=_Client(store, lambda _pass, blind: _adjudication_text(store, blind)),
        log=lambda _message: None,
    )
    assert verify_ai_review_report(store, require_complete=True).ok
    inputs = {item.blind_id: item for item in build_scoring_inputs(store)}
    cases = _cases(store)

    def tamper(lines: list[dict[str, Any]]) -> None:
        record = lines[0]
        scoring = inputs[str(record["blind_id"])]
        text = json.dumps(
            _judge_payload(quote=_quote_of(store, str(record["blind_id"])), hard="yes", scores=(1, 1, 1, 1, 1))
            | {"reason": "改过的裁定"}
        )
        record["response_text"] = text
        record["decision"] = parse_judge_output(
            text,
            case=cases[str(record["case_id"])],
            blind_id=scoring.blind_id,
            input_payload=scoring.payload,
            allow_overall_reason=True,
        )
        record["decision_sha256"] = sha256_value(record["decision"])

    _rewrite(store.review_dir / "ai-adjudication.jsonl", tamper)
    report = verify_ai_review_report(store, require_complete=True)
    assert any("response_text 与 raw_response 正文不一致" in item for item in report.violations), report.violations


async def test_verify_require_complete_rejects_packet_smaller_than_expected(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """评审包组数 < 案例×组别时，require_complete 必须判违反。"""
    store = await _exported_run(
        tmp_path,
        settings=settings_for_tests,
        faults=faults_for_tests,
        count=2,
        case_ids=["CFB-C-001"],
    )
    await _scored_agreed(store)
    assert len(build_scoring_inputs(store)) == 3
    assert summarize_ai_review(store, require_complete=True)["status"] == "pending"
    report = verify_ai_review_report(store, require_complete=True)
    assert not report.ok
    assert any("组 < 期望" in item for item in report.violations), report.violations


async def test_formal_batch_requires_identity_and_packet_anchors(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan, monkeypatch: Any
) -> None:
    """label=test 缺 review.ai 身份锚或 packet 锚必须判违反。"""
    from evaluation.carebench import runner

    monkeypatch.setattr(runner, "_require_clean_code_for_formal", lambda **_kwargs: None)
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests, label="test")
    _set_first_output_start(store, "2999-01-01T00:00:00+00:00")
    freeze_judges(
        store,
        judges=default_judges("stub-model"),
        adjudicator=default_adjudicator("stub-model"),
        stage="formal",
        log=lambda _message: None,
    )
    manifest = store.read_manifest()
    manifest["review"].pop("ai", None)
    manifest["review"].pop("packet_sha256", None)
    store.write_manifest(manifest)
    report = verify_ai_review_report(store, require_complete=True)
    assert any("未锚定 AI 身份 hash" in item for item in report.violations), report.violations
    assert any("未记录 packet_sha256" in item for item in report.violations), report.violations

    blank = await _exported_run(tmp_path / "blank", settings=settings_for_tests, faults=faults_for_tests, label="test")
    assert verify_ai_review(blank)


async def test_formal_label_rejects_calibration_stage_identity(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan, monkeypatch: Any
) -> None:
    """label=test 不能用 stage=calibration 冻结或背书。"""
    from evaluation.carebench import runner

    monkeypatch.setattr(runner, "_require_clean_code_for_formal", lambda **_kwargs: None)
    formal = await _exported_run(
        tmp_path / "formal", settings=settings_for_tests, faults=faults_for_tests, label="test"
    )
    with pytest.raises(AiReviewError, match="stage=formal"):
        freeze_judges(
            formal,
            judges=default_judges("stub-model"),
            adjudicator=default_adjudicator("stub-model"),
            stage="calibration",
            log=lambda _message: None,
        )

    store = await _exported_run(tmp_path / "changed", settings=settings_for_tests, faults=faults_for_tests)
    await _scored_agreed(store)
    manifest = store.read_manifest()
    manifest["config"]["label"] = "test"
    manifest["label"] = "test"
    store.write_manifest(manifest)
    report = verify_ai_review_report(store, require_complete=True)
    assert any("不能使用 stage=calibration" in item for item in report.violations), report.violations


async def test_verify_detects_identity_and_attempt_tampering(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """身份被替换、成功分被追加都要报出来。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    await _scored_agreed(store)

    def tamper_identity(lines: list[dict[str, Any]]) -> None:
        lines[0]["identity"]["model_id"] = "swapped-model"

    _rewrite(store.review_dir / ATTEMPTS_FILES[1], tamper_identity)
    report = verify_ai_review_report(store)
    assert any("评分者身份与冻结身份不一致" in item for item in report.violations), report.violations

    store2 = await _exported_run(tmp_path / "second", settings=settings_for_tests, faults=faults_for_tests)
    await _scored_agreed(store2)

    def duplicate_ok(lines: list[dict[str, Any]]) -> None:
        clone = json.loads(json.dumps(lines[0]))
        clone["attempt"] = 2
        lines.append(clone)

    _rewrite(store2.review_dir / ATTEMPTS_FILES[1], duplicate_ok)
    report = verify_ai_review_report(store2)
    assert any("成功评分" in item for item in report.violations), report.violations


async def test_verify_requires_adjudication_for_disagreement(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """分歧无裁定：默认告警，正式完整性检查判失败。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    _freeze_with_adjudicator(store)
    await _score_all(
        store,
        lambda pass_no, blind: json.dumps(
            _judge_payload(
                quote=_quote_of(store, blind),
                scores=(2, 2, 2, 2, 2) if pass_no == 1 else (1, 2, 2, 2, 2),
            )
        ),
    )
    report = verify_ai_review_report(store)
    assert report.ok
    assert any("没有裁定记录" in item for item in report.warnings)
    report = verify_ai_review_report(store, require_complete=True)
    assert not report.ok
    assert any("没有裁定记录" in item for item in report.violations)


async def test_verify_rejects_identity_change(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """身份文件被改不能通过。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    await _scored_agreed(store)
    path = store.review_dir / "ai-review-identity.json"
    identity = read_json(path)
    identity["judges"]["2"]["model_id"] = "swapped-model"
    write_json(path, identity)
    report = verify_ai_review_report(store)
    assert not report.ok
    assert any("identity_sha256 复算不一致" in item for item in report.violations), report.violations


async def test_verify_detects_packet_and_case_tampering(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """评审包或冻结案例被改（连 manifest hash 一起改）仍与已评分记录对不上。"""
    from evaluation.carebench.hashing import sha256_file

    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    await _scored_agreed(store)
    packet = store.review_dir / PACKET_FILE
    entries = [json.loads(line) for line in packet.read_text(encoding="utf-8").splitlines() if line.strip()]
    entries[0]["turns"][0]["output"] = "被改过的输出"
    packet.write_text(
        "".join(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n" for entry in entries), "utf-8"
    )
    manifest = store.read_manifest()
    manifest["review"]["packet_sha256"] = sha256_file(packet)
    store.write_manifest(manifest)
    report = verify_ai_review_report(store)
    assert any("输入与评审包+冻结案例重建的结果不一致" in item for item in report.violations), report.violations

    store2 = await _exported_run(tmp_path / "second", settings=settings_for_tests, faults=faults_for_tests)
    await _scored_agreed(store2)
    cases = [json.loads(line) for line in store2.cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    cases[0]["must_check"] = ["被改过的核查项"]
    store2.cases_path.write_text("".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), "utf-8")
    manifest = store2.read_manifest()
    manifest["dataset"]["sha256"] = sha256_file(store2.cases_path)
    store2.write_manifest(manifest)
    report = verify_ai_review_report(store2)
    assert any("输入与评审包+冻结案例重建的结果不一致" in item for item in report.violations), report.violations


async def test_verify_detects_adjudication_tampering(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """裁定 decision 与原始响应不一致要被抓住（连 decision hash 一起改）。"""
    from evaluation.carebench.hashing import sha256_value

    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    adjudicator = _freeze_with_adjudicator(store)
    await _score_all(
        store,
        lambda pass_no, blind: json.dumps(
            _judge_payload(
                quote=_quote_of(store, blind),
                scores=(2, 2, 2, 2, 2) if pass_no == 1 else (1, 2, 2, 2, 2),
            )
        ),
    )
    summary = summary_ai(store)["ai_scores"]
    blind = summary["disagreements"][0]["blind_id"]
    record_adjudication(
        store,
        blind_id=blind,
        adjudicator=adjudicator,
        raw_text=json.dumps(
            _judge_payload(quote=_quote_of(store, blind), scores=(2, 2, 2, 2, 2)) | {"reason": "证据支持 2 分"}
        ),
        log=lambda _message: None,
    )
    manual = verify_ai_review_report(store)
    assert manual.ok
    assert any("未关联原始裁定尝试" in item for item in manual.warnings)

    def tamper(lines: list[dict[str, Any]]) -> None:
        lines[0]["decision"]["dimensions"]["c1_context"]["score"] = 0
        lines[0]["decision_sha256"] = sha256_value(lines[0]["decision"])

    _rewrite(store.review_dir / "ai-adjudication.jsonl", tamper)
    report = verify_ai_review_report(store)
    assert any("decision 与原始响应重新解析的结果不一致" in item for item in report.violations), report.violations


async def test_summary_ai_does_not_touch_human_scoring(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """AI 评分只写 ai-* 文件；人工评分仍缺席，summary 的 human_scores 仍为 null。"""
    from evaluation.carebench.summarize import summarize_run

    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    await _scored_agreed(store)
    names = sorted(path.name for path in store.review_dir.iterdir())
    assert "ratings.imported.csv" not in names
    assert set(names) >= {"ai-review-identity.json", "ai-attempts-pass1.jsonl", "ai-attempts-pass2.jsonl"}
    summary = summarize_run(store, log=lambda _message: None)
    assert summary["human_scores"] is None
    assert (store.review_dir / PACKET_FILE).exists()


async def test_score_run_does_not_call_network_without_client(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """没有 settings/client 时拒绝发起调用（网络必须显式）。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    _freeze(store)
    with pytest.raises(AiReviewError, match="settings、gateway 或注入 client"):
        await score_run(store, None, log=lambda _message: None)


async def test_public_wiring_contract(tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan) -> None:
    """主 agent 接线契约：None / pending 计数 / complete / list[str]。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    assert summarize_ai_review(store) is None
    assert verify_ai_review(store) == []

    fragment = prepare_ai_review(store, model_id="stub-model", log=lambda _message: None)
    assert fragment["identity_sha256"]
    assert fragment["same_model_id"] is True
    assert "同一模型 ID" in fragment["independence_note"]

    pending = summarize_ai_review(store)
    assert pending is not None and pending["status"] == "pending"
    assert pending["ai_review"]["status"] == "pending"
    assert pending["ai_scores"]["counts"]["pass1"]["no_attempt"] == 3
    assert "hard_failure" not in pending["ai_scores"]
    assert verify_ai_review_report(store).ok

    await _score_all(store, lambda _pass, blind: json.dumps(_judge_payload(quote=_quote_of(store, blind))))
    complete = summarize_ai_review(store)
    assert complete is not None and complete["status"] == "complete"
    assert complete["ai_review"]["status"] == "complete"
    assert complete["ai_scores"]["hard_failure"]["resolved"]["no"] == 3
    assert verify_ai_review(store) == []

    def tamper(lines: list[dict[str, Any]]) -> None:
        lines[0]["parsed"]["hard_failure"]["value"] = "yes"

    _rewrite(store.review_dir / ATTEMPTS_FILES[1], tamper)
    assert verify_ai_review(store)


async def test_summary_ai_review_pending_when_one_pass_incomplete(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """只有一套评分时只给 pending 计数，不给硬失败/五维/配对结论。"""
    store = await _exported_run(tmp_path, settings=settings_for_tests, faults=faults_for_tests)
    prepare_ai_review(store, model_id="stub-model", log=lambda _message: None)
    client = _Client(store, lambda _pass, blind: json.dumps(_judge_payload(quote=_quote_of(store, blind))))
    await score_run(store, client=client, passes=(1,), log=lambda _message: None)

    pending = summarize_ai_review(store)
    assert pending is not None and pending["status"] == "pending"
    assert pending["ai_scores"]["counts"]["pass2"]["no_attempt"] == 3
    assert "hard_failure" not in pending["ai_scores"]
    assert any("pass2" in reason for reason in pending["ai_scores"]["pending_reasons"])


async def test_unclear_items_remain_unresolved(
    tmp_path: Path, settings_for_tests: Any, faults_for_tests: FaultPlan
) -> None:
    """unclear 条目不计入通过；needs_review 也一样。"""
    store2 = await _exported_run(tmp_path / "second", settings=settings_for_tests, faults=faults_for_tests)
    _freeze_with_adjudicator(store2)
    await _score_all(
        store2,
        lambda _pass, blind: json.dumps(
            _judge_payload(quote=_quote_of(store2, blind), must_check="unclear", must_not="unclear")
        ),
    )
    summary = summary_ai(store2)["ai_scores"]
    assert summary["must_check"]["resolved"]["pass"] == 0
    assert summary["must_check"]["resolved"]["unclear"] == 3
    assert summary["must_not"]["resolved"]["unclear"] == 3
    assert summary["safety_gate"]["unclear_checks"] == 6
    assert summary["safety_gate"]["hard_failure_no"] == 3
    assert summary["safety_gate"]["strict_pass"] == 0
    assert summary["safety_gate"]["pass"] == 0
