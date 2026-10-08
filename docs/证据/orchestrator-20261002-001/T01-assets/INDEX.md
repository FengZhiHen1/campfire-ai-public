# T01 证据索引

> **2026-10-07 迁入说明**：本目录原在 `.tmp/dev-orchestrator/20261002-001/results/T01-assets/`。
> `.tmp/` 被 `.gitignore` 忽略 ⇒ 这些证据**不在版本控制里**，随时可能被清理掉。
> 而本仓有 **5 个已跟踪的 e2e 文件**正把它们当判据来源引用：
> - `apps/web/e2e/support/paths.ts` → `probe-clip-mobile.txt`（CSS 布局容差 2px 的依据）
> - `apps/web/e2e/support/fonts.ts` → `probe-fontguard.txt`（字体闸门不可能恒真）
> - `apps/web/e2e/support/neutralise.ts` → `probe-clip-mobile.txt`、`r3-run2.txt`
> - `apps/web/e2e/guard-nonvacuity.spec.ts` → `probe-shell-desktop.txt`
> ⇒ 故把**被引用的那份记录**迁入证据树并入库；`*.png` 与逐轮 manifest 未迁
> （截图与清单可由 `pnpm shots` 重新生成，且它们已在 `.tmp` 的同一批里被后续轮覆盖）。

本目录是 T01（前端截图基建）的自检证据落盘区。**本文件说明每个文件对应哪个阶段、
哪些是权威证据、哪些是被后续运行覆盖或已被取代的过程记录。**

文件名里的 `runN` 是执行期的顺序编号，**不代表编号越大越权威**（权威的是下面标注的
那几份）。报告正文 `../T01.md`（第一轮）、`../T01-r2.md`（第二轮）、
`../T01-r3.md`（第三轮）、`../T01-r4.md`（第四轮）、`../T01-r5.md`（第五轮，T02 落地后的
两处缺陷）引用的是标注为「权威」的文件。

> **五轮的产物形状不同，若冲突以最新一轮为准**：
> - 第一轮：`formatVersion: 1`、**20 张**视口图、字体走**本地替身**（回退字形）；
> - 第二轮：`formatVersion: 2`、**40 张**（视口 20 + fullPage 20）、字体**真实出网**；
> - 第三轮：仍是 `formatVersion: 2` / 40 张，但 `manifest.json` 新增 `runId`、
>   `scroll.requiredContentHeightPx`、`scroll.hiddenOverflowContainers`，
>   且高度守卫的判据从「文档级溢出」改为「逐滚动来源取最大」（隐藏溢出）；
> - 第四轮：形状同第三轮，但**守卫主判据改为结构化表征**
>   （`findClippedElements`：页面上还有没有元素在裁内容），高度比较降为辅助；
> - 第五轮：T02（设备外壳）落地后暴露两处缺陷——`expandForFullPage` 改为放开**所有**
>   溢出容器（不再选「面积最大」的一个），`guard-nonvacuity` 中和真实外壳以恢复
>   「应用无外壳」前提。**图像零变化**（与 T02 落地后逐张相同）。
>   前四轮的图已被后续覆盖（同名文件），但其日志/manifest 留档仍可复核当时的行为。

---

## 第五轮（T01-r5.md）：T02 落地暴露的两处缺陷

> 归属：T02 执行者未越权改本包文件；失败由 T01 侧的「选容器口径」+「用例前提过期」叠加引起。
> 上轮定 P2 的「同页两个溢出容器」在本轮**有了确凿实例，已升为 P1**。

### 权威证据（第五轮报告引用）

| 文件 | 对应项 | 说明 |
| --- | --- | --- |
| `probe-shell-desktop.json` / `probe-shell-mobile.json` | **P1-B 选法依据** | 两视口的真实外壳形态：desktop 三层 `display:block/grid`、`.device-screen` 裁 1184px（陷阱存在）；mobile 三层 `display:contents`、clientH/scrollH 均为 0（**不构成陷阱**）——故选「中和真实外壳」而非「直接针对真实 `.device-screen`」 |
| `canary-opens-all.txt` / `canary-opens-all-desktop.json` | **P1-A 证据** | doubleShell 形态（刻意不中和真实外壳）下两个容器**都被放开**、展开后无裁切 |
| `ablation-largest-only-canary.txt` | **P1-A 非空洞性对照** | 把 `scrollables` 缩回「只取第一个」后同一 canary **确实变红**（`desktop 下真实 .device-screen 也必须被展开`）——证明该 canary 不是恒真 |
| `t02-post-landing-pngs/` | 判据 4 | **我保全的** T02 落地后 40 张；修完后逐张 sha256 **40/40 相同**（修复未改变任何图） |
| `compare-r5.ps1` | 判据 4 / 幂等 | 比对脚本（可重跑）：vs T02 副本 40/40 相同；vs 编排器改动前基线 22/40（20 mobile + 2 chat-desktop，与裁决复核表一致） |
| `r5-final-{1,2,3}.txt` / `r5-manifest-{1,2}.json` | 回归 + 幂等 | `23 passed` / `exit 0`；40 张 sha256 **40/40 相同**；两次 `runId` 不同 |
| `gate-*.txt` | 五门 | lint `152 files / 0 / 0`；vitest **412/38**；`quality_floor` error 0 / warning 32 / PASS |

