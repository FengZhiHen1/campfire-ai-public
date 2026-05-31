# 事件记录弹窗 — 组件骨架

## 元信息
- 目标平台: miniprogram (750rpx 基准)
- 组件类型: Bottom Sheet (底部弹出)
- 触发场景: 档案首页 `profiles/index.tsx` 点击 "+" 按钮
- 关联组件: `QuickRecordSheet.tsx` (待替换)
- Logic-ID 清单:

| ID | 类型 | 用途 |
|----|------|------|
| `form.behaviorType` | `string` | 行为类型选择 |
| `form.severity` | `string` | 严重程度 |
| `form.setting` | `string` | 发生场景 (可选) |
| `form.trigger` | `string` | 触发因素 |
| `form.manifest` | `string` | 具体表现 |
| `form.intervention` | `string` | 干预措施 (可选) |
| `form.result` | `string` | 干预结果 (可选) |
| `isSubmitting` | `boolean` | 提交中状态 |
| `setField` | `(field, value) => void` | 更新表单字段 |
| `submit` | `() => Promise<boolean>` | 提交表单 |
| `onClose` | `() => void` | 关闭弹窗 |

- 关联 Hook: `useQuickRecord` (`logics/profiles/hooks/useQuickRecord.ts`)
- 数据常量: `BEHAVIOR_OPTIONS`, `SEVERITY_OPTIONS`, `SETTING_OPTIONS` (`logics/profiles/constants.ts`)
- 关联 DESIGN.md: `docs/DESIGN.md` (Campfire-AI 主设计系统)

## 平台布局

### miniprogram (750rpx 基准)

```
┌──────────────────────────────────┐
│ [遮罩层]                          │ ← on-background 60% opacity
│                                  │   tap → onClose()
│                                  │
│ ┌──────────────────────────────┐ │
│ │         ━━━ (拖拽手柄)        │ │ ← 48rpx × 8rpx, 32rpx 高区域
│ │                              │ │   surface-variant 色
│ │  记录行为事件                 │ │ ← headline-sm, on-background
│ │  完整记录有助于AI精准匹配案例  │ │ ← body-sm, on-surface-variant
│ │                              │ │
│ │ ─── 事件分类 ───              │ │ ← section divider (background 色块)
│ │                              │ │
│ │  行为类型 *                   │ │ ← label-sm, on-surface-variant, 必填* = error 色
│ │  ┌────────┐┌────────┐┌──────┐│ │
│ │  │ 自伤   ││ 攻击   ││ 刻板 ││ │ ← 2×3 chip 网格, 间距 16rpx
│ │  │ 行为   ││ 行为   ││ 行为 ││ │   未选中: surface-variant, on-surface-variant
│ │  └────────┘└────────┘└──────┘│ │   选中: primary-container, on-primary-container
│ │  ┌────────┐┌────────┐┌──────┐│ │   高 72rpx, 圆角 16rpx
│ │  │ 情绪   ││ 社交   ││ 多动 ││ │
│ │  │ 崩溃   ││ 退缩   ││      ││ │
│ │  └────────┘└────────┘└──────┘│ │
│ │                              │ │
│ │  严重程度 *                   │ │
│ │  ┌────────┬────────┬────────┐│ │ ← 3 段分段控件
│ │  │  轻度  │  中度  │  重度  ││ │   选中: primary 背景
│ │  └────────┴────────┴────────┘│ │   未选中: surface-variant 背景
│ │                              │ │   高 80rpx, 圆角 16rpx
│ │                              │ │
│ │ ─── 发生场景 ───              │ │
│ │                              │ │
│ │  发生场景（可选）              │ │
│ │  ┌────┐ ┌────┐ ┌────┐ ┌────┐│ │ ← 4 chip 横排
│ │  │家庭│ │学校│ │公共│ │机构││ │   等宽 flex, 间距 16rpx
│ │  └────┘ └────┘ └────┘ └────┘│ │   高 64rpx, 圆角 16rpx
│ │                              │ │
│ │ ─── 事件描述 ───              │ │
│ │                              │ │
│ │  触发因素 *                   │ │
│ │  ┌──────────────────────────┐│ │ ← 单行 input
│ │  │ 如：在超市遇到噪音刺激…    ││ │   surface-variant 背景
│ │  └──────────────────────────┘│ │   h: 80rpx, 圆角 16rpx, 内边距 24rpx
│ │                              │ │
│ │  具体表现 *                   │ │
│ │  ┌──────────────────────────┐│ │ ← 多行 textarea
│ │  │                          ││ │   min-h: 160rpx
│ │  │ 如：突然捂耳蹲下，         ││ │
│ │  │ 持续约3分钟…              ││ │
│ │  └──────────────────────────┘│ │
│ │                              │ │
│ │ ─── 干预记录（可选）  ▶ ───   │ │ ← 默认折叠, tap 展开
│ │                              │ │   展开后旋转为 ▼
│ │  [展开后:]                    │ │
│ │  尝试的干预措施                │ │
│ │  ┌──────────────────────────┐│ │
│ │  │ 如：带离现场，使用降噪耳机…││ │
│ │  └──────────────────────────┘│ │
│ │                              │ │
│ │  干预结果                     │ │
│ │  ┌──────────────────────────┐│ │
│ │  │ 如：情绪逐渐平复…          ││ │
│ │  └──────────────────────────┘│ │
│ │                              │ │
│ │  ┌──────────────────────────┐│ │
│ │  │        保存记录           ││ │ ← primary 全宽按钮, sticky 底部
│ │  └──────────────────────────┘│ │   高 96rpx, 圆角 16rpx
│ │                              │ │   禁用态: surface-dim 背景
│ │                              │ │   提交中: "保存中…" + 不可点击
│ │                              │ │
│ │  [safe-area-inset-bottom]     │ │
│ └──────────────────────────────┘ │
└──────────────────────────────────┘
```

