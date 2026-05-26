# 特殊场景处理

> 本文档覆盖编排器在主循环之外需要处理的低频场景。每个场景的命令签名和返回结构权威来源为 `references/wfctl-commands.md`。

---

## 查看状态

```
# 项目全局
wfctl status
→ {active_instances: [...], recent_completed: [...], recent_failed: [...]}

# 单实例详情（含子工作流透传）
wfctl status --instance <id>
→ {stages_summary, stages: [...], active_worktrees, conflict_worktrees}
```

用户问"现在什么进度"时使用。

---

## 回退

用户要求回退时：
1. 确认目标 stage（`wfctl status --instance <id>` 查看已完成 stages）
2. `AskUserQuestion` 确认回退操作（会重置下游所有 stage）
3. `wfctl rollback --instance <id> --stage <stage_id>`
4. 调用 `wfctl next` 继续调度

---

## 暂停与恢复

**暂停**（冻结实例，重置运行中 stage）：
```
wfctl pause --instance <id> [--reason "暂停原因"]
```
wfctl 将 RUNNING stage 重置为 PENDING，实例状态 → PAUSED。`next` 对该实例自动拒绝。

**恢复**（继续调度）：
```
wfctl resume --instance <id>
```
wfctl 将实例状态 → ACTIVE。随后调用 `wfctl next` 继续调度。

恢复后原先被重置为 PENDING 的 stage 会重新 spawn。

---

## 跳过 stage

用户希望跳过某个 PENDING stage（已完成或不需要执行）时：
```
wfctl skip --instance <id> --stage <stage_id> [--reason "跳过原因"]
```
wfctl 标记 stage DONE、打锚点、写 deviation。随后调用 `wfctl next`——下游 stage 自然解除阻塞。

跳过仅适用于 PENDING 状态。RUNNING / AWAITING_CONFIRM / ERROR 各有专用命令（terminate / confirm / retry）。

---

## 终止实例

用户要求取消时：
```
wfctl terminate --instance <id> [--reason "终止原因"]
```

一级实例未合入 main 时，wfctl 返回 `requires_confirmation` 而非执行。此时向用户呈现确认：
```
AskUserQuestion: "实例 X 尚未合入 main，强制终止将丢失未合并产物。是否继续？"
```
用户确认后加 `--force` 重试：
```
wfctl terminate --instance <id> --force
```

wfctl 自动：创建备份分支 `wf-backup-{id}`、归档实例目录到 `.agent/archive/`、置 FAILED、清理 tag 和 worktree、写 deviation。

---

## 恢复误删实例

```
wfctl restore --instance <id>
```

从 `.agent/archive/{id}/` 恢复实例目录，从 `wf-backup-{id}` 分支重建 worktree。

---

## 中断恢复

编排器被重新唤醒时：
1. `wfctl status` 查看全局状态
2. 若存在僵尸实例（无 worktree 或有残留 tag）→ `wfctl cleanup` 清理。清理前 wfctl 自动创建备份分支和归档实例目录
3. 有 ACTIVE 实例 → `wfctl sync --instance <id>` 对齐消息池 → `wfctl next` 继续调度
4. 无活跃实例 → 等待用户指令，**禁止自行创建新实例**

---

## 卡住/死掉的 SubAgent 恢复

SubAgent 因崩溃、超时、平台回收等原因死亡后，对应 stage 永久卡在 RUNNING。编排器应在检测到后主动恢复，而非无限等待。

**检测时机**：
- `wfctl next` 连续多轮只返回 `await`（无就绪 stage）
- `wfctl status --instance <id>` 显示有 RUNNING stage，且 `started_at` 距今 > 10 分钟

**恢复优先级**：
1. **回退重试**（首选）：`wfctl rollback --instance <id> --stage <stage_id>` → `wfctl next`
2. **跳过**（最后手段）：`wfctl skip --instance <id> --stage <stage_id> --force` → `wfctl next`
3. **禁止**无限等待 `await`，连续 3 轮无进展必须主动介入

---

## worktree 自动同步

wfctl 在每次 `next` 时自动同步 worktree 与上游：
- **一级实例**：`next` 开头自动合并本地 main HEAD → 实例 worktree
- **子实例**：`next` 开头自动合并父实例 worktree HEAD → 子实例 worktree
- **stage continue**：复用 SubAgent 前，自动合并实例 HEAD → stage worktree

同步失败静默跳过，通过 `SYNC_SKIPPED` deviation 留痕。编排器无需额外操作——这是一个内置的底层机制。
