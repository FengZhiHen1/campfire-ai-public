"""校验：把证据包重新算一遍，任何对不上都报出来（不修补、不忽略）。

职责：核对案例/配置/批次指纹、逐条输出记录的形状与公平性（三组输入 hash 一致）、
轨迹文件存在性、进度与分母、评审包的盲化与评分导入的一致性、summary 与原始记录的
一致性。

边界：**只读**。校验失败不改任何东西——证据包坏在哪里就报哪里，让人回到原始记录判断。

判据口径：所有 hash 都按 :mod:`evaluation.carebench.hashing` 重算；所有分母都按
「案例集 × 组别」重算。任何「用 manifest 里写的数字证明 manifest 正确」的写法都不算校验。

防的是哪种篡改：**重算记录 hash 之后的篡改**。记录自带的 `record_sha256` 只能证明
「这一行没被随手改过」；把所有内容改完再重算 hash，它就不再有任何证明力。因此每条
检查都必须与**别处的独立事实**对照：运行身份对照 manifest 的其它事实与冻结绑定、
规范文本投影对照原始载荷重算、评审包对照原始记录、故障观察对照轨迹与 tool_calls、
重试/会话对照配置预算与轮次顺序。任何一条对不上都是硬违反。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import prompts
from .ai_review import ai_review_present, verify_ai_review_report
from .cases import Case, CaseSet, parse_cases
from .config import FORMAL_LABEL, RunConfig
from .hashing import batch_fingerprint, sha256_file, sha256_text, sha256_value
from .knowledge import EMBEDDING_DIM
from .manifest import identity_fingerprint
from .records import (
    FIXTURE_STATUSES,
    REQUIRED_RECORD_FIELDS,
    effective_records,
    fixture_observation,
    group_progress,
    is_final,
    key_of,
    progress_summary,
)
from .render import project
from .review import (
    CRITICAL_FAILURE_VALUES,
    MAP_FILE,
    PACKET_FILE,
    RATINGS_COLUMNS,
    blind_order,
    load_imported_ratings,
)
from .store import RunStore, read_json, trailing_partial_line
from .systems.base import RETRY_NEW_SESSION, RETRY_SAFETY

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
    _check_identity(manifest, report)
    _check_fingerprint(store, manifest, case_set, report)
    records = _check_outputs(store, manifest, case_set, config, report)
    _check_retry_and_sessions(records, config, report)
    progress = _check_progress(store, manifest, case_set, config, records, report, require_complete=require_complete)
    _check_fixtures(
        store,
        manifest,
        records,
        config,
        report,
        complete=bool(progress) and progress.get("case_groups_complete") == progress.get("case_groups_expected"),
    )
    _check_review(store, manifest, case_set, records, config, report)
    _check_summary(store, manifest, records, config, report)
    if ai_review_present(store):
        ai = verify_ai_review_report(store, require_complete=require_complete)
        report.violations.extend(f"AI 评审：{item}" for item in ai.violations)
        report.warnings.extend(f"AI 评审：{item}" for item in ai.warnings)
        report.facts["ai_review"] = ai.facts
    elif require_complete and manifest.get("label") == FORMAL_LABEL:
        report.violations.append("正式批次缺独立 AI 评审：运行完成不能替代评分完成")
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


def _check_identity(manifest: dict[str, Any], report: VerifyReport) -> None:
    """运行身份：指纹可复算、与 manifest 其它事实互相对得上、与冻结时锁定的一致。

    为什么不能只核对 `run_identity_sha256`：把身份段和指纹一起改掉，自洽性检查就全过。
    因此这里同时把身份段与**同一份 manifest 里由别处派生的字段**（`inference`、
    `knowledge_snapshot`、`systems[].model_id`）逐项对齐——只改一处必然露馅；三处一起
    改则与记录里逐条绑定的身份指纹冲突。
    """
    identity = manifest.get("run_identity")
    if not isinstance(identity, dict):
        report.violations.append("manifest 缺 run_identity：无法证明本批次跑的是哪个模型/端点/知识快照")
        return
    declared = str(manifest.get("run_identity_sha256") or "")
    actual = identity_fingerprint(identity)
    report.facts["run_identity_sha256"] = actual
    if not declared:
        report.violations.append("manifest 缺 run_identity_sha256：身份段没有可复算的指纹")
    elif declared != actual:
        report.violations.append(f"运行身份指纹与身份段复算不符（{actual[:12]}… ≠ {declared[:12]}…）：身份段被事后改过")

    chat = identity.get("chat") or {}
    embedding = identity.get("embedding") or {}
    knowledge = identity.get("knowledge") or {}
    inference = manifest.get("inference") or {}
    sdk_retry = (inference.get("retry") or {}).get("sdk_runner") or {}
    for label, left, right in (
        ("inference.model_id", identity.get("model_id"), inference.get("model_id")),
        ("inference.chat_endpoint_host", chat.get("host"), inference.get("chat_endpoint_host")),
        ("inference.embedding_endpoint_host", embedding.get("host"), inference.get("embedding_endpoint_host")),
        (
            "inference.retry.sdk_runner.model_max_retries",
            chat.get("model_max_retries"),
            sdk_retry.get("model_max_retries"),
        ),
        ("embedding.dimension", EMBEDDING_DIM, embedding.get("dimension")),
    ):
        if left != right:
            report.violations.append(f"运行身份与 {label} 不一致：run_identity={left!r} / {label}={right!r}")

    snapshot = manifest.get("knowledge_snapshot") or {}
    items = snapshot.get("items") or []
    node_total = sum(int(item.get("nodes") or 0) for item in items if isinstance(item, dict))
    for label, left, right in (
        ("knowledge_snapshot.sha256", knowledge.get("snapshot_sha256"), snapshot.get("sha256")),
        ("knowledge_snapshot.database", knowledge.get("database"), snapshot.get("database")),
        ("knowledge_snapshot.items", knowledge.get("items"), len(items)),
        ("knowledge_snapshot.nodes", knowledge.get("nodes"), node_total),
    ):
        if left != right:
            report.violations.append(f"运行身份的知识绑定与 {label} 不一致：run_identity={left!r} / {label}={right!r}")

    for meta in manifest.get("systems") or []:
        if not isinstance(meta, dict):
            continue
        if meta.get("model_id") != identity.get("model_id"):
            report.violations.append(
                f"{meta.get('system_id')} 组的装配模型 {meta.get('model_id')!r} 与运行身份模型 "
                f"{identity.get('model_id')!r} 不一致：三组必须跑同一个模型"
            )

    binding = manifest.get("freeze_binding") or {}
    frozen_sha = str(binding.get("frozen_identity_sha256") or "")
    if frozen_sha and frozen_sha != actual:
        report.violations.append(
            "本批次实际运行的运行身份与冻结时锁定的身份不同："
            f"冻结 {frozen_sha[:12]}… ≠ 实际 {actual[:12]}…（执行计划与执行结果不是一回事）"
        )
    if binding.get("config_drift") and not binding.get("config_drift_allowed"):
        report.violations.append("配置与冻结声明不同且没有显式允许（freeze_binding.config_drift=true）")
    if binding.get("config_drift") and binding.get("config_drift_allowed"):
        report.warnings.append(
            "本批次允许了配置漂移（--allow-config-drift）：实际配置与冻结声明不同，报告不得当作同一条件"
        )
    if not binding:
        report.warnings.append("manifest 缺 freeze_binding：无法核对「冻结时锁定了什么」（旧版批次）")
    elif str(manifest.get("label")) == FORMAL_LABEL and not binding.get("identity_locked"):
        report.violations.append(
            f"正式批次（label={FORMAL_LABEL}）没有冻结身份锁定：无法证明跑的是计划里的模型与知识快照"
        )


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
    if not store.freeze_path.exists():
        report.violations.append("缺 freeze.json：无法核对案例、配置与代码的冻结副本")
    else:
        frozen = read_json(store.freeze_path)
        for name, actual, declared in (
            ("config_sha256", manifest.get("config_sha256"), frozen.get("config_sha256")),
            ("code.commit", code.get("commit"), (frozen.get("code") or {}).get("commit")),
        ):
            if not declared or actual != declared:
                report.violations.append(f"manifest 的 {name} 与 freeze.json 冻结副本不一致")
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
    identity_sha = str(manifest.get("run_identity_sha256") or "")
    input_hashes: dict[tuple[str, int], set[str]] = {}

    for index, record in enumerate(records, start=1):
        missing = [name for name in REQUIRED_RECORD_FIELDS if name not in record]
        if missing:
            report.violations.append(f"第 {index} 条记录缺字段：{missing}")
            continue
        if str(record.get("batch_id")) != batch_id:
            report.violations.append(f"第 {index} 条记录的 batch_id 不属于本批次")
        if identity_sha and str(record.get("run_identity_sha256")) != identity_sha:
            report.violations.append(
                f"第 {index} 条记录的运行身份指纹与 manifest 不符：记录不是在本批次的模型/端点/知识上产生的"
            )
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
        else:
            _check_status_consistency(index, record, status_flags, report)
        expected_record_hash = sha256_value({key: value for key, value in record.items() if key != "record_sha256"})
        if record.get("record_sha256") != expected_record_hash:
            report.violations.append(
                f"第 {index} 条记录（{case_id}/{system_id}/t{turn}）的内容 hash 不符："
                "记录被事后修改过（原始输出不可改，协议 01 第 5 节）"
            )
        _check_projection(index, record, case_id=case_id, system_id=system_id, turn=turn, report=report)
        _check_retry_shape(index, record, report)

    for (case_id, turn), hashes in input_hashes.items():
        if len(hashes) > 1:
            report.violations.append(f"{case_id} 第 {turn} 轮在三组间的输入 hash 不一致（信息不对称）")

    final = effective_records(records)
    report.facts["effective_records"] = len(final)
    return records


def _check_projection(
    index: int,
    record: dict[str, Any],
    *,
    case_id: str,
    system_id: str,
    turn: int,
    report: VerifyReport,
) -> None:
    """规范文本投影必须能由「原始正文 + 结构化载荷」原样重算出来。

    评审包给评审者看的是投影；如果投影与原始载荷不一致，评审打的分就不再对应系统真实
    产出——而这条差异在记录自带的 hash 里是看不出来的（改完重算即可）。
    """
    raw = str(record.get("raw_output") or "")
    structured = record.get("structured_output") or []
    if not isinstance(structured, list):
        report.violations.append(f"第 {index} 条记录的 structured_output 不是数组")
        return
    if "output_text" not in record:
        report.violations.append(f"第 {index} 条记录缺 output_text（规范文本投影）")
        return
    expected = project(raw, structured)
    if str(record.get("output_text")) != expected:
        report.violations.append(
            f"第 {index} 条记录（{case_id}/{system_id}/t{turn}）的规范文本投影与原始载荷重算结果不一致："
            "评审看到的内容不是系统真实产出"
        )


def _check_status_consistency(index: int, record: dict[str, Any], flags: dict[str, Any], report: VerifyReport) -> None:
    """状态词表与可见产出必须自洽（四处口径同一：raw / structured / output_text / flags）。"""
    status = str(record.get("completion_status"))
    raw = str(record.get("raw_output") or "")
    structured = record.get("structured_output") or []
    output_text = str(record.get("output_text") or "") or raw
    has_output = bool(raw.strip() or structured)
    if status == "completed" and not has_output:
        report.violations.append(f"第 {index} 条记录标为 completed 但正文与结构化产出都为空")
    if status == "no_output" and has_output:
        report.violations.append(f"第 {index} 条记录标为 no_output 但存在可见产出")
    if status in {"error", "timeout"} and not isinstance(record.get("error"), dict):
        report.violations.append(f"第 {index} 条记录标为 {status} 但缺 error 说明")
    expected_flags = {
        "empty_output": not output_text.strip(),
        "structured_only": bool(structured) and not raw.strip(),
        "refusal_suspected": prompts.refusal_suspected(output_text),
    }
    for name, expected in expected_flags.items():
        if name not in flags:
            report.violations.append(f"第 {index} 条记录缺 status_flags.{name}")
        elif not isinstance(flags[name], bool) or flags[name] != expected:
            report.violations.append(
                f"第 {index} 条记录的 status_flags.{name}={flags[name]!r} 与重算结果 {expected} 不一致"
            )


def _check_retry_shape(index: int, record: dict[str, Any], report: VerifyReport) -> None:
    """`retry` 段必须与记录自身的尝试序号一致（两处口径不能各写一份）。"""
    retry = record.get("retry")
    if not isinstance(retry, dict):
        report.violations.append(f"第 {index} 条记录缺 retry 段")
        return
    if retry.get("attempt") != record.get("attempt"):
        report.violations.append(
            f"第 {index} 条记录的 retry.attempt={retry.get('attempt')} 与 attempt={record.get('attempt')} 不一致"
        )
    if str(retry.get("retry_safety")) not in RETRY_SAFETY:
        report.violations.append(f"第 {index} 条记录的 retry.retry_safety 非法：{retry.get('retry_safety')!r}")


def _check_retry_and_sessions(records: list[dict[str, Any]], config: RunConfig, report: VerifyReport) -> None:
    """重试预算与会话隔离：尝试序号连续、预算不超、换会话只在失败落库时发生、同轮输入不重复。

    「用户输入无重复」是这里的核心：C 组失败尝试若已写入会话，原地重试会让模型在自己
    的历史里看到同一条使用者消息两次，后续每一轮都带着这段重复历史——那种污染在记录
    的 hash 里完全看不出来，只能靠会话序列核对。
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        if not {"case_id", "system_id", "turn", "attempt"} <= set(record):
            continue
        groups.setdefault((str(record["case_id"]), str(record["system_id"])), []).append(record)
    budget = 1 + config.max_outer_retries
    for (case_id, system_id), items in groups.items():
        per_turn: dict[int, list[dict[str, Any]]] = {}
        for record in items:
            per_turn.setdefault(int(record["turn"]), []).append(record)
        for turn, attempts in per_turn.items():
            numbering = sorted(int(record["attempt"]) for record in attempts)
            if numbering != list(range(1, len(numbering) + 1)):
                report.violations.append(
                    f"{case_id}/{system_id}/t{turn} 的尝试序号不是从 1 连续递增：{numbering}"
                    "（记录被改过，或续跑重写了已落盘的尝试）"
                )
            ordered = sorted(attempts, key=lambda record: int(record["attempt"]))
            for earlier in ordered[:-1]:
                if str(earlier.get("completion_status")) not in config.retry_on:
                    report.violations.append(
                        f"{case_id}/{system_id}/t{turn} 对不可重试状态（{earlier.get('completion_status')}）"
                        "发起了重试：这不是策略允许的重试"
                    )
        used = max((int(record["attempt"]) for record in items), default=0)
        if used > budget:
            report.violations.append(
                f"{case_id}/{system_id} 共用了 {used} 次尝试，超过预算 {budget}"
                f"（max_outer_retries={config.max_outer_retries}）"
            )
        _check_session_sequence(case_id, system_id, items, config, report)