- **弹窗外壳**: `surface` 背景, 顶部 32rpx 圆角, 最大高度 85vh, 超出纵向滚动
- **遮罩**: `on-background` 60% opacity, tap → `onClose()`
- **入场动画**: 从底部滑入 `translateY(100%)→0`, 300ms ease-out; 遮罩 `opacity 0→1` 200ms
- **手柄**: 48rpx 宽 × 8rpx 高, `surface-variant` 色, 圆角, 水平居中

## 功能块详述

### 区块A — 拖拽手柄 + 标题

- **职责**: 底部弹窗的常规 affordance + 操作引导
- **手柄**: 48rpx × 8rpx, `surface-variant` 背景, 圆角 8rpx, 水平居中, 上方 16rpx 间距
- **标题**: "记录行为事件", `headline-sm`, `on-background`, 居中
- **副标题**: "完整记录有助于 AI 精准匹配案例", `body-sm`, `on-surface-variant`, 居中, 上方 8rpx
- **下间距**: 32rpx

### 区块B — 事件分类 (Section 1)

- **职责**: 必填的核心分类 — 选行为类型 + 定严重程度
- **分组标题**: 无独立标题 — 用 `background` 色块 16rpx 高作为视觉分隔。或用 "事件分类" label-sm 标注
- **行为类型 chip 网格** (2×3):
  - 6 个 chip: 自伤行为 / 攻击行为 / 刻板行为 / 情绪崩溃 / 社交退缩 / 多动
  - Chip 规格: 高度 72rpx, 16rpx 圆角, 12rpx 最小内边距
  - 未选中: `surface-variant` 背景, `on-surface-variant` 文字, body-sm
  - 选中: `primary-container` 背景, `on-primary-container` 文字
  - 网格间距: 16rpx
  - 选中逻辑: 单选 (行为类型互斥)
- **严重程度分段控件**:
  - 3 段: 轻度 / 中度 / 重度
  - 高度 80rpx, 16rpx 圆角, 等宽分布
  - 选中: `primary` 背景, `on-primary` 文字
  - 未选中: `surface-variant` 背景, `on-surface-variant` 文字
  - 选中逻辑: 单选
- **字段标签**: "行为类型 *" 和 "严重程度 *", `label-sm`, `on-surface-variant`, 必填星号 `error` 色
- **间距**: 标签与控件间距 12rpx, 控件组之间 24rpx
- **三态**: 无需 — 控件始终可交互

### 区块C — 发生场景 (Section 2)

- **职责**: 可选的场景标注
- **分组标题**: "发生场景（可选）" 用 section divider 分隔
- **4 个横向 chip**: 家庭 / 学校 / 公共场合 / 机构
- Chip 规格: 等宽 flex, 高度 64rpx, 16rpx 圆角
- 选中/未选中态同区块B
- 选中逻辑: 单选
- **间距**: 下 24rpx

