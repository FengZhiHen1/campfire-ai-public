/**
 * 模块: app/PlaceholderPage
 * 职责: 路由骨架的「本页没有内容」渲染——页面标题 + 一行说明，并按原因说明是「还没做」还是「没有这一页」
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

/**
 * 「这里没有内容」的两种**互斥**原因。
 *
 * 为什么要在类型上分开、而不是一个布尔开关：404 与占位虽然视觉形态相近，
 * 但对使用者是两件事——前者是「没有这一页，请去别处」，后者是「这一页有、还没做完」。
 * 一个 `building?: boolean` 形式的开关会允许「不传」，而两种不传的默认值都是错的：
 *   - 默认 true ⇒ 将来新增的 404 类页面忘记传参就重现「没有这一页 / 这一页在建设中」并置；
 *   - 默认 false ⇒ 将来新增的占位页忘记传参就静默丢掉「建设中」，破坏上面的禁止行为。
 * ⇒ 本组件**不设默认值**，调用方必须显式说出原因；漏传是编译错误而不是文案缺陷。
 */
export type PlaceholderReason =
  /** 路径有效、页面还没实现 ⇒ 追加「本页尚在建设中。」 */
  | 'building'
  /** 路径本身不存在（404）⇒ 只说没有这一页，不说建设中 */
  | 'missing';

/** 占位页 props；标题与说明由路由表提供，文案中文、标识英文。 */
export interface PlaceholderPageProps {
  /** 页面标题（中文）。 */
  title: string;
  /** 一行说明（中文）：本页建成后做什么，或为什么这个地址没有对应页面。 */
  description: string;
  /** 这里没有内容的原因；决定是否追加「本页尚在建设中。」。 */
  reason: PlaceholderReason;
}

/**
 * 渲染一个没有内容的页面。
 *
 * 前置: title 与 description 均非空（由路由表的静态配置保证）；reason 由调用方显式给出
 * 后置: 输出标题与说明各一处；reason 为 'building' 时额外输出一行「本页尚在建设中。」，
 *       为 'missing' 时不输出它（路径不存在与页面在建设中不能并置）
 * 异常: 无
 */
export function PlaceholderPage({ title, description, reason }: PlaceholderPageProps) {
  return (
    <section className="page" aria-labelledby="page-title">
      <h1 className="page-title" id="page-title">
        {title}
      </h1>
      <p className="page-note">{description}</p>
      {reason === 'building' && <p className="status-note">本页尚在建设中。</p>}
    </section>
  );
}
