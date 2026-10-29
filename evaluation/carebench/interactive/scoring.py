"""独立评分先落盘，分歧再裁定；无效结构只在预定预算内补采。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Budget, Scenario
from .review import ADJUDICATOR_PROMPT, SCORER_PROMPTS, build_review_payload, disagreement, parse_rating
from .storage import append, records
from .transport import completion


def review_payload(root: Path, episode: dict[str, Any], scenario: Scenario) -> dict[str, Any]:
    enriched = {**episode, "turns": [dict(turn) for turn in episode["turns"]]}
    for turn in enriched["turns"]:
        turn["trace"] = json.loads((root / turn["trace_file"]).read_text(encoding="utf-8"))
    return build_review_payload(enriched, scenario)


async def rate(
    *, root: Path, gateway: Any, episode_id: str, role: str, prompt: str, payload: dict[str, Any], budget: Budget
) -> dict[str, Any] | None:
    # 先占用尝试编号。进程被杀也会消耗预算，不得通过重启获得额外评分。
    reservations = [
        row
        for row in records(root / "rating-reservations.jsonl")
        if row["episode_id"] == episode_id and row["role"] == role
    ]
    previous = [
        row
        for row in records(root / "rating-attempts.jsonl")
        if row["episode_id"] == episode_id and row["role"] == role
    ]
    completed_attempts = {row["attempt"] for row in previous}
    calls = records(root / "calls.jsonl")
    for reservation in reservations:
        if reservation["attempt"] in completed_attempts:
            continue
        start = next(
            (
                row
                for row in calls
                if row["kind"] == "started"
                and row["context"]
                == {
                    "purpose": role,
                    "episode_id": episode_id,
                    "attempt": reservation["attempt"],
                }
            ),
            None,
        )
        finish = next(
            (row for row in calls if start and row["kind"] == "finished" and row["call_id"] == start["call_id"]), None
        )
        recovered = {
            "episode_id": episode_id,
            "role": role,
            "attempt": reservation["attempt"],
            "payload": payload,
            "status": "error",
            "error_type": "Interrupted",
        }
        if finish and finish["status"] == "ok":
            recovered["response"] = finish["response"]
            try:
                recovered["rating"] = parse_rating(
                    finish["response"]["text"],
                    payload,
                    require_overall_reason=role == "adjudicator",
                )
                recovered["status"] = "ok"
                recovered.pop("error_type")
            except ValueError as exc:
                recovered.update(status="invalid", issues=getattr(exc, "issues", []))
        previous.append(append(root / "rating-attempts.jsonl", recovered))
    valid = [row for row in previous if row["status"] == "ok"]
    if valid:
        return valid[0]["rating"]
    for attempt in range(len(reservations) + 1, budget.rating_attempts + 1):
        append(
            root / "rating-reservations.jsonl",
            {"episode_id": episode_id, "role": role, "attempt": attempt},
        )
        complete = completion(
            gateway,
            root,
            context={"purpose": role, "episode_id": episode_id, "attempt": attempt},
        )
        row: dict[str, Any] = {
            "episode_id": episode_id,
            "role": role,
            "attempt": attempt,
            "payload": payload,
        }
        try:
            response = await complete(prompt, payload)
            row["response"] = response
            rating = parse_rating(response["text"], payload, require_overall_reason=role == "adjudicator")
        except (ValueError, KeyError, TypeError) as exc:
            row.update(status="invalid", error_type=type(exc).__name__, issues=getattr(exc, "issues", []))
        except Exception as exc:  # noqa: BLE001
            row.update(status="error", error_type=type(exc).__name__)
        else:
            row.update(status="ok", rating=rating)
            append(root / "rating-attempts.jsonl", row)
            return rating
        append(root / "rating-attempts.jsonl", row)
    return None


async def score_episode(root: Path, episode: dict[str, Any], scenario: Scenario, budget: Budget, gateway: Any) -> None:
    identifier = episode["episode_id"]
    payload = review_payload(root, episode, scenario)
    # 两个调用不含对方评分；先后顺序不改变互不可见性。
    first = await rate(
        root=root,
        gateway=gateway,
        episode_id=identifier,
        role="scorer_a",
        prompt=SCORER_PROMPTS[0],
        payload=payload,
        budget=budget,
    )
    second = await rate(
        root=root,
        gateway=gateway,
        episode_id=identifier,
        role="scorer_b",
        prompt=SCORER_PROMPTS[1],
        payload=payload,
        budget=budget,
    )
    final, diverged = None, None
    if first is not None and second is not None:
        diverged = disagreement(first, second)
        if diverged:
            final = await rate(
                root=root,
                gateway=gateway,
                episode_id=identifier,
                role="adjudicator",
                prompt=ADJUDICATOR_PROMPT,
                payload={**payload, "independent_ratings": [first, second]},
                budget=budget,
            )
        else:
            final = first
    append(
        root / "ratings.jsonl",
        {
            "episode_id": identifier,
            "payload": payload,
            "first": first,
            "second": second,
            "disagreement": diverged,
            "final": final,
            "status": "ok" if final is not None else "unresolved",
        },
    )
