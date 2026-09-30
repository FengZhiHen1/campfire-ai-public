/**
 * 模块: app/PlaceholderPage
 * 职责: 路由骨架的统一占位渲染——页面标题 + 一行说明，明确「建设中」而不是空白页
 * 数据来源:
 *   - docs/项目结构设计.md: MUST — 第 9 节（app 层负责路由与装配）
 * 边界:
 *   - 依赖: 无（纯渲染）
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止渲染空 div 冒充页面（占位也必须说明这是什么页、为何还没内容）
 *   - 禁止在此做数据获取（数据获取归 features 层，本层只做骨架）
 */

import './placeholder.css';

/** 占位页 props；标题与说明由路由表提供，文案中文、标识英文。 */
export interface PlaceholderPageProps {
  /** 页面标题（中文）。 */
  title: string;
  /** 一行说明（中文）：本页建成后做什么，当前为何是占位。 */
  description: string;
}

/**
 * 渲染一个占位页。
 *
 * 前置: title 与 description 均非空（由路由表的静态配置保证）
 * 后置: 输出标题与说明各一处，页面区域不再是空白
 * 异常: 无
 */
export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <section className="page" aria-labelledby="page-title">
      <h1 className="page-title" id="page-title">
        {title}
      </h1>
      <p className="page-note">{description}</p>
      <p className="status-note">本页尚在建设中。</p>
    </section>
  );
}
