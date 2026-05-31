# 智能应急咨询 — 主页面 功能块骨架

## 元信息
- 目标平台: miniprogram (750rpx 基准)
- 关联页面: idle → 选择页(`select.tsx`) → 主页(本页: streaming/completed/error)
- 设计作用域: 特定功能页 — 核心咨询结果展示
- 页面职责: 入口引导(idle) → 加载过渡(submitting) → 方案生成(streaming) → 结果展示(completed) → 异常恢复(error)
- Logic-ID 清单:

| ID | 类型 | 用途 |
|----|------|------|
| `sessionState` | `ConsultSessionState` | 页面状态路由 |
| `behaviorDescription` | `string` | 用户原始描述 |
| `behaviorTypeSelection` | `BehaviorTypeCategory[]` | 已选行为类型 |
| `emotionLevel` | `'轻' \| '中' \| '重'` | 情绪等级 |
| `planSections` | `PlanSection[]` | 四段式方案数据 |
| `accumulatedText` | `string` | 流式累积文本 |
| `crisisLevel` | `CrisisLevel \| undefined` | 危机等级 |
| `ticketGuide` | `TicketGuide` | 工单引导标记 |
| `referencedCases` | `ReferencedCase[]` | 参考案例列表 |
| `isConsultActive` | `boolean` | 是否活跃咨询中 |
| `startConsult` | `() => void` | idle → selecting_behavior |
| `startNewConsult` | `() => void` | completed → selecting_behavior |
| `goToTicket` | `() => void` | 跳转工单 |
| `goBackToSelecting` | `() => void` | 返回修改 |
| `retrySubmit` | `() => Promise<void>` | 重试提交 |
| `retryStream` | `() => Promise<void>` | 重新生成 |

- 状态路由: 本页面处理 `idle` / `submitting` / `streaming` / `completed` / `ticket_guide` / `submit_failed` / `stream_failed`，其中 `selecting_behavior` 已独立为 `select.tsx`
- 前端包: `apps/mini-program/src`
- 关联 DESIGN.md: `docs/DESIGN.md` (Campfire-AI 主系统), `_tokens.scss`
- 视觉方向: 抛弃聊天隐喻，采用**应急方案仪表盘** — 方案卡片是绝对主角

## 平台布局

### miniprogram (750rpx 基准) — idle 状态

```
┌──────────────────────────────────┐ ← 750rpx 全宽
│ [原生导航栏]                      │
│          应急咨询                  │
├──────────────────────────────────┤
│                                  │
│                                  │
│         [抽象篝火图形]            │ ← primary-container 圆形区域 240rpx
│         (线条风, primary 色)      │   内含抽象暖光几何图形
│                                  │
│        应急咨询                   │ ← headline-sm, on-background
│                                  │
│    描述孩子当前的行为表现          │ ← body-sm, on-surface-variant
│    获取基于真实案例的应急建议      │   居中, 最多两行
│                                  │
│                                  │
│    ┌────────────────────────┐   │
│    │      开始咨询           │   │ ← primary 全宽按钮, 96rpx高, 32rpx圆角
│    └────────────────────────┘   │   左右 margin 64rpx
│                                  │
│                                  │
├──────────────────────────────────┤
│ [Disclaimer — 常驻底部]           │ ← surface-dim 背景条
│ 基于真实案例的AI建议，不构成医疗诊断│   footnote 22rpx, on-surface-variant
├──────────────────────────────────┤
│ [safe-area-inset-bottom]         │
└──────────────────────────────────┘
```

- **导航**: 原生导航栏, 居中标题 "应急咨询", 无返回按钮（这是 Tab 入口首页）
- **空态**: 无需 — idle 状态本身就是首次进入的展示态
- **交互**: "开始咨询" → `startConsult()` → 跳转选择页

### miniprogram (750rpx 基准) — submitting 状态

