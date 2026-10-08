# 并发协议（编排期，2026-10-02 起）

用户要求「尽量提高并发」。本文件是**编排器实测过的**并发边界，派发时随任务包一起给子代理。

## 一、能并发 / 不能并发（实测结论）

| 动作 | 能否并发 | 依据（编排器实测） |
|---|---|---|
| 读源码 / 读 PNG / 读文档 | ✅ 任意并发 | 纯读，无共享写 |
| 写自己的报告与 assets | ✅ 任意并发 | 各写各自目录（`.tmp/.../results/T0x-assets/`、`tmp/reviewer-T0x/`） |
| `pnpm --filter @campfire/web test`（vitest） | ✅ 可并发 | 只读源码 + jsdom，不写 `dist/` |
| `pnpm --filter @campfire/web lint` / `typecheck` | ✅ 可并发 | 只读 |
| 起 preview 服务器（**各自不同端口**） | ✅ 可并发 | **实测**：4188 与 4189 同时监听、都返回 200，共用同一 `dist/` |
| `vite preview --outDir <私有副本>` | ✅ 可并发 | **实测**：4190 指向私有 dist 副本、返回 200 |
| **`pnpm --filter @campfire/web build`** | ❌ **必须串行** | 写 `apps/web/dist/` 与 `apps/web/src/shared/styles/tokens.css`（`sync-tokens` 生成物，**是受版本控制的文件**） |
| **`pnpm --filter @campfire/web shots`** | ❌ **必须串行** | 内含 `build`；且 `PREVIEW_PORT=4173` 是 `paths.ts` 里的**硬编码常量** + `--strictPort`；还写默认落点 `tmp/screenshots/` |

**关键实测事实**：`PREVIEW_PORT` 是硬编码常量（`apps/web/e2e/support/paths.ts:103`），
**不能用环境变量改**。所以 `shots` 无法换端口 —— 端口只能串行。
改它属于改动 T01 已验收的交付物（需返工+复验），本轮不做。

**但这不是主要瓶颈**：`shots` 独占窗口实测约 **40 秒**（build ~15s + 22s 用例）。
真正耗时的是 LLM 推理与会话，那部分**完全并行**。

## 二、正确做法

### 不需要端口的活儿（多数情况）

直接干，不取锁。**尤其是**：审查者读截图、读源码、写报告；执行者做静态分析。

### 需要构建产物的只读审查（最高效的并发形态）

**不要**每次都 `build`。共享一份已验证的 `dist/`，各自起**不同端口**的 preview：

```powershell
# 每个代理用自己的端口，指向同一份 dist（只读使用，不写它）
cd apps/web
node node_modules/vite/bin/vite.js preview --port <你的端口> --strictPort --host 127.0.0.1
```

端口分配（避免撞车，取 4188–4199）：
- 编排器：4188
- T03 执行者：4189
- T02 审查者：4190
- 后续审查者：4191+
- **4173 保留给 `shots`**（硬编码，不可改）

**注意**：多个 preview 共用一个 `dist/` 是安全的，但**前提是没人同时在 `build`**。
若你要一边预览一边让别人构建，先把自己的 `dist` 复制成私有副本再用 `--outDir` 指过去。

### 需要 build / shots 的活儿

先取端口锁（见 `tools/README.md`），做完释放：

```powershell
pwsh -NoProfile -File .tmp/dev-orchestrator/20261002-001/tools/preview-lock.ps1 acquire -Holder '<你是谁>'
# ... 独占窗口，跑 build / shots ...
pwsh -NoProfile -File .tmp/dev-orchestrator/20261002-001/tools/preview-lock.ps1 release
```

## 三、落点隔离（防互相覆盖产物）

`shots` 支持 `$env:SHOTS_OUT` 改落点（`paths.ts:38` 已实现）：

```powershell
$env:SHOTS_OUT='tmp/screenshots/<你的名字>'   # 相对仓库根
```

- **默认落点 `tmp/screenshots/` = 团队基线**，只有「确认本轮产物可作为新基线」时才写它。
- **改动前基线** `.tmp/dev-orchestrator/20261002-001/facts-probe/baseline-20261002-001/`
  **只读**，任何情况不得写或删。

## 四、端口锁的正确性（编排器已测）

| 场景 | 结果 |
|---|---|
| 正常 acquire → release | ✅ |
| 占用时第二个 acquire（超时 4s） | ✅ 退出码 1（互斥成立） |
| **4 个 acquire 同时抢** | ✅ **恰好 1 个成功**（3 个退出码 1） |
| 陈旧锁（锁龄 > 15 分钟） | ✅ 自动回收并告警 |

**踩过的坑（已修）**：早期版本按「持有 pid 是否还存在」判断陈旧锁。
但锁的持有者是一次 `pwsh -File ... acquire` 调用，**取到锁后立刻退出**，
于是第二次 acquire 时 pid 必然消失 ⇒ **活锁被当成陈旧锁抢走，互斥完全失效**
（互斥测试当场暴露：第 2 个 holder 在 2 次尝试内抢到了锁）。
现改为**只看锁龄**。若某动作要持锁 > 15 分钟，需调大 `-StaleMinutes` 或分次续锁。

## 五、给子代理的派发模板（一段话）

> 并发边界已实测并写在 `.tmp/dev-orchestrator/20261002-001/tools/CONCURRENCY.md`。
> 你**不需要**跑 `build` 或 `shots`（那份 `dist/` 已验证可用）；
> 若你需要浏览器预览，用**你自己的端口**（<分配给你的端口>）起 preview，指向现有 `dist/`
> （`cd apps/web; node node_modules/vite/bin/vite.js preview --port <port> --strictPort --host 127.0.0.1`）。
> **绝对不要**跑 `pnpm build` 或 `pnpm shots`，也不要占用 4173——那会打断别人的构建。
> 你的产物只写自己的目录：`<你的 assets 目录>`。
