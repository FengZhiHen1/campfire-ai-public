"""FinalizeProcessor：组装 actions + 全部 DONE 合并。

步骤 13, 14：最终收尾。
"""

from __future__ import annotations

from dataclasses import dataclass

from infrastructure.errors import GitError
from domain.workflow.spec import StageTargetType
from scheduler.context import ExecutionContext
from state.model import InstanceState, StageStatus, InstanceStatus, StateDelta, StageState
from scheduler.processors.base import ProcessorResult, SideEffect
from runtime.worktree.manager import merge_instance_to_main, tag_anchor as _tag_anchor


@dataclass
class FinalizeProcessor:
    """最终收尾：检查全部 DONE，执行合并。"""

    def process(self, ctx: ExecutionContext, state: InstanceState) -> ProcessorResult:
        if not self._check_all_done(state, ctx):
            return ProcessorResult()

        # 非根实例或已确认合并 → 直接执行合并
        if state.parent_instance_id or state.merge_confirmed:
            return self._execute_merge(ctx, state)

        # 根实例：插入合并确认伪 stage
        merge_stage = StageState(
            stage_id="__merge__",
            stage_instance_id="__merge__",
            status=StageStatus.AWAITING_CONFIRM,
            confirm_questions=[
                f"yes：实例 {ctx.instance_id}（{state.goal}）全部 stage 已完成，合入 main",
                f"no：暂不合入，保留工作区",
            ],
        )
        delta = StateDelta(append_stages=[merge_stage])
        return ProcessorResult(state_delta=delta)

    def _check_all_done(self, state: InstanceState, ctx: ExecutionContext) -> bool:
        """检查是否所有非虚拟 stage 都 DONE。"""
        non_virtual = [s for s in ctx.spec.stages if s.target_type != StageTargetType.VIRTUAL]
        if not non_virtual:
            return False
        return all(
            state.first_stage_by_id(s.stage_id)
            and state.first_stage_by_id(s.stage_id).status == StageStatus.DONE
            for s in non_virtual
        )

    def _execute_merge(self, ctx: ExecutionContext, state: InstanceState) -> ProcessorResult:
        """执行实例 worktree 合入主仓库。"""
        delta = StateDelta()
        actions: list[dict] = []
        side_effects: list[SideEffect] = []

        def _silent_tag(iid: str, anchor: str) -> None:
            try:
                _tag_anchor(iid, anchor)
            except Exception:
                pass

        try:
            success, conflict_files = merge_instance_to_main(ctx.instance_id)
            side_effects.append(SideEffect(
                kind="git_merge", description="Finalize merge to main", execute=None,
            ))
            if success:
                delta.instance_updates["status"] = InstanceStatus.COMPLETED
                anchor = f"{ctx.spec.anchor_prefix}-{ctx.instance_id}-final"
                side_effects.append(SideEffect(
                    kind="git_tag",
                    description="Final anchor",
                    execute=lambda iid=ctx.instance_id, a=anchor: _silent_tag(iid, a),
                ))
                actions.append({"action": "merge_to_main", "status": "completed"})
            else:
                actions.append({
                    "action": "conflict",
                    "conflict_files": conflict_files,
                    "worktree": ".",
                })
        except GitError as e:
            actions.append({"action": "merge_to_main", "status": "error", "reason": str(e)})

        return ProcessorResult(state_delta=delta, actions=actions, side_effects=side_effects)
