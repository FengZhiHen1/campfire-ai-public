# T01 裁决记录（编排器）

日期：2026-10-02。对象：`docs/证据/materials/orchestrator-T01-worktree-report.md` §4.1 的三条待裁决取舍。
（**2026-10-07 订正路径**：该报告原误存在 `apps/api/tests/results/T01.md`——一个
**不是测试**的目录里（无 `__init__.py`、无 `test_*.py`、无任何引用），已迁到证据树。
本行原先只写 `results/T01.md`，相对路径看不出它当时住在测试包里。）
依据：任务包 `tasks/T01.md`、执行者报告与证据、编排器本轮独立实测（见下）。

---

## 裁决 1：视口尺寸 与 fullPage **两者都要**（原验收标准第 3 条是我写窄了）

**这是编排器侧的缺陷，不是执行者的问题。** 任务包验收标准第 3 条写「每张 PNG 的实际像素尺寸 = 视口 × 2」，
它与 `fullPage` 不可兼得——我写下这条时没有想清楚「截图要给谁用」：
本任务的截图**主要是给视觉审查与人工目视用的**，而裁掉 1184px（`profile-mobile`）会让
「档案页版式是否舒展、层级是否清楚」这类判断**根本做不了**。

**新裁决**：
- 保留现有 20 张**视口尺寸**截图，文件名不变（`<page>-<viewport>.png`）。它们回答「首屏长什么样」，
  对验证设备外壳（T02）尤其必要——外壳的判定就是首屏几何。
- **新增** 20 张 **fullPage** 截图，文件名 `<page>-<viewport>-full.png`。它们回答「整页长什么样」，
  供 T03 的逐页视觉审计使用。
- 尺寸断言拆成两条：视口图 `= 视口 × 2`；fullPage 图 `宽 = 视口宽 × 2 且 高 = 文档高 × 2`。
  两条都由 PNG IHDR 实读复算，不符即失败。
- `manifest.json` 里每张图加 `kind: "viewport" | "full"` 字段；`manifest.shots` 变为 40 张
  （仍保留 `truncatedByPx` 指标，它对视口图依然有意义）。

**fullPage 的已知陷阱（必须处理，不得静默）**：
`.tab-bar` 与 `.confirm-sheet` 是 `position: fixed`。Chromium 的 fullPage 截图对 fixed 元素的
处理会让它**只出现在其视口位置**（可能落在长图中间），而不是贴在页面底部——这会让 fullPage 图
看起来"底部有一条悬浮栏卡在中间"，误导视觉审查。

本仓已有同一问题的既有解法可循：`tmp/design-render/render.mjs` 的 `flow` 模式就是用
`FLOW_CSS = '.emergency-controls { position: static !important; }'` 把 sticky/fixed 中和为 static，
再截文档流形态（其 README 第 29–33 行明确登记了这个取舍）。

**要求**：fullPage 截图前注入等价的中和样式，把 `position: fixed` 的**布局**行为改为 `static`
（**只改 position，不改任何视觉参数**：颜色、边框、圆角、尺寸、间距都不动），使 fixed 元素按文档流
出现在页面末尾。并在 `manifest.json` 对应条目里记 `fixedNeutralised: true`，在报告里说明这条中和
以及它与视口图的差异。**不得**用「反正是长图」来掩盖。

**编排器本轮实测（供参考，非裁决依据）**：`fullPage` 是否可用我**未能独立确认**——
我的探针用了空夹具，`documentHeight === viewportHeight`（844/844 与 1000/1000），
因此 fullPage 与视口图等价，**没有真正测到长内容下的拼接行为**。这一条是我探针的局限，
如实登记。执行者须在**有真实长内容**（`profile` 页 1184px 裁切量）的条件下自己验证 fixed 中和
前后的差异，并在报告里给出前后两张图的对照。

### 裁决 1 补充（编排器事后发现的漏洞，必须一并处理）

**漏洞**：`fullPage` 截的是**文档**全高。在**当前**结构下这没问题（滚动容器是 `body`，文档高 = 内容高）。
**但设备外壳落地后（T02）**，滚动容器变成 `.device-screen`（`overflow-y: auto`，高 844），
文档高 ≈ 视口高 → `fullPage` 只会截到「一个 844px 的外壳，内容停在顶部」，
**整页内容根本没展开**。而且它**静默**：截图成功、尺寸断言（高 = 文档高 × 2）照样通过。

**补充要求**：
1. fullPage 截图前，定位**实际主滚动容器**（文档滚动用 `documentElement`；否则取
   `overflow-y` 为 auto/scroll 且 `scrollHeight > clientHeight` 的元素），**临时**展开
   （`height: auto; max-height: none; overflow: visible`），必要时放开文档/body，截完**必须恢复**并断言回到原状。
   只改布局约束，不改视觉参数。