def _check_session_sequence(
    case_id: str,
    system_id: str,
    items: list[dict[str, Any]],
    config: RunConfig,
    report: VerifyReport,
) -> None:
    """会话序列：账号与会话一一对应、放弃的会话不得复用、换会话必须从第 1 轮重开。"""
    account_of: dict[str, str] = {}
    closed: set[str] = set()
    turn_history: dict[str, dict[int, dict[str, Any]]] = {}
    for index, record in enumerate(items):
        session_id = str(record.get("session_id") or "")
        account_id = str(record.get("account_id") or "")
        turn = int(record.get("turn") or 0)
        if not session_id or not account_id:
            report.violations.append(f"{case_id}/{system_id} 有记录缺 session_id/account_id：无法核对会话隔离")
            continue
        known = account_of.get(session_id)
        if known is not None and known != account_id:
            report.violations.append(f"{case_id}/{system_id} 的会话 {session_id[:8]}… 对应了两个不同账号")
        account_of.setdefault(session_id, account_id)
        if session_id in closed:
            report.violations.append(
                f"{case_id}/{system_id} 复用了已放弃的会话 {session_id[:8]}…：该会话里已有一次失败留下的历史"
            )
        if index > 0:
            previous = items[index - 1]
            previous_session = str(previous.get("session_id") or "")
            if session_id != previous_session:
                previous_retry = previous.get("retry") or {}
                previous_safety = str(previous_retry.get("retry_safety") or "")
                previous_status = str(previous.get("completion_status"))
                if previous_safety != RETRY_NEW_SESSION or previous_status not in config.retry_on:
                    report.violations.append(
                        f"{case_id}/{system_id}：上一条记录（{previous_status}/{previous_safety or 'n/a'}）"
                        "之后换了会话——只有「失败已落库」才允许换会话重开"
                    )
                if turn != 1:
                    report.violations.append(
                        f"{case_id}/{system_id}：换新会话后从第 {turn} 轮开始，没有从第 1 轮重开（会漏跑轮次）"
                    )
                closed.add(previous_session)
        session_turns = turn_history.setdefault(session_id, {})
        earlier = session_turns.get(turn)
        if earlier is not None:
            earlier_retry = earlier.get("retry") or {}
            if (
                str(earlier_retry.get("retry_safety")) != "same_session"
                or str(earlier.get("completion_status")) not in config.retry_on
            ):
                report.violations.append(
                    f"{case_id}/{system_id}/t{turn} 在同一会话里重复发送了同一轮使用者输入"
                    "（前一条不是「未落库的可重试失败」）：会话历史会出现重复消息，污染后续轮次"
                )
        session_turns[turn] = record


