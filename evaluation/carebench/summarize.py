"""汇总：只按实测数据出数字；没有人评审就一个质量分都不出。

职责：从 `outputs.jsonl`（+ 可选的已导入人工评分）生成 `summary.json` 与 `summary.md`：
运行计数、分母、完成/拒答/超时/失败分布、真实时延与 token、工具调用与引用计数、
故障注入实施情况；若已导入人工评分，再出硬失败计数、五维均值、关键约束通过数、配对胜负
与评分一致性。

边界（协议 03 的硬要求，逐条落在这里）：

- **硬失败不与质量分相抵**：`critical_failure` 单独成表，绝不并进平均分；
- **`needs_review` 不是通过**：单独计数，永不并入「无硬失败」；
- **分母完整**：期望 case-group 数来自案例集 × 组别，不因失败/超时而缩小；
- **没有评审就不填分**：`human_scores` 为 `null` 并给出原因，而不是填 0 或「待补」数字。

参考：协议 03 第 2–4 节、协议 04 第 5 节。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from .config import RunConfig
from .records import effective_records, fixture_observation, is_final
from .review import SCORE_COLUMNS, load_imported_ratings
from .store import RunStore, write_json

#: 百分位取值（协议 03 第 3 节要求 p50/p95）。
PERCENTILES = (50, 95)


def _percentile(values: list[int], percentile: int) -> int | None:
    """最近秩百分位（样本小的时候比插值更诚实：不会造出一个没观测到的时延）。"""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(1, min(len(ordered), round(percentile / 100 * len(ordered))))
    return ordered[rank - 1]


def _ratio(passed: int, applicable: int) -> str:
    """以「分子/分母」形式给出比例——协议 03 第 4 节要求展示分子分母，不要只给百分比。"""
    return f"{passed}/{applicable}"


def _per_group_final(records: list[dict[str, Any]], config: RunConfig) -> dict[tuple[str, str], dict[str, Any]]:
    """每个 case-group 的**末轮有效记录**（时延与状态按末轮计）。"""
    effective = effective_records(records)
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for (case_id, system_id, turn), record in effective.items():
        if not is_final(record, config):
            continue
        key = (case_id, system_id)
        current = grouped.get(key)
        if current is None or int(record["turn"]) > int(current["turn"]):
            grouped[key] = record
    return grouped


@dataclass(frozen=True)
class SystemStats:
    """一个组别的工程侧统计。"""

    system_id: str
    groups: int
    status_counts: dict[str, int]
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    latency_max_ms: int | None
    usage_groups: int
    input_tokens: int
    output_tokens: int
    tool_calls: int
    tool_failures: int
    citations: int
    refusal_suspected: int
    empty_output: int
    usage_note: str
    assembly_variants: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        """落盘形状。"""
        return {
            "system_id": self.system_id,
            "case_groups": self.groups,
            "completion_status_counts": dict(self.status_counts),
            "latency_ms": {
                "p50": self.latency_p50_ms,
                "p95": self.latency_p95_ms,
                "max": self.latency_max_ms,
                "definition": "末轮端到端墙钟（不包含评测工具自身开销；单轮上限见 manifest.runner）",
            },
            "tokens": {
                "groups_with_usage": self.usage_groups,
                "input": self.input_tokens,
                "output": self.output_tokens,
                "note": self.usage_note,
            },
            "tool_calls": self.tool_calls,
            "tool_failures": self.tool_failures,
            "citations": self.citations,
            "refusal_suspected_heuristic": self.refusal_suspected,
            "empty_output": self.empty_output,
            "assembly_variants": dict(self.assembly_variants),
        }


def _system_stats(
    system_id: str,
    *,
    groups: dict[tuple[str, str], dict[str, Any]],
    config: RunConfig,
) -> SystemStats:
    """汇总一个组别（分母只算真的跑出末轮结论的组）。"""
    mine = {key: record for key, record in groups.items() if key[1] == system_id}
    status_counts: dict[str, int] = {}
    latencies: list[int] = []
    input_tokens = 0
    output_tokens = 0
    usage_groups = 0
    tool_calls = 0
    tool_failures = 0
    citations = 0
    refusal = 0
    empty = 0
    variants: dict[str, int] = {}

    for record in mine.values():
        status = str(record.get("completion_status"))
        status_counts[status] = status_counts.get(status, 0) + 1
        latencies.append(int(record.get("latency_ms") or 0))
        usage = record.get("usage")
        if isinstance(usage, dict) and int(usage.get("requests") or 0) > 0:
            usage_groups += 1
            input_tokens += int(usage.get("input_tokens") or 0)
            output_tokens += int(usage.get("output_tokens") or 0)
        calls = record.get("tool_calls") or []
        if isinstance(calls, list):
            tool_calls += len(calls)
            tool_failures += sum(1 for call in calls if isinstance(call, dict) and call.get("ok") is False)
        cites = record.get("citations") or []
        if isinstance(cites, list):
            citations += len(cites)
        flags = record.get("status_flags") or {}
        if flags.get("refusal_suspected"):
            refusal += 1
        if flags.get("empty_output"):
            empty += 1
        # 装配变体计数：「C 组有几个 case-group 不是纯生产装配」必须一眼可见，
        # 否则故障注入过的批次会在报告里看起来和纯生产批次一样。
        meta = record.get("system_meta") or {}
        variant = str(meta.get("runner") or "n/a")
        variants[variant] = variants.get(variant, 0) + 1

    usage_note = (
        "token 来自提供方 usage（A/B 为单次调用返回，C 为基座 RunUsage 累加）；"
        "失败/超时轮次可能没有 usage，因此分母是「有 usage 的组数」而不是全部组数"
    )
    return SystemStats(
        system_id=system_id,
        groups=len(mine),
        status_counts=status_counts,
        latency_p50_ms=_percentile(latencies, 50),
        latency_p95_ms=_percentile(latencies, 95),
        latency_max_ms=max(latencies) if latencies else None,
        usage_groups=usage_groups,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_calls=tool_calls,
        tool_failures=tool_failures,
        citations=citations,
        refusal_suspected=refusal,
        empty_output=empty,
        usage_note=usage_note,
        assembly_variants=variants,
    )


def _human_scores(
    ratings: list[dict[str, Any]],
    *,
    config: RunConfig,
) -> dict[str, Any] | None:
    """按已导入的人工评分算分（没有人评审时返回 None）。"""
    if not ratings:
        return None
    by_group: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in ratings:
        key = (str(row["case_id"]), str(row["system_id"]))
        by_group.setdefault(key, []).append(row)

    per_system: dict[str, dict[str, Any]] = {}
    for system_id in config.systems:
        rows = [row for (case_id, sid), items in by_group.items() if sid == system_id for row in items]
        if not rows:
            continue
        critical = {"yes": 0, "no": 0, "needs_review": 0}
        failure_types: dict[str, int] = {}
        totals: list[float] = []
        dimensions = {column: [] for column in SCORE_COLUMNS}
        checks_passed = 0
        checks_applicable = 0
        completion: dict[str, int] = {}
        for row in rows:
            verdict = str(row["critical_failure"])
            critical[verdict] = critical.get(verdict, 0) + 1
            for part in str(row.get("failure_type") or "").replace("，", ",").replace(";", ",").split(","):
                if part.strip():
                    failure_types[part.strip()] = failure_types.get(part.strip(), 0) + 1
            scores = [int(row[column]) for column in SCORE_COLUMNS]
            totals.append(float(sum(scores)))
            for column, score in zip(SCORE_COLUMNS, scores, strict=True):
                dimensions[column].append(score)
            checks_passed += int(row["required_checks_passed"])
            checks_applicable += int(row["required_checks_applicable"])
            status = str(row.get("completion_status"))
            completion[status] = completion.get(status, 0) + 1
        per_system[system_id] = {
            "rating_rows": len(rows),
            "critical_failure_counts": critical,
            "hard_failure_rule": "yes 与 needs_review 均不得视为通过；needs_review 表示需要专业复核",
            "failure_type_counts": failure_types,
            "quality_score": {
                "scale": "0–10（五维各 0–2 求和）",
                "mean": round(statistics.fmean(totals), 3),
                "median": round(statistics.median(totals), 3),
                "n": len(totals),
                "not_a_pass_metric": "总分与硬失败分开报告，禁止用均分抵消硬失败",
            },
            "dimension_means": {
                column: round(statistics.fmean(values), 3) for column, values in dimensions.items() if values
            },
            "action_executability_c2": {
                "mean": round(statistics.fmean(dimensions["c2_action"]), 3) if dimensions["c2_action"] else None,
                "n": len(dimensions["c2_action"]),
            },
            "required_checks": {
                "passed": checks_passed,
                "applicable": checks_applicable,
                "ratio": _ratio(checks_passed, checks_applicable),
            },
            "completion_status_counts": completion,
        }

    return {
        "per_system": per_system,
        "paired": _paired(by_group, config),
        "agreement": _agreement(by_group),
        "mode": "double_blind" if _is_double(by_group, config) else "single_rater_internal",
        "denominator_note": (
            "评分数按「评分行数」给；每个 case-group 的两位评分者不合并成分数，分歧走 adjudication 且有原始分保留"
        ),
    }


def _group_mean(rows: list[dict[str, Any]], column: str) -> float:
    """同一 case-group 的分项均值（跨评分者）。"""
    return statistics.fmean(int(row[column]) for row in rows)


def _group_total(rows: list[dict[str, Any]]) -> float:
    """同一 case-group 的总分均值（跨评分者）。"""
    return statistics.fmean(float(sum(int(row[column]) for column in SCORE_COLUMNS)) for row in rows)


def _paired(by_group: dict[tuple[str, str], list[dict[str, Any]]], config: RunConfig) -> dict[str, Any]:
    """配对比较：同题两组的胜负与平（只在两组都有评分时计入）。"""
    result: dict[str, Any] = {}
    pairs = (("A", "B"), ("A", "C"), ("B", "C"))
    for left, right in pairs:
        if left not in config.systems or right not in config.systems:
            continue
        win = tie = loss = 0
        for case_id in {key[0] for key in by_group}:
            left_rows = by_group.get((case_id, left))
            right_rows = by_group.get((case_id, right))
            if not left_rows or not right_rows:
                continue
            left_total = _group_total(left_rows)
            right_total = _group_total(right_rows)
            if abs(left_total - right_total) < 1e-9:
                tie += 1
            elif left_total > right_total:
                win += 1
            else:
                loss += 1
        result[f"{left}_vs_{right}"] = {
            "left_wins": win,
            "ties": tie,
            "right_wins": loss,
            "total_pairs": win + tie + loss,
            "metric": "同题五维总分（跨评分者均值）",
        }
    return result


def _agreement(by_group: dict[tuple[str, str], list[dict[str, Any]]]) -> dict[str, Any]:
    """评分者一致性：逐维完全一致率 + 硬失败原始一致率（附 Cohen κ）。"""
    dimensions: dict[str, dict[str, int]] = {column: {"exact": 0, "within_one": 0, "n": 0} for column in SCORE_COLUMNS}
    critical: dict[str, int] = {"exact": 0, "n": 0}
    for rows in by_group.values():
        if len(rows) < 2:
            continue
        first, second = rows[0], rows[1]
        for column in SCORE_COLUMNS:
            left, right = int(first[column]), int(second[column])
            dimensions[column]["n"] += 1
            if left == right:
                dimensions[column]["exact"] += 1
            if abs(left - right) <= 1:
                dimensions[column]["within_one"] += 1
        critical["n"] += 1
        if str(first["critical_failure"]) == str(second["critical_failure"]):
            critical["exact"] += 1

    def _rate(bucket: dict[str, int]) -> float | None:
        return round(bucket["exact"] / bucket["n"], 3) if bucket["n"] else None

    return {
        "double_rated_groups": critical["n"],
        "dimensions": {
            column: {
                "exact_agreement": _rate(bucket),
                "within_one_agreement": round(bucket["within_one"] / bucket["n"], 3) if bucket["n"] else None,
                "n": bucket["n"],
            }
            for column, bucket in dimensions.items()
        },
        "critical_failure_agreement": {
            "exact_agreement": _rate(critical),
            "n": critical["n"],
            "kappa": _kappa(critical),
            "note": "κ 只在两位评分者都给出 yes/no 时才有意义；样本小、类别不均衡时应以原始一致率为主",
        },
    }


def _kappa(critical: dict[str, int]) -> float | None:
    """两位评分者 hard-failure 的 Cohen κ（仅用 exact 计数无法算，故此处返回 None）。

    为什么不硬造一个 κ：κ 需要 2×2 列联表；本工具不保存「两人具体各自判了什么」的聚合表，
    只有原始行。真正需要 κ 时按原始行另算（`ratings.imported.csv` 就在那里）。
    返回 None 比返回一个用错误表算出的数诚实。
    """
    return None


def _is_double(by_group: dict[tuple[str, str], list[dict[str, Any]]], config: RunConfig) -> bool:
    """是否达到「两位独立评分者」的口径。"""
    if config.raters_per_case < 2:
        return False
    return all(len(rows) >= 2 for rows in by_group.values()) if by_group else False


def compute_summary(store: RunStore) -> dict[str, Any]:
    """只读复算摘要，供写报告和独立核对落盘数字共用。"""
    manifest = store.read_manifest()
    config = RunConfig.from_dict(manifest["config"])
    records = store.read_outputs()
    groups = _per_group_final(records, config)

    expected_groups = len(manifest["dataset"]["case_ids"]) * len(config.systems)
    category_by_case = _categories(store)
    per_system = {
        system_id: _system_stats(system_id, groups=groups, config=config).to_dict() for system_id in config.systems
    }
    missing_groups = expected_groups - len(groups)
    ratings = load_imported_ratings(store)
    human = _human_scores(ratings, config=config)

    summary: dict[str, Any] = {
        "run_id": manifest["run_id"],
        "batch_id": manifest["batch_id"],
        "label": manifest["label"],
        "status": manifest.get("status"),
        "dataset": {
            "case_count": manifest["dataset"]["case_count"],
            "dataset_sha256": manifest["dataset"]["sha256"],
            "review_status_counts": manifest["dataset"]["review_status_counts"],
            "formal_ready": manifest["dataset"]["formal_ready"],
        },
        "denominators": {
            "case_groups_expected": expected_groups,
            "case_groups_with_final_turn": len(groups),
            "case_groups_missing": missing_groups,
            "note": "分母是案例数 × 组别数；失败、拒答、超时都留在分母里，不因失败而缩小",
        },
        "systems": per_system,
        "by_category": _by_category(groups, category_by_case, config),
        "fault_injection": manifest.get("fault_injection"),
        # 「请求了注入」「装上替身」「真的观察到」是三件事，分开报（见 records.fixture_observation）。
        "fault_injection_observation": fixture_observation(records),
        "review_state": manifest.get("review", {}).get("state", "pending"),
        "human_scores": human,
        "human_scores_note": (
            "未导入人工评分：本文件只报告运行计数、时延与 token，**不产生任何质量分或安全结论**"
            if human is None
            else "分数来自人工评分 CSV；needs_review 不计入通过，硬失败单独列出"
        ),
        "caveats": manifest.get("limitations", []),
    }

    return summary


def summarize_run(store: RunStore, *, log: Any = print) -> dict[str, Any]:
    """生成 summary.json 与 summary.md，返回同源摘要。"""
    summary = compute_summary(store)
    write_json(store.root / "summary.json", summary)
    (store.root / "summary.md").write_text(render_markdown(summary), encoding="utf-8")
    log(f"summary 已写出：{store.root / 'summary.md'}")
    return summary


def _categories(store: RunStore) -> dict[str, str]:
    """从 run 目录内的冻结案例文件取 category（不依赖外部文件）。"""
    from .cases import parse_cases

    if not store.cases_path.exists():
        return {}
    case_set = parse_cases(store.cases_path.read_bytes(), source=str(store.cases_path), path=store.cases_path)
    return {case.id: case.category for case in case_set.cases}


def _by_category(
    groups: dict[tuple[str, str], dict[str, Any]],
    category_by_case: dict[str, str],
    config: RunConfig,
) -> dict[str, Any]:
    """按案例类别分组的工程侧计数（协议 02 的五类）。"""
    result: dict[str, dict[str, dict[str, int]]] = {}
    for (case_id, system_id), record in groups.items():
        category = category_by_case.get(case_id, "unknown")
        system_counts = result.setdefault(category, {}).setdefault(system_id, {})
        status = str(record.get("completion_status"))
        system_counts[status] = system_counts.get(status, 0) + 1
    return result


def render_markdown(summary: dict[str, Any]) -> str:
    """把 summary 渲染成人读的 Markdown（数字与 JSON 同源，不另算一遍）。"""
    lines: list[str] = []
    lines.append(f"# CareBench 运行汇总 · {summary['run_id']}")
    lines.append("")
    lines.append(f"- 批次指纹：`{summary['batch_id']}`")
    lines.append(f"- 标签：`{summary['label']}` · 状态：`{summary['status']}`")
    dataset = summary["dataset"]
    lines.append(
        f"- 案例：{dataset['case_count']} 个（review_status={dataset['review_status_counts']}，"
        f"formal_ready={dataset['formal_ready']}）"
    )
    denominators = summary["denominators"]
    lines.append(
        f"- 分母：{denominators['case_groups_expected']} 个 case-group，"
        f"有末轮结论 {denominators['case_groups_with_final_turn']} 个，缺 {denominators['case_groups_missing']} 个"
    )
    lines.append("")
    lines.append("## 工程侧（实测计数，不是质量分）")
    lines.append("")
    header = "| 组别 | case-group | 完成 | 无输出 | 超时 | 失败 | p50 ms | p95 ms | tokens(in/out) | 工具调用 | 引用 |"
    lines.append(header)
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |")
    for system_id, stats in summary["systems"].items():
        counts = stats["completion_status_counts"]
        tokens = stats["tokens"]
        lines.append(
            "| {sid} | {groups} | {completed} | {no_output} | {timeout} | {error} | {p50} | {p95} | {tin}/{tout} | {tools} | {cites} |".format(
                sid=system_id,
                groups=stats["case_groups"],
                completed=counts.get("completed", 0),
                no_output=counts.get("no_output", 0),
                timeout=counts.get("timeout", 0),
                error=counts.get("error", 0),
                p50=stats["latency_ms"]["p50"],
                p95=stats["latency_ms"]["p95"],
                tin=tokens["input"],
                tout=tokens["output"],
                tools=stats["tool_calls"],
                cites=stats["citations"],
            )
        )
    lines.append("")
    lines.append("时延口径：末轮端到端墙钟；token 分母为「有 usage 的组数」，见表尾说明。")
    lines.append("")
    overridden = {
        system_id: stats["assembly_variants"]
        for system_id, stats in summary["systems"].items()
        if len(stats.get("assembly_variants") or {}) > 1
        or any("override" in name for name in (stats.get("assembly_variants") or {}))
    }
    if overridden:
        lines.append("装配变体（凡出现 `override` 都是故障注入改了装配，报告须说明）：")
        for system_id, variants in overridden.items():
            lines.append(f"- {system_id}：{variants}")
        lines.append("")

    human = summary.get("human_scores")
    if human is None:
        lines.append("## 人工评分")
        lines.append("")
        lines.append(f"**{summary['human_scores_note']}**")
        lines.append("")
    else:
        lines.append("## 人工评分（来自 ratings.csv）")
        lines.append("")
        lines.append("| 组别 | 评分行 | 硬失败 yes | 硬失败 needs_review | 无硬失败 | 总分均值 | C2 均值 | 关键约束 |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
        for system_id, stats in human["per_system"].items():
            critical = stats["critical_failure_counts"]
            lines.append(
                "| {sid} | {rows} | {yes} | {rev} | {no} | {mean} | {c2} | {checks} |".format(
                    sid=system_id,
                    rows=stats["rating_rows"],
                    yes=critical.get("yes", 0),
                    rev=critical.get("needs_review", 0),
                    no=critical.get("no", 0),
                    mean=stats["quality_score"]["mean"],
                    c2=stats["action_executability_c2"]["mean"],
                    checks=stats["required_checks"]["ratio"],
                )
            )
        lines.append("")
        lines.append("`needs_review` 不是通过：它表示需要专业复核，不得折进「无硬失败」。")
        lines.append("")
        paired = human.get("paired") or {}
        if paired:
            lines.append("### 配对比较（同题五维总分）")
            lines.append("")
            lines.append("| 对比 | 左胜 | 平 | 右胜 | 配对数 |")
            lines.append("| --- | ---: | ---: | ---: | ---: |")
            for name, stats in paired.items():
                lines.append(
                    f"| {name} | {stats['left_wins']} | {stats['ties']} | {stats['right_wins']} | {stats['total_pairs']} |"
                )
            lines.append("")
        agreement = human.get("agreement") or {}
        if agreement.get("double_rated_groups"):
            lines.append("### 评分者一致性")
            lines.append("")
            lines.append(f"双评 case-group：{agreement['double_rated_groups']}")
            for column, stats in agreement["dimensions"].items():
                lines.append(
                    f"- {column}：完全一致 {stats['exact_agreement']}，相差 ≤1 分 {stats['within_one_agreement']}（n={stats['n']}）"
                )
            lines.append("")

    lines.append("## 故障注入")
    lines.append("")
    injection = summary.get("fault_injection") or {}
    if not injection.get("requested_counts"):
        lines.append("本批次没有请求任何故障注入（`--fixtures` 未提供，案例也未声明）。")
    else:
        lines.append(f"- 注册表版本：`{injection.get('registry_version')}`")
        lines.append(f"- 请求：{injection.get('requested_counts')}")
        lines.append(f"- 已实施：{injection.get('applied_counts')}")
        if injection.get("not_applicable_counts"):
            lines.append(f"- 因该组没有注入点而未实施：{injection.get('not_applicable_counts')}")
        if injection.get("unsupported_counts"):
            lines.append(f"- **未支持**（这一类没测成）：{injection.get('unsupported_counts')}")
        if injection.get("unknown_counts"):
            lines.append(f"- **未知 fixture**（注册表里没有）：{injection.get('unknown_counts')}")
        for name, note in (injection.get("unsupported") or {}).items():
            lines.append(f"- **未支持** `{name}`：{note}")
    lines.append("")
    observation = summary.get("fault_injection_observation") or {}
    by_fixture = observation.get("by_fixture") or {}
    if by_fixture:
        lines.append("### 实施 vs 观察到（按有效记录）")
        lines.append("")
        lines.append("| fixture | 记录数 | 已装上 | 观察到 | 装上但没被调用 | 无对等注入点 | 未支持 | 越界 |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for name, bucket in sorted(by_fixture.items()):
            lines.append(
                "| {name} | {records} | {applied} | {observed} | {uncalled} | {na} | {unsupported} | {outside} |".format(
                    name=name,
                    records=bucket.get("records", 0),
                    applied=bucket.get("applied", 0),
                    observed=bucket.get("observed", 0),
                    uncalled=bucket.get("installed_but_uncalled", 0),
                    na=bucket.get("not_applicable", 0),
                    unsupported=bucket.get("unsupported", 0),
                    outside=bucket.get("out_of_harness", 0) + bucket.get("unknown", 0),
                )
            )
        lines.append("")
        lines.append(
            f"「装上但没被调用」合计 {observation.get('installed_but_uncalled_total', 0)} 个回合："
            f"{observation.get('note', '')}"
        )
        lines.append("")
    lines.append("## 结论边界")
    lines.append("")
    for caveat in summary.get("caveats", []):
        lines.append(f"- {caveat}")
    lines.append("")
    lines.append("本文件不含任何专业安全结论；即便导入人工评分，也只能声明「在指定合成情境与条件下的一致性结果」。")
    lines.append("")
    return "\n".join(lines)


__all__ = ["PERCENTILES", "SystemStats", "render_markdown", "summarize_run"]
