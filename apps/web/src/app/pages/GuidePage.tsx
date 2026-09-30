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

import type { ReactElement } from 'react';
import { Link } from 'react-router';

import { AppShell } from '../../shared/ui/AppShell';
import styles from './guidePage.module.css';

/** 小节标识；图标表与文案表都按它索引，避免两处顺序漂移。 */
type SectionKey = 'emergency' | 'daily' | 'records' | 'privacy';

/**
 * 小节图标：1.6px 描边、currentColor 上色（实际颜色由 .sectionIcon 给 --fg-2）。
 *
 * 为什么四枚形状刻意不同（火焰/对话/文档/数据柱）：页面设计把「图标 + 标题」列为该页
 * 不依赖颜色的层次与双通道手段（使用说明.md:16、:52），而本页零 accent——四枚若同形，
 * 这层区分就退化成装饰。画法与 AppShell 的 tab 图标同族（24 视框、1.6px、aria-hidden）。
 * 数据与隐私用中性的数据柱而不是盾牌/锁：本页是资料处理告知，盾形或对勾会读成安全承诺，
 * 与 AC-10（不得声称已获专业认可、不得作安全承诺）相冲。
 */
const SECTION_ICONS: Readonly<Record<SectionKey, ReactElement>> = {
  emergency: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M12 3.6c2.7 3.2 4.7 5.2 4.7 8.2a4.7 4.7 0 1 1-9.4 0c0-3 2-5 4.7-8.2z" strokeLinejoin="round" />
      <path d="M12 13.2c1.1 1.3 1.8 2 1.8 3.1a1.8 1.8 0 1 1-3.6 0c0-1.1.7-1.8 1.8-3.1z" />
    </svg>
  ),
  daily: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M4 6h16v10H9l-5 4z" strokeLinejoin="round" />
    </svg>
  ),
  records: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M6 3h8l4 4v14H6z" strokeLinejoin="round" />
      <path d="M14 3v4h4" />
      <path d="M9 12h6M9 16h6" />
    </svg>
  ),
  privacy: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <ellipse cx="12" cy="6.5" rx="7" ry="3" />
      <path d="M5 6.5v11c0 1.7 3.1 3 7 3s7-1.3 7-3v-11" />
      <path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" />
    </svg>
  ),
};

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
  {
    key: 'privacy',
    title: '数据与隐私',
    body: '你的咨询内容会发送给模型服务处理后返回。',
  },
] as const satisfies readonly { key: SectionKey; title: string; body: string; note?: string }[];

/**
 * 渲染使用说明页。
 *
 * 前置: 无（全页静态内容）
 * 后置: 输出次级页头（返回 + 标题）、四张小节卡、数据与隐私内联链接与尾部边界说明行
 * 异常: 无
 */
export function GuidePage() {
  return (
    <AppShell>
      {/* 次级页面头：返回 + 标题（页面设计第 13 行「返回导航由页头承担」）。
       * 设计原文此处写 .page-head，但该页同时声明自己是次级页，而契约把返回控件
       * 与吸顶頭定义在 .subpage-head 上，其余四个次级页（记忆页/对话页/案例库浏览页/
       * 应急表单页）设计也均写 .subpage-head——按编排器裁决视为设计原文笔误，
       * 保留 .subpage-head，标题字号/字重补齐在契约层（components.css 的 .sp-title）。 */}
      <header className="subpage-head">
        <Link className="sp-back" to="/settings">
          ← 返回
        </Link>
        <span className="sp-title">使用说明</span>
      </header>

      {SECTIONS.map((section) => (
        <article className="tile" key={section.key}>
          <div className={styles.sectionHead}>
            <span className={styles.sectionIcon}>{SECTION_ICONS[section.key]}</span>
            <h2 className={styles.sectionTitle}>{section.title}</h2>
          </div>
          <p className={styles.sectionBody}>{section.body}</p>
          {'note' in section && <p className={styles.sectionNote}>{section.note}</p>}
          {section.key === 'privacy' && (
            // 分工：本页一句话，详单在设置页（RQ-LIM-03 的告知落点）。
            // 这一行做成 flex 行，让内联链接拿到 44px 真实热区（裸 a 无 min-height，
            // 属契约层缺口，见 guidePage.module.css 的就地说明）。
            <p className={`${styles.sectionBody} ${styles.privacyRow}`}>
              详见
              <Link to="/settings">设置页 · 关于你的数据</Link>
            </p>
          )}
        </article>
      ))}

      {/* 尾部说明行：与设置页一期边界卡同一口径，不重复展开。 */}
      <p className={styles.tailNote}>本应用尚未经专业审阅，不能替代专业服务</p>
    </AppShell>
  );
}