### 区块D — 事件描述 (Section 3)

- **职责**: 核心文本输入 — 触发因素 + 具体表现
- **触发因素**:
  - 单行 Input, `surface-variant` 背景, 16rpx 圆角
  - 高度 80rpx, 内边距 24rpx
  - Placeholder: "如：在超市遇到噪音刺激…"
  - 标签: "触发因素 *"
- **具体表现**:
  - 多行 Textarea, `surface-variant` 背景, 16rpx 圆角
  - 最小高度 160rpx, 内边距 24rpx
  - Placeholder: "如：突然捂耳蹲下，持续约3分钟…"
  - 标签: "具体表现 *"
- **间距**: 标签 12rpx + 控件, 控件间 24rpx

### 区块E — 干预记录 (Section 4, 可折叠)

- **职责**: 可选的干预记录, 默认折叠以节省高度
- **折叠态**: section divider 行, 显示 "干预记录（可选） ▶", 点击展开
- **展开态**: chevron 旋转为 ▼, 展开两个输入框:
  - 干预措施: 单行 Input, "如：带离现场，使用降噪耳机…"
  - 干预结果: 单行 Input, "如：情绪逐渐平复…"
- **展开动画**: `height` + `opacity`, 200ms ease-in-out
- **间距**: 展开后下 24rpx

### 区块F — 提交按钮

- **职责**: 保存记录并关闭弹窗
- **文字**: "保存记录"
- **可用态**: `primary` 背景, `on-primary` 文字, 全宽, 96rpx 高, 16rpx 圆角
- **禁用态** (必填字段未填写): `surface-dim` 背景, `on-surface-variant` 文字
- **提交中** (`isSubmitting`): 按钮文字变为 "保存中…", 不可点击
- **校验规则**: `behaviorType` 非空 && `severity` 非空 && `trigger` 非空 && `manifest` 非空
- **底部安全区**: `padding-bottom: env(safe-area-inset-bottom)`
- **间距**: 上下 32rpx

## 表单校验逻辑

| 字段 | 必填 | 校验规则 |
|------|------|---------|
| behaviorType | ✅ | 非空字符串 (6 选 1) |
| severity | ✅ | 非空字符串 (3 选 1) |
| setting | — | 允许空 |
| trigger | ✅ | 去除首尾空白后非空 |
| manifest | ✅ | 去除首尾空白后非空 |
| intervention | — | 允许空，折叠时不校验 |
| result | — | 允许空，折叠时不校验 |

- 点击 "保存记录" 时校验，不通过则 Toast "请填写必填项"
- 校验逻辑复用现有 `useQuickRecord.submit()` 中的校验

## 和现有实现的差异

| 维度 | 旧实现 | 新设计 |
|------|--------|--------|
| 行为类型 | Picker 下拉 | 2×3 chip 网格, 直接点选 |
| 严重程度 | Picker 下拉 | 3 段分段控件 |
| 发生场景 | Picker 下拉 | 4 chip 横排 |
| 字段分组 | 无, 7 字段平铺 | 4 个 section, 色块分隔 |
| 干预记录 | 始终展示 | 默认折叠, 点击展开 |
| 视觉风格 | 裸 Picker + Input 堆叠 | chip / 分段控件 / 统一圆角 / 色块层级 |
| emoji | 无 (此组件暂无) | 无 — 维持 |
| 表单高度 | ~800rpx, 需大量滚动 | 折叠态 ~700rpx, 展开态 ~900rpx |

## 平台检查清单

| # | 检查项 | 通过？ |
|---|--------|-------|
| 1 | 触控热区 ≥ 44pt (chip ≥ 72rpx) | ✅ |
| 2 | 拇指热区内无破坏性操作 | ✅ (提交按钮在底部) |
| 3 | safe-area-inset-bottom 已预留 | ✅ |
| M1 | 所有尺寸以 750rpx 基准标注 | ✅ |
| M2 | 胶囊按钮区域不涉及 (弹窗覆盖全屏) | ✅ |
| M4 | 字体层级用语义标注 | ✅ |
| M5 | 弹窗最大高度 ≤ 85vh, 超出可滚动 | ✅ |
