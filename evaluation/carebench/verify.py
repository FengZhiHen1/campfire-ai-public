"""校验：把证据包重新算一遍，任何对不上都报出来（不修补、不忽略）。

职责：核对案例/配置/批次指纹、逐条输出记录的形状与公平性（三组输入 hash 一致）、
轨迹文件存在性、进度与分母、评审包的盲化与评分导入的一致性、summary 与原始记录的
一致性。

边界：**只读**。校验失败不改任何东西——证据包坏在哪里就报哪里，让人回到原始记录判断。

判据口径：所有 hash 都按 :mod:`evaluation.carebench.hashing` 重算；所有分母都按
「案例集 × 组别」重算。任何「用 manifest 里写的数字证明 manifest 正确」的写法都不算校验。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import prompts
from .cases import Case, CaseSet, parse_cases
from .config import RunConfig
from .hashing import batch_fingerprint, sha256_file, sha256_text, sha256_value
from .records import REQUIRED_RECORD_FIELDS, effective_records, group_progress, is_final, key_of, progress_summary
from .review import CRITICAL_FAILURE_VALUES, MAP_FILE, PACKET_FILE, RATINGS_COLUMNS, load_imported_ratings
from .store import RunStore, read_json, trailing_partial_line

#: 评审包里禁止出现的键/值模式（盲化的机械判据）。
FORBIDDEN_PACKET_KEYS = ("system_id", "system", "label", "model_id", "assembly")


@dataclass
class VerifyReport:
    """校验结论。"""

    run_id: str
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """是否有硬违反（warning 不影响通过）。"""
        return not self.violations

    def to_dict(self) -> dict[str, Any]:
        """落盘形状。"""
        return {
            "run_id": self.run_id,
            "ok": self.ok,
            "violations": list(self.violations),
            "warnings": list(self.warnings),
            "facts": dict(self.facts),
        }


def verify_run(store: RunStore, *, require_complete: bool = False) -> VerifyReport:
    """校验一个 run 目录。

    Args:
        require_complete: 要求所有 case-group 都有最终结论（正式批次用 true）。
    """
    report = VerifyReport(run_id=store.root.name)

    if not store.manifest_path.exists():
        report.violations.append("缺 manifest.json：这不是一个完整的证据包")
        return report
    manifest = store.read_manifest()

    case_set = _check_cases(store, manifest, report)
    config = _check_config(manifest, report)
    _check_fingerprint(store, manifest, case_set, report)
    records = _check_outputs(store, manifest, case_set, config, report)
    _check_progress(store, manifest, case_set, config, records, report, require_complete=require_complete)
    _check_review(store, manifest, records, config, report)
    _check_summary(store, manifest, records, config, report)
    return report


def _check_cases(store: RunStore, manifest: dict[str, Any], report: VerifyReport) -> CaseSet | None:
    """案例文件的字节 hash、逐案 hash 与 manifest 声明是否一致。"""
    if not store.cases_path.exists():
        report.violations.append("缺 cases.frozen.jsonl：无法复算案例 hash")
        return None
    actual = sha256_file(store.cases_path)
    declared = str(manifest.get("dataset", {}).get("sha256") or "")
    if actual != declared:
        report.violations.append(f"case 文件 hash 与 manifest 不符（{actual[:12]}… ≠ {declared[:12]}…）")
    if store.freeze_path.exists():
        frozen = read_json(store.freeze_path)
        if str(frozen.get("dataset_sha256") or "") != actual:
            report.violations.append("freeze.json 的 dataset_sha256 与 run 目录内的案例文件不符")
        if str(frozen.get("cases_sha256") or "") != actual:
            report.violations.append("freeze.json 的 cases_sha256 与 run 目录内的案例文件不符")
    case_set = parse_cases(store.cases_path.read_bytes(), source=str(store.cases_path), path=store.cases_path)
    per_case = manifest.get("dataset", {}).get("per_case_sha256") or {}
    for case in case_set.cases:
        if per_case.get(case.id) != case.sha256:
            report.violations.append(f"{case.id} 的逐案 hash 与 manifest 不符（案例被改过）")
    if list(case_set.ids) != list(manifest.get("dataset", {}).get("case_ids") or []):
        report.violations.append("manifest 的 case_ids 与案例文件顺序/内容不一致")
    report.facts["case_count"] = len(case_set.cases)
    return case_set


def _check_config(manifest: dict[str, Any], report: VerifyReport) -> RunConfig:
    """配置 hash 复算（从 manifest 里那份配置本身算）。"""
    config_payload = manifest.get("config")
    if not isinstance(config_payload, dict):
        report.violations.append("manifest 里没有 config：无法复算配置 hash")
        return RunConfig()
    declared = str(manifest.get("config_sha256") or "")
    actual = sha256_value(config_payload)
    if actual != declared:
        report.violations.append(f"config hash 与 manifest.config 复算结果不符（{actual[:12]}… ≠ {declared[:12]}…）")
    return RunConfig.from_dict(config_payload)


def _check_fingerprint(
    store: RunStore,
    manifest: dict[str, Any],
    case_set: CaseSet | None,
    report: VerifyReport,
) -> None:
    """批次指纹复算：案例 + 配置 + 代码提交三者联合。"""
    code = manifest.get("code") or {}
    expected = batch_fingerprint(
        dataset_sha256=str(manifest.get("dataset", {}).get("sha256") or ""),
        config_sha256=str(manifest.get("config_sha256") or ""),
        code_commit=str(code.get("commit") or ""),
    )
    if expected != manifest.get("batch_id"):
        report.violations.append(f"batch_id 复算不一致（{expected[:12]}… ≠ {str(manifest.get('batch_id'))[:12]}…）")
    if code.get("dirty"):
        report.warnings.append("manifest 记录代码工作区有未提交改动：本批次的复现性依赖 commit 之外的本地状态")
    if case_set is not None and case_set.sha256 != (manifest.get("dataset", {}) or {}).get("sha256"):
        # 已在 _check_cases 报过；这里只保证指纹用同一份 hash。
        pass


def _check_outputs(
    store: RunStore,
    manifest: dict[str, Any],
    case_set: CaseSet | None,
    config: RunConfig,
    report: VerifyReport,
) -> list[dict[str, Any]]:
    """逐条核对输出记录：字段、批次、案例/组别/轮次、输入 hash（公平性）、轨迹存在。"""
    if trailing_partial_line(store.outputs_path):
        report.warnings.append("outputs.jsonl 末尾有不完整行（上次中断留下）：该行未计入任何统计")
    records = store.read_outputs()
    report.facts["records"] = len(records)
    if case_set is None:
        return records

    case_by_id: dict[str, Case] = {case.id: case for case in case_set.cases}
    batch_id = str(manifest.get("batch_id") or "")
    input_hashes: dict[tuple[str, int], set[str]] = {}

    for index, record in enumerate(records, start=1):
        missing = [name for name in REQUIRED_RECORD_FIELDS if name not in record]
        if missing:
            report.violations.append(f"第 {index} 条记录缺字段：{missing}")
            continue
        if str(record.get("batch_id")) != batch_id:
            report.violations.append(f"第 {index} 条记录的 batch_id 不属于本批次")
        case_id = str(record.get("case_id"))
        system_id = str(record.get("system_id"))
        turn = int(record.get("turn") or 0)
        case = case_by_id.get(case_id)
        if case is None:
            report.violations.append(f"第 {index} 条记录的 case_id 不在案例集里：{case_id}")
            continue
        if system_id not in config.systems:
            report.violations.append(f"第 {index} 条记录的 system_id 未启用：{system_id}")
        if turn < 1 or turn > case.turns:
            report.violations.append(f"第 {index} 条记录的 turn={turn} 超出 {case_id} 的轮数（{case.turns}）")
        expected_input = prompts.render_user_turn(
            shared_context=case.shared_context,
            message=case.message_for_turn(turn) if 1 <= turn <= case.turns else "",
            is_followup=turn > 1,
        )
        if record.get("input_sha256") != sha256_text(expected_input):
            report.violations.append(
                f"第 {index} 条记录（{case_id}/{system_id}/t{turn}）的输入文本与案例渲染不一致："
                "三组信息可得性可能不对称"
            )
        input_hashes.setdefault((case_id, turn), set()).add(str(record.get("input_sha256")))
        trace_file = record.get("trace_file")
        if not trace_file or not (store.root / str(trace_file)).exists():
            report.violations.append(f"第 {index} 条记录的轨迹文件不存在：{trace_file}")
        status_flags = record.get("status_flags")
        if not isinstance(status_flags, dict):
            report.violations.append(f"第 {index} 条记录缺 status_flags")
        expected_record_hash = sha256_value({key: value for key, value in record.items() if key != "record_sha256"})
        if record.get("record_sha256") != expected_record_hash:
            report.violations.append(
                f"第 {index} 条记录（{case_id}/{system_id}/t{turn}）的内容 hash 不符："
                "记录被事后修改过（原始输出不可改，协议 01 第 5 节）"
            )

    for (case_id, turn), hashes in input_hashes.items():
        if len(hashes) > 1:
            report.violations.append(f"{case_id} 第 {turn} 轮在三组间的输入 hash 不一致（信息不对称）")

    final = effective_records(records)
    report.facts["effective_records"] = len(final)
    return records


def _check_progress(
    store: RunStore,
    manifest: dict[str, Any],
    case_set: CaseSet | None,
    config: RunConfig,
    records: list[dict[str, Any]],
    report: VerifyReport,
    *,
    require_complete: bool,
) -> None:
    """进度与分母：期望组数必须等于案例数 × 组别数；state.json 必须与记录一致。"""
    if case_set is None:
        return
    progress = group_progress(records, cases=case_set.cases, system_ids=list(config.systems), config=config)
    summary = progress_summary(progress)
    report.facts["progress"] = summary

    declared = manifest.get("progress") or {}
    for key in ("case_groups_expected", "turns_expected"):
        if key in declared and int(declared[key]) != int(summary[key]):
            report.violations.append(f"manifest.progress.{key}={declared[key]} 与复算结果 {summary[key]} 不一致")

    state = store.read_state()
    if state is not None:
        state_progress = state.get("progress") or {}
        if int(state_progress.get("case_groups_complete", -1)) != int(summary["case_groups_complete"]):
            report.warnings.append("state.json 的完成组数与记录复算不一致（中断后续跑未刷新，或 state 被外部改过）")

    if require_complete and summary["case_groups_complete"] != summary["case_groups_expected"]:
        report.violations.append(
            f"要求跑满但只完成 {summary['case_groups_complete']}/{summary['case_groups_expected']} 个 case-group"
            "（正式批次不得用部分结果充当完整结果）"
        )

    # 末轮结论：每条有效记录的 (案例, 组别, 轮次) 必须落在声明的轮数内，且不带越界状态。
    final = effective_records(records)
    for case in case_set.cases:
        for system_id in config.systems:
            for turn in range(1, case.turns + 1):
                record = final.get((case.id, system_id, turn))
                if record is not None and not is_final(record, config):
                    report.warnings.append(
                        f"{case.id}/{system_id}/t{turn} 只剩可重试状态（{record.get('completion_status')}）"
                        "且未用完重试额度：属未完成运行"
                    )


def _check_review(
    store: RunStore,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    config: RunConfig,
    report: VerifyReport,
) -> None:
    """评审包盲化、映射完整、评分导入与映射一致。"""
    packet_path = store.review_dir / PACKET_FILE
    map_path = store.review_dir / MAP_FILE
    ratings = load_imported_ratings(store)
    review_meta = manifest.get("review") or {}
    report.facts["review_state"] = review_meta.get("state", "pending")

    if ratings and not review_meta.get("ratings_imported"):
        report.violations.append("存在 ratings.imported.csv，但 manifest 未记录 rating 导入状态")
    if not ratings and review_meta.get("human_scores_available"):
        report.violations.append("manifest 声称有人工评分，但没有 ratings.imported.csv")
    if review_meta.get("human_scores_available") and review_meta.get("state") != "ratings_imported":
        report.violations.append(f"manifest.review.state={review_meta.get('state')!r} 与「有人工评分」矛盾")

    if not packet_path.exists():
        if ratings:
            report.violations.append("有评分导入但没有评审包：评分的来源无法核对")
        return
    packet_text = packet_path.read_text(encoding="utf-8")
    for key in FORBIDDEN_PACKET_KEYS:
        if re.search(rf'"{key}"\s*:', packet_text):
            report.violations.append(f"评审包含有组别标识字段 `{key}`：盲化失效")
    if not map_path.exists():
        report.violations.append("缺 blind-map.json：无法核对盲化映射")
        return
    mapping = read_json(map_path)
    per_case: dict[str, dict[str, str]] = mapping.get("map") or {}
    if not str(mapping.get("warning") or "").strip():
        report.violations.append("blind-map.json 缺少「不得交给评审者」的警示标记")

    system_ids = list(config.systems)
    for case_id, blind_map in per_case.items():
        if sorted(blind_map.values()) != sorted(system_ids):
            report.violations.append(f"{case_id} 的盲化映射没有覆盖全部组别")
        if len(set(blind_map.values())) != len(blind_map):
            report.violations.append(f"{case_id} 的盲化映射有重复组别（同一系统出现两次）")

    blind_to_system = {blind_id: system for blind_map in per_case.values() for blind_id, system in blind_map.items()}
    for row in ratings:
        if str(row.get("blind_id")) not in blind_to_system:
            report.violations.append(f"评分行引用了未知 blind_id：{row.get('blind_id')}")
            continue
        if str(row.get("system_id")) != blind_to_system[str(row.get("blind_id"))]:
            report.violations.append(f"评分行的组别解析与盲化映射不一致：{row.get('blind_id')}")
        if str(row.get("critical_failure")) not in CRITICAL_FAILURE_VALUES:
            report.violations.append(f"评分行 critical_failure 非法：{row.get('critical_failure')}")
        for column in RATINGS_COLUMNS:
            if column not in row:
                report.violations.append(f"评分行缺列：{column}")
                break


def _check_summary(
    store: RunStore,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    config: RunConfig,
    report: VerifyReport,
) -> None:
    """summary 与原始记录一致（分母、状态计数、有无人工分）。"""
    summary_path = store.root / "summary.json"
    if not summary_path.exists():
        report.warnings.append("缺 summary.json：先运行 summarize 才能形成报告")
        return
    summary = read_json(summary_path)
    expected_groups = len(manifest.get("dataset", {}).get("case_ids") or []) * len(config.systems)
    got = int((summary.get("denominators") or {}).get("case_groups_expected", -1))
    if got != expected_groups:
        report.violations.append(f"summary 的分母 {got} ≠ 案例数 × 组别数 {expected_groups}")

    has_ratings = bool(load_imported_ratings(store))
    if has_ratings and summary.get("human_scores") is None:
        report.violations.append("已导入人工评分但 summary 没算分：summary 过期，请重跑 summarize")
    if not has_ratings and summary.get("human_scores") is not None:
        report.violations.append("没有人工评分却出现 human_scores：绝不能由程序生成质量分")

    final = effective_records(records)
    for system_id in config.systems:
        stats = (summary.get("systems") or {}).get(system_id)
        if not isinstance(stats, dict):
            report.violations.append(f"summary 缺组别 {system_id}")
            continue
        # case-group 数 = 该组跑出末轮结论的**不同案例**数（不是轮次数）
        actual = len({case_id for (case_id, sid, _turn) in final if sid == system_id})
        if int(stats.get("case_groups", -1)) != actual:
            report.violations.append(
                f"summary 里 {system_id} 的 case-group 数 {stats.get('case_groups')} ≠ 记录数 {actual}"
            )


def verify_paths(run_dir: Path, *, require_complete: bool = False) -> VerifyReport:
    """按目录路径校验（CLI 用）。"""
    return verify_run(RunStore(root=run_dir), require_complete=require_complete)


__all__ = ["FORBIDDEN_PACKET_KEYS", "VerifyReport", "verify_paths", "verify_run", "key_of"]
