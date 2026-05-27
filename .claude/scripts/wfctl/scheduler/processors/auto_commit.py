"""AutoCommitProcessor：DONE stage 自动提交 + 补锚。

步骤 2, 2.5：对刚转为 DONE 的 stage 自动提交 git 变更并打锚点。
git commit 流程保留在 processor 内执行（链式副作用），tag_anchor 提取为独立副作用。
"""

from __future__ import annotations

from dataclasses import dataclass

from infrastructure.errors import GitError
from runtime.worktree.git import git_add_all, git_commit_file, git_status_porcelain, git_tag_exists
from infrastructure.project import find_root
from scheduler.context import ExecutionContext
from state.model import InstanceState, StageStatus
from scheduler.processors.base import ProcessorResult, SideEffect
from runtime.worktree.manager import tag_anchor


@dataclass
class AutoCommitProcessor:
    """自动提交 DONE stage 的变更并补锚点。"""

    def process(self, ctx: ExecutionContext, state: InstanceState) -> ProcessorResult:
        side_effects: list[SideEffect] = []
        self._auto_commit_done_stages(ctx, state, side_effects)
        self._ensure_anchors_for_done_stages(ctx, state, side_effects)
        return ProcessorResult(side_effects=side_effects)

    def _auto_commit_done_stages(
        self, ctx: ExecutionContext, state: InstanceState, side_effects: list[SideEffect],
    ) -> None:
        import json

        for stage_inst_id in state.cycle_meta.newly_done_stage_instance_ids:
            st = state.stage_by_instance_id(stage_inst_id)
            if not st or st.status != StageStatus.DONE:
                continue

            worktree = ctx.worktree_map.get(st.stage_id)
            if not worktree or not worktree.exists():
                continue

            # 从消息文件读取 report
            report = f"stage {st.stage_id} done"
            message_id = st.output_message_id or ""
            if message_id:
                msg_path = (
                    ctx.root / ".agent" / "instances" / ctx.instance_id
                    / "messages" / f"{message_id}.json"
                )
                if msg_path.exists():
                    try:
                        msg_data = json.loads(msg_path.read_text(encoding="utf-8"))
                        report = msg_data.get("report", report)
                    except Exception:
                        pass

            full_msg = (
                f"{report}\n\n"
                f"wf-stage: {stage_inst_id}\n"
                f"wf-instance: {ctx.instance_id}\n"
                f"wf-message: {message_id}\n"
            )

            msg_file = worktree / ".wfctl_commit_msg"
            msg_file.write_text(full_msg, encoding="utf-8")

            rc, _, stderr = git_add_all(worktree)
            if rc != 0:
                msg_file.unlink(missing_ok=True)
                raise GitError(f"auto-commit add failed for stage {st.stage_id}: {stderr}")

            rc, _, stderr = git_commit_file(worktree, msg_file, allow_empty=True)
            msg_file.unlink(missing_ok=True)
            if rc != 0:
                raise GitError(f"auto-commit failed for stage {st.stage_id}: {stderr}")

            side_effects.append(SideEffect(
                kind="git_commit",
                description=f"Auto-commit {stage_inst_id}",
                execute=None,
            ))

            # 独立副作用：tag_anchor 延迟到 orchestrator 执行
            anchor = f"{ctx.spec.anchor_prefix}-{ctx.instance_id}-{stage_inst_id}"
            side_effects.append(SideEffect(
                kind="git_tag",
                description=f"Anchor {stage_inst_id}",
                execute=lambda iid=ctx.instance_id, a=anchor, w=worktree: tag_anchor(iid, a, worktree=w),
            ))

    def _ensure_anchors_for_done_stages(
        self, ctx: ExecutionContext, state: InstanceState, side_effects: list[SideEffect],
    ) -> None:
        root = find_root()
        newly_done = set(state.cycle_meta.newly_done_stage_instance_ids)
        for st in state.stages:
            if st.status != StageStatus.DONE:
                continue
            # 跳过 _auto_commit_done_stages 已处理的 stage，避免锚点重复创建
            if st.stage_instance_id in newly_done:
                continue
            stage_id = st.stage_id
            stage_inst = st.stage_instance_id
            anchor_name = f"{ctx.spec.anchor_prefix}-{ctx.instance_id}-{stage_inst}"

            worktree = ctx.worktree_map.get(stage_id)
            if not worktree or not worktree.exists():
                continue

            if git_tag_exists(worktree, anchor_name):
                continue

            rc, stdout, _ = git_status_porcelain(worktree)
            if rc != 0:
                continue
            if stdout.strip():
                report = f"stage {stage_id} done (confirmed)"
                full_msg = (
                    f"{report}\n\n"
                    f"wf-stage: {stage_inst}\n"
                    f"wf-instance: {ctx.instance_id}\n"
                )
                msg_file = worktree / ".wfctl_commit_msg"
                msg_file.write_text(full_msg, encoding="utf-8")

                rc_add, _, stderr = git_add_all(worktree)
                if rc_add != 0:
                    msg_file.unlink(missing_ok=True)
                    continue

                rc_commit, _, _ = git_commit_file(worktree, msg_file, allow_empty=True)
                msg_file.unlink(missing_ok=True)
                if rc_commit != 0:
                    continue

                side_effects.append(SideEffect(
                    kind="git_commit",
                    description=f"Anchor commit {stage_inst}",
                    execute=None,
                ))

            # 独立副作用：tag_anchor 延迟到 orchestrator 执行
            side_effects.append(SideEffect(
                kind="git_tag",
                description=f"Ensure anchor {stage_inst}",
                execute=lambda iid=ctx.instance_id, a=anchor_name, w=worktree: tag_anchor(iid, a, worktree=w),
            ))