```
┌──────────────────────────────────┐
│ [原生导航栏]     应急咨询         │
├──────────────────────────────────┤
│                                  │
│                                  │
│         [暖光呼吸动画]            │ ← 160rpx 圆形区域
│         primary 色光晕            │   opacity 0.4→0.8 呼吸, 2s
│         (无 emoji, 纯色光)        │
│                                  │
│       正在分析案例库…             │ ← body-md, on-background
│       匹配最相似的历史案例         │ ← body-sm, on-surface-variant
│                                  │
│   ┌──┐ ┌──┐ ┌──┐ ┌──┐         │
│   └──┘ └──┘ └──┘ └──┘         │ ← 4 个进度指示条
│   (依次亮起, 循环)               │    surface-variant→primary 色
│                                  │    w: 48rpx h: 8rpx 圆角
├──────────────────────────────────┤
│ [Disclaimer]                     │
└──────────────────────────────────┘
```

- **加载态**: 无骨架屏闪烁矩形 — 用暖光呼吸动画 + 进度点序列, 传达"系统正在工作"而非"请等待"
- **文案**: "正在分析案例库…" → 匹配完成后自动过渡到 streaming

### miniprogram (750rpx 基准) — streaming 状态

```
┌──────────────────────────────────┐
│ [原生导航栏]  应急咨询  [等级]   │ ← crisisLevel 有值时显示危机徽章
├──────────────────────────────────┤
│                                  │
│ [用户查询摘要]                    │ ← 紧凑卡片, surface 背景
│ ┌──────────────────────────────┐ │
│ │ 自伤行为 · 情绪中度           │ │ ← label-sm, primary-container pill
│ │ "孩子在商场突然蹲下尖叫..."    │ │ ← body-sm, on-background
│ └──────────────────────────────┘ │   左右 32rpx margin
│                                  │
│ [干预方案卡片] ← 核心视觉锚点     │
│ ┌──────────────────────────────┐ │
│ │ 干预建议大纲                  │ │ ← headline-sm, on-background
│ │                              │ │
│ │ ▎🛡️ 即时安全干预              │ │ ← 4px 左侧 tertiary accent bar
│ │   正在生成… ▍                 │ │   标题 28rpx semibold
│ │                              │ │   流式文本 + 打字机光标
│ │ ▎💬 情绪安抚话术              │ │ ← 4px 左侧 primary accent bar
│ │   (待生成)                    │ │   浅色 placeholder 文字
│ │                              │ │
│ │ ▎👁️ 后续观察指标              │ │ ← 4px 左侧 secondary accent bar
│ │   (待生成)                    │ │
│ │                              │ │
│ │ ▎🏥 就医判断标准              │ │ ← 4px 左侧 error accent bar
│ │   (待生成)                    │ │   (仅当有就医建议时红色, 否则 secondary)
│ └──────────────────────────────┘ │
│                                  │
│ [操作区 — streaming 期间禁用]     │
│ ┌──────────────────────────────┐ │
│ │      生成中… (禁用)           │ │ ← surface-dim 禁用按钮
│ └──────────────────────────────┘ │
│                                  │
├──────────────────────────────────┤
│ [Disclaimer]                     │
└──────────────────────────────────┘
```

- **核心变更**: 不再先显示"流式文本气泡"再切换为卡片。**方案卡片从 streaming 第一帧就出现**，骨架先于内容
- **四段标题始终可见** — 给用户"结构即将填满"的预期，消除布局跳动
- **当前活跃段**: 正在接收内容的段显示打字机光标；未开始的段显示 "（待生成）" 浅色占位
- **流式动画**: 文字 `opacity 0→1 + translateY(2px)→0`, 150ms, ease-out; 光标 `opacity 1→0.4` 脉动 1.5s
- **段落完成过渡**: 每段内容接收完毕后, 自动 12rpx 呼吸间距, 200ms ease-in-out

### miniprogram (750rpx 基准) — completed 状态

