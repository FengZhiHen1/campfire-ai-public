/**
 * 模块: app/pages/GuidePage
 * 职责: 使用说明页——四条路的静态说明（应急/日常/档案与记忆/数据与隐私）与尾部边界说明
 * 数据来源:
 *   - docs/design/pages/使用说明.md: MUST — 全文（布局结构、组件选用、数据与文案、状态覆盖）
 *   - docs/design/components.html: MUST — .subpage-head/.sp-back/.sp-title/.tile
 * 边界:
 *   - 依赖: shared/ui（AppShell）与 react-router
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止把四张小节卡做成可点入口（说明卡不是入口卡，页面设计响应式节）
 *   - 禁止弱化 RQ-LIM-04 硬文案（逐字呈现，与设置页同口径）
 *   - 禁止在本页使用 accent（与设置页同纪律：说明页是手册页不是行动页）
 *
 * 为什么归 app 层：它的追溯是引导收束的跳转落点与告知导览，不是某个特性的业务页面；
 * 页面本身零取数、零业务规则，只是呈现成稿文案。
 */

import { Link } from 'react-router';

import { AppShell } from '../../shared/ui/AppShell';
import styles from './guidePage.module.css';

/** 小节文案（页面设计「数据与文案」节的成稿，逐字呈现）。 */
const SECTIONS = [
  {
    key: 'emergency',
    title: '应急咨询',
    body: '正在现场、正在发生时用；回答几个问题，马上给你可行动的建议',
    // RQ-LIM-04 硬文案：与设置页一期边界卡同一口径，逐字。
    note: '紧急医疗情况请直接就医或拨打急救电话',
  },
  {
    key: 'daily',
    title: '日常咨询',
    body: '想聊聊正在准备或刚发生的事，随时开始',
  },
  {
    key: 'records',
    title: '档案与记忆',
    body: '你说的话会累积成档案；系统整理的推断要经你确认才算数',
  },
] as const;

/**
 * 渲染使用说明页。
 *
 * 前置: 无（全页静态内容）
 * 后置: 输出次级页头（返回 + 标题）、三张小节卡、数据与隐私小节与尾部边界说明行
 * 异常: 无
 */
export function GuidePage() {
  return (
    <AppShell>
      <header className="subpage-head">
        <Link className="sp-back" to="/settings">
          ← 返回
        </Link>
        <span className="sp-title">使用说明</span>
      </header>

      {SECTIONS.map((section) => (
        <article className="tile" key={section.key}>
          <h2 className={styles.sectionTitle}>{section.title}</h2>
          <p className={styles.sectionBody}>{section.body}</p>
          {'note' in section && <p className={styles.sectionNote}>{section.note}</p>}
        </article>
      ))}

      <article className="tile">
        <h2 className={styles.sectionTitle}>数据与隐私</h2>
        <p className={styles.sectionBody}>你的咨询内容会发送给模型服务处理后返回。</p>
        {/* 分工：本页一句话，详单在设置页（RQ-LIM-03 的告知落点）。 */}
        <p className={styles.sectionBody}>
          详见
          <Link to="/settings">设置页 · 关于你的数据</Link>
        </p>
      </article>

      {/* 尾部说明行：与设置页一期边界卡同一口径，不重复展开。 */}
      <p className={styles.tailNote}>本应用尚未经专业审阅，不能替代专业服务</p>
    </AppShell>
  );
}
