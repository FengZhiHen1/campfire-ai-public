"""AI 评分执行器：两套评分者各自 stateless 调用，原始尝试逐条追加。

职责：读冻结身份与盲化评分输入，按 pass 并发调用现有 OpenAI 客户端，逐个记录
请求、响应、解析结果与错误。

边界：

- **不做网络调用除非显式调用本函数**；测试注入 `client` 替身，不联网；
- 不重试、不改写：失败/无效尝试原样留下，重评是追加新尝试而不是覆盖；
- 两个 pass 的请求彼此独立（各自 system 提示），不共享上下文或对方结论；
- 不在这里算分、不读 `human_scores`。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from .ai_review import (
    AiReviewError,
    ScoreSchemaError,
    _effective_ok,
    _frozen_adjudicator,
    append_adjudication_attempt,
    append_attempt,
    build_adjudication_request,
    build_request,
    build_scoring_inputs,
    disagreement_detail,
    load_adjudication_attempts,
    load_adjudications,
    load_attempts,
    load_frozen_cases,
    load_identity,
    parse_judge_output,
    record_adjudication,
    utc_now,
)
from .store import RunStore


@dataclass(frozen=True)
class ScoreRunResult:
    """一次评分执行的计数（不含分数）。"""

    total: int
    ok: int
    invalid: int
    error: int
    skipped: int

    def to_dict(self) -> dict[str, int]:
        """落盘形状。"""
        return {
            "total": self.total,
            "ok": self.ok,
            "invalid": self.invalid,
            "error": self.error,
            "skipped": self.skipped,
        }


async def score_run(
    store: RunStore,
    settings: Any = None,
    *,
    client: Any = None,
    gateway: Any = None,
    passes: tuple[int, ...] = (1, 2),
    blind_ids: list[str] | None = None,
    max_concurrency: int = 4,
    log: Any = print,
) -> ScoreRunResult:
    """跑两套独立评分（调用方必须显式调用；测试用 `client` 替身）。

    Args:
        store: 已导出评审包并冻结身份的批次。
        settings: 未注入 `client` 时用于构造 :class:`ModelGateway` 的配置。
        client: 测试缝（有 `chat.completions.create` 的异步客户端）。
        passes: 要跑的评分者（默认两位都跑）。
        blind_ids: 只跑这些盲化编号（默认全部）。
        max_concurrency: 并发上限（有界）。

    Raises:
        AiReviewError: 未冻结身份、缺评分输入，或 pass 非法。
    """
    if max_concurrency < 1:
        raise AiReviewError("max_concurrency 必须为正")
    if not passes:
        raise AiReviewError("passes 不能为空：至少选择一位评分者")
    if len(set(passes)) != len(passes):
        raise AiReviewError(f"passes 含重复评分者：{list(passes)}（同一 pass/blind 只能评一次）")
    bad_passes = [pass_no for pass_no in passes if pass_no not in (1, 2)]
    if bad_passes:
        raise AiReviewError(f"未知 pass：{bad_passes}")
    identity = load_identity(store)
    cases = {case.id: case for case in load_frozen_cases(store).cases}
    inputs = {item.blind_id: item for item in build_scoring_inputs(store)}
    selected = [blind for blind in inputs if blind_ids is None or blind in set(blind_ids)]
    if not selected:
        raise AiReviewError("没有可评分的 blind 组")

    judges = {pass_no: _judge(identity, pass_no) for pass_no in passes}
    existing = {pass_no: {record.get("blind_id") for record in _ok_records(store, pass_no)} for pass_no in passes}
    pending = []
    for pass_no in passes:
        judge = judges[pass_no]
        for blind_id in selected:
            if blind_id in existing[pass_no]:
                continue
            pending.append((judge, inputs[blind_id]))

    records: list[dict[str, Any]] = []
    if pending:
        client, owned_gateway = _resolve_client(settings=settings, client=client, gateway=gateway)
        semaphore = asyncio.Semaphore(max_concurrency)
        tasks = [_score_one(store, client, judge, scoring, cases, semaphore) for judge, scoring in pending]
        try:
            records = list(await asyncio.gather(*tasks))
        finally:
            if owned_gateway is not None:
                await owned_gateway.aclose()

    result = ScoreRunResult(
        total=len(pending),
        ok=sum(1 for record in records if record["status"] == "ok"),
        invalid=sum(1 for record in records if record["status"] == "invalid"),
        error=sum(1 for record in records if record["status"] == "error"),
        skipped=len(passes) * len(selected) - len(pending),
    )
    log(
        f"AI 评分尝试：共 {result.total}，成功 {result.ok}，无效 {result.invalid}，"
        f"失败 {result.error}，跳过已有成功 {result.skipped}"
    )
    return result


async def adjudicate_run(
    store: RunStore,
    settings: Any = None,
    *,
    client: Any = None,
    gateway: Any = None,
    blind_ids: list[str] | None = None,
    max_concurrency: int = 4,
    log: Any = print,
) -> ScoreRunResult:
    """对未完成的分歧做第三位独立裁定；原始尝试只追加，已裁定跳过。

    成功/无效/异常都先写 `ai-adjudication-attempts.jsonl`；成功后再写裁定记录并链接
    尝试 hash。进程在两步之间中断时，下次执行直接用已有成功尝试补裁定记录，不重打模型。

    Raises:
        AiReviewError: 未冻结裁定者身份、没有评分包，或并发参数非法。
        asyncio.CancelledError: 原样抛出（不当作普通错误吞掉）。
    """
    if max_concurrency < 1:
        raise AiReviewError("max_concurrency 必须为正")
    identity = load_identity(store)
    adjudicator = _frozen_adjudicator(identity)
    if adjudicator is None:
        raise AiReviewError("未冻结裁定者身份：formal 分歧复核必须冻结第三位身份")
    inputs = {item.blind_id: item for item in build_scoring_inputs(store)}
    cases = {case.id: case for case in load_frozen_cases(store).cases}
    selected = {blind for blind in inputs if blind_ids is None or blind in set(blind_ids)}
    final = {str(record.get("blind_id")) for record in load_adjudications(store)}
    first_ok = _effective_ok(store, 1)
    second_ok = _effective_ok(store, 2)
    attempts_by_blind: dict[str, list[dict[str, Any]]] = {}
    for item in load_adjudication_attempts(store):
        attempts_by_blind.setdefault(str(item.get("blind_id") or ""), []).append(item)

    targets: list[Any] = []
    skipped = 0
    for blind, scoring in inputs.items():
        if blind not in selected:
            continue
        if blind in final:
            skipped += 1
            continue
        first = first_ok.get(blind)
        second = second_ok.get(blind)
        if first is None or second is None or not disagreement_detail(first["parsed"], second["parsed"])["any"]:
            continue
        targets.append((blind, scoring, first, second))

    recovered: list[dict[str, Any]] = []
    pending: list[Any] = []
    for blind, scoring, first, second in targets:
        oks = sorted(
            (item for item in attempts_by_blind.get(blind, []) if item.get("status") == "ok"),
            key=lambda item: int(item.get("attempt") or 0),
        )
        if oks:
            record_adjudication(
                store,
                blind_id=blind,
                adjudicator=adjudicator,
                raw_text=str(oks[-1].get("response_text") or ""),
                raw_response=oks[-1].get("raw_response"),
                attempt_record_sha256=str(oks[-1].get("record_sha256")),
                log=log,
            )
            recovered.append(oks[-1])
        else:
            pending.append((blind, scoring, first, second))

    records: list[dict[str, Any]] = []
    if pending:
        client, owned_gateway = _resolve_client(settings=settings, client=client, gateway=gateway)
        semaphore = asyncio.Semaphore(max_concurrency)
        tasks = [
            _adjudicate_one(store, client, adjudicator, blind, scoring, cases, first, second, semaphore, log)
            for blind, scoring, first, second in pending
        ]
        try:
            records = list(await asyncio.gather(*tasks))
        finally:
            if owned_gateway is not None:
                await owned_gateway.aclose()

    result = ScoreRunResult(
        total=len(targets),
        ok=sum(1 for record in [*recovered, *records] if record["status"] == "ok"),
        invalid=sum(1 for record in records if record["status"] == "invalid"),
        error=sum(1 for record in records if record["status"] == "error"),
        skipped=skipped,
    )
    log(
        f"分歧裁定尝试：共 {result.total}，成功 {result.ok}，无效 {result.invalid}，"
        f"失败 {result.error}，跳过已有裁定 {result.skipped}"
    )
    return result


def _resolve_client(*, settings: Any, client: Any, gateway: Any) -> tuple[Any, Any]:
    """返回 (client, 自有 gateway)。外部 gateway 只需提供 `.client`，由调用方关闭。"""
    if client is not None:
        return client, None
    if gateway is not None:
        candidate = getattr(gateway, "client", None)
        if candidate is None or not hasattr(candidate, "chat"):
            raise AiReviewError("传入的 gateway 没有可用的 .client（需要 OpenAI 兼容客户端）")
        return candidate, None
    if settings is None:
        raise AiReviewError("需要 settings、gateway 或注入 client：不会凭空发起网络调用")
    from campfire.agent.model import ModelGateway

    owned = ModelGateway(settings)
    return owned.client, owned


def _judge(identity: dict[str, Any], pass_no: int):
    """从冻结身份取评分者。"""
    from .ai_review import JudgeIdentity

    return JudgeIdentity.from_dict(identity["judges"][str(pass_no)])


def _ok_records(store: RunStore, pass_no: int) -> list[dict[str, Any]]:
    """该 pass 的成功尝试（用于跳过，不覆盖）。"""
    return [record for record in load_attempts(store, pass_no) if record.get("status") == "ok"]


async def _adjudicate_one(
    store: RunStore,
    client: Any,
    adjudicator: Any,
    blind_id: str,
    scoring: Any,
    cases: dict[str, Any],
    first: dict[str, Any],
    second: dict[str, Any],
    semaphore: asyncio.Semaphore,
    log: Any,
) -> dict[str, Any]:
    """裁定一条：成功/无效/失败都先落原始尝试；成功再写裁定记录。"""
    async with semaphore:
        request = build_adjudication_request(adjudicator, scoring.payload, first["parsed"], second["parsed"])
        started_at = utc_now()
        started = time.monotonic()
        raw_response: dict[str, Any] | None = None
        response_text = ""
        decision: dict[str, Any] | None = None
        errors: list[str] = []
        status = "error"
        try:
            response = await client.chat.completions.create(**request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 —— 只留类型，原始消息可能含端点细节
            errors.append(type(exc).__name__)
        else:
            raw_response = _serialize_response(response)
            response_text = _response_text(response)
            try:
                decision = parse_judge_output(
                    response_text,
                    case=cases[scoring.case_id],
                    blind_id=blind_id,
                    input_payload=scoring.payload,
                    allow_overall_reason=True,
                )
                status = "ok"
            except ScoreSchemaError as exc:
                status = "invalid"
                errors.extend(exc.issues)
        latency_ms = int((time.monotonic() - started) * 1000)
        attempt = append_adjudication_attempt(
            store,
            {
                "blind_id": blind_id,
                "case_id": scoring.case_id,
                "adjudicator": adjudicator.public_dict(),
                "input_sha256": scoring.sha256,
                "request": request,
                "request_sha256": _sha(request),
                "response_text": response_text,
                "raw_response": raw_response,
                "raw_response_sha256": _sha(raw_response) if raw_response is not None else None,
                "status": status,
                "decision": decision,
                "decision_sha256": _sha(decision) if decision is not None else None,
                "errors": errors,
                "started_at": started_at,
                "ended_at": utc_now(),
                "latency_ms": latency_ms,
            },
        )
        if status == "ok":
            record_adjudication(
                store,
                blind_id=blind_id,
                adjudicator=adjudicator,
                raw_text=response_text,
                raw_response=raw_response,
                attempt_record_sha256=attempt["record_sha256"],
                log=log,
            )
        return attempt


async def _score_one(
    store: RunStore,
    client: Any,
    judge: Any,
    scoring: Any,
    cases: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """评一条：成功/无效/失败都落成一条原始尝试。"""
    async with semaphore:
        request = build_request(judge, scoring.payload)
        started_at = utc_now()
        started = time.monotonic()
        raw_response: dict[str, Any] | None = None
        response_text = ""
        parsed: dict[str, Any] | None = None
        errors: list[str] = []
        status = "error"
        try:
            response = await client.chat.completions.create(**request)
            raw_response = _serialize_response(response)
            response_text = _response_text(response)
        except Exception as exc:  # noqa: BLE001 —— 只留类型，原始消息可能含端点细节
            errors.append(type(exc).__name__)
        else:
            try:
                parsed = parse_judge_output(
                    response_text,
                    case=cases[scoring.case_id],
                    blind_id=scoring.blind_id,
                    input_payload=scoring.payload,
                )
                status = "ok"
            except ScoreSchemaError as exc:
                status = "invalid"
                errors.extend(exc.issues)
        latency_ms = int((time.monotonic() - started) * 1000)
        record = {
            "blind_id": scoring.blind_id,
            "case_id": scoring.case_id,
            "rater_id": judge.rater_id,
            "identity": judge.public_dict(),
            "input": scoring.payload,
            "input_sha256": scoring.sha256,
            "request": request,
            "request_sha256": _sha(request),
            "response_text": response_text,
            "raw_response": raw_response,
            "raw_response_sha256": _sha(raw_response) if raw_response is not None else None,
            "status": status,
            "parsed": parsed,
            "parsed_sha256": _sha(parsed) if parsed is not None else None,
            "errors": errors,
            "started_at": started_at,
            "ended_at": utc_now(),
            "latency_ms": latency_ms,
        }
        return append_attempt(store, judge.pass_no, record)


def _sha(value: Any) -> str:
    """记录内复用的内容 hash（与 `hashing.sha256_value` 同口径）。"""
    from .hashing import sha256_value

    return sha256_value(value)


def _serialize_response(response: Any) -> dict[str, Any]:
    """把 SDK 响应转成可落盘的 JSON（失败时只留文本与标识）。"""
    dump = getattr(response, "model_dump", None)
    if callable(dump):
        try:
            payload = dump()
        except Exception:  # noqa: BLE001 —— 序列化失败不改变评分事实，退回最小形状
            payload = None
        if isinstance(payload, dict):
            return payload
    return {
        "text": _response_text(response),
        "id": getattr(response, "id", None),
        "model": getattr(response, "model", None),
    }


def _response_text(response: Any) -> str:
    """取第一条 choice 的正文（没有则空串）。"""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    return content if isinstance(content, str) else ""


__all__ = ["ScoreRunResult", "adjudicate_run", "score_run"]
