/**
 * 模块: shared/ui/BrandMark
 * 职责: 品牌图标的单色内联实现——与 docs/design/assets/brand-mark.svg 同形，颜色走 currentColor
 * 数据来源:
 *   - docs/design/DESIGN.md: MUST — 品牌图标节（单色标记、保持静态、名称承担可访问文字标识）
 * 边界:
 *   - 依赖: 无
 *   - 被依赖: app 的登录页与首页页头
 * 禁止行为:
 *   - 禁止给图标加渐变、发光或独立循环动效（DESIGN.md 品牌图标节）
 *   - 禁止把图标当作唯一的可访问标识（它 aria-hidden，名称由相邻标题承担）
 *
 * 为什么内联而不是引用 svg 文件：设计源文件用写死的 #C2410C 填充，直接内联会绕开 token 层；
 * 这里改用 currentColor，颜色由使用处的 token 决定（DESIGN.md：图标计作一处 accent）。
 * 几何路径与设计源文件逐字相同，不重绘。
 */

/** 品牌图标 props。 */
export interface BrandMarkProps {
  /** 图标边长（CSS 长度，如 '1.2em'）；默认 1.2em 与登录页品牌区一致。 */
  size?: string;
}

/**
 * 渲染品牌图标。
 *
 * 前置: 无
 * 后置: 输出一个 aria-hidden 的单色 SVG，着色取 currentColor
 * 异常: 无
 */
export function BrandMark({ size = '1.2em' }: BrandMarkProps) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 128 128"
      width={size}
      height={size}
      fill="currentColor"
      style={{ flex: 'none' }}
    >
      <path d="M69 9c11 9 19 22 19 35 0 13-7 22-19 31-10 8-15 15-14 24 1 5 4 9 9 14-8-6-15-8-23-12-12-6-17-15-15-27 2-13 11-21 22-30C64 31 73 23 69 9Z" />
      <path d="M89 61c2 8 10 15 13 23 6 14-4 22-25 26 10-10 12-16 8-23-5-8-3-17 4-26Z" />
      <path d="M16 103c16-4 33 1 48 13 16-12 33-17 48-13-1 8-5 13-13 12-15-2-26 2-35 9-9-7-20-11-35-9-8 1-12-4-13-12Z" />
    </svg>
  );
}
