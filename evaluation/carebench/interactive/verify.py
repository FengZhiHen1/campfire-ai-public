"""离线重算分母、披露和评分；缺失记录不会被当作通过。"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from campfire.surfaces.consult.emergency import EmergencyItem
from campfire.surfaces.consult.injections import render_emergency_intake

from ..hashing import sha256_file, sha256_value
from .freeze import load_run
from .review import disagreement, parse_rating
from .scoring import review_payload
from .storage import records
from .user_policy import compose_reply, parse_selection, policy_payload


def verify(root: Path, *, require_complete: bool = False) -> dict[str, Any]:
    issues: list[str] = []
    try:
        manifest, scenarios, budget = load_run(root)
        by_case = {case.id: case for case in scenarios}
        tables = {
            name: records(root / f"{name}.jsonl")
            for name in (
                "episodes",
                "journal",
                "policy-attempts",
                "rating-attempts",
                "rating-reservations",
                "ratings",
                "calls",
                "http",
            )
        }
        episodes, ratings = tables["episodes"], tables["ratings"]
        expected = {item["episode_id"]: item for item in manifest["plan"]}
        if not expected:
            raise ValueError("冻结分母为空")
        for name in ("episodes", "ratings"):
            identifiers = [row["episode_id"] for row in tables[name]]
            if len(identifiers) != len(set(identifiers)) or set(identifiers) - set(expected):
                issues.append(f"{name} 含重复或计划外记录")
        if require_complete and {row["episode_id"] for row in episodes} != set(expected):
            issues.append("生成终局未覆盖完整冻结分母")
        if require_complete and {row["episode_id"] for row in ratings} != set(expected):
            issues.append("评分终局未覆盖完整冻结分母")
        starts = [row for row in tables["journal"] if row["kind"] == "episode_started"]
        if len({row["episode_id"] for row in starts}) != len(starts):
            issues.append("episode_started 重复")
        if {row["episode_id"] for row in starts} - set(expected):
            issues.append("存在计划外请求")
        if require_complete and {row["episode_id"] for row in starts} != {row["episode_id"] for row in episodes}:
            issues.append("开始的任务没有终局记录")
        for key in ("session_id", "account_id"):
            if len({row[key] for row in starts}) != len(starts):
                issues.append(f"{key} 被多个任务复用")
        policy_by_turn: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for row in tables["policy-attempts"]:
            policy_by_turn[row["episode_id"], row["turn"]].append(row)
        for episode in episodes:
            identifier = episode["episode_id"]
            plan = expected.get(identifier)
            if not plan:
                continue
            scenario = by_case[plan["case_id"]]
            if any(episode.get(key) != plan[key] for key in ("case_id", "system_id", "repetition")):
                issues.append(f"{identifier}: 计划字段不同")
            if episode["entry"] != scenario.entry:
                issues.append(f"{identifier}: 入口不同")
            if episode["terminal_status"] not in {"completed", "no_output", "error", "timeout"}:
                issues.append(f"{identifier}: 非法终局")
            turns = episode["turns"]
            if [turn["turn"] for turn in turns] != list(range(1, len(turns) + 1)):
                issues.append(f"{identifier}: 回合缺失或重复")
            if len(turns) > scenario.max_assistant_turns:
                issues.append(f"{identifier}: 超出回合预算")
            if episode["waiting_ms"] != sum(turn["latency_ms"] for turn in turns):
                issues.append(f"{identifier}: 墙钟累计不一致")
            disclosed = {fact["id"] for fact in scenario.facts if fact["initial"]}
            used_feedback: set[str] = set()
            user_text = scenario.opening
            events = {event["after_turn"]: event for event in episode["user_events"]}
            if len(events) != len(episode["user_events"]):
                issues.append(f"{identifier}: 家长回复重复")
            for turn in turns:
                number = turn["turn"]
                prefix = f"{identifier}/t{number}"
                if turn["user_text"] != user_text or turn["known_fact_ids_before"] != sorted(disclosed):
                    issues.append(f"{prefix}: 输入/披露时序不一致")
                trace_file = turn["trace_file"]
                if trace_file != f"traces/{identifier}__t{number}.json":
                    issues.append(f"{prefix}: 非法轨迹路径")
                    continue
                if sha256_file(root / trace_file) != turn["trace_sha256"]:
                    issues.append(f"{prefix}: 轨迹 hash 不同")
                trace = json.loads((root / trace_file).read_text(encoding="utf-8"))
                if episode["system_id"] == "C" and turn["status"] == "completed":
                    actual_request = (trace.get("interactive") or {}).get("request") or {}
                    emergency_first = scenario.entry == "emergency" and number == 1
                    actual_input = (
                        render_emergency_intake([EmergencyItem(key="what_happened", value=user_text)])
                        if emergency_first
                        else user_text
                    )
                    if (
                        actual_request.get("user_input") != actual_input
                        or actual_request.get("activated_skills")
                        != (["emergency-consulting"] if emergency_first else [])
                        or actual_request.get("activation_record_items") != (2 if emergency_first else 0)
                    ):
                        issues.append(f"{prefix}: 真实入口请求与冻结入口不一致")
                turn_journal = [
                    row
                    for row in tables["journal"]
                    if row.get("episode_id") == identifier and row.get("turn") == number
                ]
                begun = [row for row in turn_journal if row["kind"] == "turn_started"]
                finished = [row for row in turn_journal if row["kind"] == "turn_finished"]
                if len(begun) != 1 or len(finished) != 1:
                    issues.append(f"{prefix}: 请求开始/完成日志不完整")
                else:
                    if begun[0]["input_sha256"] != sha256_value(user_text):
                        issues.append(f"{prefix}: 输入 hash 不同")
                    actual = {k: v for k, v in finished[0].items() if k not in {"kind", "episode_id", "record_sha256"}}
                    if actual != turn:
                        issues.append(f"{prefix}: 终局与回合日志不一致")
                attempts = policy_by_turn.get((identifier, number), [])
                if [row["attempt"] for row in attempts] != list(range(1, len(attempts) + 1)):
                    issues.append(f"{prefix}: 披露识别尝试不连续")
                if len(attempts) > budget.policy_attempts:
                    issues.append(f"{prefix}: 披露识别超预算")
                valid = [row for row in attempts if row["status"] == "ok"]
                if len(valid) > 1 or (valid and valid[-1] != attempts[-1]):
                    issues.append(f"{prefix}: 有效识别后继续重采")
                payload = policy_payload(scenario, turn["output_text"], used_feedback)
                for row in attempts:
                    if row["input"] != payload or row["input_sha256"] != sha256_value(payload):
                        issues.append(f"{prefix}: 模拟家长输入不同或含非冻结事实")
                if valid:
                    row = valid[0]
                    selection = parse_selection(row["response"]["text"], payload)
                    reply = compose_reply(
                        scenario,
                        selection,
                        disclosed=disclosed,
                        used_feedback=used_feedback,
                        max_facts=budget.max_facts_per_reply,
                    )
                    if selection != row["selection"] or reply != row["reply"]:
                        issues.append(f"{prefix}: 披露无法复算")
                    if number in events:
                        event = events[number]
                        if (
                            any(event.get(key) != value for key, value in reply.items())
                            or event.get("selection") != selection
                            or event.get("policy_record_sha256") != row["record_sha256"]
                        ):
                            issues.append(f"{prefix}: 家长回复偏离冻结答案")
                        disclosed.update(reply["disclosed_fact_ids"])
                        used_feedback.update(reply["feedback_ids"])
                        user_text = reply["reply"]
                elif number in events:
                    issues.append(f"{prefix}: 家长回答没有有效识别记录")
            if set(events) - {turn["turn"] for turn in turns}:
                issues.append(f"{identifier}: 家长回复没有对应助手回合")
        by_episode = {row["episode_id"]: row for row in episodes}
        attempts_by_role: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in tables["rating-attempts"]:
            if row["episode_id"] not in expected or row["role"] not in {"scorer_a", "scorer_b", "adjudicator"}:
                issues.append("评分尝试含未知任务或角色")
            attempts_by_role[row["episode_id"], row["role"]].append(row)
        for key, rows in attempts_by_role.items():
            if [row["attempt"] for row in rows] != list(range(1, len(rows) + 1)):
                issues.append(f"{key}: 评分尝试不连续")
            if len(rows) > budget.rating_attempts:
                issues.append(f"{key}: 评分超预算")
            good = [row for row in rows if row["status"] == "ok"]
            if len(good) > 1 or (good and good[-1] != rows[-1]):
                issues.append(f"{key}: 有效评分后继续重采")
        for review in ratings:
            identifier = review["episode_id"]
            if identifier not in by_episode:
                issues.append(f"{identifier}: 无生成记录的评分")
                continue
            payload = review_payload(root, by_episode[identifier], by_case[by_episode[identifier]["case_id"]])
            if review["payload"] != payload:
                issues.append(f"{identifier}: 评分输入不能从原始记录复算")
            for role, target in (("scorer_a", "first"), ("scorer_b", "second"), ("adjudicator", "final")):
                rows = attempts_by_role.get((identifier, role), [])
                required_payload = payload
                if role == "adjudicator":
                    if review["disagreement"] is not True:
                        if rows:
                            issues.append(f"{identifier}: 未分歧却裁定")
                        continue
                    required_payload = {**payload, "independent_ratings": [review["first"], review["second"]]}
                for row in rows:
                    if row["payload"] != required_payload:
                        issues.append(f"{identifier}/{role}: 独立评分输入不同或提前看过评分")
                    if row["status"] == "ok":
                        parsed = parse_rating(
                            row["response"]["text"],
                            required_payload,
                            require_overall_reason=role == "adjudicator",
                        )
                        if parsed != row["rating"] or parsed != review[target]:
                            issues.append(f"{identifier}/{role}: 原始评分与终局不一致")
                    elif row["status"] == "invalid" and "response" in row:
                        try:
                            parse_rating(
                                row["response"]["text"],
                                required_payload,
                                require_overall_reason=role == "adjudicator",
                            )
                        except ValueError:
                            pass
                        else:
                            issues.append(f"{identifier}/{role}: 有效评分被错误丢弃")
                good = [row for row in rows if row["status"] == "ok"]
                if target != "final" and (good[0]["rating"] if good else None) != review[target]:
                    issues.append(f"{identifier}/{role}: 没有对应有效评分")
            if review["first"] is not None and review["second"] is not None:
                diverged = disagreement(review["first"], review["second"])
                if diverged != review["disagreement"]:
                    issues.append(f"{identifier}: 分歧判定不同")
                if not diverged and review["final"] != review["first"]:
                    issues.append(f"{identifier}: 无分歧终局不同")
            if require_complete and (review["final"] is None or review["status"] != "ok"):
                issues.append(f"{identifier}: 评分仍未闭合")
        reservations = [(row["episode_id"], row["role"], row["attempt"]) for row in tables["rating-reservations"]]
        attempts = [(row["episode_id"], row["role"], row["attempt"]) for row in tables["rating-attempts"]]
        if len(set(reservations)) != len(reservations) or Counter(reservations) != Counter(attempts):
            issues.append("评分预约与实际尝试不一致")
        call_starts = {row["call_id"]: row for row in tables["calls"] if row["kind"] == "started"}
        call_finishes = {row["call_id"]: row for row in tables["calls"] if row["kind"] == "finished"}
        for row in [*tables["policy-attempts"], *tables["rating-attempts"]]:
            response = row.get("response")
            if not response:
                continue
            start = call_starts.get(response.get("call_id"))
            finish = call_finishes.get(response.get("call_id"))
            if (
                not start
                or not finish
                or finish.get("response") != response
                or start["payload"] != row.get("input", row.get("payload"))
                or start["context"]["episode_id"] != row["episode_id"]
            ):
                issues.append("原始识别/评分响应缺少匹配的请求开始与完成记录")
        for kind, start_kind, finish_kind in (
            ("calls", "started", "finished"),
            ("http", "request", "response_headers"),
        ):
            starts = [row["call_id"] for row in tables[kind] if row["kind"] == start_kind]
            finishes = [row["call_id"] for row in tables[kind] if row["kind"] == finish_kind]
            if len(set(starts)) != len(starts) or len(set(finishes)) != len(finishes) or set(finishes) - set(starts):
                issues.append(f"{kind}: 请求记录重复或无开始")
            # 网络失败允许没有响应头；所有外层调用结束与错误仍须留档。
            if kind == "calls" and require_complete and set(starts) != set(finishes):
                issues.append("存在未封存的模拟家长/评分调用")
        return {
            "ok": not issues,
            "issues": issues,
            "planned": len(expected),
            "episodes": len(episodes),
            "ratings": len(ratings),
            "require_complete": require_complete,
            "integrity_only": "完整性核验不证明内容专业正确或产品优越。",
        }
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return {
            "ok": False,
            "issues": [*issues, f"核验中止：{type(exc).__name__}"],
            "require_complete": require_complete,
        }