def _read_trace(store: RunStore, record: dict[str, Any], index: int, report: VerifyReport) -> dict[str, Any] | None:
    """读记录引用的轨迹文件（读不到已在别处报过，这里返回 None 让调用方降级判断）。"""
    trace_file = record.get("trace_file")
    if not trace_file:
        return None
    try:
        payload = store.read_trace(str(trace_file))
    except (OSError, ValueError, json.JSONDecodeError):
        report.violations.append(f"第 {index} 条记录的轨迹文件无法读取：{trace_file}")
        return None
    return payload if isinstance(payload, dict) else None


def _check_fixtures(
    store: RunStore,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    config: RunConfig,
    report: VerifyReport,
    *,
    complete: bool,
) -> None:
    """故障注入的「请求 / 实施 / 观察到」三件事必须与轨迹对得上，且汇总不注水。"""
    for index, record in enumerate(records, start=1):
        entries = record.get("fixtures")
        if not isinstance(entries, list):
            report.violations.append(f"第 {index} 条记录缺 fixtures 清单（无法判断本轮请求了什么故障）")
            continue
        if not entries:
            continue
        trace = _read_trace(store, record, index, report)
        calls = record.get("tool_calls") or []
        if not isinstance(calls, list):
            report.violations.append(f"第 {index} 条记录的 tool_calls 不是数组")
            calls = []
        tool_calls = sum(1 for call in calls if isinstance(call, dict) and call.get("name") == "search_knowledge")
        retrieval = ((trace or {}).get("retrieval") or {}) if trace else {}
        for item in entries:
            if not isinstance(item, dict):
                report.violations.append(f"第 {index} 条记录的 fixtures 项不是对象")
                continue
            name = str(item.get("name") or "")
            status = str(item.get("status") or "")
            applied = bool(item.get("applied"))
            if status not in FIXTURE_STATUSES:
                report.violations.append(f"第 {index} 条记录的 fixture {name!r} 状态非法：{status!r}")
            if applied is not (status == "applied"):
                report.violations.append(
                    f"第 {index} 条记录的 fixture {name!r}：applied={applied} 与 status={status!r} 矛盾"
                )
            observed_calls = item.get("observed_calls")
            if not isinstance(observed_calls, int) or observed_calls < 0:
                report.violations.append(f"第 {index} 条记录的 fixture {name!r} 缺 observed_calls")
                continue
            if name.startswith("tool_"):
                expected_calls = tool_calls
            elif name.startswith("retrieval_"):
                expected_calls = 1 if retrieval else 0
            else:
                expected_calls = 0
            if observed_calls != expected_calls:
                report.violations.append(
                    f"第 {index} 条记录的 fixture {name!r}：observed_calls={observed_calls} 与"
                    f"轨迹/tool_calls 复算 {expected_calls} 不一致"
                )
            expected_observed = bool(applied and expected_calls > 0)
            if bool(item.get("observed")) is not expected_observed:
                report.violations.append(
                    f"第 {index} 条记录的 fixture {name!r}：observed={item.get('observed')} 与复算"
                    f"{expected_observed} 不一致（「装上」不等于「观察到」）"
                )

    injection = manifest.get("fault_injection") or {}
    recomputed = _recompute_fault_counts(records, config)
    report.facts["fault_injection_counts"] = recomputed
    mismatches: list[str] = []
    for key, counts in recomputed.items():
        declared = {str(name): int(value) for name, value in (injection.get(key) or {}).items()}
        if declared != counts:
            mismatches.append(f"{key}: manifest={declared} 复算={counts}")
    if mismatches and complete:
        report.violations.append("manifest.fault_injection 与记录复算不一致：" + "；".join(mismatches))
    elif mismatches:
        report.warnings.append(
            "manifest.fault_injection 与已跑记录复算不一致（批次未跑满，可能只是还没跑到）：" + "；".join(mismatches)
        )


