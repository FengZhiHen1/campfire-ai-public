"""confirm 命令——处理用户确认 AWAITING_CONFIRM 的 stage。

confirm 将 stage 重置为 PENDING 并保留 system_agent_id，
调度器随后通过 continue action 将用户选择传回同一 SubAgent。
DONE 由 SubAgent 通过 routing_choice 上报驱动流转。
"""

from domain.dag.graph import build_adjacency
from infrastructure.errors import InputError
from compat.workflow.registry import load_workflow
from domain.transition.policy import TransitionPolicy
from compat.instance.registry import load_instance_state, save_instance_state
from state.model import StageStatus, StateDelta
from state.timeline import append_timeline


def register_confirm(subparsers):
    p = subparsers.add_parser("confirm", help="确认 AWAITING_CONFIRM 的 stage")
    p.add_argument("--instance", required=True, help="实例 ID")
    p.add_argument("--stage", required=True, help="目标 stage_id")
    p.add_argument("--choice", required=True, help="用户选择的选项值")
    p.add_argument("--feedback", default="", help="用户反馈文本")
    p.set_defaults(handler=_handle_confirm)


def _handle_confirm(args) -> dict:
    state = load_instance_state(args.instance)

    # 加载 spec 和邻接表
    from services.resolver import find_workflow_dir
    version = state.version
    wf_dir = find_workflow_dir(state.workflow_id, version if version else None)
    spec = load_workflow(wf_dir / "WORKFLOW.yaml")
    adj = build_adjacency(spec)

    # __merge__ 伪 stage
    if args.stage == "__merge__":
        return _handle_merge_confirm(args, state)

    # 查找 AWAITING_CONFIRM 的 stage 实例
    candidates = state.stages_by_id(args.stage)
    if not candidates:
        raise InputError(f"Stage not found: {args.stage}", code="STAGE_NOT_FOUND")

    stage = next((s for s in candidates if s.status == StageStatus.AWAITING_CONFIRM), None)
    if stage is None:
        # 容错：SubAgent 可能已通过 continue 自行处理确认，stage 已 PENDING。
        # 若 pending_choice 匹配，视为幂等确认，直接返回成功。
        pending_match = next(
            (s for s in candidates
             if s.status == StageStatus.PENDING and s.pending_choice == args.choice),
            None,
        )
        if pending_match is not None:
            return {
                "status": "ok",
                "stage_id": args.stage,
                "new_status": "PENDING",
                "matched": args.choice,
                "loop": pending_match.loop_counter,
                "already_confirmed": True,
            }

        statuses = {s.stage_instance_id: s.status.value for s in candidates}
        raise InputError(
            f"No AWAITING_CONFIRM instance for stage {args.stage}. "
            f"Existing instances: {statuses}",
            code="INVALID_ARGUMENT",
        )

    # 纯决策：永远返回 PENDING + continue
    policy = TransitionPolicy.from_adjacency(adj, args.stage)
    result = policy.on_confirm(stage, args.choice, bool(args.feedback))

    # 构建 StateDelta（传入 state 以便 loop_exceeded 时激活目标 stage）
    delta = TransitionPolicy.build_confirm_delta(result, stage, state)

    # 应用状态变更
    new_state = state.apply_delta(delta)

    # ── 副作用区 ──
    if result.requires_feedback and args.feedback:
        _write_feedback_message(args.instance, args.stage, stage, args.choice, args.feedback)

    append_timeline(args.instance, args.stage, result.timeline_event_label, {
        "choice": args.choice,
        "reason": result.reason,
    })

    save_instance_state(args.instance, new_state)

    return {
        "status": "ok",
        "stage_id": args.stage,
        "new_status": "PENDING",
        "matched": args.choice,
        "loop": stage.loop_counter + 1,
    }


def _handle_merge_confirm(args, state) -> dict:
    result = TransitionPolicy.on_merge_confirm(args.choice)
    remove_ids = [s.stage_instance_id for s in state.stages if s.stage_id == "__merge__"]
    delta = StateDelta(
        remove_stage_instance_ids=remove_ids,
        instance_updates={"merge_confirmed": result.merge_confirmed},
    )
    new_state = state.apply_delta(delta)
    save_instance_state(args.instance, new_state)
    return {"status": "ok", "stage_id": "__merge__", "merge_confirmed": result.merge_confirmed}


def _write_feedback_message(instance_id: str, stage_id: str, stage, choice: str, feedback: str):
    from runtime.message.handler import write_message
    write_message(
        instance_id=instance_id,
        stage_id=stage_id,
        stage_instance_id=stage.stage_instance_id,
        status="PENDING",
        report=feedback,
        checkpoint_summary=f"用户反馈（选项 {choice}）：{feedback}",
    )