```
┌──────────────────────────────────┐
│ [原生导航栏]  应急咨询  [等级]   │
├──────────────────────────────────┤
│ <scroll-view>                    │
│                                  │
│ [用户查询摘要] ← 同 streaming     │
│ ┌──────────────────────────────┐ │
│ └──────────────────────────────┘ │
│                                  │
│ [干预方案卡片]                   │
│ ┌──────────────────────────────┐ │
│ │ 干预建议大纲                  │ │
│ │                              │ │
│ │ ▎🛡️ 即时安全干预 (完成)       │ │ ← 标题旁 ✓ tertiary 小勾
│ │   1. 立即将孩子移至安静环境    │ │ ← body-md 18px, line-height 1.8
│ │   2. 移除周围尖锐物品         │ │
│ │                              │ │
│ │ ▎💬 情绪安抚话术 (完成)       │ │
│ │   "深呼吸，我知道你现在很难受" │ │ ← 安抚话术用引用样式
│ │   ...                        │ │   italic + 左侧 primary 4px 竖条
│ │                              │ │
│ │ ▎👁️ 后续观察指标 (完成)       │ │
│ │   • 自伤行为持续超过5分钟      │ │
│ │   • 是否有新的攻击行为         │ │
│ │                              │ │
│ │ ▎🏥 就医判断标准 (完成)       │ │
│ │   • 如意识模糊，立即呼叫120    │ │
│ │                              │ │
│ │ ─────────────────────────── │ │ ← ghost border 分割
│ │ 基于 4 个相似案例  │ ● 高可信 │ │ ← tertiary pill + 置信度徽章
│ └──────────────────────────────┘ │
│                                  │
│ [参考案例] (条件渲染)             │
│ ┌──────────────────────────────┐ │
│ │ 参考案例 (2)          ▼ 展开  │ │ ← 默认折叠, 点击展开
│ │ ─────────────────────────── │ │
│ │ CASE-2024-0087               │ │
│ │ 5岁男童, ASD诊断, 商场环境…   │ │
│ │ ——————————————————————————— │ │
│ │ CASE-2024-0156               │ │
│ │ 7岁男童, 类似自伤行为…        │ │
│ └──────────────────────────────┘ │
│                                  │
│ [操作区]                         │
│ ┌──────────────────────────────┐ │
│ │       🔄 开始新咨询           │ │ ← primary 全宽按钮 96rpx
│ └──────────────────────────────┘ │
│                                  │
│ </scroll-view>                   │
├──────────────────────────────────┤
│ [人工兜底条] (条件渲染)           │ ← ticketGuide.show 时出现
│ 🚨 立即联系人工专家               │   error 背景, 56rpx高, sticky
├──────────────────────────────────┤
│ [Disclaimer]                     │
│ 基于真实案例的AI建议，不构成医疗诊断│
├──────────────────────────────────┤
│ [safe-area-inset-bottom]         │
└──────────────────────────────────┘
```

- **方案卡片**: 四段内容全部展开（危机场景不折叠信息）, 每段左侧 accent bar 4rpx 宽
- **安抚话术特殊样式**: italic + 引用块样式 (surface-variant 背景 + primary 左竖条)
- **置信度徽章**: pill 形状, 三档 (高/中/低), 对应 tertiary / primary-container / surface-variant+error 色
- **参考案例**: 默认折叠, 点击展开, 每项可点击跳转案例详情
- **人工兜底条**: `ticketGuide.show` 时从底部滑入, error 背景, 点击直接生成工单

### miniprogram (750rpx 基准) — error 状态 (submit_failed / stream_failed)

```
┌──────────────────────────────────┐
│ [原生导航栏]     应急咨询         │
├──────────────────────────────────┤
│                                  │
│                                  │
│         [抽象感叹图形]            │ ← error-container 圆形 160rpx
│         (线条风, error 色)        │   非 emoji ⚠️
│                                  │
│        生成失败                   │ ← headline-sm, on-background
│    网络连接异常，请检查网络后重试   │ ← body-sm, on-surface-variant
│    或返回修改描述重新提交          │
│                                  │
│    ┌────────────────────────┐   │
│    │      重试生成           │   │ ← primary 全宽按钮
│    └────────────────────────┘   │
│                                  │
│    ┌────────────────────────┐   │
│    │      返回修改           │   │ ← secondary 全宽按钮 (outline)
│    └────────────────────────┘   │
│                                  │
├──────────────────────────────────┤
│ [Disclaimer]                     │
└──────────────────────────────────┘
```

