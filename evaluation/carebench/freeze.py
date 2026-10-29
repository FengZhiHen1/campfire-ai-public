"""冻结：把案例集与配置钉成不可再改的身份（协议 04 第 1 节、05 第 6 节 P2）。

职责：读一份案例 JSONL，逐字节复制进冻结目录，并写出 `freeze.json`（案例 hash、
逐案 hash、配置 hash、代码提交、协议快照 hash、轮数分布、审阅状态分布、冻结人）。

边界：不判断案例质量、不改案例内容。**看过输出之后不得重新冻结同一批**——
那不是本模块能机械阻止的事，但本模块会把两次冻结的 hash 差异暴露在 verify 里。

为什么要「冻结目录」而不是每次运行现读源文件：源文件在 `inbox/`（只读来源）与将来的
正式集之间会移动；一旦运行记录里的案例 hash 与手头文件对不上，整批结果就无法复算。
冻结目录就是这个问题的答案——它是 run 目录里 `cases.frozen.jsonl` 的来源。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .cases import CaseSet, load_case_file
from .config import RunConfig
from .faults import plan_from_cases
from .hashing import sha256_file
from .knowledge import REPO_ROOT
from .manifest import code_facts, protocol_snapshot_facts, utc_now
from .store import read_json, write_json

#: 冻结目录内的案例文件名。
FROZEN_CASES = "cases.frozen.jsonl"

#: 冻结记录文件名。
FROZEN_RECORD = "freeze.json"


class FreezeError(RuntimeError):
    """冻结失败：目标目录已有内容且与本批不同（不允许静默覆盖已冻结的案例）。"""


@dataclass(frozen=True)
class FrozenSet:
    """一份冻结产物：目录、案例集与记录。"""

    directory: Path
    case_set: CaseSet
    record: dict[str, Any]

    @property
    def dataset_sha256(self) -> str:
        """冻结记录的案例 hash。"""
        return str(self.record["dataset_sha256"])


def freeze_cases(
    *,
    cases_path: Path,
    label: str,
    out_dir: Path,
    config: RunConfig,
    operator: str | None = None,
) -> FrozenSet:
    """冻结一份案例集到 `out_dir`。

    Args:
        cases_path: 案例 JSONL（可以是 `inbox/` 或仓库内的副本）。
        label: `calibration` / `pilot` / `test`（只作记录与措辞，不参与运行逻辑）。
        out_dir: 冻结目录（已存在且内容不同则拒绝）。
        config: 冻结时声明的配置（其 hash 进记录；运行时若配置不同会被 run 拦下）。
        operator: 冻结人（缺省取环境变量，见 `manifest.environment_facts`）。

    Raises:
        FreezeError: 目标目录已存在且案例 hash 不同。
        CaseValidationError: 案例结构不合法。
    """
    case_set = load_case_file(cases_path)
    # 冻结的标签必须写进被 hash 的那份配置：
    # 否则 `freeze --label calibration` 记下的是「label=pilot」的 hash，而 `run` 用
    # label=calibration 的配置，两者必然不等，配置漂移守卫会误报（实测踩过）。
    config = replace(config, label=label)
    raw = case_set.raw_bytes
    dataset_sha = case_set.sha256

    out_dir.mkdir(parents=True, exist_ok=True)
    target_cases = out_dir / FROZEN_CASES
    target_record = out_dir / FROZEN_RECORD

    if target_cases.exists():
        existing_sha = sha256_file(target_cases)
        if existing_sha != dataset_sha:
            raise FreezeError(
                f"{out_dir} 已冻结过另一版案例（{existing_sha[:12]}… ≠ {dataset_sha[:12]}…）："
                "看过输出后不得重冻同一批——请换一个冻结目录/标签，共同构成回归集"
            )
        # 内容一致：只刷新元数据（幂等，便于重跑 preflight/freeze 而不制造分叉）。
        record = read_json(target_record) if target_record.exists() else {}
        record.update(_record_payload(case_set=case_set, config=config, label=label, operator=operator))
        record["refrozen_at"] = utc_now()
        write_json(target_record, record)
        return FrozenSet(directory=out_dir, case_set=case_set, record=record)

    target_cases.write_bytes(raw)
    # 复制后立刻复算：磁盘写坏了要在这里发现，而不是等到 verify。
    if sha256_file(target_cases) != dataset_sha:
        raise FreezeError(f"写出的案例文件 hash 与源文件不一致：{target_cases}")

    record = _record_payload(case_set=case_set, config=config, label=label, operator=operator)
    record["frozen_at"] = utc_now()
    write_json(target_record, record)
    return FrozenSet(directory=out_dir, case_set=case_set, record=record)


def _record_payload(
    *,
    case_set: CaseSet,
    config: RunConfig,
    label: str,
    operator: str | None,
) -> dict[str, Any]:
    """冻结记录的正文字段（覆盖写入时只更新这些，保留原 frozen_at）。"""
    from .manifest import environment_facts

    plan = plan_from_cases(list(case_set.cases))
    turns_histogram: dict[str, int] = {}
    for case in case_set.cases:
        key = str(case.turns)
        turns_histogram[key] = turns_histogram.get(key, 0) + 1
    fixtures = {case_id: [name for name, _ in entries] for case_id, entries in plan.requested.items()}
    return {
        "label": label,
        "source_path": str(case_set.path),
        "dataset_sha256": case_set.sha256,
        "case_count": len(case_set.cases),
        "case_ids": list(case_set.ids),
        "per_case_sha256": {case.id: case.sha256 for case in case_set.cases},
        "split": case_set.split,
        "review_status_counts": case_set.review_status_counts,
        "formal_ready": all(case.approved for case in case_set.cases),
        "source_kind_counts": _source_kind_counts(case_set),
        "turns_histogram": turns_histogram,
        "case_fixtures": fixtures,
        "config": config.to_dict(),
        "config_sha256": config.sha256,
        "code": code_facts(REPO_ROOT),
        "protocol_snapshot_sha256": protocol_snapshot_facts()["sha256"],
        "operator": operator or environment_facts(REPO_ROOT)["operator"],
        "note": (
            "本记录只声明「这一批案例与配置是什么」，不声明它们被专业审核过："
            "review_status 与 formal_ready 如实反映上游状态"
        ),
    }


def _source_kind_counts(case_set: CaseSet) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in case_set.cases:
        counts[case.source_kind] = counts.get(case.source_kind, 0) + 1
    return counts


def load_frozen(directory: Path) -> FrozenSet:
    """读取一份冻结产物并复算 hash。

    Raises:
        FileNotFoundError: 目录里缺案例文件或记录。
        FreezeError: 案例文件 hash 与记录不符（冻结物被改过）。
    """
    from .cases import parse_cases

    cases_path = directory / FROZEN_CASES
    record_path = directory / FROZEN_RECORD
    record = read_json(record_path)
    raw = cases_path.read_bytes()
    case_set = parse_cases(raw, source=str(cases_path), path=cases_path)
    declared = str(record.get("dataset_sha256") or "")
    if declared != case_set.sha256:
        raise FreezeError(
            f"{cases_path} 的 hash 与冻结记录不符（{case_set.sha256[:12]}… ≠ {declared[:12]}…）：冻结物被改过"
        )
    return FrozenSet(directory=directory, case_set=case_set, record=record)


__all__ = [
    "FROZEN_CASES",
    "FROZEN_RECORD",
    "FreezeError",
    "FrozenSet",
    "freeze_cases",
    "load_frozen",
]