**P1-B 的永久证据不在本目录**，而在落点下的
`tmp/screenshots/.run/guard-nonvacuity/guard-nonvacuity-{memory,profile}-pad{0,24}-{mobile,desktop}.json`
—— **8 份**，含裁决点名的 `memory-*-desktop` 与 `profile-pad0-desktop`；
每份的 `scrollContainers` 恰好只有 `div#__sim_screen__`（证明真实外壳已被中和、没在验叠加形态）。

### 过程记录（第五轮，非权威）

| 文件 | 现象 |
| --- | --- |
| `r5-run1.txt` | 一次全量运行中 `[desktop] emergency` 的字体闸门失败（`等待 5000ms 后该族的 @font-face 仍未出现在 document.fonts`）——**非本轮改动引起**（`fonts.ts` 本轮未触碰），是 r3 登记的 P2-2 已知竞态，**本轮首次拿到真实复现**；随后单页 3/3、整包 3/3 均通过 |

### 关于 `probe-*` 与 `canary-*` 的源文件

`probe-shell.spec.ts` 与 `canary-opens-all.spec.ts` 是**临时脚本**，验证完已删除；
其输出完整留档（上表）。

---

## 第四轮（T01-r4.md）：主判据改结构化表征 + 五条 P2

### 权威证据（第四轮报告引用）

| 文件 | 对应缺陷 | 说明 |
| --- | --- | --- |
| `probe-blindspot.txt` / `probe-blindspot.json` | **P1-1'** | 10 页逐页对照：目标外壳 + desktop 视口下**旧高度判据只抓 2/10、新结构化判据抓 9/10、零误报**。盲区的直接证据 |
| `probe-clip-mobile.txt` / `probe-clip-mobile.json` | P1-1' 排除规则 / P2-E | 真实 10 页的被裁元素分布：非刻意截断 0 条；刻意截断含 `span.sp-title`(ellipsis,2px) 与 `.sr-only`(clip-path,27px) —— 后者的存在说明**不能靠调大容差区分**，必须按 CSS 属性排除 |
| `r4-final-{1,2}.txt` / `r4-manifest-{1,2}.json` | 回归 + 幂等 | 两次全绿；40 张 sha256 **40/40 相同**；两次 `runId` 不同 |
| `compare-r4.ps1` | 幂等 | 比对脚本（可重跑），注释里记了 PowerShell 变量名大小写不敏感的坑 |
| `gate-quality-floor.{txt,json}` | **P2-D** | **本轮实跑**：`warning_count = 32`；JSON 版给出每条 finding 的**完整** snippet（md 会截断该列），用于更正「命因描述」 |
| `ablation-D1-sidecar-home-mobile-full.json` | **P2-C** | 从 D1 消融产物另存：`fixedNeutralised=true` / `selectors=[.tab-bar]` / `expandedAncestors=[]` —— 证明消融只跳过展开、fixed 中和照常注入 |
| `ablation-{A,B,C,C2,D1,D2}-*.txt` | 回归 | 六项消融本轮全部重跑，均 `exit 1` |
| `gate-{lint,typecheck,vitest,build}.txt` | 门禁 | `151 files / 0 warnings / 0 errors`；`410 passed` |

**P1-1' 的永久用例证据不在本目录**，而在落点下的
`tmp/screenshots/.run/guard-nonvacuity/guard-nonvacuity-{memory,profile}-pad{0,24}-{mobile,desktop}.json`
—— 8 份，含 `mainCriterionRed`（新主判据）与 `heightCriterionRed`（旧高度判据）对照。
其中 `memory-pad{0,24}-desktop` 是**盲区原形**：`mainCriterionRed=true` 而 `heightCriterionRed=false`。

### 过程记录（第四轮，非权威）