- **错误文案**: 由 `getErrorMessage(errorCode)` 提供, 不硬编码
- **submit_failed**: 显示 "重试提交" + "返回修改"
- **stream_failed**: 显示 "重新生成" + "返回修改"
- **不**使用 toast/alert 阻断式提示

## 功能块详述

### 区块A — 导航栏

- **职责**: 页面标识 + 危机等级可视化
- **idle/submitting/error**: 仅标题 "应急咨询", 居中
- **streaming/completed**: 标题 + 右侧危机徽章（仅 `crisisLevel` 有值时显示）
- **危机徽章三态**:
  | 等级 | crisisLevel | 背景色 | 文字 |
  |------|-------------|--------|------|
  | 轻度 | `mild` | `tertiary` | 等级：轻度 |
  | 中度 | `moderate` | `primary` | 等级：中度 |
  | 重度 | `severe` | `error` | 等级：重度 (脉动动画) |
- **徽章形状**: pill, 8rpx radius, 8rpx 12rpx padding, 高度 56rpx
- **导航栏高度**: 88rpx (含状态栏则由原生导航栏处理)

### 区块B — idle 入口区

- **职责**: 建立场景认知 + 引导行动
- **抽象图形**: 160rpx 圆形, `primary-container` 背景, 内含 abstract 几何线条（篝火/暖光意象）。纯 CSS/SVG 实现, 不依赖 emoji 或图片
- **标题 & 副标题**: 垂直居中排列, 上下间距 32rpx
- **CTA 按钮**: `primary` 背景, `on-primary` 文字, 96rpx 高, 32rpx 圆角, 左右 margin 64rpx
- **三态**: 无需 — 静态展示

### 区块C — submitting 加载区

- **职责**: 告知系统正在工作，缓解等待焦虑
- **视觉**: 摒弃灰色骨架屏闪烁。用 `primary` 色暖光呼吸（160rpx 圆形区, `opacity 0.4→0.8`, 2s `ease-in-out` `infinite`）+ 4 个进度点依次亮起
- **进度点**: 48rpx × 8rpx 圆角条, 4 个, 间距 16rpx。动画: 从左到右依次填充 `primary` 色, 循环
- **文案**: "正在分析案例库…" (主), "匹配最相似的历史案例" (副)
- **过渡**: SSE 首段结构数据到达 → 自动切换到 streaming 卡片

### 区块D — 用户查询摘要

- **职责**: 紧凑展示用户刚才提交的内容, 作为方案的上下文锚点
- **形态**: `surface` 背景卡片, 16rpx 圆角, 32rpx 内边距
- **内容**:
  - 第一行: 行为类型 → `primary-container` 色 pill 标签 (如 "自伤行为"),  + "·" 分隔 + 情绪等级文字
  - 第二行: 用户描述文本, 最多 3 行, 超出省略
- **边距**: 左右 32rpx, 下 16rpx

### 区块E — 干预方案卡片 (HERO)

- **职责**: 承载 AI 生成的四段式应急方案 — 这是用户来此页面的唯一目的
- **streaming 态**:
  - 卡片完整出现（标题 + 四段标题 + accent bars 始终可见）
  - 未开始的段显示浅色占位文字 "（待生成）"
  - 当前活跃段: 打字机光标 + 逐字浮现
  - 已完成的段: 右上角显示 tertiary 色 ✓
- **completed 态**:
  - 全部内容展示, 各段独立滚动区域
