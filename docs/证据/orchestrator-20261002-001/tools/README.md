# 预览服务器端口锁（并发协议）

## 为什么要它

`apps/web/e2e/support/paths.ts` 里 `PREVIEW_PORT = 4173` 是**硬编码常量**，
`playwright.config.ts` 的 `webServer` 用 `--strictPort` 起它。
因此**任何两个并发运行的 `pnpm --filter @campfire/web shots`
（或任何要起 preview / 跑 build 的动作）会互抢 4173 而直接失败**，
且它们共用 `apps/web/dist/` 与默认落点 `tmp/screenshots/`。

端口本身改不了（改 `paths.ts` 属于改动 T01 已验收的交付物，需另行返工+复验）。
所以并发协议是：**端口串行、其余全并行**。
`shots` 独占窗口实测约 **40 秒**（build ~15s + 22s 用例），串行代价很小；
真正耗时的是 LLM 推理与会话，那部分完全并行。

## 用法（每个要碰端口的动作前后各调一次）

```powershell
# 取锁（默认最多等 15 分钟，每 5 秒重试）
pwsh -NoProfile -File .tmp/dev-orchestrator/20261002-001/tools/preview-lock.ps1 acquire

# …此处是唯一允许使用 4173 / build / 默认落点的窗口…

# 释放（务必执行，即使上一步失败）
pwsh -NoProfile -File .tmp/dev-orchestrator/20261002-001/tools/preview-lock.ps1 release
```

退出码：`0` = 成功；`1` = 未取到（超时或被占用）。

## 规则（对执行者/审查者同样有效）

1. **取锁前**先确认 4173 空闲：`Get-NetTCPConnection -LocalPort 4173 -State Listen`。
2. **必须成对**：acquire 之后无论成功失败都要 release（用 try/finally 的语义，
   即两条命令都单独跑，不要因为中间失败就跳过 release）。
3. **不要**手工删除锁文件，除非 `acquire` 报「锁已过期」让你确认；
   锁自带 `holder` 与 `acquiredAt`，**锁龄超 15 分钟视为陈旧**，`acquire` 会自动回收并打印告警。
   **注意**：陈旧性**只看锁龄，不看持有 pid 是否存活**——因为持有者是一次
   `pwsh -File ... acquire` 调用，取到锁后立刻退出，pid 必然消失。
   早期版本按「pid 不存在即陈旧」判断，导致**活锁被立刻抢走、互斥失效**
   （2026-10-02 的互斥测试当场暴露：第 2 个 holder 在 2 次尝试内抢到了锁）。
   如果某个动作确实要长时间持锁（>15 分钟），要**分多次续锁**或调大 `-StaleMinutes`。
4. **不需要端口的活儿一律不要取锁**：读源码、读 PNG、静态分析、写报告都不取锁——
   那是本协议「尽量并发」的要点。
5. **落点隔离**：若你要跑 `shots` 但不想覆盖团队基线，用
   `$env:SHOTS_OUT='tmp/screenshots/<你的名字>'`。**默认落点 `tmp/screenshots/`
   是团队基线，只有「确认本轮产物可作为新基线」时才写它。**
6. **构建产物共用**：`apps/web/dist/` 也被 `build` 重写，同样在锁内。

## 已知的例外

- **改动前基线**（`.tmp/dev-orchestrator/20261002-001/facts-probe/baseline-20261002-001/`）
  **只读**，任何情况下不得写入或删除。
- `tmp/reviewer-*/` 是审查者私有目录，随 `tmp/` 被 gitignore，可自由读写。