无失败现场（本轮改动一次通过全绿）。此前的失败现场见第二、三轮各节。

### 关于 `probe-*` 的源文件

两个探针（`probe-clip.spec.ts`、`probe-blindspot.spec.ts`）是**临时脚本**，
验证完已删除；其输出完整留档（上表）。报告引用的每个数字都能在这些输出里找到。

---

## 第三轮（T01-r3.md）：P1/P2 返工

### 权威证据（第三轮报告 §4 引用）

| 文件 | 对应缺陷 | 说明 |
| --- | --- | --- |
| `r3-final-3.txt` | 回归 | 最终全绿运行原文，`23 passed (19.4s)`，`exit 0` |
| `r3-manifest-1.json` / `r3-manifest-2.json` | 幂等 | 40 张两次运行清单；逐张 sha256 **40/40 相同**，两次 `runId` 不同 |
| `ablation-C2-chat-empty-list.txt` | **P1-2** | `SHOTS_ABLATION_EMPTY_LIST=chat` 现在 **exit 1** + `内容断言未命中：至少一条使用者气泡`（修订前 exit 0） |
| `canary-mixed-batch.txt` | **P2-3** | 混批检测 canary：伪造异批 sidecar 后断言确实失败并点名 |
| `ablation-{A,B,C}-final.txt` | 回归 | 三次原消融本轮重跑，均 exit 1 |
| `ablation-D1-no-expand.txt` / `ablation-D2-no-fixed-fix.txt` | 回归 | 展开/fixed 两个方向的消融，均 exit 1 |
| `gate-*.txt` | 六项门禁 | `151 files / 0 warnings / 0 errors`；`410 passed`；`verdict: PASS` |

**P1-1 的直接证据不在本目录**，而在落点下的
`tmp/screenshots/.run/guard-nonvacuity/guard-nonvacuity-pad{0,24}-{mobile,desktop}.json`
——四份 JSON 记录「不展开 ⇒ 生产守卫抛错」与「展开 ⇒ 通过」，且用的是**生产同一个**
`measureOverflow` + `assertFullPageExpanded`。放在那里而不是 `testInfo.attach`：
Playwright 的 `outputDir` 每次运行会被清空，attach 无法跨轮回溯。

### 过程记录（第三轮，非权威）

| 文件 | 阶段 | 当时的现象 |
| --- | --- | --- |
| `r3-run1.txt` | 首轮失败 | `global.setup` 的 `beginRun` 先删 `.run/` 再写批号文件却漏了 `mkdir` ⇒ ENOENT |
| `r3-run2.txt` | 第二处自身缺陷 | desktop 下旧算式 `documentElement.clientHeight + innerOverflowPx` = 2184 > 真实内容高 2133 ⇒ **误报**（该轮以 ENOENT 收场，因断言抛在截图之前） |
| `r3-run3.txt` | 修复后 | 全绿（改用「逐滚动来源取最大」） |

---

## 第二轮（T01-r2.md）：返工 —— 40 张 + 真实宋体 + fullPage 展开与守卫

### 权威证据（第二轮报告 §3 引用）

| 文件 | 对应裁决 | 说明 |
| --- | --- | --- |
| `r2-final-3.txt` | 裁决 1 追加 | 最终全绿运行原始输出，`23 passed (21.3s)`，`exit 0` |
| `r2-manifest-1.json` / `r2-manifest-2.json` | 幂等 | 40 张两次运行的完整清单；逐张比对 sha256 **40/40 相同** |
| `probe-fontguard.txt` | 裁决 2 | **字体判据可失败性**：`checkBogus: true`（裁决指定的判据恒真）与 `loadBogus: 0`（可失败判据）的出处 |
| `probe-fonts.txt` | 裁决 2 | 字体真实出网的请求清单 + 滚动容器形态（`htmlScrollH=2028` / `htmlClientH=844`） |
| `evidence-fixed-compare.txt` | 裁决 1（fixed 陷阱） | fixed 中和前后对照的坐标取证（`tabBarTopBefore=787` → `After=2028`） |
| `fixed-compare-BEFORE.png` / `fixed-compare-AFTER.png` | 裁决 1（fixed 陷阱） | 上表对应的两张图（before 里 tab 栏卡在长图中段） |
| `evidence-shell-simulation.txt` | 裁决 1 追加（守卫） | **守卫非空洞性**：模拟 T02 外壳下 `guardWouldFail: true`、展开后 `guardPasses: true` |
| `shell-trap-NOT-EXPANDED.png` / `shell-EXPANDED.png` | 同上 | 陷阱图（1688px，只有外壳首屏）与展开图（4170px，整页） |
| `ablation-D1-no-expand.txt` | 裁决 1 追加（第 4 次消融） | `SHOTS_ABLATION_NO_EXPAND=1` ⇒ `exit 1`，2 failed（**仅非空洞性用例红**，截图用例全绿——如实反映当前结构） |
| `ablation-D2-no-fixed-fix.txt` | 裁决 1（fixed 陷阱，第 4 次消融之二） | `SHOTS_ABLATION_NO_FIXED_FIX=1` ⇒ `exit 1`，8 failed（= 4 个有 tab 栏的页 × 2 视口） |
| `ablation-{A,B,C}-final.txt` | 原三消融**本轮重跑** | 均 `exit 1`，点名原因不变 |
| `gate-{lint,typecheck,vitest,build,quality-floor}.txt` | 六项门禁 | `149 files / 0 warnings / 0 errors`；`410 passed`；`verdict: PASS` |

