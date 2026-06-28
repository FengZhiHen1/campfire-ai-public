import { Link } from 'react-router-dom';
import type { PlanSection, ReferencedCase } from '@/logics/consult';

export interface CompletedPanelProps {
  behaviorTypeSelection: string[];
  behaviorDescription: string;
  emotionLevel?: string;
  planSections: PlanSection[];
  referencedCases: ReferencedCase[];
  crisisLevel?: string;
  onStartNew: () => void;
  onGoToTicket: () => void;
  onShowEscalation: () => void;
  ticketGuideShow: boolean;
}

const SECTION_LABELS: Record<string, string> = {
  action: '即时安全干预',
  soothe: '情绪安抚话术',
  observe: '后续观察指标',
  medical: '就医判断标准',
};

function getConfidenceClass(crisisLevel?: string): string {
  if (crisisLevel === 'severe') return 'low';
  if (crisisLevel === 'moderate') return 'medium';
  return 'high';
}
function getConfidenceLabel(crisisLevel?: string): string {
  if (crisisLevel === 'severe') return '需人工复核';
  if (crisisLevel === 'moderate') return '中可信';
  return '高可信';
}

export default function CompletedPanel({
  behaviorTypeSelection,
  behaviorDescription,
  emotionLevel,
  planSections,
  referencedCases,
  crisisLevel,
  onStartNew,
  onGoToTicket,
  onShowEscalation,
  ticketGuideShow,
}: CompletedPanelProps) {
  return (
    <div className="state-panel active">
      <div className="query-summary">
        <div className="query-tags">
          <span className="query-pill">{behaviorTypeSelection[0] ?? ''}</span>
          {emotionLevel && <span className="query-emotion">· 情绪{emotionLevel}度</span>}
        </div>
        <p className="query-text">{behaviorDescription}</p>
      </div>

      <div className="plan-card">
        <h3>干预建议大纲</h3>
        {planSections.map((s) => (
          <div key={s.type} className={`plan-section ${s.type} done`}>
            <div className="plan-section-head">
              <span className="plan-section-label">{SECTION_LABELS[s.type] ?? s.type}</span>
              <span className="plan-section-check visible">✓</span>
            </div>
            <div className="plan-section-body" dangerouslySetInnerHTML={{ __html: s.content }} />
          </div>
        ))}

        <div className="plan-footer">
          <span className="case-ref-pill">基于 {referencedCases.length} 个相似案例</span>
          <span className={`confidence-pill ${getConfidenceClass(crisisLevel)}`}>
            <span className="confidence-dot" /> {getConfidenceLabel(crisisLevel)}
          </span>
        </div>
      </div>

      {referencedCases.length > 0 && (
        <details className="ref-cases">
          <summary><span>参考案例（{referencedCases.length}）</span></summary>
          {referencedCases.map((rc, i) => (
            <Link key={i} className="ref-case-item" to={`/cases/card/${rc.caseId ?? i}`}>
              <div className="case-id">{rc.caseId ?? `CASE-${i}`}</div>
              <div>{rc.summary}</div>
            </Link>
          ))}
        </details>
      )}

      <div className="action-area">
        <button className="btn btn-primary" onClick={onStartNew}>开始新咨询</button>
        <button className="action-link" onClick={ticketGuideShow ? onShowEscalation : onGoToTicket}>
          联系人工专家
        </button>
      </div>

      <div className="disclaimer">基于归档案例的 AI 生成建议，不构成医疗诊断。严重情况请咨询专业医生。</div>
    </div>
  );
}
