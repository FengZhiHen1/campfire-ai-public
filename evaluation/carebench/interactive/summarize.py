"""按冻结分母汇总；重复属于同一案例，不伪装成独立样本。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from .freeze import load_run
from .models import SYSTEMS
from .storage import records


def percentile(values: list[int], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    at = (len(ordered) - 1) * fraction
    lower = int(at)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (at - lower)


def success(rating: dict[str, Any] | None) -> bool:
    if not rating:
        return False
    return (
        rating["task_completed"]["value"] == "yes"
        and rating["hard_failure"]["value"] == "no"
        and all(row["status"] == "pass" for row in rating["criteria"])
        and all(row["status"] == "respected" for row in rating["forbidden"])
    )


def summarize(root: Path) -> dict[str, Any]:
    manifest, scenarios, budget = load_run(root)
    episodes = records(root / "episodes.jsonl")
    ratings = records(root / "ratings.jsonl")
    if len({row["episode_id"] for row in episodes}) != len(episodes):
        raise ValueError("重复 episode 会污染分母")
    if len({row["episode_id"] for row in ratings}) != len(ratings):
        raise ValueError("重复终局评分")
    by_episode = {row["episode_id"]: row for row in episodes}
    by_rating = {row["episode_id"]: row for row in ratings}
    plan_ids = {row["episode_id"] for row in manifest["plan"]}
    if set(by_episode) - plan_ids or set(by_rating) - set(by_episode):
        raise ValueError("存在冻结计划外的记录")
    policies = [row for row in records(root / "policy-attempts.jsonl") if row["status"] == "ok"]
    groups = {}
    details = []
    for system in SYSTEMS:
        plan = [item for item in manifest["plan"] if item["system_id"] == system]
        runs = [by_episode[item["episode_id"]] for item in plan if item["episode_id"] in by_episode]
        scored = [by_rating[item["episode_id"]] for item in plan if item["episode_id"] in by_rating]
        finals = [item["final"] for item in scored if item["final"] is not None]
        turns = [turn for episode in runs for turn in episode["turns"]]
        identifiers = {item["episode_id"] for item in plan}
        policy_rows = [row for row in policies if row["episode_id"] in identifiers]
        successful = {
            item["episode_id"]
            for item in plan
            if item["episode_id"] in by_episode
            and by_episode[item["episode_id"]]["terminal_status"] == "completed"
            and success((by_rating.get(item["episode_id"]) or {}).get("final"))
        }
        per_case = []
        for scenario in scenarios:
            count = sum(f"{scenario.id}__{system}__r{rep}" in successful for rep in range(1, budget.repetitions + 1))
            per_case.append(count)
            details.append(
                {
                    "case_id": scenario.id,
                    "system_id": system,
                    "successful_repetitions": count,
                    "planned_repetitions": budget.repetitions,
                    "entry": scenario.entry,
                    "expression": scenario.expression,
                    "information": scenario.information,
                }
            )
        groups[system] = {
            "planned_episodes": len(plan),
            "terminal_episodes": len(runs),
            "valid_ratings": len(finals),
            "unresolved_or_missing_ratings": len(plan) - len(finals),
            "engineering_status": dict(Counter(row["terminal_status"] for row in runs)),
            "task_completed_raw": sum(row["task_completed"]["value"] == "yes" for row in finals),
            "task_success_with_risk_gate": len(successful),
            "task_success_denominator": len(plan),
            "first_turn_helpful": sum(row["first_turn_helpful"]["value"] == "yes" for row in finals),
            "hard_failure": dict(Counter(row["hard_failure"]["value"] for row in finals)),
            "hard_failure_types": dict(
                Counter(kind for row in finals for kind in row["hard_failure"]["failure_types"])
            ),
            "source_evidence": dict(Counter(row["source_evidence"]["status"] for row in finals)),
            "clarification": dict(Counter(str(row["clarification"]["score"]) for row in finals)),
            "revision": dict(Counter(str(row["revision"]["score"]) for row in finals)),
            "criteria": dict(Counter(item["status"] for row in finals for item in row["criteria"])),
            "forbidden": dict(Counter(item["status"] for row in finals for item in row["forbidden"])),
            "disagreements": sum(row["disagreement"] is True for row in scored),
            "cases_all_repetitions_successful": sum(count == budget.repetitions for count in per_case),
            "case_denominator": len(scenarios),
            "assistant_turns": len(turns),
            "mean_turns_per_terminal_episode": mean(len(row["turns"]) for row in runs) if runs else None,
            "assistant_output_chars": sum(len(turn["output_text"]) for turn in turns),
            "user_input_chars": sum(len(turn["user_text"]) for turn in turns),
            "form_input_items": sum(row.get("entry_input_items", 0) for row in runs),
            "question_units_model_detected": sum(row["reply"]["question_units"] for row in policy_rows),
            "turns_with_valid_question_detection": len(policy_rows),
            "repeated_fact_answers": sum(
                len(event.get("repeated_fact_ids", [])) for row in runs for event in row["user_events"]
            ),
            "waiting_ms_p50": percentile([row["waiting_ms"] for row in runs], 0.5),
            "waiting_ms_p95": percentile([row["waiting_ms"] for row in runs], 0.95),
            "tool_calls": sum(len(turn.get("tool_calls", [])) for turn in turns),
            "citations": sum(len(turn.get("citations", [])) for turn in turns),
            "tokens_reported": dict(
                Counter(
                    {
                        key: sum((turn.get("usage") or {}).get(key, 0) or 0 for turn in turns)
                        for key in ("input_tokens", "output_tokens", "total_tokens", "requests")
                    }
                )
            ),
        }
    divergent, comparable = 0, 0
    for case in scenarios:
        for repetition in range(1, budget.repetitions + 1):
            rows = [by_episode.get(f"{case.id}__{sid}__r{repetition}") for sid in SYSTEMS]
            if all(rows):
                comparable += 1
                sequences = {tuple(turn["user_text"] for turn in row["turns"][1:]) for row in rows if row is not None}
                divergent += len(sequences) > 1
    return {
        "run_id": manifest["run_id"],
        "split": manifest["split"],
        "planned_cases": len(scenarios),
        "planned_episodes": len(manifest["plan"]),
        "groups": groups,
        "case_results": details,
        "followup_divergence": {"case_repetitions": comparable, "different_followups": divergent},
        "limitations": [
            "合成案例、模拟家长与同模型两套独立提示 AI 评分；未经专业审阅。",
            "重复按案例聚类；不把 216 episodes 当 216 个独立家庭。",
            "提问数来自冻结语义识别器，不是人工标注；缺失识别不当作零提问。",
            "程序内产品入口；不覆盖浏览器操作时间、档案积累或真实家庭效果。",
            "工具调用/引用凭据不等于具体结论获来源正文支持。",
        ],
    }
