# 篝火智答（Campfire-AI）Design System

> Base: warm-editorial（`vendor/open-design/design-systems/warm-editorial`）
> 定型于 2026-10-06，经用户确认。token 与组件以 `tokens.css` / `components.html` 为准。

## 调性与方向

一本安静的照护手册，遇险时是稳定的火光。暖米纸底、宋体标题承载"读物的温度"，火焰橙是唯一的篝火记忆点——印刷级饱和度，鲜艳但沉着。面向监护人的手机 H5：日常咨询要"可以慢慢读"，应急路径要"一眼找到该做的"。

## 品牌图标

- 图标源文件为 [`assets/brand-mark.svg`](assets/brand-mark.svg)：以一大一小两簇火光和收简的书页构成单色标记，使用 `#C2410C` 与透明留白；登录页与首页页头均与「篝火智答」名称搭配。
- 图标保持静态，不加渐变、发光或独立循环动效。与可读名称并列时，图标作为装饰，名称承担可访问的文字标识；首页页头的图标计作一处 accent。
- 缩小使用时保持原始比例和透明留白，不另加轮廓或细线。浏览器标签等极小尺寸仍需在实现期按实际设备复核。

## Overrides（相对 base 的改造）

- 品牌色：火焰橙 `#C2410C`（用户定型）——篝火意象；应急入口、主 CTA、链接
- 字体栈：标题 = 思源宋体（Noto Serif SC）weight 500 webfont + 系统宋体回退；正文 = 系统无衬线栈（PingFang SC / 苹方 / 雅黑），白话可读性优先，零加载成本。Google Fonts 国内加载可靠性待实现期验证（可换镜像或自托管）
- `--meta`：焦糖棕 → 石棕灰 `#57534E`（原值与 accent 同色，火焰橙定型后冲突）
- 语义色：压饱和、偏暖（`#3F7A44 / #B45309 / #B3372F`）；新增应急三值 token（stable / unruled / high）
- 密度：标准——手机留白呼吸但不空洞；应急页页面级适度紧凑，不动体系 token
- 圆角：小圆角语言（10–24px），继承 base——温暖但不幼儿园
- 明暗：仅亮色主题（一期；暗色模式按既有定调待视觉契约包含时再做）

## 布局与 posture 要点

- **仅适配手机端（2026-10-06 用户定调）**：所有页面只按手机单列设计；平板与 PC 端不做多栏适配，直接渲染为居中的手机宽度容器（手机蒙版，token `--phone-shell-max: 480px`）——容器外以 `--surface-warm` 暖沙色为蒙版底、容器本身带 `--elev-ring` 边界示意手机边界。禁止宽屏多栏布局、桌面 hover 信息分层等桌面专属设计
- **手机蒙版 + 宽视口设备外壳（2026-10-02 用户授权定型的规格）**：≥560px 视口下不再只是「居中的窄列」，而是把应用渲染进一台**手机外壳**里，使 PC/平板上的观感是「在一台手机里运行的应用」（用户原话：「需要做一个模拟手机外壳，模拟手机应用，而不是单纯减少宽度」）。几何：屏幕内容区 `390×844`、bezel `12px`（画在 390×844 之外，`box-sizing: content-box`）、圆角 `56px`、bezel 取暖色系深色（从 `--fg` 派生的 `color-mix`，**不用冷黑**——本系统是暖米纸 + 火焰橙，冷黑会与调性冲突）。结构与机制：

  - 三层结构 `.device-stage`（居中舞台）> `.device`（外壳本体）> `.device-screen`（屏幕区，外壳内唯一滚动容器）；
  - `.device` 带 `transform: translateZ(0)` 是**承重属性**：它让外壳成为其后代 `position: fixed` 元素的包含块，因此契约里的 `.tab-bar` 与 `.confirm-sheet` 无需从 `fixed` 改成 `absolute` 就会收进外壳（底边贴外壳内容盒底边、宽度为屏幕宽而不是视口宽）。移除它两者立刻逃到视口；
  - **外壳内不得用视口单位作尺寸基准**：`100svh` 解析为视口高而不是外壳高，会把 844px 的屏幕撑出无谓滚动；外壳内改用相对屏幕区的 `%`；
  - **<560px 行为不变**：三层包裹在该断点下退化为 `display: contents`（不生成盒子），真实手机仍是满幅、无 bezel 与投影；
  - 阈值取 560 而非 900：外壳外宽 414px 加舞台内边距后约 462px，560 给两侧留出呼吸；取 560 而非更高也让平板竖屏（768）获得同一观感。几何字面量是实现级派生值，集中在 `apps/web/src/shared/styles/global.css` 的设备外壳段落，不进 `tokens.css`。
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
- 组件总览：base 继承（按钮/输入/卡片/徽章/链接/排版/布局）+ 项目组件（flame-dot、tab-bar、subpage-head、page-head、check-row、choice、progress、tag、bubble-user、msg-doc、run-status、skeleton、empty-state、error-card、question-card、action-card、citation-block、reasoning-row、tool-row、candidate-toast、confirm-sheet、list-row、group-collapse）——三态基元（skeleton / empty-state / error-card）是各页 loading/empty/error 形态的唯一来源，禁止页内自造
