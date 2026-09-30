# 篝火智答（Campfire-AI）Design System

> Base: warm-editorial（`vendor/open-design/design-systems/warm-editorial`）
> 定型于 2026-10-06，经用户确认。token 与组件以 `tokens.css` / `components.html` 为准。

## 调性与方向

一本安静的照护手册，遇险时是稳定的火光。暖米纸底、宋体标题承载"读物的温度"，火焰橙是唯一的篝火记忆点——印刷级饱和度，鲜艳但沉着。面向监护人的手机 H5：日常咨询要"可以慢慢读"，应急路径要"一眼找到该做的"。

## Overrides（相对 base 的改造）

- 品牌色：火焰橙 `#C2410C`（用户定型）——篝火意象；应急入口、主 CTA、链接
- 字体栈：标题 = 思源宋体（Noto Serif SC）weight 500 webfont + 系统宋体回退；正文 = 系统无衬线栈（PingFang SC / 苹方 / 雅黑），白话可读性优先，零加载成本。Google Fonts 国内加载可靠性待实现期验证（可换镜像或自托管）
- `--meta`：焦糖棕 → 石棕灰 `#57534E`（原值与 accent 同色，火焰橙定型后冲突）
- 语义色：压饱和、偏暖（`#3F7A44 / #B45309 / #B3372F`）；新增应急三值 token（stable / unruled / high）
- 密度：标准——手机留白呼吸但不空洞；应急页页面级适度紧凑，不动体系 token
- 圆角：小圆角语言（10–24px），继承 base——温暖但不幼儿园
- 明暗：仅亮色主题（一期；暗色模式按既有定调待视觉契约包含时再做）

## 布局与 posture 要点

- **仅适配手机端（2026-10-06 用户定调）**：所有页面只按手机单列设计；平板与 PC 端不做多栏适配，直接渲染为居中的手机宽度容器（手机蒙版）——内容容器 max-width 480px 居中，容器外以 `--surface-warm` 暖沙色为蒙版底、容器本身带 `--elev-ring` 边界示意手机边界。禁止宽屏多栏布局、桌面 hover 信息分层等桌面专属设计
- 单屏 accent 可见使用 ≤2 处（craft 红线）：典型组合 = 一个主 CTA + 一处强调文字
- 卡片三层语言：`panel`（抬升面板）> `tile`（平铺卡）> `mini-card`（warm 内衬）；阴影只给 panel，tile 用边框
- 状态确认 150ms、进入 240ms（移动端取短值）；唯一循环动效是篝火呼吸点（2s，respect `prefers-reduced-motion`）
- 移动端触控热区 ≥44×44px；正文 ≥16px；安全区预留 `safe-area-inset-*`
- 汉字排印：标题宋体 500、不加粗；全大写仅用于 eyebrow 且带 0.06em+ 字距

## 反模式（项目专属）

- emoji 作 UI 图标；荧光橙 / 橙色渐变横幅；紫色渐变 + 白底；AI 默认蓝紫
- 等宽三列卡片、所有间距相等的模板布局
- 医疗风险三值用裸色块表达（必须走 `.status.stable/.unruled/.high` 语义徽章）
- 思考过程（reasoning）渲染为正文或当作依据引用（技术设计已定）

## Craft 强制清单

`color, typography, anti-ai-slop, state-coverage, form-validation, animation-discipline, accessibility-baseline`

（页面设计与实现验收必须加载 `vendor/open-design/craft/` 对应文件；表单页与有数据区块的页面必配 form-validation / state-coverage）

## 下游消费指引

- 页面设计与实现前必读：本文件 + `tokens.css` + `components.html`
- token 契约：`tokens.css`（实现代码直接引用其中 CSS 变量）
- 组件形状：`components.html`（匹配而非发明；新组件走契约修订，标 `@source: project`）
- 页面设计文档：`docs/design/pages/`（逐页产出，经确认后为实现输入）
