/**
 * 模块: features/accounts/view/AboutPage
 * 职责: 「关于篝火智答」次级页——承载数据用途、外部模型告知与一期使用边界硬文案。
 *        这本是原先堆在设置页里的说明，现独立成页，让「我的」回到原生感设置入口列表。
 * 数据来源:
 *   - docs/design/pages/设置页.md: MUST — 数据与文案（三项告知成稿）、RQ-LIM-03/RQ-LIM-04 硬文案
 *   - docs/design/pages/使用说明.md: MUST — 数据与隐私小节的详单落点（本页）
 * 边界:
 *   - 依赖: shared/ui（AppShell、BackLink）、viewModel/useSettings 的成稿文案
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止弱化一期边界硬文案（AC-10 反向声明逐字呈现，与设置页同一口径）
 *   - 禁止在本页使用 accent（说明页是告知页，不是行动页，与设置/使用说明同纪律）
 *   - 禁止出现专业认可、临床效果、安全承诺类表述（AC-10）
 *
 * 为什么归 accounts/view 而不是 app/pages：它的文案真源是设置页的告知（SETTINGS_COPY、
 * DATA_FACTS），与「我的」同属账号侧告知；挪走后会与设置页的成稿漂移。页面自身零取数、
 * 零业务规则，只呈现成稿文案与一个返回入口。
 */

import { BackLink } from '../../../shared/ui/BackLink';

import { AppShell } from '../../../shared/ui/AppShell';
import { DATA_FACTS, SETTINGS_COPY } from '../viewModel/useSettings';
import styles from './aboutPage.module.css';

/**
 * 渲染「关于篝火智答」页。
 *
 * 前置: 无（全页静态内容）
 * 后置: 输出次级页头（返回 + 标题）、三项数据用途告知、一期边界硬文案与尾注
 * 异常: 无
 */
export function AboutPage() {
  return (
    <AppShell>
      <header className="subpage-head">
        <BackLink fallback="/settings" />
        <span className="sp-title">{SETTINGS_COPY.aboutTitle}</span>
      </header>

      <p className={styles.lead}>{SETTINGS_COPY.aboutLead}</p>

      <section className={styles.data} aria-labelledby="about-data">
        <h2 className={styles.groupTitle} id="about-data">
          {SETTINGS_COPY.dataGroup}
        </h2>
        <dl className={styles.facts}>
          {DATA_FACTS.map((fact) => (
            <div key={fact.title}>
              <dt>{fact.title}</dt>
              <dd>{fact.body}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className={styles.notice} aria-label={SETTINGS_COPY.noticeGroup}>
        <p className={styles.boundary}>{SETTINGS_COPY.boundary}</p>
      </section>
    </AppShell>
  );
}