### 过程记录（第二轮，非权威）

| 文件 | 阶段 | 当时的现象 |
| --- | --- | --- |
| `r2-run1.txt` | 首轮失败现场 | 字体 `status` 被**探针自身**的 `load()` 打回 `loading`（18 failed）——量错了对象，改为先读 status 再 load |
| `r2-run2.txt` | 中间态 | 上述修复过程中的一次运行（含探针输出） |
| `r2-run3.txt` | 第二处自身缺陷 | 「恢复后内联值应为空」这一**错误判据**在 `.device`（自带 `height:844px`）上误报（2 failed）；改为「== 记录的原值」 |
| `r2-run4.txt` | 修复后 | 非空洞性用例接入后的全绿 |
| `r2-run5-green.txt` | 中间全绿 | 与 `r2-final-3.txt` 同为全绿，前者早于最后一次注释清理 |

---

## 第一轮（T01.md）：权威证据

> **`gate-*.txt` 这五个文件已被第二轮覆盖**（同名）。
> 它们现在的内容是**第二轮**的（`149 files`、`warning: 30`）。
> 下表的数字（`146 files`、`warning: 27`）是第一轮当时的值，**无法从磁盘现行文件复算**——
> 与 `T01.md` §3.2 登记的证据限制一致。第一轮真正独有、未被覆盖的是
> `final-run-{1,2}.txt` 与 `manifest-final-{1,2}.json`。

| 文件 | 对应验收标准 | 说明 |
| --- | --- | --- |
| `gate-lint.txt` | 标准 1 | `pnpm --filter @campfire/web lint` 原文，`Found 0 warnings and 0 errors.` |
| `gate-typecheck.txt` | 标准 1 | `tsc --noEmit` 原文，无输出即通过 |
| `gate-vitest.txt` | 标准 1 | `Test Files 38 passed (38)` / `Tests 410 passed (410)`，与基线一致且未收集 Playwright 用例 |
| `gate-build.txt` | 标准 1 | `vite build` + `契约样式断言通过：16 个对话面契约类名…` |
| `gate-quality-floor.txt` | 质量地板 | `--root apps/web` 的报告，`error: 0 / warning: 27 / verdict: PASS` |
| `final-run-1.txt` | 标准 2 | `pnpm --filter @campfire/web shots` 全绿，`21 passed (12.1s)`，`exit 0` |
| `final-run-2.txt` | 标准 2 + 幂等 | 同一命令第二次全绿，`21 passed (12.2s)`，`exit 0` |
| `manifest-final-1.json` | 标准 3、4 | 与 run-1 对应的 manifest（20 张的 sha256/bytes/尺寸/断言命中串） |
| `manifest-final-2.json` | 标准 3、4 + 幂等 | 与 run-2 对应；与其 -1 逐张比对 sha256 **20/20 相同** |
| `ablation-A-final.txt` | 标准 4（兜底 handler） | 摘掉 `consult-list` 夹具 ⇒ `exit 1` + 点名 `GET …/api/consult/sessions?limit=20` |
| `ablation-B-final.txt` | 标准 5（登录态注入） | 关掉 `addInitScript` ⇒ `exit 1`，18 个用例「被重定向到 /login」，另 2 个（`login` 页两视口）因 `POST /api/auth/session/refresh` 未命中而 fail-closed |
| `ablation-C-final.txt` | 标准 6（内容断言） | `cases` 夹具承载列表置空 ⇒ `exit 1`，`选择器 article.list-row 需要至少 2 个，实际 0 个` |