def _recompute_fault_counts(records: list[dict[str, Any]], config: RunConfig) -> dict[str, dict[str, int]]:
    """按每个 case-group 的**首条记录**复算注入统计（同一组的后续轮次/重试不重复计）。"""
    first: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        key = (str(record.get("case_id")), str(record.get("system_id")))
        if key[1] not in config.systems:
            continue
        first.setdefault(key, record)
    buckets: dict[str, dict[str, int]] = {
        "requested_counts": {},
        "applied_counts": {},
        "not_applicable_counts": {},
        "unsupported_counts": {},
        "out_of_harness_counts": {},
        "unknown_counts": {},
    }
    bucket_names = {
        "applied": "applied_counts",
        "not_applicable": "not_applicable_counts",
        "unsupported": "unsupported_counts",
        "out_of_harness": "out_of_harness_counts",
    }
    for record in first.values():
        for item in record.get("fixtures") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            status = str(item.get("status") or ("applied" if item.get("applied") else "unknown"))
            _bump(buckets["requested_counts"], name)
            _bump(buckets[bucket_names.get(status, "unknown_counts")], name)
    return buckets


def _bump(bucket: dict[str, int], name: str) -> None:
    """计数 +1（空名字也计：让「缺名字的条目」在复算里暴露成差异）。"""
    bucket[name] = bucket.get(name, 0) + 1


