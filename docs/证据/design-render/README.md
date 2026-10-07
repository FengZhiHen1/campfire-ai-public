# 现行组件设计渲染图（对照用）

> **这不是设计权威。** 设计权威是 [`docs/design/`](../../design/) 三件套
> （`tokens.css` / `components.html` / `DESIGN.md`）。本目录只是把它们渲染成 PNG，
> 方便拿图片逐一比对 `apps/web` 的前端落地是否准确。
>
> **2026-10-06 迁入 `docs/证据/design-render/`**（原在 `tmp/design-render/`）：
> 本目录的**渲染器与说明是既有解法的规范来源**（被 `apps/web/e2e/support/neutralise.ts`
> 与 `fonts.ts` 以 MUST 引用），属**需入库的证据**，故随其他证据一并迁入 `docs/证据/`。
> PNG 产物（`sections/`、`states/`、`page-annotated*.png`）**未迁入**——它们按本文定义
> 是可重新生成的中间产物；需要时用 `render.mjs` 重渲染即可（真源哈希见 `inventory.json`）。

## 边界与判据

| 项 | 值 |
| --- | --- |
| 渲染输入（唯一） | `docs/design/components.html`（它自身 `<link>` 引入 `docs/design/tokens.css`） |
| 渲染时真源 sha256 | 见 `inventory.json` → `sources`（比对前先核这枚哈希，变了就要重渲染） |
| 渲染器 | `render.mjs`（零第三方依赖：本机 Chrome + CDP） |
| 视口 | 390×844 CSS px，deviceScaleFactor 2（手机单列定调） |
| 字体前置 | `document.fonts.ready` 后截图；`inventory.json` → `preshoot.notoSerif` 必须为 `true` |
| 产物校验 | 每张图的像素尺寸从 PNG 字节读回并与「CSS 尺寸 × dpr」比对（容差 2px），不符即整轮失败 |
| 尺寸实测 | 宽度 30/30 精确相符；高度 26/30 短 1–2px、4/30 精确（最大偏差 2px，**成因未确定**，正被容差吸收） |

**已核实**（本次渲染实测，非推断）：

- `notoSerif: true` —— 标题字体的 Noto Serif SC 确实加载，图里的宋体字形是契约字形而非回退字形；
- `bodyBg: rgb(241, 227, 207)` = `--surface-warm`，`--accent` 为 `#c2410c`（图里火焰橙按钮）；
- 9 个分区图与 `components.html` 的 9 个 `.component-section` 一一对应，无遗漏（渲染器对此有闸门）。

**未验证 / 已知局限**（看图时请带上下面的折扣）：

1. **分区图与 `flow` 状态图按文档流排版**，`.emergency-controls` 的 `sticky` 被中和为 `static`
   （与契约自带的 `@media print { .emergency-controls { position: static } }` 同语义）。
   单张静态图无法表达「吸附」，所以按钮出现在流的末尾而非浮在底部。
   真实吸附形态见 `states/warning-sticky.png`。
2. **固定定位元素**（`.tab-bar`、`.confirm-sheet`）在分区图里按文档流呈现，不代表运行时的覆盖层级。
3. **动效是静止的**：篝火呼吸点（2s 循环）与 150/240ms 过渡在 PNG 里只是一帧。
4. **仅覆盖 `components.html` 内的形态**。`docs/design/pages/*.md` 是页面设计文档（Markdown，
   无 HTML 实现），本目录不含页面级截图。若要页面级对照，需要另建渲染源。
5. **渲染环境是本机浏览器**（Chrome 154 + 系统字体）。不同机器的字体栅格化会有细微差别。
6. **中文字形来自系统回退**：Noto Serif SC 的 webfont 来自 Google Fonts 且本次可达；
   正文用的 `--font-body` 是系统无衬线栈（微软雅黑），随机器而变。
7. **高度普遍短 1–2px（26/30 张）**：宽度 30/30 精确，高度偏差只出现在纵向。
   我**未能确定成因**（排除项：不是 `Math.round` 的取整方式——有 1 次 599.3 取整后
   反而高了 1px；也不是 dpr 倍率）。它低于 2px 容差，所以闸门放行；若某次偏差 ≥3px，
   闸门会失败并列出具体文件。**结论：边缘 1–2px 可能被裁掉，最底部的分隔线要留意。**
   谁要是查清了成因，请顺手把容差收紧到 1px。