- **卡片外壳**: `surface` 背景, 16rpx 圆角, `diffuse shadow`, 32rpx 内边距, 左右 32rpx margin
- **四段式规范**:
  | 段名 | 左侧 accent bar | 标题色 | 正文规格 |
  |------|----------------|--------|---------|
  | 即时安全干预 | `tertiary` 4rpx | `tertiary` | body-md, 1.8 line-height |
  | 情绪安抚话术 | `primary` 4rpx | `primary` | italic + 引用块样式 |
  | 后续观察指标 | `secondary` 4rpx | `secondary` | body-md, bullet list |
  | 就医判断标准 | `error` 或 `secondary` 4rpx | `error` 或 `secondary` | body-md, 仅需就医时红色 |
- **安抚话术特殊处理**: 第一句作为引用块 (`surface-variant` 背景 + 4rpx `primary` 左竖条, italic), 后续句子普通列表
- **段间距**: 32rpx (completed 态), 24rpx (streaming 态)
- **底部信息栏**: ghost border 分割线 + 案例引用 pill (`tertiary-container` 背景, 如 "基于 4 个相似案例") + 置信度徽章
- **三态**: 
  - Loading (streaming): 标题 + 结构可见, 内容逐字填充
  - Empty: 不适用 — streaming 阶段必有内容
  - Error (stream_failed): 不适用 — streaming 失败走 error 状态页

### 区块F — 置信度徽章

- **三档**:
  | 档位 | 条件 | 背景 | 文字色 | 文案 |
  |------|------|------|--------|------|
  | 高可信 | `crisisLevel === 'mild'` 或 score ≥ 0.85 | `tertiary` | `on-tertiary` | 高可信 ● |
  | 中可信 | `crisisLevel === 'moderate'` 或 0.70-0.84 | `primary-container` | `on-primary-container` | 中可信 ● |
  | 低可信/需复核 | `crisisLevel === 'severe'` 或 < 0.70 | `surface-variant` | `error` | 需人工复核 ● |
- **形状**: pill, 8rpx radius, 8rpx × 12rpx padding
- **动画**: completed 时 `opacity 0→1 + translateY(4px)→0`, 300ms ease-out
- **关联行为**: 低可信时 `ticketGuide.show` 自动为 true, 人工兜底条滑入

### 区块G — 参考案例

- **职责**: 提供方案的可溯源性 — "这个建议是有真实案例支撑的"
- **条件渲染**: `referencedCases.length > 0`
- **形态**: 可折叠卡片组
  - 折叠态: "参考案例 (N)" + "▼ 展开", `surface` 背景
  - 展开态: 逐条展示, 每条含案例标题 + 摘要文本
- **交互**: 点击案例跳转 `cases/detail`
- **边距**: 左右 32rpx, 上下 16rpx

### 区块H — 操作区

- **completed 态**:
  - 主按钮: "开始新咨询", `primary` 背景, 全宽 96rpx 高 → `startNewConsult()`
  - 次要链接: "联系人工专家", `secondary` 色文字, 居中, 80rpx 高 → `goToTicket()`
- **streaming 态**: 按钮禁用, 显示 "生成中…", `surface-dim` 背景
- **边距**: 左右 32rpx, 上 32rpx, 下 16rpx

### 区块I — 人工兜底条 (sticky overlay)

- **条件渲染**: `ticketGuide.show === true`
- **形态**: 全宽 sticky 条, `error` 背景, 56rpx 高, 顶部 16rpx 圆角
- **文字**: "立即联系人工专家", `on-error` 色, 16px semibold
- **动画**: 从底部滑入 `translateY(100%)→0`, 300ms ease-out
- **点击**: 直接调用 `goToTicket()`, 无二次确认（DESIGN.md: "Speed is safety"）

### 区块J — 免责声明

- **职责**: 合规提示, 全状态常驻底部
- **形态**: `surface-dim` 背景条, 24rpx padding, 居中
- **文字**: "基于归档案例的 AI 生成建议，不构成医疗诊断。严重情况请咨询专业医生。"
- **样式**: `footnote` (22rpx), `on-surface-variant` 80% opacity

## 设计决策记录

### 为什么抛弃聊天隐喻？

