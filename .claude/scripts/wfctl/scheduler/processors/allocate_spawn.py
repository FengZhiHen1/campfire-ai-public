"""AllocateSpawnProcessor：worktree 分配 + spawn/continue action 生成。

步骤 13：为就绪 stage 分配 worktree 并生成 spawn/continue action。
agent 匹配通过扫描实例 stage state（system_agent_id），不再依赖 running_agents.json。
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.dag.graph import AdjacencyList
from domain.workflow.spec import StageSpec, StageTargetType
from infrastructure.timestamp import iso_timestamp
from scheduler.context import ExecutionContext
from state.model import InstanceState, StageState, StateDelta, StageStatus
from scheduler.processors.base import ProcessorResult, SideEffect
from runtime.worktree.manager import (
    create_parallel_worktree,
    create_stage_worktree,
    sync_stage_with_instance,
)


@dataclass
class AllocateSpawnProcessor:
    """为就绪 stage 分配 worktree 并生成 action。"""

    def process(self, ctx: ExecutionContext, state: InstanceState) -> ProcessorResult:
        ready = state.cycle_meta.ready_candidates
        if not ready:
            return ProcessorResult()

        actions: list[dict] = []
        side_effects: list[SideEffect] = []
        delta = StateDelta()
        multi_ready = len(ready) > 1

        for stage_id, stage_inst_id in ready:
            stage_spec = ctx.adj.stages.get(stage_id)
            if not stage_spec:
                continue

            st = state.stage_by_instance_id(stage_inst_id)
            if not st:
                continue

            if stage_spec.target_type == StageTargetType.VIRTUAL:
                delta.stage_updates[st.stage_instance_id] = {"status": StageStatus.DONE}
                continue

            if stage_spec.target_type == StageTargetType.WORKFLOW:
                continue

            is_parallel = stage_inst_id != stage_id or st.fan_out_target

            skill_id = stage_spec.target
            matched_sys_id: str | None = None
            matched_stage_id: str | None = None
            if not is_parallel:
                matched_sys_id, matched_stage_id = _find_agent_by_skill(state, skill_id, ctx)

            # worktree 分配
            if multi_ready or is_parallel:
                if self._is_parallel_instance(stage_inst_id):
                    base_id, idx_str = stage_inst_id.rsplit("_", 1)
                    worktree = create_parallel_worktree(ctx.instance_id, base_id, int(idx_str))
                    side_effects.append(SideEffect(
                        kind="worktree_create",
                        description=f"Parallel worktree {stage_inst_id}",
                        execute=None,
                    ))
                else:
                    worktree = create_stage_worktree(ctx.instance_id, stage_inst_id)
                    side_effects.append(SideEffect(
                        kind="worktree_create",
                        description=f"Stage worktree {stage_inst_id}",
                        execute=None,
                    ))
            else:
                worktree = ctx.root / ".tmp" / "worktrees" / f"instance-{ctx.instance_id}"

            # 更新 stage 状态
            updates: dict = {
                "status": StageStatus.RUNNING,
                "started_at": iso_timestamp(),
            }

            # 构建 context
            context = self._build_context(stage_id, ctx.adj, state, stage_spec)

            needs_targets = any(
                s.parallel and s.parallel.source == stage_id
                for s in ctx.spec.stages
            )
            updates["requires_parallel_targets"] = needs_targets

            routing_choices = self._collect_success_choices(ctx.adj, stage_id)
            updates["valid_routing_choices"] = routing_choices
            updates["pending_choice"] = ""

            if matched_sys_id:
                # Level 2 同步
                sync_result = sync_stage_with_instance(ctx.instance_id, stage_inst_id)
                if not sync_result.success:
                    updates["status"] = StageStatus.CONFLICT
                    updates["conflict_files"] = sync_result.conflict_files
                    delta.stage_updates[st.stage_instance_id] = updates
                    actions.append({
                        "action": "conflict",
                        "instance_id": ctx.instance_id,
                        "stage_id": stage_id,
                        "stage_instance_id": stage_inst_id,
                        "worktree": str(worktree.relative_to(ctx.root)),
                        "conflict_files": sync_result.conflict_files,
                        "source_stage": stage_id,
                    })
                    continue

                # 同 Skill 延续：标记前一 stage 的 continued_to（跳过自引用）
                if matched_stage_id != stage_id:
                    prev_st = state.first_stage_by_id(matched_stage_id)
                    if prev_st:
                        delta.stage_updates[prev_st.stage_instance_id] = {"continued_to": st.stage_id}

                updates["system_agent_id"] = matched_sys_id
                delta.stage_updates[st.stage_instance_id] = updates

                actions.append({
                    "action": "continue",
                    "instance_id": ctx.instance_id,
                    "stage_id": stage_id,
                    "skill_id": skill_id,
                    "worktree": str(worktree.relative_to(ctx.root)),
                    "system_agent_id": matched_sys_id,
                    "requires_parallel_targets": needs_targets,
                    "valid_routing_choices": routing_choices,
                    "pending_choice": st.pending_choice,
                    "context": context,
                })
            else:
                delta.stage_updates[st.stage_instance_id] = updates
                actions.append({
                    "action": "spawn",
                    "instance_id": ctx.instance_id,
                    "stage_id": stage_id,
                    "skill_id": skill_id,
                    "worktree": str(worktree.relative_to(ctx.root)),
                    "requires_parallel_targets": needs_targets,
                    "valid_routing_choices": routing_choices,
                    "pending_choice": st.pending_choice,
                    "context": context,
                })

        return ProcessorResult(state_delta=delta, actions=actions, side_effects=side_effects)

    def _is_parallel_instance(self, stage_inst_id: str) -> bool:
        parts = stage_inst_id.rsplit("_", 1)
        return len(parts) == 2 and parts[1].isdigit()

    def _build_context(self, stage_id: str, adj: AdjacencyList, state: InstanceState, stage_spec: StageSpec) -> dict:
        upstream_summaries = []
        for edge in adj.incoming.get(stage_id, []):
            upstream_stage = next((s for s in state.stages if s.stage_id == edge.from_stage), None)
            if upstream_stage and upstream_stage.output_message_id:
                upstream_summaries.append({
                    "stage_id": edge.from_stage,
                    "message_id": upstream_stage.output_message_id,
                })
        return {
            "upstream": upstream_summaries,
            "stage_name": stage_spec.name or stage_id,
            "successor_stages_block": self._build_successor_stages_block(stage_id, stage_spec, adj),
        }

    def _build_successor_stages_block(self, stage_id: str, stage_spec: StageSpec, adj: AdjacencyList) -> str:
        current_skill_id = stage_spec.target
        current_name = stage_spec.name or stage_id
        successors: list[tuple[str, str, str | None]] = []
        for edge in adj.outgoing.get(stage_id, []):
            if edge.condition.value in ("success", "always"):
                succ_spec = adj.stages.get(edge.to_stage)
                if succ_spec and succ_spec.target_type != StageTargetType.VIRTUAL:
                    successors.append((edge.to_stage, succ_spec.name or edge.to_stage, succ_spec.target))
        if not successors:
            return "你是工作流的最后一个 stage，需产出最终交付物。完成后上报 DONE。"
        lines = [
            "本 stage 下游还有以下 stage，它们将由编排器独立调度，**不属于你的职责范围**："
        ]
        for succ_id, succ_name, succ_skill in successors:
            if succ_skill == current_skill_id:
                lines.append(
                    f"  - {succ_id}「{succ_name}」⚠️ 与你使用同一 Skill——"
                    f"你只需执行 Skill 中属于「{current_name}」的部分"
                )
            else:
                lines.append(f"  - {succ_id}「{succ_name}」")
        lines.append("")
        lines.append(
            f"你只需完成「{current_name}」的工作，产出 checkpoint，"
            f"然后上报 DONE / AWAITING_CONFIRM 并停止。"
            f"后续 stage 由编排器根据你的 checkpoint 和路由选择独立调度。"
        )
        return "\n".join(lines)

    def _collect_success_choices(self, adj: AdjacencyList, stage_id: str) -> list[str]:
        choices: list[str] = []
        for e in adj.outgoing.get(stage_id, []):
            if e.condition.value == "success" and e.choice and e.choice not in choices:
                choices.append(e.choice)
        return choices


def _find_agent_by_skill(
    state: InstanceState, skill_id: str, ctx: ExecutionContext,
) -> tuple[str | None, str | None]:
    """扫描当前实例的 stage state，查找同 skill 且有 system_agent_id 的记录。

    优先级：RUNNING > PENDING（含 confirm 后等待 continue）> DONE。
    并行 stage 已在外层短路，此处不处理。

    Returns:
        (system_agent_id, stage_id) 或 (None, None)
    """
    target_stage_ids = {
        sid for sid, spec in ctx.adj.stages.items()
        if spec.target_type == StageTargetType.SKILL and spec.target == skill_id
    }
    done_match: tuple[str, str] | None = None
    pending_match: tuple[str, str] | None = None
    for st in state.stages:
        if st.stage_id not in target_stage_ids or not st.system_agent_id:
            continue
        if st.status == StageStatus.RUNNING:
            return st.system_agent_id, st.stage_id
        if st.status == StageStatus.PENDING and pending_match is None:
            pending_match = (st.system_agent_id, st.stage_id)
        if st.status == StageStatus.DONE and done_match is None:
            done_match = (st.system_agent_id, st.stage_id)
    if pending_match:
        return pending_match
    if done_match:
        return done_match
    return None, None
