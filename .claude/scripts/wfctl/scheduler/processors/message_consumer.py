"""ConsumeMessagesProcessor：消费消息 + AWAITING_CONFIRM 合法性校验。

步骤 1, 1.5：直接操作 InstanceState，零 dict 桥接。
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.dag.graph import is_backward_edge
from domain.transition.policy import TransitionPolicy
from infrastructure.project import find_root
from runtime.message.handler import scan_messages
from scheduler.context import ExecutionContext
from state.model import (
    CycleMeta,
    InstanceState,
    StageState,
    StageStatus,
    StateDelta,
)
from infrastructure.errors import ValidationError
from scheduler.processors.base import ProcessorResult, SideEffect
from services.state_manager import append_deviation as _append_deviation
from state.timeline import append_timeline as _append_timeline
from services.validator import validate_modified_files as _validate_modified_files


@dataclass
class ConsumeMessagesProcessor:
    """消费消息池并校验 AWAITING_CONFIRM 合法性。

    纯函数风格：读消息 → 生成 StateDelta + CycleMeta → 返回。
    """

    def process(self, ctx: ExecutionContext, state: InstanceState) -> ProcessorResult:
        root = find_root()
        consumed_ids = set(state.consumed_message_ids)
        messages = scan_messages(ctx.instance_id, consumed_ids)

        delta = StateDelta()
        side_effects: list[SideEffect] = []
        side_effects.append(SideEffect(
            kind="file_read", description="Scan messages", execute=None,
        ))
        cycle_meta = state.cycle_meta
        new_consumed: set[str] = set(consumed_ids)

        # 构建 stage_instance_id → StageState 索引
        stage_index: dict[str, StageState] = {}
        stage_by_stage_id: dict[str, list[StageState]] = {}
        for st in state.stages:
            stage_index[st.stage_instance_id] = st
            stage_by_stage_id.setdefault(st.stage_id, []).append(st)

        for msg in messages:
            msg_id = msg.get("message_id", "")
            if not msg_id:
                continue

            # 定位 stage：优先 stage_instance_id，回退 stage_id
            st = self._find_stage(msg, stage_index, stage_by_stage_id)
            if st is None:
                new_consumed.add(msg_id)
                continue

            # 校验 modified_files
            try:
                wt = ctx.worktree_map.get(st.stage_id) if ctx.worktree_map else None
                if msg.get("modified_files") and wt:
                    _validate_modified_files(wt, msg["modified_files"], st.stage_id)
                    side_effects.append(SideEffect(
                        kind="file_read", description=f"Validate modified files for {st.stage_id}", execute=None,
                    ))
            except Exception as e:
                import traceback

                # ACCESS_VIOLATION: 软处理 — 记录偏差、置为 PENDING 重试，
                # 让 SubAgent 有机会修正，而非直接 ERROR 终止。
                if isinstance(e, ValidationError) and e.code == "ACCESS_VIOLATION":
                    delta.stage_updates[st.stage_instance_id] = {
                        "status": StageStatus.PENDING,
                        "attempt_count": st.attempt_count + 1,
                    }
                    _append_deviation(
                        ctx.instance_id,
                        "ACCESS_VIOLATION",
                        f"{st.stage_id}: {e}",
                        stage_id=st.stage_id,
                    )
                    side_effects.append(SideEffect(
                        kind="file_write",
                        description=f"Timeline running→pending (access violation) for {st.stage_id}",
                        execute=lambda iid=ctx.instance_id, sid=st.stage_id, r=str(e): _append_timeline(
                            iid, sid, "running→pending",
                            {"reason": r, "action": "retry"},
                        ),
                    ))
                    new_consumed.add(msg_id)
                    continue

                delta.stage_updates[st.stage_instance_id] = {}
                side_effects.append(SideEffect(
                    kind="file_write",
                    description=f"Timeline running→error for {st.stage_id}",
                    execute=lambda iid=ctx.instance_id, sid=st.stage_id, r=str(e), mid=msg_id, ist=msg.get("status"), tb=traceback.format_exc(): _append_timeline(
                        iid, sid, "running→error", {"reason": r, "message_id": mid, "intended_status": ist, "traceback": tb},
                    ),
                ))
                cycle_meta = cycle_meta.with_error(st.stage_instance_id)
                new_consumed.add(msg_id)
                continue

            old_status = st.status
            msg_status = msg.get("status", old_status.value)

            # 防御：拒绝非法 status 值（SubAgent 绕过 wfctl message write 手写 JSON 导致）
            # 不加入 consumed_message_ids——保留消息文件，修复后重试即可恢复
            if msg_status not in {s.value for s in StageStatus}:
                side_effects.append(SideEffect(
                    kind="deviation_write",
                    description=f"Illegal message status '{msg_status}' from {st.stage_id}",
                    execute=lambda iid=ctx.instance_id, sid=st.stage_id, mid=msg_id, ms=msg_status: _append_deviation(
                        iid, "ILLEGAL_MESSAGE_STATUS",
                        f"消息 {mid} 的 status='{ms}' 不是合法枚举值，已被跳过（未消费）。"
                        f"修复消息文件后重新 sync 即可恢复。",
                        stage_id=sid,
                    ),
                ))
                continue

            # 状态无变化 → 只消费消息 ID
            if old_status.value == msg_status:
                new_consumed.add(msg_id)
                continue

            if msg_status == "DONE":
                routing_choice = msg.get("routing_choice")
                if routing_choice:
                    valid = st.valid_routing_choices
                    if valid and routing_choice not in valid:
                        cycle_meta = cycle_meta.with_error(st.stage_instance_id)
                        side_effects.append(SideEffect(
                            kind="file_write",
                            description=f"Timeline invalid routing_choice for {st.stage_id}",
                            execute=lambda iid=ctx.instance_id, sid=st.stage_id, mid=msg_id, rc=routing_choice, v=valid: _append_timeline(
                                iid, sid, "running→error", {"message_id": mid, "reason": f"非法 routing_choice: '{rc}'，合法值: {v}"},
                            ),
                        ))
                        new_consumed.add(msg_id)
                        continue
                    delta.stage_updates[st.stage_instance_id] = {
                        "exit_condition": "success",
                        "output_message_id": msg_id,
                        "routing_choice": routing_choice,
                    }
                else:
                    delta.stage_updates[st.stage_instance_id] = {
                        "exit_condition": "success",
                        "output_message_id": msg_id,
                    }
                side_effects.append(SideEffect(
                    kind="file_write",
                    description=f"Timeline running→done for {st.stage_id}",
                    execute=lambda iid=ctx.instance_id, sid=st.stage_id, mid=msg_id: _append_timeline(
                        iid, sid, "running→done", {"message_id": mid},
                    ),
                ))
                cycle_meta = cycle_meta.with_done(st.stage_instance_id)

            elif msg_status == "ERROR":
                delta.stage_updates[st.stage_instance_id] = {
                    "output_message_id": msg_id,
                }
                side_effects.append(SideEffect(
                    kind="file_write",
                    description=f"Timeline running→error for {st.stage_id}",
                    execute=lambda iid=ctx.instance_id, sid=st.stage_id, mid=msg_id, rpt=msg.get("report", ""): _append_timeline(
                        iid, sid, "running→error", {"message_id": mid, "reason": rpt},
                    ),
                ))
                cycle_meta = cycle_meta.with_error(st.stage_instance_id)

            elif msg_status == "AWAITING_CONFIRM":
                updates: dict = {
                    "output_message_id": msg_id,
                }
                if msg.get("confirm_questions"):
                    updates["confirm_questions"] = msg["confirm_questions"]
                delta.stage_updates[st.stage_instance_id] = updates
                side_effects.append(SideEffect(
                    kind="file_write",
                    description=f"Timeline running→awaiting_confirm for {st.stage_id}",
                    execute=lambda iid=ctx.instance_id, sid=st.stage_id, mid=msg_id: _append_timeline(
                        iid, sid, "running→awaiting_confirm", {"message_id": mid},
                    ),
                ))
                cycle_meta = cycle_meta.with_awaiting_confirm(st.stage_instance_id)

            elif msg_status == "RUNNING":
                delta.stage_updates[st.stage_instance_id] = {"status": StageStatus.RUNNING}
                side_effects.append(SideEffect(
                    kind="file_write",
                    description=f"Timeline scheduled for {st.stage_id}",
                    execute=lambda iid=ctx.instance_id, sid=st.stage_id, mid=msg_id: _append_timeline(
                        iid, sid, "scheduled", {"message_id": mid},
                    ),
                ))

            new_consumed.add(msg_id)

        # 1.5 Cascade reset：DONE + routing_choice 匹配回边时触发级联重置
        stage_order = [s.stage_id for s in ctx.spec.stages]
        for sid in list(cycle_meta.newly_done_stage_instance_ids):
            st = stage_index.get(sid)
            if st is None:
                continue
            routing_choice = st.routing_choice or delta.stage_updates.get(sid, {}).get("routing_choice", "")
            if not routing_choice:
                continue
            policy = TransitionPolicy.from_adjacency(ctx.adj, st.stage_id)
            matched = policy.match_success_edge(routing_choice)
            if matched is None:
                continue
            if not is_backward_edge(stage_order, st.stage_id, matched.to_stage):
                continue
            cascade = TransitionPolicy.compute_cascade_reset(
                state, st.stage_id, matched.to_stage, stage_order,
            )
            if cascade.removed_stage_instance_ids or cascade.reset_stage_instance_ids:
                delta.remove_stage_instance_ids.extend(cascade.removed_stage_instance_ids)
                spec_stage_map = {s.stage_id: s for s in ctx.spec.stages}
                for reset_sid in cascade.reset_stage_instance_ids:
                    stage_spec = spec_stage_map.get(reset_sid)
                    delta.append_stages.append(StageState(
                        stage_id=reset_sid,
                        stage_instance_id=reset_sid,
                        status=StageStatus.PENDING,
                        model=stage_spec.model if stage_spec else None,
                    ))
                if cascade.cleanup_running_agent_stage_ids:
                    # stage state 中的 system_agent_id 随 stage 重置自然失效，无需额外清理
                    pass

        # 更新 consumed_message_ids
        delta.instance_updates["consumed_message_ids"] = frozenset(new_consumed)

        # 构建最终 StateDelta（含 cycle_meta，frozen dataclass 不支持直接赋值）
        final_delta = StateDelta(
            stage_updates=delta.stage_updates,
            instance_updates=delta.instance_updates,
            append_stages=delta.append_stages,
            remove_stage_instance_ids=delta.remove_stage_instance_ids,
            cycle_meta=cycle_meta,
        )
        return ProcessorResult(state_delta=final_delta, side_effects=side_effects)

    @staticmethod
    def _find_stage(
        msg: dict,
        stage_index: dict[str, StageState],
        stage_by_stage_id: dict[str, list[StageState]],
    ) -> StageState | None:
        sid = msg.get("stage_instance_id") or msg.get("stage_id")
        if not sid:
            return None
        st = stage_index.get(sid)
        if st is not None:
            return st
        # 回退：按 stage_id 查找（取第一个 PENDING/RUNNING/ERROR/AWAITING_CONFIRM）
        candidates = stage_by_stage_id.get(sid, [])
        for s in candidates:
            if s.status in (StageStatus.RUNNING, StageStatus.PENDING, StageStatus.ERROR, StageStatus.AWAITING_CONFIRM):
                return s
        return candidates[0] if candidates else None
