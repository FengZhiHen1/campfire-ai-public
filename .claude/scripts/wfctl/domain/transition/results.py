"""状态转换结果类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from domain.workflow.spec import StageStatus

if TYPE_CHECKING:
    from state.model import StateDelta


@dataclass(frozen=True)
class TransitionResult:
    """单次状态转换结果（on_error 用）。

    next_status: 转换后的目标状态
    target_stage_id: 若需路由到其他 stage，目标 stage_id
    updates: 附加字段变更 (e.g., attempt_count increment)
    action: 触发动作 "retry" | "spawn" | "terminate" | ""
    """

    next_status: StageStatus
    target_stage_id: str | None = None
    updates: dict[str, Any] = field(default_factory=dict)
    action: str = ""


@dataclass(frozen=True)
class ConfirmResult:
    """确认操作的纯决策结果。

    正常情况返回 PENDING + continue，保留 system_agent_id
    以便调度器将用户选择传回同一 SubAgent。
    唯一例外：loop_counter ≥ 自环边 max_loop 时返回 DONE + spawn，
    触发 loop_exceeded 逃生路径。
    """

    next_status: StageStatus
    choice: str = ""
    updates: dict[str, Any] = field(default_factory=dict)
    requires_feedback: bool = False
    action: str = ""
    reason: str = ""
    loop_exceeded_target: str | None = None

    @property
    def timeline_event_label(self) -> str:
        if self.loop_exceeded_target is not None:
            return "loop_exceeded"
        return "awaiting_confirm→pending"


@dataclass(frozen=True)
class CascadeResetResult:
    """回边级联重置结果。

    reset_stage_instance_ids: 需重置为 PENDING 的 stage_instance_id 列表
    removed_stage_instance_ids: 需移除的 stage_instance_id（折叠为单条）
    cleanup_running_agent_stage_ids: 级联重置涉及的 stage_id 列表（其 system_agent_id 随重置自然失效）
    """

    reset_stage_instance_ids: list[str] = field(default_factory=list)
    removed_stage_instance_ids: list[str] = field(default_factory=list)
    cleanup_running_agent_stage_ids: list[str] = field(default_factory=list)

    def to_state_delta(self, spec_stages: list[Any]) -> Any:
        """纯决策：将级联重置结果转换为 StateDelta。"""
        from state.model import StageState, StageStatus, StateDelta
        spec_stage_map = {s.stage_id: s for s in spec_stages}
        append_stages: list[StageState] = []
        for sid in self.reset_stage_instance_ids:
            stage_spec = spec_stage_map.get(sid)
            append_stages.append(StageState(
                stage_id=sid,
                stage_instance_id=sid,
                status=StageStatus.PENDING,
                model=stage_spec.model if stage_spec else None,
            ))
        return StateDelta(
            remove_stage_instance_ids=self.removed_stage_instance_ids,
            append_stages=append_stages,
        )


@dataclass(frozen=True)
class RollbackResult:
    """回退操作的纯决策结果。"""

    reset_stage_ids: list[str] = field(default_factory=list)
    delta: Any = None  # StateDelta (lazy import)

    @property
    def state_delta(self) -> StateDelta:
        from state.model import StateDelta
        return self.delta if isinstance(self.delta, StateDelta) else StateDelta()


@dataclass(frozen=True)
class SkipResult:
    """跳过操作的纯决策结果。"""

    stage_instance_ids: list[str] = field(default_factory=list)
    force_applied: bool = False
    blocked_message_ids: list[str] = field(default_factory=list)
    delta: Any = None  # StateDelta (lazy import)

    @property
    def state_delta(self) -> StateDelta:
        from state.model import StateDelta
        return self.delta if isinstance(self.delta, StateDelta) else StateDelta()


@dataclass(frozen=True)
class MergeConfirmResult:
    """__merge__ 伪 stage 确认结果。"""

    merge_confirmed: bool = False
    remove_merge_stage: bool = True


@dataclass(frozen=True)
class SyncResult:
    """worktree 同步结果。

    success: 同步是否成功（无冲突）
    conflict_files: 冲突文件路径列表（success=False 时填充）
    """

    success: bool
    conflict_files: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        """人类可读的冲突描述。"""
        if self.success:
            return ""
        return f"conflict files: {self.conflict_files}"
