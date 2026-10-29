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
    append_attempt,
    build_request,
    build_scoring_inputs,
    load_attempts,
    load_frozen_cases,
    load_identity,
    parse_judge_output,
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
    bad_passes = [pass_no for pass_no in passes if pass_no not in (1, 2)]
    if bad_passes:
        raise AiReviewError(f"未知 pass：{bad_passes}")
    if client is None and settings is None:
        raise AiReviewError("需要 settings 或注入 client：评分不会凭空发起网络调用")

    identity = load_identity(store)
    cases = {case.id: case for case in load_frozen_cases(store).cases}
    inputs = {item.blind_id: item for item in build_scoring_inputs(store)}
    selected = [blind for blind in inputs if blind_ids is None or blind in set(blind_ids)]
    if not selected:
        raise AiReviewError("没有可评分的 blind 组")

    gateway = None
    owns_client = False
    if client is None:
        from campfire.agent.model import ModelGateway

        gateway = ModelGateway(settings)
        client = gateway.client
        owns_client = True

    judges = {pass_no: _judge(identity, pass_no) for pass_no in passes}
    existing = {pass_no: {record.get("blind_id") for record in _ok_records(store, pass_no)} for pass_no in passes}
    semaphore = asyncio.Semaphore(max_concurrency)
    tasks = []
    for pass_no in passes:
        judge = judges[pass_no]
        for blind_id in selected:
            if blind_id in existing[pass_no]:
                continue
            tasks.append(_score_one(store, client, judge, inputs[blind_id], cases, semaphore))

    try:
        records = await asyncio.gather(*tasks) if tasks else []
    finally:
        if owns_client and gateway is not None:
            await gateway.aclose()

    result = ScoreRunResult(
        total=len(tasks),
        ok=sum(1 for record in records if record["status"] == "ok"),
        invalid=sum(1 for record in records if record["status"] == "invalid"),
        error=sum(1 for record in records if record["status"] == "error"),
        skipped=len(passes) * len(selected) - len(tasks),
    )
    log(
        f"AI 评分尝试：共 {result.total}，成功 {result.ok}，无效 {result.invalid}，"
        f"失败 {result.error}，跳过已有成功 {result.skipped}"
    )
    return result


def _judge(identity: dict[str, Any], pass_no: int):
    """从冻结身份取评分者。"""
    from .ai_review import JudgeIdentity

    return JudgeIdentity.from_dict(identity["judges"][str(pass_no)])


def _ok_records(store: RunStore, pass_no: int) -> list[dict[str, Any]]:
    """该 pass 的成功尝试（用于跳过，不覆盖）。"""
    return [record for record in load_attempts(store, pass_no) if record.get("status") == "ok"]


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


__all__ = ["ScoreRunResult", "score_run"]
