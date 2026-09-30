/**
 * 模块: app/pages/HomePage
 * 职责: 首页——两个咨询入口（应急/日常）与次级入口行；应用的主导航落点
 * 数据来源:
 *   - docs/design/pages/首页.md: MUST — 全文（布局结构、组件选用、数据与文案、状态覆盖、动效意图）
 *   - docs/design/components.html: MUST — .page-head/.panel/.emergency-entry/.flame-dot/.tile/.mini-card
 * 边界:
 *   - 依赖: shared/ui（AppShell、BrandMark）与 react-router
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止在首页放账号名或设置入口（账号与设置归「我的」tab，页面设计页头节）
 *   - 禁止把两条入口做成等宽孪生卡（差异驱动：应急有描边+呼吸点，日常是纸面卡）
 *   - 禁止为「最近会话预览」造空态（首页没有「空」语义，页面设计状态覆盖表）
 *
 * 为什么首页是导航外壳而不是 features/consult 的页面：首页页设计的追溯节写明
 * 「咨询面设计明确首页是导航外壳，不属于咨询面」。它不装配任何咨询面能力，
 * 只做入口分发，因此归 app 层；两条入口目标路由由咨询面（T11/T12）实现。
 */

import { Link } from 'react-router';

import { AppShell } from '../../shared/ui/AppShell';
import { BrandMark } from '../../shared/ui/BrandMark';
import styles from './homePage.module.css';

/** 页面文案（页面设计「数据与文案」节的成稿，逐字呈现）。 */
const COPY = {
  title: '篝火智答',
  emergencyTitle: '现在需要帮助',
  emergencyBody: '在现场遇到正在发生的情况？回答几个问题，马上给你可行动的建议',
  emergencyAction: '开始应急咨询',
  dailyTitle: '日常咨询',
  dailyBody: '想聊聊正在准备或刚发生的事，随时开始',
  dailyNext: '开始日常咨询',
  casesTitle: '案例库',
  casesBody: '看看别的家庭怎么处理类似情况',
  libraryTitle: '资料库说明',
  libraryBody: '每条建议都标来源与适用范围',
} as const;

/**
 * 渲染首页。
 *
 * 前置: 无（静态导航页，不取数）
 * 后置: 输出页头、应急入口、日常入口与次级入口行；底部 tab 栏当前项为首页
 * 异常: 无
 *
 * 为什么首页不取数：页面设计的「状态覆盖」表写明应急/日常/次级入口是静态内容、
 * 无加载态；唯一可选的「最近会话预览」是非关键增强，其三种状态
 * （loading/empty/error）都要求不渲染该区块。首页因此整体不渲染该区块——
 * 这与它的三种状态要求一致，不是缺项；接入取数归咨询面（T11/T12）。
 */
export function HomePage() {
  return (
    <AppShell tab="home">
      <div className={styles.page}>
        <header className="page-head">
          <span className={styles.brandRow}>
            <BrandMark size="1em" />
            <h1 className={styles.title}>{COPY.title}</h1>
          </span>
        </header>

        {/* 应急与日常入口合成一组：设计要求这两条之间用 --space-4、其余区块用 --space-6
         * （首页.md:21）。gap 是容器级属性、无法逐对设置，因此把这对入口放进一个 gap
         * 更紧的组里，组外仍由 .page 的 --space-6 拉开——两组距离的差异即「两条咨询
         * 入口 vs 次级入口行」的层级差异，不是排版偶然。 */}
        <div className={styles.entryGroup}>
          {/* 应急入口：本页唯一 accent 重量级使用（描边 + 呼吸点 + 主按钮属同一强调单元）。 */}
          <article className={`panel emergency-entry ${styles.emergency}`}>
            <div className="entry-title">
              <span className="flame-dot breathing" aria-hidden="true" />
              <h2 className={styles.entryHeading}>{COPY.emergencyTitle}</h2>
            </div>
            <p>{COPY.emergencyBody}</p>
            <Link className="btn btn-primary block" to="/consult/emergency">
              {COPY.emergencyAction}
            </Link>
          </article>

          {/* 日常咨询入口：整卡可点，热区即整卡（≥44px）。 */}
          <Link className="tile daily-entry" to="/consult">
            <h2 className={styles.entryHeading}>{COPY.dailyTitle}</h2>
            <p>{COPY.dailyBody}</p>
            <span className="entry-next">{COPY.dailyNext}</span>
          </Link>
        </div>

        <div className={styles.secondaryRow}>
          <Link className="mini-card" to="/cases">
            <h3 className={styles.secondaryTitle}>{COPY.casesTitle}</h3>
            <p className={styles.secondaryBody}>{COPY.casesBody}</p>
          </Link>
          {/* 指向案例库浏览页的「资料」分区：首页页设计写明这个入口「→ 进案例库的资料分区」，
           * 而该页的库切换只有「案例」/「资料」两档，其中「资料」就是 knowledge 库
           * （资料库面契约第 2 节：library 取 knowledge | case）。
           * 分区参数名在页面设计里没有定义，沿用该页 deep-link 已有的 section 参数，
           * 取值用库别原值——写别的值会被解析成「没给分区」而静默落到案例分区。 */}
          <Link className="mini-card" to="/cases?section=knowledge">
            <h3 className={styles.secondaryTitle}>{COPY.libraryTitle}</h3>
            <p className={styles.secondaryBody}>{COPY.libraryBody}</p>
          </Link>
        </div>
      </div>
    </AppShell>
  );
}
