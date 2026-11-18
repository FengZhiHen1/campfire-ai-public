/**
 * 首页：从描述问题开始，现场求助与阅读资料保持独立可达。
 *
 * 布局决策（本轮精修）：
 * - 品牌字标只作朴素眉题（不带页头底边），「今天，想聊些什么？」直接成为页面主标题，
 *   让引导语、输入器、现场求助连成一段，而不是三个各自为政的卡片；
 * - 措辞从「进入对话」改为「开始聊」，用户的痛点是不知道那一大块空白输入框要写多少、
 *   写完要按哪里——改成直接开写、短框短说明，主按钮明确仍是「确认发送后才分析」；
 * - 应急入口不做通用左侧强调线卡片，而用「火光点 + 一句定位 + 跨行直达入口」的紧凑条：
 *   它读作一件紧急的事，与日常输入器靠版式区分，不靠一条可复制到任何卡片的左边线；
 * - 日常输入与应急入口都在初始首屏可见：320×640 下也必须整块可见、中心可点，
 *   「开始应急咨询」链接不允许被底部导航遮住；
 * - 日常输入保留「先写草稿、显式发送」的边界：点主按钮只建会话并把草稿交给对话页，
 *   真正发送后才开始分析；空草稿时主按钮禁用（中性态），首屏只有应急入口是立即可执行的橙色动作。
 */
import { Link, useNavigate } from 'react-router';
import type { ConsultPort } from '../../features/consult/application/ports';
import { consultChatPath } from '../../features/consult/view/consultRoutes';
import { useConversationEntry } from '../../features/consult/viewModel/useConversationEntry';
import { AppShell } from '../../shared/ui/AppShell';
import { BrandMark } from '../../shared/ui/BrandMark';
import { Icon } from '../../shared/ui/Icon';
import { ErrorCard } from '../../shared/ui/StatePrimitives';
import styles from './homePage.module.css';

export function HomePage({ consult }: { consult: ConsultPort }) {
  const navigate = useNavigate();
  const entry = useConversationEntry(consult, (sessionId, draft, onboardingPending) => {
    // `guidePending` 交给对话页：引导待注入时那里要给「跳过引导」入口（契约第 6 节、RQ-ACC-02）。
    void navigate(consultChatPath(sessionId), { state: { draft, guidePending: onboardingPending } });
  });
  const draftEmpty = entry.draft.trim() === '';

  return (
    <AppShell tab="home">
      <div className={styles.page}>
        <header className={styles.masthead}>
          {/* 品牌是眉题，不是返回或跳转入口：首页链接到首页没有去处，链接语义是空的，
           * 会让读屏与「可点即有事发生」的预期落空。这里只呈现字标，不承担导航。 */}
          <div className={styles.brandRow}>
            <BrandMark size="22px" />
            <span className={styles.title}>篝火智答</span>
          </div>
          <Link className={styles.guideLink} to="/guide" state={{ returnTo: '/' }}>
            使用说明 <Icon name="chevron" />
          </Link>
        </header>

        <section className={styles.conversation} aria-labelledby="home-start">
          <h1 id="home-start" className={styles.startLead}>今天，想聊些什么？</h1>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void entry.start();
            }}
          >
            <label className="sr-only" htmlFor="home-draft">想聊的事情</label>
            <textarea
              id="home-draft"
              rows={2}
              placeholder="写下正在准备或刚发生的事……"
              value={entry.draft}
              disabled={entry.creating}
              onChange={(event) => entry.setDraft(event.target.value)}
            />
            <div className={styles.composeBottom}>
              <span className={styles.draftNote}>发送后开始分析</span>
              {/* 空白时主按钮禁用：首屏只留应急入口作为立即可执行的橙色动作；
               * 禁用态显式改成中性暖灰（见 homePage.module.css），不呈现为可点的橙色。 */}
              <button type="submit" className={`btn btn-primary ${styles.enterButton}`} disabled={entry.creating || draftEmpty}>
                {entry.creating ? '正在进入…' : '开始聊'} <Icon name="arrow" />
              </button>
            </div>
          </form>
          {entry.failure !== null && <ErrorCard title={entry.failure.title} description={entry.failure.message} />}
        </section>

        {/* 现场求助：一件紧急的事，用火光点与跨行直达入口表达，而不是通用的左侧强调线卡片。
         * 整块也可点，热区更大；标题、定位、动作读作一条连续的火光入口。 */}
        <article className={styles.emergency}>
          <div className={styles.emergencyHead}>
            <span className={styles.emergencyFlame}>
              <span className="flame-dot breathing" aria-hidden="true" />
            </span>
            <div className={styles.emergencyCopy}>
              <h2>现在需要帮助</h2>
              <p>在现场遇到正在发生的情况？回答几个问题，马上给你可行动的建议</p>
            </div>
          </div>
          <Link className={styles.emergencyLink} to="/consult/emergency" state={{ returnTo: '/' }}>
            开始应急咨询 <Icon name="arrow" />
          </Link>
        </article>

        <Link className={styles.historyLink} to="/consult">
          <Icon name="chat" />
          <span>继续之前的咨询</span>
          <Icon name="chevron" />
        </Link>

        <section className={styles.resources} aria-label="案例与资料">
          <p className="eyebrow">案例与资料</p>
          <div className={styles.secondaryRow}>
            <Link className={styles.resourceLink} to="/cases" state={{ returnTo: '/' }}>
              <Icon name="book" />
              <span><strong>案例库</strong><small>看看别的家庭怎么处理类似情况</small></span>
              <Icon name="chevron" />
            </Link>
            <Link className={styles.resourceLink} to="/cases?section=knowledge" state={{ returnTo: '/' }}>
              <Icon name="shield" />
              <span><strong>资料库</strong><small>浏览资料，查看来源与适用范围</small></span>
              <Icon name="chevron" />
            </Link>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
