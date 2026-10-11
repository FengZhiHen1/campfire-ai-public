/** 首页：从描述问题开始，现场求助与阅读资料保持独立可达。 */
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
  const entry = useConversationEntry(consult, (sessionId, draft) => {
    void navigate(consultChatPath(sessionId), { state: { draft } });
  });
  return (
    <AppShell tab="home">
      <div className={styles.page}>
        <header className={styles.masthead}>
          <span className={styles.brandRow}>
            <BrandMark size="24px" />
            <h1 className={styles.title}>篝火智答</h1>
          </span>
          <Link className={styles.guideLink} to="/guide" state={{ returnTo: '/' }}>
            使用说明 <Icon name="chevron" />
          </Link>
        </header>
        <section className={styles.welcome} aria-labelledby="home-welcome">
          <p className="eyebrow">陪你梳理，一起往前</p>
          <h2 id="home-welcome">今天，想聊些什么？</h2>
          <p>从一件小事开始。说说你的困惑，我们一起找到下一步。</p>
        </section>
        <section className={styles.conversation} aria-label="日常咨询">
          <form onSubmit={(event) => {
            event.preventDefault();
            void entry.start();
          }}>
            <label className="sr-only" htmlFor="home-draft">想聊的事情</label>
            <textarea
              id="home-draft"
              rows={3}
              placeholder="写下正在准备或刚发生的事……"
              value={entry.draft}
              disabled={entry.creating}
              onChange={(event) => entry.setDraft(event.target.value)}
            />
            <div className={styles.composeBottom}>
              <span className="meta">日常咨询</span>
              <button type="submit" className="btn btn-primary" disabled={entry.creating || entry.draft.trim() === ''}>
                {entry.creating ? '正在进入…' : '进入对话'} <Icon name="arrow" />
              </button>
            </div>
          </form>
          <p className={styles.draftNote}>进入后可继续补充，发送时才开始分析。</p>
          {entry.failure !== null && <ErrorCard title={entry.failure.title} description={entry.failure.message} />}
        </section>
        <article className={'panel emergency-entry ' + styles.emergency}>
          <div className="entry-title">
            <span className="flame-dot breathing" aria-hidden="true" />
            <h2>现在需要帮助</h2>
          </div>
          <p>在现场遇到正在发生的情况？回答几个问题，马上给你可行动的建议</p>
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
