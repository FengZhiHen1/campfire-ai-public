# 智能咨询 — 选择页面 功能块骨架

## 元信息
- 目标平台: miniprogram (750rpx 基准)
- 关联页面: 咨询首页 (idle) → 选择页 → 结果页 (streaming/completed)
- 设计作用域: 特定功能页（替换现有 `selecting_behavior` 底部弹窗）
- Logic-ID 清单:
  | ID | 类型 | 用途 |
  |----|------|------|
  | `behaviorTypeSelection` | `BehaviorTypeCategory[]` | 已选行为类型列表 |
  | `behaviorDescription` | `string` | 行为描述文本 |
  | `emotionLevel` | `'轻' \| '中' \| '重'` | 情绪等级 |
  | `isInputValid` | `boolean` | 提交按钮是否可点击 |
  | `selectedProfileId` | `string \| undefined` | 关联档案 ID |
  | `setBehaviorTypes` | `(types: BehaviorTypeCategory[]) => void` | 更新行为类型选择 |
  | `setBehaviorDescription` | `(desc: string) => void` | 更新描述文本 |
  | `setEmotionLevel` | `(level: EmotionLevel) => void` | 设置情绪等级 |
  | `setSelectedProfile` | `(id: string \| undefined) => void` | 设置关联档案 |
  | `submitConsult` | `() => Promise<void>` | 提交咨询 |
  | `cancelSelection` | `() => void` | 返回 idle |
- 前端包: `apps/mini-program/src`
- 编码规范: `frontend.md` (React Code Quality Directives)

## 平台布局

### miniprogram (750rpx 基准)

```
┌──────────────────────────────────┐ ← 750rpx 全宽
│ [原生导航栏]                      │ ← 动态高度, 胶囊按钮避让
│ ← 返回       应急咨询              │
├──────────────────────────────────┤
│                                  │
│ [区块A — 页头]                    │
│ LOGIC: (纯展示, 无状态绑定)        │
│ 标题: "描述当前行为"               │
│ 副标题: 16px 辅助文字              │
│                                  │
├──────────────────────────────────┤
│ [区块B — 关联档案] (条件渲染)     │
│ LOGIC: selectedProfileId,        │
│        setSelectedProfile         │
│ 横向滑动芯片列表                  │
│ "不关联" + profile nicknames     │
│                                  │
├──────────────────────────────────┤
│ [区块C — 行为类型列表]            │
│ LOGIC: behaviorTypeSelection,    │
│        setBehaviorTypes           │
│ ┌────────────────────────────┐  │
│ │ [抽象图标]  自伤行为     ●  │  │ ← 选中: primary-container 背景
│ │             咬手、撞头…      │  │        右侧填充圆点
│ ├────────────────────────────┤  │
│ │ [抽象图标]  攻击行为     ○  │  │ ← 未选中: surface 背景
│ │             打人、摔东西…    │  │        右侧空心圆环
│ ├────────────────────────────┤  │
│ │            ...               │  │
│ └────────────────────────────┘  │
│                                  │
├──────────────────────────────────┤
│ [区块D — 情绪等级]                │
│ LOGIC: emotionLevel,             │
│        setEmotionLevel            │
│ ┌──────┬──────┬──────┐          │
│ │ 轻度 │ 中度 │ 重度 │          │ ← 三段式分段选择器
│ └──────┴──────┴──────┘          │
│                                  │
├──────────────────────────────────┤
│ [区块E — 补充描述]                │
│ LOGIC: behaviorDescription,      │
│        setBehaviorDescription     │
│ ┌────────────────────────────┐  │
│ │ 例如: 孩子在商场突然蹲下尖叫…│  │ ← 多行文本域
│ │                            │  │
│ └────────────────────────────┘  │
│                                  │
├──────────────────────────────────┤
│ [区块F — 底部操作栏]              │
│ LOGIC: isInputValid,             │
│        submitConsult,            │
│        cancelSelection            │
│ ┌────────────────────────────┐  │
│ │      获取应急建议           │  │ ← 主按钮 primary 全宽 96rpx 高
│ └────────────────────────────┘  │
│        直接描述, 不选择分类       │  ← 次要链接, secondary 色
│                                  │
├──────────────────────────────────┤
│ [safe-area-inset-bottom]         │ ← 系统安全区
└──────────────────────────────────┘
```

- **导航**: 原生导航栏, 标题 "应急咨询", 左侧返回按钮 → `cancelSelection()`
- **手势**: 无特殊手势需求, 标准垂直滚动
- **安全区**: 底部按钮需 `env(safe-area-inset-bottom)` padding
- **键盘**: 文本域聚焦时页面自然上推（小程序原生行为）

## 功能块详述

### 区块A — 页头

- **职责**: 告知用户当前步骤、引导决策
- **标题**: "描述当前行为" (`headline-sm`, on-background)
- **副标题**: "选择行为类型，以便匹配最相似的案例" (`body-sm`, on-surface-variant)
- **布局**: 左对齐, 标题与副标题间距 8rpx
- **三态**: 无需 (静态文案)
- **边距**: 左右 32rpx, 上 32rpx, 下 24rpx

### 区块B — 关联档案 (条件渲染)

- **职责**: 可选地关联已有档案, 让 AI 参考孩子的历史行为模式
- **显示条件**: `profiles.length > 0`
- **形态**: 横向滑动芯片组, "不关联" 默认为选中态
- **选中态**: `primary-container` 填充, `on-primary-container` 文字
- **未选中态**: `surface-variant` 背景, `on-surface-variant` 文字
- **边距**: 左右 32rpx, 下 32rpx
- **数据注入**: `useProfileStore` → `list`, `useProfile` → `fetchProfiles`

