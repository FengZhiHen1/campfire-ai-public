"""输出记录的口径：哪一条算数、一个 case-group 跑完了没有、还差哪几轮。

职责：把 `outputs.jsonl` 的追加流解释成「进度与终局」，供 runner（续跑）、
summarize（计数与分母）、verify（完整性）三处共用。

边界：不做统计汇总、不判断质量。

三条口径（写在代码里而不是注释里，避免三处各解释一次）：

1. **一次尝试一条记录**，`attempt` 从 1 开始；同一 (案例, 组别, 轮次) 的多条记录里，
   `attempt` 最大的是「有效记录」。首错不删——它就在列表里，供人查。
2. **终局状态**有四种（`completed` / `no_output` / `timeout` / `error`），全部进分母。
   「没跑完」不等于「没记录」：没有记录就说明这一轮没跑（或跑挂了没落盘）。
3. **可重试**只看预锁策略：状态属于 `config.retry_on` 且尝试次数还没用完。续跑据此
   决定要不要再跑一次——不因为「结果不好看」重跑。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from .cases import Case
from .config import RunConfig

#: 记录里必须有的字段（verify 与 resume 都按它判「这条记录可用」）。
REQUIRED_RECORD_FIELDS = (
    "batch_id",
    "run_id",
    "case_id",
    "system_id",
    "turn",
    "attempt",
    "session_id",
    "account_id",
    "started_at",
    "ended_at",
    "latency_ms",
    "completion_status",
    "raw_output",
    "status_flags",
    "error",
    "usage",
    "tool_calls",
    "citations",
    "trace_file",
    "input_text",
    "input_sha256",
    "fixtures",
    "retry",
    "record_sha256",
)


def key_of(record: dict[str, Any]) -> tuple[str, str, int]:
    """记录的三元键：案例 × 组别 × 轮次。"""
    return (str(record["case_id"]), str(record["system_id"]), int(record["turn"]))


def attempt_of(record: dict[str, Any]) -> int:
    """尝试序号（坏值按 1 处理：宁可多跑一次，也不把记录当墙外之物丢掉）。"""
    value = record.get("attempt")
    return int(value) if isinstance(value, int) and value >= 1 else 1


def effective_records(records: Iterable[dict[str, Any]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    """每个 (案例, 组别, 轮次) 的有效记录（尝试序号最大的那条）。"""
    chosen: dict[tuple[str, str, int], dict[str, Any]] = {}
    for record in records:
        if not {"case_id", "system_id", "turn"} <= set(record):
            continue
        key = key_of(record)
        current = chosen.get(key)
        if current is None or attempt_of(record) > attempt_of(current):
            chosen[key] = record
    return chosen


def attempts_for(records: Iterable[dict[str, Any]], key: tuple[str, str, int]) -> list[dict[str, Any]]:
    """某个键的全部尝试（按尝试序号排序，保留首错）。"""
    same = [record for record in records if key_of(record) == key]
    return sorted(same, key=attempt_of)


def group_session(records: Sequence[dict[str, Any]], *, case_id: str, system_id: str) -> tuple[str, str] | None:
    """取该 case-group **当前在用**的（会话 id, 账号 id）；没有记录时返回 None。

    会话必须复用：第二轮要么落在同一段对话里，要么就不是「第二轮」。
    取**尝试序号最大**的那条记录：失败尝试若已落库，续跑会换新会话重开（见
    `runner._run_case_group`），此时最新的会话才是该继续的那一段；取最早的那条会把
    已经作废的会话当成真源。
    """
    latest: dict[str, Any] | None = None
    for record in records:
        if record.get("case_id") != case_id or record.get("system_id") != system_id:
            continue
        if latest is None or attempt_of(record) >= attempt_of(latest):
            latest = record
    if latest is None:
        return None
    session_id = latest.get("session_id")
    account_id = latest.get("account_id")
    if isinstance(session_id, str) and isinstance(account_id, str):
        return session_id, account_id
    return None


def prior_turns(
    records: Sequence[dict[str, Any]], *, case_id: str, system_id: str, before_turn: int
) -> list[tuple[str, str]]:
    """该 case-group 在 `before_turn` 之前的（使用者文本, 助手正文）。

    A/B 适配器的对话历史在内存里，进程重启后需要据此重建——重建的依据就是当时真正发出去
    的文本（`outputs.jsonl` 的 `raw_output`），而不是重新渲染一遍再假定它没变。
    只取每轮的有效记录，且只取已有正文的轮次。
    """
    effective = effective_records(records)
    result: list[tuple[str, str]] = []
    for (cid, sid, turn), record in sorted(effective.items(), key=lambda item: item[0][2]):
        if cid != case_id or sid != system_id or turn >= before_turn:
            continue
        text = record.get("input_text")
        output = record.get("raw_output")
        if isinstance(text, str) and isinstance(output, str):
            result.append((text, output))
    return result


def group_attempts_used(records: Iterable[dict[str, Any]], *, case_id: str, system_id: str) -> int:
    """该 case-group 已用掉的「轮次尝试」次数（整组最大尝试序号）。

    重试预算按整组计：否则「第 1 轮失败重开、第 2 轮又失败」会变成两次重试，
    而协议只允许一次。
    """
    return max(
        (
            attempt_of(record)
            for record in records
            if record.get("case_id") == case_id and record.get("system_id") == system_id
        ),
        default=0,
    )


def is_final(record: dict[str, Any], config: RunConfig, *, group_attempts: int | None = None) -> bool:
    """这条记录是否已经是最终结论（不需要再按策略重试）。

    `group_attempts` 为该组已用的尝试次数（不给就按本条记录的序号判断）：
    预算按整组计时，重试换会话重开也不会额外获得额度。
    """
    status = record.get("completion_status")
    if status not in config.retry_on:
        return True
    used = attempt_of(record) if group_attempts is None else max(group_attempts, attempt_of(record))
    return used >= 1 + config.max_outer_retries


def needs_attempt(
    records: Sequence[dict[str, Any]],
    *,
    case: Case,
    system_id: str,
    config: RunConfig,
) -> list[int]:
    """还差哪几轮没跑或需要再试一次（按轮次升序）。"""
    effective = effective_records(records)
    used = group_attempts_used(records, case_id=case.id, system_id=system_id)
    pending: list[int] = []
    for turn in range(1, case.turns + 1):
        record = effective.get((case.id, system_id, turn))
        if record is None:
            pending.append(turn)
            continue
        # 预算已用尽的失败是最终结论，不再补跑（`is_final` 已按整组预算判断）
        if not is_final(record, config, group_attempts=used):
            pending.append(turn)
    return pending


def next_attempt(records: Sequence[dict[str, Any]], *, case_id: str, system_id: str, turn: int) -> int:
    """下一次尝试的序号（没有历史时是 1）。"""
    existing = attempts_for(records, (case_id, system_id, turn))
    return (attempt_of(existing[-1]) + 1) if existing else 1


@dataclass(frozen=True)
class GroupProgress:
    """一个 case-group 的进度（分母的基本单位）。"""

    case_id: str
    system_id: str
    turns_expected: int
    turns_final: int

    @property
    def complete(self) -> bool:
        """全部轮次都有最终结论（不论结论是完成、拒答、超时还是失败）。"""
        return self.turns_final >= self.turns_expected


def group_progress(
    records: Sequence[dict[str, Any]],
    *,
    cases: Sequence[Case],
    system_ids: Sequence[str],
    config: RunConfig,
) -> list[GroupProgress]:
    """全部 case-group 的进度（含一个都没跑的组：分母必须完整）。"""
    effective = effective_records(records)
    progress: list[GroupProgress] = []
    for case in cases:
        for system_id in system_ids:
            final = 0
            for turn in range(1, case.turns + 1):
                record = effective.get((case.id, system_id, turn))
                if record is not None and is_final(record, config):
                    final += 1
            progress.append(
                GroupProgress(
                    case_id=case.id,
                    system_id=system_id,
                    turns_expected=case.turns,
                    turns_final=final,
                )
            )
    return progress


def progress_summary(progress: Sequence[GroupProgress]) -> dict[str, int]:
    """进度汇总：期望组数、完成组数、部分组数（分母永远等于期望组数）。"""
    complete = sum(1 for item in progress if item.complete)
    return {
        "case_groups_expected": len(progress),
        "case_groups_complete": complete,
        "case_groups_partial": sum(1 for item in progress if 0 < item.turns_final < item.turns_expected),
        "case_groups_not_started": sum(1 for item in progress if item.turns_final == 0),
        "turns_expected": sum(item.turns_expected for item in progress),
        "turns_final": sum(item.turns_final for item in progress),
    }


__all__ = [
    "REQUIRED_RECORD_FIELDS",
    "GroupProgress",
    "attempt_of",
    "attempts_for",
    "effective_records",
    "group_attempts_used",
    "group_progress",
    "group_session",
    "is_final",
    "key_of",
    "needs_attempt",
    "next_attempt",
    "prior_turns",
    "progress_summary",
]