1. **危机场景 ≠ 社交聊天** — 聊天 UI 传递"轻松交谈"的信号, 与紧张处境冲突
2. **方案是交付物, 不是消息** — 把四段式应急方案塞在气泡里, 严重降级了它的权威感
3. **Chat 暗示多轮对话** — 当前 MVP 是单轮 consult, 不需要聊天历史感
4. **布局稳定 > 动态插入** — 聊天列表的消息插入导致滚动位置跳动, streaming 期间尤其糟糕

### 为什么 streaming 直接显示卡片骨架？

当前实现先显示裸文本气泡, 检测到结构化数据后切换为卡片 — 这一跳破坏了阅读连续性。方案卡片骨架从第一帧就告诉用户:"你的结构化方案正在组装", 视觉预期一致。

## 平台适配检查清单

| # | 检查项 | 通过？ |
|---|--------|-------|
| 1 | 触控热区 ≥ 44pt (按钮 ≥ 88rpx) | ✅ |
| 2 | 拇指热区内无破坏性操作 | ✅ (completed 态主按钮在底部, 是建设性操作) |
| 3 | safe-area-inset-bottom 已预留 | ✅ |
| M1 | 所有尺寸以 750rpx 基准标注 | ✅ |
| M2 | 胶囊按钮区域已预留且标注为"动态获取" | ✅ |
| M3 | 原生 TabBar 入口数 | N/A (非 TabBar 页面, 从 Tab 进入) |
| M4 | 字体层级用语义标注 | ✅ |
| M5 | 内容区高度已扣除导航栏 + 安全区 | ✅ |

## 文件拆分方案

当前 440 行 `index.tsx` 将拆分为:

```
consult/pages/
├── index.tsx          ← 主页面 (idle / submitting / streaming / completed / error)
├── select.tsx         ← 选择页面 (selecting_behavior, 独立页面)
└── components/
    ├── IdleEntry.tsx       ← idle 入口区 (区块B)
    ├── SubmittingGlow.tsx  ← submitting 暖光加载 (区块C)
    ├── UserQuerySummary.tsx← 用户查询摘要 (区块D)
    ├── PlanCard.tsx        ← 干预方案卡片 (区块E, 含 streaming/completed 两态)
    ├── ConfidenceBadge.tsx ← 置信度徽章 (区块F)
    ├── ReferenceCases.tsx  ← 参考案例 (区块G)
    ├── EscalationBar.tsx   ← 人工兜底条 (区块I)
    └── DisclaimerBar.tsx   ← 免责声明 (区块J)
```

每个组件 ≤ 200 行, 纯 Props 驱动, 不直接调用 Hook。

## 和现有实现的差异

| 维度 | 旧实现 | 新设计 |
|------|--------|--------|
| 核心隐喻 | 聊天对话 | **应急方案仪表盘** |
| idle | emoji 🔥 + 标题 + 按钮 | 抽象篝火几何图形 + CTA |
| submitting | 灰色骨架屏闪烁矩形 ×3 | **暖光呼吸动画 + 进度点** |
| streaming 过渡 | 裸文本气泡 → 卡片（布局跳变） | **卡片骨架从第一帧就出现** |
| 方案卡片 | emoji 图标 (🛡️💬👁️🏥) | 抽象 accent bar + 标题（无 emoji） |
| 安抚话术 | 普通引用块 | italic + surface-variant 专属样式 |
| 参考案例 | 始终展开 | 默认折叠, 点击展开 |
| 置信度 | 仅文字 | 三档色 pill 徽章 |

## 和选择页的导航关系

```
Tab "应急咨询"
    │
    ▼
idle (本页 index.tsx)
    │ 点击 "开始咨询"
    ▼
selecting_behavior (select.tsx)
    │ 提交 → submitting (本页)
    │ 取消 → idle (本页)
    ▼
submitting → streaming → completed (本页)
    │
    ├── startNewConsult() → selecting_behavior (select.tsx)
    ├── goToTicket() → tickets/detail (工单详情)
    └── goBackToSelecting() → selecting_behavior (select.tsx)
```