2. **fail-loud 守卫**：`manifest.scroll.truncatedByPx > 0` 的页面，其 fullPage 图高度必须**显著大于**视口高×2，
   否则用例失败（错误信息写明「fullPage 未真正展开内容，长图不可用」）。
   这条守卫的目的是**在外壳落地后第一时间变红**，暴露上述静默陷阱——否则 T03 会拿 20 张「外壳首屏」
   当「整页」去审版式，结论全废。
3. `manifest.json` 的 fullPage 条目记 `contentHeightPx` 与 `expandedScrollContainer`。

---

## 裁决 2：字体改用**真实思源宋体**（原「无对外网请求」标准也是我写窄了）

**编排器独立实测**：Google Fonts 在本机可达——
```
GET https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@500&display=swap
→ HTTP 200，236 字节，返回 @font-face 指向 fonts.gstatic.com 的 .ttf
```

**为什么必须改**：本设计的调性是「暖米纸底、**宋体标题承载读物的温度**」（`DESIGN.md` 调性节），
`--font-display` 的第一顺位就是 `"Noto Serif SC"`。用系统回退字形截图，等于**用错误的字形去审一套
以字形为核心的设计语言**——T03 的「视觉观感」审计会建立在错误前提上，字号阶梯、字重、行宽的观感
全部失真。这是**证据质量问题**，不是洁癖。

我那条「日志中无对外网请求」的本意是「**无真实后端依赖**」（不起 uvicorn、不连数据库），
字体 CDN 不是后端。我把它写成「除 localhost:4173 外一律无对外请求」，是我写窄了。

**新裁决**：
- 允许 `fonts.googleapis.com` 与 `fonts.gstatic.com` 两个 host **真实出网**加载字体；
  其余外部 host 仍然**阻断**且让用例失败（显式清单，不放宽为「外部一律放行」）。
- **必须加字体加载断言（fail-loud）**：截图前 `await document.fonts.ready` 并断言
  `document.fonts.check('500 28px "Noto Serif SC"') === true`。不成立即**让用例失败**，
  错误信息要说明「字体未加载，截图会退化为回退字形，证据不可用」。
  **理由**：静默产出回退字形的截图，比产出失败更糟——它会让人拿错误的图去审字形。
- `manifest.json` 记每张图的 `fontLoaded: true` 与该断言的实际值。
- `manifest.stubbedExternalHosts` 语义改为「被阻断的清单外 host」，字体 host 不再计入。

**成本如实登记**：截图现在依赖字体 CDN 可达。若不可达，`shots` **明确失败**（这是有意的：
宁可失败，也不产出字形失真的证据）。CI(Linux) 的字体可达性未验证——已在报告 §4.2(4) 登记。

**不做的事（边界，不属本包）**：把字体**本地化**（自托管 `.ttf`）是**产品改动**，会改变生产加载行为，
且 `DESIGN.md` 自己把「国内加载可靠性」标为待实现期验证。这属独立任务，本轮不做；
编排器会向用户提示这条建议。

---

## 裁决 3：`chat` 的 SSE 立场 —— **接受，无需改动**

执行者的立场（目标形态是「刷新后已水合的历史对话」，因此不需要任何 SSE 帧）**正确且有据**：
`useConsultRuntime` 只在发送消息之后才订阅运行流，而截图目标是历史水合形态。

尤其值得肯定的是它**把立场机器化了**（`mustNotRequest: ['/api/consult/runs/']` +
`expectNeverRequested`），而不是用「不记就没事」的默认写法——后者会让将来某次改动静默打开订阅、
截图悄悄换个形态而无人察觉。这正是「守卫必须真的会失败」的要求。

**裁决**：接受。`manifest.requests` 里无 `/api/consult/runs/` 即为达成。

**补充要求（非缺陷，是覆盖面）**：目前 chat 只截到「纯消息历史」一种形态，而对话页**最重的组件**
（提问卡 `.question-card`、行动卡 `.action-card`、依据区 `.citation-block`、运行状态条 `.run-status`、
技能选择器）在契约参照图 `tmp/design-render/sections/conversation.png` 与
`states/question-*.png`、`states/chat-*.png` 里都有形态。**不要求 T01 现在补**——
这些额外形态的驱动归 **T03**（它有写自己驱动脚本的授权，且届时清单会指出需要哪些态）。
在此登记，避免后续误以为「chat 只该有一种形态」。

---

## 汇总：T01 需要做的返工（小改，非重做）

1. 新增 20 张 fullPage 截图（含 fixed 中和 + `fixedNeutralised` 登记）。
2. 尺寸断言拆成视口图与 fullPage 两条。
3. 字体改为真实加载（两个 host 放行），加 `document.fonts.check` fail-loud 断言。
4. `manifest.json` 加 `kind`、`fontLoaded` 字段；`shots` 计数与清点更新。
5. 报告补：fixed 中和前后对照图、字体加载实测原文、fullPage 尺寸复算抽查。

**不变的部分**：三次消融的有效性与写法、fail-closed 兜底、登录态注入、幂等要求（现在应验 40 张）、
`apps/web/src/` 零改动、`--out`/`SHOTS_OUT` 通道——全部沿用，不需重做。
