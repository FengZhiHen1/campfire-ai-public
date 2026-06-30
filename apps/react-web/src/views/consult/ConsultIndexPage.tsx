import { useEffect, useRef, useState } from 'react';
import { useConsult } from '@/logics/consult';
import { useConsultStore } from '@/logics/consult/store/useConsultStore';
import PageContent from '@/views/_shared/layout/PageContent';
import IdlePanel from './components/IdlePanel';
import SubmittingPanel from './components/SubmittingPanel';
import StreamingPanel from './components/StreamingPanel';
import CompletedPanel from './components/CompletedPanel';
import ErrorPanel from './components/ErrorPanel';
import TicketGuidePanel from './components/TicketGuidePanel';
import './ConsultIndexPage.css';

const CRISIS_LABELS: Record<string, string> = {
  mild: '等级：轻度',
  moderate: '等级：中度',
  severe: '等级：重度',
};

export default function ConsultIndexPage() {
  const consult = useConsult();
  const [showEscalation, setShowEscalation] = useState(false);

  // 从 consult/select 返回时，store 可能仍停留在 selecting_behavior，
  // 导致内容区没有匹配的面板。仅在组件挂载时执行一次重置，
  // 避免用户点击"开始咨询"后状态被立即复位到 idle。
  const hasResetRef = useRef(false);
  const sessionState = useConsultStore((s) => s.sessionState);
  const cancelSelection = useConsultStore((s) => s.cancelSelection);
  useEffect(() => {
    if (hasResetRef.current) return;
    hasResetRef.current = true;
    if (sessionState === 'selecting_behavior') {
      cancelSelection();
    }
  }, [sessionState, cancelSelection]);

  const crisisBadgeClass = consult.crisisLevel
    ? `crisis-badge ${consult.crisisLevel} show`
    : 'crisis-badge';

  return (
    <>
      {/* Navigation Bar */}
      <div className="consult-nav" data-testid="consult-navbar">
        <span className="nav-title">应急咨询</span>
        <span className={crisisBadgeClass} data-testid="consult-navbar-crisis-badge">
          {consult.crisisLevel ? CRISIS_LABELS[consult.crisisLevel] : ''}
        </span>
      </div>

      <PageContent className="consult-page-content">
        {consult.sessionState === 'idle' && (
          <IdlePanel onStartConsult={consult.startConsult} />
        )}
        {consult.sessionState === 'submitting' && <SubmittingPanel />}
        {consult.sessionState === 'streaming' && (
          <StreamingPanel
            behaviorTypeSelection={consult.behaviorTypeSelection}
            behaviorDescription={consult.behaviorDescription}
            emotionLevel={consult.emotionLevel}
            planSections={consult.planSections}
          />
        )}
        {consult.sessionState === 'completed' && (
          <CompletedPanel
            behaviorTypeSelection={consult.behaviorTypeSelection}
            behaviorDescription={consult.behaviorDescription}
            emotionLevel={consult.emotionLevel}
            planSections={consult.planSections}
            referencedCases={consult.referencedCases}
            crisisLevel={consult.crisisLevel}
            confidenceScore={consult.confidenceScore}
            onStartNew={consult.startNewConsult}
            onGoToTicket={consult.goToTicket}
            onShowEscalation={() => setShowEscalation(true)}
            ticketGuideShow={consult.ticketGuide?.show ?? false}
          />
        )}
        {consult.sessionState === 'submit_failed' && (
          <ErrorPanel
            variant="submit_failed"
            errorMessage={consult.getErrorMessage(consult.errorCode ?? 'UNKNOWN')}
            onRetry={consult.retrySubmit}
            onBack={consult.goBackToSelecting}
          />
        )}
        {consult.sessionState === 'stream_failed' && (
          <ErrorPanel
            variant="stream_failed"
            errorMessage={consult.getErrorMessage(consult.errorCode ?? 'STREAM_BROKEN')}
            onRetry={consult.retryStream}
            onBack={consult.goBackToSelecting}
          />
        )}
        {consult.sessionState === 'ticket_guide' && (
          <TicketGuidePanel
            onGoToTicket={consult.goToTicket}
            onNewConsult={consult.startNewConsult}
          />
        )}
      </PageContent>

      {/* Escalation Bar */}
      {(consult.ticketGuide?.show || showEscalation) && (
        <button
          className="escalation-bar show"
          data-testid="consult-escalation-bar"
          onClick={consult.goToTicket}
        >
          <svg viewBox="0 0 24 24">
            <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
          </svg>
          立即联系人工专家
        </button>
      )}
    </>
  );
}
