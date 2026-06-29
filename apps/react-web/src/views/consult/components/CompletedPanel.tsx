import { Link } from 'react-router-dom';
import type { PlanSection, ReferencedCase, BehaviorTypeCategory } from '@/logics/consult';

export interface CompletedPanelProps {
  behaviorTypeSelection: BehaviorTypeCategory[];
  behaviorDescription: string;
  emotionLevel?: string;
  planSections: PlanSection[];
  referencedCases: ReferencedCase[];
  crisisLevel?: string;
  confidenceScore?: number;
  onStartNew: () => void;
  onGoToTicket: () => void;
  onShowEscalation: () => void;
  ticketGuideShow: boolean;
}

type SectionType = 'action' | 'soothe' | 'observe' | 'medical';

const SECTION_ORDER: SectionType[] = ['action', 'soothe', 'observe', 'medical'];

const SECTION_LABELS: Record<SectionType, string> = {
  action: '即时安全干预',
  soothe: '情绪安抚话术',
  observe: '后续观察指标',
  medical: '就医判断标准',
};

const TYPE_LABELS: Record<BehaviorTypeCategory, string> = {
  SELF_INJURY: '自伤行为',
  AGGRESSION: '攻击行为',
  ELOPEMENT: '出走/逃跑',
  EMOTIONAL_MELTDOWN: '情绪崩溃',
  MEDICATION: '用药相关',
  STEREOTYPY: '刻板行为',
  OTHER: '其他',
};

function inferSectionType(title: string): SectionType {
  const t = title.trim();
  if (t.includes('即时') || t.includes('安全') || t.includes('干预')) return 'action';
  if (t.includes('安抚') || t.includes('话术')) return 'soothe';
  if (t.includes('观察') || t.includes('指标')) return 'observe';
  if (t.includes('就医') || t.includes('判断')) return 'medical';
  return 'action';
}

const QUOTE_RE = /^[“""「『〝]+|["""」』〞]+$/g;

function stripQuotes(text: string): string {
  return text.replace(QUOTE_RE, '');
}

function isQuotedLine(line: string): boolean {
  return stripQuotes(line) !== line;
}

function normalizeLines(contents: string[]): string[] {
  return contents
    .flatMap((c) => c.split('\n'))
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
}

function renderBodyHtml(contents: string[]): string {
  const lines = normalizeLines(contents);
  if (lines.length === 0) return '';
  return lines
    .map((line) => {
      if (isQuotedLine(line)) {
        return `<div class="soothe-quote"><p>${stripQuotes(line)}</p></div>`;
      }
      return `<p>${line}</p>`;
    })
    .join('');
}

function buildSections(planSections: PlanSection[]): { type: SectionType; section: PlanSection }[] {
  const byType = new Map<SectionType, PlanSection>();
  planSections.forEach((sec) => {
    const type = inferSectionType(sec.title);
    if (!byType.has(type) || (sec.contents.length > 0 && !byType.get(type)!.contents.length)) {
      byType.set(type, sec);
    }
  });
  return SECTION_ORDER.map((type) => ({
    type,
    section: byType.get(type) ?? { title: SECTION_LABELS[type], contents: [], isCompleted: true },
  }));
}

function getConfidenceLevel(confidenceScore: number | undefined, crisisLevel?: string): 'high' | 'medium' | 'low' {
  if (typeof confidenceScore === 'number') {
    if (confidenceScore >= 0.85) return 'high';
    if (confidenceScore >= 0.7) return 'medium';
    return 'low';
  }
  if (crisisLevel === 'severe') return 'low';
  if (crisisLevel === 'moderate') return 'medium';
  return 'high';
}

function getConfidenceLabel(level: 'high' | 'medium' | 'low'): string {
  switch (level) {
    case 'high': return '高可信';
    case 'medium': return '中可信';
    case 'low': return '需人工复核';
  }
}

export default function CompletedPanel({
  behaviorTypeSelection,
  behaviorDescription,
  emotionLevel,
  planSections,
  referencedCases,
  crisisLevel,
  confidenceScore,
  onStartNew,
  onGoToTicket,
  onShowEscalation,
  ticketGuideShow,
}: CompletedPanelProps) {
  const sections = buildSections(planSections);
  const confidenceLevel = getConfidenceLevel(confidenceScore, crisisLevel);

  return (
    <div className="state-panel active" data-testid="consult-completed">
      <div className="query-summary" data-testid="consult-user-summary">
        <div className="query-tags">
          <span className="query-pill" data-testid="consult-user-summary-type">
            {TYPE_LABELS[behaviorTypeSelection[0]] ?? behaviorTypeSelection[0] ?? ''}
          </span>
          {emotionLevel && <span className="query-emotion">· 情绪{emotionLevel}度</span>}
        </div>
        <p className="query-text" data-testid="consult-user-summary-desc">{behaviorDescription}</p>
      </div>

      <div className="plan-card" data-testid="consult-plan-card">
        <h3 data-testid="consult-plan-card-header">干预建议大纲</h3>
        {sections.map(({ type, section }, idx) => (
          <div
            key={type}
            className={`plan-section ${type} done`}
            data-testid={`consult-plan-section-${idx}`}
            data-section={type}
          >
            <div className="plan-section-head">
              <span className="plan-section-label">{SECTION_LABELS[type]}</span>
              <span className="plan-section-check visible">✓</span>
            </div>
            <div
              className="plan-section-body"
              dangerouslySetInnerHTML={{ __html: renderBodyHtml(section.contents) }}
            />
          </div>
        ))}

        <div className="plan-footer" data-testid="consult-plan-footer">
          <span className="case-ref-pill">基于 {referencedCases.length} 个相似案例</span>
          <span className={`confidence-pill ${confidenceLevel}`} data-testid="consult-confidence-badge">
            <span className="confidence-dot" /> {getConfidenceLabel(confidenceLevel)}
          </span>
        </div>
      </div>

      {referencedCases.length > 0 && (
        <details className="ref-cases" data-testid="consult-ref-cases">
          <summary data-testid="consult-ref-cases-toggle">
            <span>参考案例（{referencedCases.length}）</span>
          </summary>
          {referencedCases.map((rc, i) => (
            <Link
              key={i}
              className="ref-case-item"
              data-testid={`consult-ref-case-${i}`}
              to={`/cases/card/${rc.case_id ?? i}`}
            >
              <div className="case-id">{rc.case_id ?? `CASE-${i}`}</div>
              <div>{rc.case_title}</div>
            </Link>
          ))}
        </details>
      )}

      <div className="action-area" data-testid="consult-actions">
        <button className="btn btn-primary" data-testid="consult-actions-new-btn" onClick={onStartNew}>开始新咨询</button>
        <button
          className="action-link"
          data-testid="consult-actions-expert-link"
          onClick={ticketGuideShow ? onGoToTicket : onShowEscalation}
        >
          联系人工专家
        </button>
      </div>

      <div className="disclaimer" data-testid="consult-disclaimer">基于归档案例的 AI 生成建议，不构成医疗诊断。严重情况请咨询专业医生。</div>
    </div>
  );
}
