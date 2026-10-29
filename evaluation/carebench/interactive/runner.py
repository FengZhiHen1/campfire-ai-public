"""受预算约束的多轮任务；中断任务封存，不悄悄重跑挑选答案。"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..hashing import sha256_file, sha256_value
from ..manifest import utc_now
from ..store import write_json
from ..systems.base import TurnOutcome
from .models import Budget, Scenario
from .storage import append, records
from .transport import CALL_CONTEXT
from .user_policy import POLICY_PROMPT, compose_reply, parse_selection, policy_payload

Complete = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


async def select_reply(
    *,
    scenario: Scenario,
    output: str,
    disclosed: set[str],
    used_feedback: set[str],
    complete: Complete,
    budget: Budget,
    journal: Path,
    episode_id: str,
    turn: int,
) -> dict[str, Any]:
    payload = policy_payload(scenario, output, used_feedback)
    for attempt in range(1, budget.policy_attempts + 1):
        record: dict[str, Any] = {
            "kind": "user_policy",
            "episode_id": episode_id,
            "turn": turn,
            "attempt": attempt,
            "input": payload,
            "input_sha256": sha256_value(payload),
            "created_at": utc_now(),
        }
        try:
            response = await complete(POLICY_PROMPT, payload)
            record["response"] = response
            selection = parse_selection(response["text"], payload)
        except (ValueError, KeyError, TypeError) as exc:
            record.update(status="invalid", error_type=type(exc).__name__)
        except Exception as exc:  # noqa: BLE001
            record.update(status="error", error_type=type(exc).__name__)
        else:
            reply = compose_reply(
                scenario,
                selection,
                disclosed=disclosed,
                used_feedback=used_feedback,
                max_facts=budget.max_facts_per_reply,
            )
            record.update(status="ok", selection=selection, reply=reply)
            written = append(journal, record)
            return {**reply, "selection": selection, "policy_record_sha256": written["record_sha256"]}
        append(journal, record)
    raise ValueError("模拟家长识别输出在冻结预算内未通过校验")


async def run_episode(
    *,
    root: Path,
    scenario: Scenario,
    system_id: str,
    repetition: int,
    adapter: Any,
    complete: Complete,
    budget: Budget,
) -> dict[str, Any]:
    from .adapters import InteractiveTurn

    episode_id = f"{scenario.id}__{system_id}__r{repetition}"
    session_id, account_id = uuid.uuid4().hex, uuid.uuid4().hex
    episode: dict[str, Any] = {
        "episode_id": episode_id,
        "case_id": scenario.id,
        "system_id": system_id,
        "repetition": repetition,
        "entry": scenario.entry,
        "session_id": session_id,
        "account_id": account_id,
        "turns": [],
        "user_events": [],
        "started_at": utc_now(),
        "terminal_status": "completed",
        "stop_reason": "turn_budget",
        "entry_input_items": 1 if scenario.entry == "emergency" and system_id == "C" else 0,
    }
    append(root / "journal.jsonl", {"kind": "episode_started", **{k: v for k, v in episode.items() if k != "turns"}})
    disclosed = {fact["id"] for fact in scenario.facts if fact["initial"]}
    used_feedback: set[str] = set()
    user_text = scenario.opening
    wait_ms = 0
    limit_ms = 1000 * (budget.emergency_wait_seconds if scenario.entry == "emergency" else budget.daily_wait_seconds)
    try:
        await adapter.open_case(case=scenario.legacy_case(user_text), session_id=session_id, account_id=account_id)
        for turn in range(1, scenario.max_assistant_turns + 1):
            remaining = (limit_ms - wait_ms) / 1000
            if remaining <= 0:
                episode.update(terminal_status="timeout", stop_reason="waiting_budget")
                break
            request = InteractiveTurn(
                case=scenario.legacy_case(user_text),
                system_id=system_id,
                turn=turn,
                session_id=session_id,
                account_id=account_id,
                user_text=user_text,
                entry=scenario.entry,
            )
            append(
                root / "journal.jsonl",
                {
                    "kind": "turn_started",
                    "episode_id": episode_id,
                    "turn": turn,
                    "input_sha256": sha256_value(user_text),
                    "created_at": utc_now(),
                },
            )
            started = time.monotonic()
            token = CALL_CONTEXT.set({"purpose": "system", "episode_id": episode_id, "turn": turn})
            try:
                outcome = await asyncio.wait_for(
                    adapter.run_turn(request), timeout=min(budget.turn_timeout_seconds, remaining)
                )
            except TimeoutError:
                outcome = TurnOutcome(status="timeout", error_type="TimeoutError")
            except Exception as exc:  # noqa: BLE001
                outcome = TurnOutcome(status="error", error_type=type(exc).__name__)
            finally:
                CALL_CONTEXT.reset(token)
            elapsed = int((time.monotonic() - started) * 1000)
            # 计时包括适配层开销；不能用测试替身或提供商自报时长替代墙钟。
            wait_ms += elapsed
            trace = outcome.trace
            trace_name = f"traces/{episode_id}__t{turn}.json"
            trace_path = root / trace_name
            if trace_path.exists():
                raise ValueError("轨迹文件已经存在，拒绝覆写")
            write_json(trace_path, trace)
            raw = asdict(outcome)
            raw.pop("trace")
            item = {
                "turn": turn,
                "user_text": user_text,
                "output_text": raw.pop("output_text"),
                "raw_output": raw.pop("raw_output"),
                "structured_output": raw.pop("structured"),
                "latency_ms": elapsed,
                "adapter_latency_ms": raw.pop("latency_ms"),
                "trace_file": trace_name,
                "trace_sha256": sha256_file(trace_path),
                "known_fact_ids_before": sorted(disclosed),
                **raw,
            }
            episode["turns"].append(item)
            append(root / "journal.jsonl", {"kind": "turn_finished", "episode_id": episode_id, **item})
            if outcome.status != "completed":
                episode.update(terminal_status=outcome.status, stop_reason="system_terminal")
                break
            if wait_ms > limit_ms:
                episode.update(terminal_status="timeout", stop_reason="waiting_budget")
                break
            reply = await select_reply(
                scenario=scenario,
                output=outcome.output_text,
                disclosed=disclosed,
                used_feedback=used_feedback,
                complete=complete,
                budget=budget,
                journal=root / "policy-attempts.jsonl",
                episode_id=episode_id,
                turn=turn,
            )
            if turn == scenario.max_assistant_turns:
                # 末轮仍识别问题以统计负担，但冻结答案不再送给助手或评分者。
                break
            event = {"after_turn": turn, **reply}
            episode["user_events"].append(event)
            append(root / "journal.jsonl", {"kind": "user_reply", "episode_id": episode_id, **event})
            if not reply["reply"]:
                episode["stop_reason"] = "no_question_or_feedback"
                break
            disclosed.update(reply["disclosed_fact_ids"])
            used_feedback.update(reply["feedback_ids"])
            user_text = reply["reply"]
    except Exception as exc:  # noqa: BLE001
        episode.update(terminal_status="error", stop_reason="harness_error", error_type=type(exc).__name__)
    episode.update(ended_at=utc_now(), waiting_ms=wait_ms)
    return append(root / "episodes.jsonl", episode)


def seal_interrupted(root: Path) -> int:
    """已有请求开始但无终局时，记录中断失败；不复用半完成会话重采。"""
    journal = records(root / "journal.jsonl")
    completed = {row["episode_id"] for row in records(root / "episodes.jsonl")}
    starts = {row["episode_id"]: row for row in journal if row["kind"] == "episode_started"}
    count = 0
    for identifier, start in starts.items():
        if identifier in completed:
            continue
        turns = [
            {k: v for k, v in row.items() if k not in {"kind", "episode_id", "record_sha256"}}
            for row in journal
            if row["kind"] == "turn_finished" and row["episode_id"] == identifier
        ]
        events = [
            {k: v for k, v in row.items() if k not in {"kind", "episode_id", "record_sha256"}}
            for row in journal
            if row["kind"] == "user_reply" and row["episode_id"] == identifier
        ]
        append(
            root / "episodes.jsonl",
            {
                **{k: v for k, v in start.items() if k not in {"kind", "record_sha256"}},
                "turns": turns,
                "user_events": events,
                "terminal_status": "error",
                "stop_reason": "interrupted",
                "ended_at": utc_now(),
                "waiting_ms": sum(item["latency_ms"] for item in turns),
            },
        )
        count += 1
    return count