def _check_progress(
    store: RunStore,
    manifest: dict[str, Any],
    case_set: CaseSet | None,
    config: RunConfig,
    records: list[dict[str, Any]],
    report: VerifyReport,
    *,
    require_complete: bool,
) -> dict[str, int] | None:
    """进度与分母：期望组数必须等于案例数 × 组别数；state.json 必须与记录一致。"""
    if case_set is None:
        return None
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
    return summary


def _check_review(
    store: RunStore,
    manifest: dict[str, Any],
    case_set: CaseSet | None,
    records: list[dict[str, Any]],
    config: RunConfig,
    report: VerifyReport,
) -> None:
    """评审包盲化、映射完整、评分导入与映射一致、**包内容与原始记录逐字对照**。"""
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
        # 映射必须是由（review_seed, case_id）派生的那一份：手工改过的映射会让评分
        # 记到别的组别上，而「覆盖了全部组别」这条检查看不出来。
        derived = blind_order(system_ids, seed=config.review_seed, case_id=case_id)
        expected_map = {f"{case_id}-X{position}": system for position, system in enumerate(derived, start=1)}
        if blind_map != expected_map:
            report.violations.append(f"{case_id} 的盲化映射不是由 review_seed 派生出来的（可能被手工改过）")

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

    declared_sha = str(review_meta.get("packet_sha256") or "")
    actual_sha = sha256_text(packet_text)
    if declared_sha and declared_sha != actual_sha:
        report.violations.append(
            f"评审包 hash 与 manifest 记录不符（{actual_sha[:12]}… ≠ {declared_sha[:12]}…）：导出后被改过"
        )
    _check_packet_contents(
        packet_text=packet_text,
        mapping=per_case,
        case_set=case_set,
        records=records,
        config=config,
        report=report,
    )


