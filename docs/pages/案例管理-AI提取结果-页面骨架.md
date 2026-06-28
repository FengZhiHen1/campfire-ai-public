# 案例管理 — AI提取结果 内容骨架

> 生成日期：2026-06-28
> 源文档：`docs/功能设计/功能模块全拆解.md#04-真实案例库管理`（CASE-04）
> 目标平台：miniprogram（触控）
> 数据来源：`useExtractionResult()` Hook

---

## 元信息

| 属性 | 值 |
|------|-----|
| 目标平台 | miniprogram |
| 视图名称 | AI提取结果（cases-extraction-result） |
| 所属页面 | 案例管理（cases） |
| 页面职责 | 展示 AI 从叙事中自动提取的干预案例卡片，支持逐张审核编辑、保存、全部提交 |
| 入口来源 | 案例详情页"提取卡片" |

### Logic-ID 清单

| ID | 类型 | 用途 |
|----|------|------|
| `cards` | `ExtractedCard[]` | AI 提取的卡片列表 |
| `activeTab` | `number` | 当前编辑的卡片索引 |
| `editing` | `ExtractedCard \| null` | 当前编辑中的卡片数据 |
| `loading` | `boolean` | 页面初始加载 |
| `extracting` | `boolean` | AI 提取进行中 |
| `extractFailed` | `boolean` | 提取失败 |
| `isSaving` | `boolean` | 保存单张卡片中 |
| `isSubmittingAll` | `boolean` | 提交全部审核中 |

---

## 内容区块

### 状态路由

| 状态 | 展示 |
|------|------|
| `loading` | 骨架占位 + "正在加载..." |
| `extracting` | 提取中动画 + "AI 正在分析叙事内容..." + 预计时间提示 |
| `extractFailed` | "提取失败" + AI 处理异常说明 + "重试"按钮 |
| `cards.length === 0` | AI 未能识别干预场景提示 |
| Normal | Tab 栏 + 编辑表单 + 底部操作 |

### 区块A — Tab 栏
- **职责**: 在多张提取的卡片之间切换编辑
- **内容**: 横向滚动 Tab——每卡片以标题（或"卡片 N"）为标签
- **交互**: 点击切换 `activeTab`
- **data-testid**: `er-tabs`

### 区块B — 编辑表单
- **基础信息**: 卡片标题（文本）、适用场景（多行文本）
- **分类标签**: 行为类型（按钮组选择）、严重程度、场景、家属端大类
- **四段式内容**: 即时安全干预/情绪安抚话术/观察指标/就医判断——每段有 AI 提取的预填内容，用户可修改。AI 推断的字段标注"推断"标记 + 推断原因
- **质量标注**: 循证等级（只读）、禁忌与注意（多行文本）、不适用人群/场景（多行文本）
- **AI推断说明面板**: 如有推断字段，展示推断理由汇总
- **data-testid**: `er-form`, `er-quartet-card`, `er-field__inferred-badge`

### 区块C — 底部操作
- **职责**: 保存当前卡片 + 提交全部审核
- **内容**: "保存当前卡片"按钮 + "提交全部审核"按钮
- **交互**: 保存 → 存为草稿；提交 → 全部卡片进入审核队列
- **data-testid**: `er-footer`, `er-footer__save-btn`, `er-footer__submit-btn`

### data-testid 节点清单

```
er-tabs, er-tabs__btn--active
er-form, er-group, er-field, er-picker-btn--active
er-quartet-card--{accent}, er-field__inferred-badge
er-inferred-panel
er-footer, er-footer__save-btn, er-footer__submit-btn
```