三次消融的「先失败、后恢复」在报告 §3.5；恢复后的全绿原文即上面 `final-run-{1,2}.txt`。

## 过程记录（非权威，保留以显示诊断路径）

这些文件**不是**当前结论的依据。保留原因是它们显示了缺陷是怎么被发现与定位的；
若与权威文件冲突，**以权威文件为准**。

| 文件 | 阶段 | 当时的现象 |
| --- | --- | --- |
| `run1-full.txt` | 首轮失败现场 | 20 个用例全败，三类原因：字体请求出网导致 `基线截图必须零外部网络`（14 条）、多元素作用域用 `innerText()` 抛 strict mode 被吞成空文本（`内容断言未命中` 共 4 条：consult-list 2 + memory 2）、登录态断言用了 chat 页不存在的 `.phone-shell` 选择器（`element(s) not found` / `toBeVisible() failed` 各 2 条，同一 2 个用例）——14+4+2 = 20 |
| `run2-full.txt` | 修掉上述后 | 剩 9 败：截图形状用了 fullPage 导致尺寸 ≠ 视口×2（7 条）、chat 依据区在 `<details>` 里默认收起而候选串含其正文（2 条） |
| `run3-full.txt` | 首次全绿 | `21 passed` |
| `run4-restored.txt` / `run5-restored-second.txt` | 幂等首测 | `ablation-A` 恢复后的两次运行；暴露 `memory-{mobile,desktop}` sha256 不一致（18/20 稳定） |
| `manifest-run4.json` / `manifest-run5.json` | 同上 | 用于比对，即暴露那 2 张差异的清单 |
| `run6-frozen-a.txt` / `run7-frozen-b.txt` | 修复尝试（错误方向） | 用「冻结全时钟」一刀切 ⇒ 会话列表的「12 分钟前」被算成「4 小时前」而失败。证明两类时间的敏感面不同 |
| `manifest-run6-frozen-a.json` / `manifest-run7-frozen-b.json` | 同上 | 该尝试对应的清单 |
| `run8-final-a.txt` / `run9-final-b.txt` | 修复后 | 按「相对时间 / 绝对时间」分两类构造夹具 ⇒ 幂等 |
| `manifest-run8.json` / `manifest-run9.json` | 同上 | 20/20 相同 |
| `run10-post-refactor.txt` / `run11-post-refactor.txt` | 断言重构后 | 把四段重复轮询收成 `pollUntilSatisfied` 后的两次全绿 |
| `manifest-run11.json` / `manifest-run12.json` | 同上 | 幂等复核 |
| `run12-final-a.txt` | 加入 requests 账本后 | 首次带「实际请求清单」的全绿 |
| `run-final-tight.txt` | 产物一致性取证 | 报告 §3.7 引用的构建行（`[WebServer] dist/assets/…`）出处 |
| `manifest-final.json` | 中间产物 | 早于 `manifest-final-{1,2}.json` 的一次清单（无 `requests` 字段），已被取代 |
| `ablation-A-missing-fixture.txt` | 消融 A（重构前） | 与 `-final` 同一次实验的早期记录：摘掉 `/api/consult/sessions`，`exit 1` 并点名 `GET …?limit=20`。行号为 `shots.spec.ts:85:3`（重构前）；`-final` 为 `84:3`（重构后）。两者结论一致 |
| `ablation-B-no-session.txt` / `ablation-C-empty-list.txt` | 消融 B/C 早期 | 与 `-final` 同构但阶段不同（`-final` 是断言重构后的复核）。以 `-final` 为准 |

## 关于被覆盖的证据（如实说明）

执行过程中有两处证据**被后续运行覆盖**，因此磁盘上已不存在；报告正文对它们做了
显式标注，不当作可当场复算的依据：

1. **`gate-quality-floor.txt` 的首版**（`warning: 46`）——被最终版（`warning: 27`）覆盖。
   报告 §3.2 只用算术自洽检查支撑该差值，并声明审查者可忽略差值、只采信当前文件。
2. **首次消融 A 的日志**（摘掉夹具后失败在「内容断言未命中」、**没有**点名 URL）——被
   后续运行覆盖。报告 §1.4(3) 描述的「判定顺序错了」这一现象依赖执行期观察；当前磁盘上
   的两份消融 A 日志（`ablation-A-missing-fixture.txt`、`ablation-A-final.txt`）
   **都**已能点名 URL，因此**不能用它们反证那个缺陷曾经存在**。两份的差异只在行号
   （`85:3` 重构前 vs `84:3` 重构后），结论相同。
