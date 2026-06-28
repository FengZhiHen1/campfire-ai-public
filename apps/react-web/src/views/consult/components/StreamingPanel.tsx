import type { PlanSection } from '@/logics/consult';

export interface StreamingPanelProps {
  behaviorTypeSelection: string[];
  behaviorDescription: string;
  emotionLevel?: string;
  planSections: PlanSection[];
}

const SECTION_KEYS = ['action', 'soothe', 'observe', 'medical'] as const;
const SECTION_LABELS: Record<string, string> = {
  action: '即时安全干预',
  soothe: '情绪安抚话术',
  observe: '后续观察指标',
  medical: '就医判断标准',
};

function PlanSectionItem({ section }: { section: PlanSection }) {
  const label = SECTION_LABELS[section.type] ?? section.type;
  const bodyHtml = section.content || '<span class="plan-section-placeholder">（待生成）</span>';
  const hasContent = section.isCompleted;

  return (
    <div className={`plan-section ${section.type} streaming-sec${hasContent ? ' done' : ''}`}>
      <div className="plan-section-head">
        <span className="plan-section-label">{label}</span>
        <span className={`plan-section-check${hasContent ? ' visible' : ''}`}>✓</span>
      </div>
      <div
        className="plan-section-body"
        dangerouslySetInnerHTML={{ __html: bodyHtml }}
      />
    </div>
  );
}

export default function StreamingPanel({
  behaviorTypeSelection,
  behaviorDescription,
  emotionLevel,
  planSections,
}: StreamingPanelProps) {
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
        {SECTION_KEYS.map((key) => {
          const section = planSections.find((s) => s.type === key);
          return section ? (
            <PlanSectionItem key={key} section={section} />
          ) : (
            <div key={key} className={`plan-section ${key} streaming-sec`}>
              <div className="plan-section-head">
                <span className="plan-section-label">{SECTION_LABELS[key]}</span>
                <span className="plan-section-check">✓</span>
              </div>
              <div className="plan-section-body">
                <span className="plan-section-placeholder">（待生成）</span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="action-area">
        <button className="btn btn-primary" disabled>生成中…</button>
      </div>
      <div className="disclaimer">基于归档案例的 AI 生成建议，不构成医疗诊断。严重情况请咨询专业医生。</div>
    </div>
  );
}