def _check_packet_contents(
    *,
    packet_text: str,
    mapping: dict[str, dict[str, str]],
    case_set: CaseSet | None,
    records: list[dict[str, Any]],
    config: RunConfig,
    report: VerifyReport,
) -> None:
    """评审包的每一行都必须等于原始记录的规范投影（否则评审看到的不是系统产出）。"""
    if case_set is None:
        return
    effective = effective_records(records)
    expected: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for case in case_set.cases:
        for system_id in config.systems:
            group: list[dict[str, Any]] = []
            for turn in range(1, case.turns + 1):
                record = effective.get((case.id, system_id, turn))
                if record is None or not is_final(record, config):
                    group = []
                    break
                group.append(record)
            if group:
                expected[(case.id, system_id)] = group

    case_of_blind = {blind_id: case_id for case_id, per_case in mapping.items() for blind_id in per_case}
    seen: set[tuple[str, str]] = set()
    for line_no, line in enumerate(packet_text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            report.violations.append(f"评审包第 {line_no} 行不是合法 JSON")
            continue
        if not isinstance(payload, dict):
            report.violations.append(f"评审包第 {line_no} 行不是对象")
            continue
        blind_id = str(payload.get("blind_id") or "")
        system_id = None
        for case_id, per_case in mapping.items():
            if blind_id in per_case:
                system_id = per_case[blind_id]
                break
        if system_id is None:
            report.violations.append(f"评审包第 {line_no} 行的 blind_id 不在映射里：{blind_id!r}")
            continue
        case_id = str(payload.get("case_id") or "")
        mapped_case = case_of_blind.get(blind_id)
        if mapped_case is not None and case_id != mapped_case:
            report.violations.append(f"评审包第 {line_no} 行的 case_id={case_id!r} 与盲化映射 {mapped_case!r} 不一致")
        key = (case_id, system_id)
        if key in seen:
            report.violations.append(f"评审包里 {case_id}/{blind_id} 出现了不止一次")
        seen.add(key)
        group = expected.get(key)
        if group is None:
            report.violations.append(f"评审包导出了没有最终结论的 case-group：{case_id}（{blind_id}）")
            continue
        turns_payload = payload.get("turns") or []
        if len(turns_payload) != len(group):
            report.violations.append(f"评审包 {blind_id} 的轮次数 {len(turns_payload)} ≠ 记录的轮次数 {len(group)}")
            continue
        for record, turn_payload in zip(group, turns_payload, strict=True):
            if not isinstance(turn_payload, dict):
                report.violations.append(f"评审包 {blind_id} 的轮次项不是对象")
                continue
            turn = int(record.get("turn") or 0)
            expected_output = str(record.get("output_text") or record.get("raw_output") or "")
            pairs = (
                ("user_text", turn_payload.get("user_text"), record.get("input_text")),
                ("output", turn_payload.get("output"), expected_output),
                (
                    "structured_output",
                    turn_payload.get("structured_output") or [],
                    record.get("structured_output") or [],
                ),
                ("completion_status", turn_payload.get("completion_status"), record.get("completion_status")),
                ("latency_ms", turn_payload.get("latency_ms"), record.get("latency_ms")),
            )
            for label, actual, want in pairs:
                if actual != want:
                    report.violations.append(
                        f"评审包 {blind_id}/t{turn} 的 {label} 与原始记录不一致：盲评看到的不是系统真实产出"
                    )
        last = group[-1]
        last_output = str(last.get("output_text") or last.get("raw_output") or "")
        if str(payload.get("final_output") or "") != last_output:
            report.violations.append(f"评审包 {blind_id} 的 final_output 与原始记录末轮投影不一致")
        if (payload.get("structured_output") or []) != (last.get("structured_output") or []):
            report.violations.append(f"评审包 {blind_id} 的 structured_output 与原始记录末轮载荷不一致")

    missing = set(expected) - seen
    for case_id, system_id in sorted(missing):
        report.violations.append(f"评审包漏掉了已完成的 case-group：{case_id}/{system_id}")


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

    # 故障观察统计必须与记录复算一致：把「装上但没被调用」写成「观察到」是最容易混过去的一处。
    observed = summary.get("fault_injection_observation")
    recomputed = fixture_observation(records)
    if observed is None:
        report.warnings.append("summary 缺 fault_injection_observation：summary 过期或旧版，请重跑 summarize")
    elif observed != recomputed:
        report.violations.append(
            f"summary 的故障观察统计与记录复算不一致（summary 被改过或过期）：summary={observed} 复算={recomputed}"
        )

    from .summarize import compute_summary

    expected = compute_summary(store)
    for name, value in expected.items():
        if summary.get(name) != value:
            report.violations.append(f"summary.{name} 与原始证据复算不一致：摘要被改过或过期")


def verify_paths(run_dir: Path, *, require_complete: bool = False) -> VerifyReport:
    """按目录路径校验（CLI 用）。"""
    return verify_run(RunStore(root=run_dir), require_complete=require_complete)


__all__ = ["FORBIDDEN_PACKET_KEYS", "VerifyReport", "verify_paths", "verify_run", "key_of"]
