"""py-agent-kernel runtime——审计与用量追踪（T2.8）。

- ToolCallAudit：每次工具调用（含阻断记录）审计
- UsageTracker：Token/成本聚合（按扩展/Skill/面维度的聚合基础数据）
- eval 批量运行入口：宿主 eval-set 回归用（S5 消费）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallRecord:
    """单次工具调用审计记录。"""

    tool_name: str
    tool_call_id: str
    params: dict[str, Any]
    blocked: bool
    block_reason: str | None
    is_error: bool
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0


class AuditRecorder:
    """工具调用审计记录器（内存聚合 + 回调外送）。

    trace_id 透传宿主日志体系：宿主构造时注入 sink 回调
    （如 py_logger 结构化日志），内核不绑定具体日志实现。
    """

    def __init__(self, sink: Any | None = None) -> None:
        self._records: list[ToolCallRecord] = []
        self._sink = sink  # Callable[[ToolCallRecord], None] | None

    def record(self, record: ToolCallRecord) -> None:
        self._records.append(record)
        if self._sink is not None:
            try:
                self._sink(record)
            except Exception:
                pass  # 审计外送失败不影响主流程

    @property
    def records(self) -> list[ToolCallRecord]:
        return list(self._records)

    def blocked_calls(self) -> list[ToolCallRecord]:
        """全部阻断记录（安全审计面）。"""
        return [r for r in self._records if r.blocked]


@dataclass
class UsageSnapshot:
    """Token 用量聚合快照。"""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    run_count: int = 0
    tool_call_count: int = 0


class UsageTracker:
    """Token/成本聚合（run 级）。"""

    def __init__(self) -> None:
        self._snapshot = UsageSnapshot()

    def track_run(self, usage: Any, tool_call_count: int = 0) -> None:
        """聚合一次 run 的用量（pydantic-ai RunUsage）。"""
        self._snapshot.run_count += 1
        self._snapshot.total_input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        self._snapshot.total_output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        self._snapshot.tool_call_count += tool_call_count

    @property
    def snapshot(self) -> UsageSnapshot:
        return UsageSnapshot(
            total_input_tokens=self._snapshot.total_input_tokens,
            total_output_tokens=self._snapshot.total_output_tokens,
            run_count=self._snapshot.run_count,
            tool_call_count=self._snapshot.tool_call_count,
        )


__all__ = ["ToolCallRecord", "AuditRecorder", "UsageSnapshot", "UsageTracker"]
