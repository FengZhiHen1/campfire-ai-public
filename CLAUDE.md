# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## CSS / SCSS 编写规范（mini-program）

### 设计令牌
- 所有颜色、间距、圆角、阴影、字号优先使用 `apps/mini-program/src/views/shared/styles/_tokens.scss` 中的 `$cf-*` 变量或 `@include cf-*` mixins。
- 新增颜色值必须先进入 `_tokens.scss`，禁止在业务样式中写死 `#hex` / `rgb` / `rgba`（除 `tokens` 文件与 `h5-simulator.scss` 外）。
- 常用 mixins：
  - `@include cf-page-shell` — 页面外壳
  - `@include cf-card` — 标准卡片
  - `@include cf-btn-reset` — 清除 Taro button 默认边框
  - `@include cf-shadow-diffuse` / `@include cf-shadow-deep`

### 动画
- 动画 keyframes 统一放在 `app.scss`，以 `cf-*` 为前缀。
- 业务文件禁止自定义局部 keyframes；如需新动画，先在 `app.scss` 注册。

### 命名
- 页面/组件级样式使用 BEM：`.block__element--modifier`。
- 文件名与顶级 class 保持一致。

### 工程化
- 提交前运行 `pnpm lint:style`（当前为 warning 级别，后续将提升为 error）。
- 新增 `.scss` 文件必须 `@use '../../shared/styles/tokens' as *;`（路径按实际层级调整）。

### 文件组织
- 避免单文件超过 600 行；可按结构拆分为 `_partial.scss` 并通过 `@use './partial';` 聚合。
- H5 模拟器样式统一放在 `src/h5-simulator.scss`，不混入 `app.scss`。