### 区块C — 行为类型列表

- **职责**: 核心决策区 — 让用户选择 1 个或多个行为类型
- **列表项结构** (每条高度 ≥ 88rpx 触控热区):
  - 左侧: 抽象线条图标 (32rpx × 32rpx, secondary 色)
  - 中间: 标题 (body-md, on-background) + 描述 (footnote, on-surface-variant)
  - 右侧: 选中指示器 — 选中为填充圆 (primary), 未选中为空心圆环 (outline-variant)
- **选中态**: `primary-container` 背景 (`#FEF3C7`), 卡片圆角 16rpx, 微内边距
- **未选中态**: `surface` 背景, 无额外样式
- **选项间分隔**: 无可见分隔线 — 用背景色块区分, 间距 8rpx
- **交互**: 点击 toggle 选中/取消, 支持多选 (≥1)
- **7 个选项**:
  | value | 中文名 | 描述 |
  |-------|--------|------|
  | SELF_INJURY | 自伤行为 | 咬手、撞头、抓挠自己等 |
  | AGGRESSION | 攻击行为 | 打人、摔东西、破坏物品等 |
  | ELOPEMENT | 出走/逃跑 | 试图离开安全区域、走失等 |
  | MEDICATION | 用药相关 | 拒绝服药、误服、过量等 |
  | EMOTIONAL_MELTDOWN | 情绪崩溃 | 大哭、尖叫、无法安抚等 |
  | STEREOTYPY | 刻板行为 | 重复动作、摇晃、排列物品等 |
  | OTHER | 其他 | 以上都不是，请在下方描述 |
- **空态**: 无 — 列表始终完整展示
- **边距**: 左右 32rpx, 下 32rpx

### 区块D — 情绪等级

- **职责**: 快速标注当前情绪的严重程度
- **形态**: 三段式分段按钮 (Segmented Control), 等宽分布
- **选中态**: `primary` 背景, `on-primary` 文字
- **未选中态**: `surface-variant` 背景, `on-surface-variant` 文字
- **选项**: 轻度 / 中度 / 重度
- **高度**: 80rpx (触控热区 ≥ 88rpx 等效)
- **边距**: 左右 32rpx, 下 32rpx

### 区块E — 补充描述

- **职责**: 让用户用自然语言描述当前场景
- **形态**: 多行文本域, `surface-variant` 背景, 圆角 16rpx
- **placeholder**: "例如：孩子在商场突然捂住耳朵蹲下尖叫，持续了约5分钟…"
- **最小高度**: 200rpx, 最大高度: 400rpx
- **字数限制**: 2000 字
- **内边距**: 32rpx
- **边距**: 左右 32rpx, 下 32rpx

### 区块F — 底部操作栏

- **职责**: 提交咨询 + 退出入口
- **主按钮**:
  - 文字: "获取应急建议"
  - 样式: `primary` 背景, `on-primary` 文字, 圆角 16rpx, 高度 96rpx, 全宽
  - 禁用态 (`isInputValid === false`): `surface-dim` 背景, `on-surface-variant` 文字
  - 点击: `submitConsult()`
- **次要链接**:
  - 文字: "直接描述，不选择分类"
  - 样式: `secondary` 色, 无背景, 居中, 高度 80rpx
  - 点击: 自动勾选 OTHER → `submitConsult()`
  - 含义: 跳过行为分类选择，直接以文本描述提交
- **间距**: 主按钮与次要链接间距 16rpx
- **底部**: `padding-bottom: env(safe-area-inset-bottom)`
- **边距**: 左右 32rpx

## 平台适配检查清单

| # | 检查项 | 通过？ |
|---|--------|-------|
| 1 | 触控热区 ≥ 44pt (列表项 ≥ 88rpx) | ✅ |
| 2 | 拇指热区内无破坏性操作 | ✅ (主操作在底部, 是确认而非破坏) |
| 3 | safe-area-inset-bottom 已预留 | ✅ 区块F |
| 4 | 底部固定元素与系统导航不重叠 | ✅ (本页面为原生导航栏, 非底部 TabBar 页面) |
| M1 | 所有尺寸以 750rpx 基准标注 | ✅ |
| M2 | 胶囊按钮区域已预留且标注为"动态获取" | ✅ (原生导航栏自动处理) |
| M3 | 原生 TabBar 入口数 ≤ 5 | N/A (非 TabBar 页面) |
| M4 | 字体层级用语义标注而非 rpx 值 | ✅ |
| M5 | 内容区高度已扣除导航栏 + 安全区 | ✅ |

## 和现有实现的差异

| 维度 | 旧实现 (bottom sheet) | 新设计 (full page) |
|------|----------------------|-------------------|
| 页面形态 | 底部弹窗, 600rpx 高 | 独立全屏页面 |
| 图标 | 🩹👊🏃💊💢🔄❓ emoji | 抽象线条图标 (SVG/iconfont) |
| 选项布局 | 2 列网格, 方形卡片 | 纵向列表, 横条卡片 |
| 选中指示 | 右上角小勾号 | 整卡变色 + 右侧填充圆点 |
| 情绪选择 | 等宽按钮 (与旧版同) | 三段式分段控件 (视觉升级) |
| 返回方式 | 点击遮罩或取消 | 原生导航栏返回按钮 |
| 档案选择 | 内联 wrap 按钮 | 横向滑动芯片 |
| 信息层级 | 7 层内容堆叠在弹窗 | 6 个区块依次排列, 清晰分层 |