## 目录内容

```
tmp/design-render/
├── README.md                  ← 本文件
├── render.mjs                 ← 渲染器（唯一可执行入口）
├── inventory.json             ← 清单：真源哈希 + 每张图的尺寸/字节/sha256/说明
├── page-annotated.png         ← 全页目录（1x，带分区标注条，作索引）
├── page-annotated-top.png     ← 全页目录顶部（2x，标注条样式可判读）
├── page-annotated.pins.json   ← 标注条的分区名与 y 坐标
├── sections/                  ← 9 张分区图：01–09，与 components.html 的 section 一一对应
└── states/                    ← 20 张状态图：页面状态、对话情境、提问卡、吸附态、表单失败
```

### 分区图 `sections/`（对应 `components.html` 的 01–09）

| 文件 | 内容 |
| --- | --- |
| `situation-entry.png` | 首页入口：应急优先面板 + 日常入口整卡可点 |
| `safety.png` | 应急表单采集、可跳过追问、提问卡 |
| `provenance.png` | 行动卡七节结构、来源标签、依据折叠、三值风险徽章、过期卡 |
| `plan.png` | 档案摘要与「待确认」候选分层、list-row、空态 |
| `forms.png` | 输入与校验反馈、服务失败就地重试、日常对话输入 |
| `actions.png` | 操作层级：主 / 次 / 静默（跳过）/ 危险 |
| `states.png` | 状态切换器 + 默认选中的「失败」形态 |
| `conversation.png` | 完整对话工作面：消息、追问、依据、运行反馈、技能选择 |
| `foundation.png` | 基础输入、卡片三层语言、页头与 tab 栏、消息骨架 |

### 状态图 `states/`

页面状态（由契约页自身的 `#state-picker` 切出，未注入任何自造样式）：
`state-populated` / `state-loading` / `state-delayed` / `state-empty` / `state-no-results` /
`state-error` / `state-partial`

对话工作面（由 `#chat-scenario` 切出；`chat-*` 的时间敏感情境已按契约脚本的定时器等待到位）：
`chat-daily` / `chat-emergency` / `chat-history` / `chat-history-error` /
`chat-retrieval-error` / `chat-reconnecting` / `chat-delayed`

提问卡（由 `#question-scenario` 切出）：`question-daily` / `question-single` / `question-emergency`

其它：`warning-sticky`（sticky 真实生效）、`form-save-error`（驱动出的保存失败形态）

## 重新生成

```powershell
node tmp/design-render/render.mjs                 # 全量，约 30 秒
node tmp/design-render/render.mjs --only=states   # 只重渲染文件名含该子串的产物
node tmp/design-render/render.mjs --scale=1       # 改 dpr（默认 2）
```

渲染器在以下情况**失败退出**（而不是静默产出坏图）：

- 产出 0 张图，或有分区没有对应产物；
- 任何一张图的 PNG 实际像素与「CSS 尺寸 × dpr」相差超过 2px（疑似截断）；
- 目标选择器无命中，或矩形为 0 尺寸（状态没真正切过去）；
- `--only=` 未匹配任何产物；
- Noto Serif SC 未加载、视口宽度不是 390。

前四条已用**消融实验**逐一验证过：临时放入坏目标（不存在的选择器、隐藏元素、
匹配不到产物的 `--only`），确认每次都 `exit 1` 并点名具体文件，随后移除。

## 怎么用它判断前端落地是否准确

1. 先核 `inventory.json` → `sources[].sha256` 与当前 `docs/design/` 一致，否则先重渲染。
2. 打开对应分区图，与 `apps/web` 页面截图并排比对：**色彩**（火焰橙 `#c2410c`、暖米纸底）、
   **字号阶梯**、**圆角语言**、**卡片层级**（panel 有阴影 / tile 只有边框 / mini-card 暖底）、
   **状态四态**（loading / empty / error / 中断）的措辞与按钮。
3. 契约类名与 `apps/web/src/shared/styles/components.css` 的对应关系，
   由 `apps/web/scripts/check-contract-css.mjs` 在 `pnpm build` 时机械把关；
   本目录的图是**人工目视**那一道，二者互补。
