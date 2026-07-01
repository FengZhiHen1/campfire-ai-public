import type { PlanSection, BehaviorTypeCategory } from '@/logics/consult';

export interface StreamingPanelProps {
  behaviorTypeSelection: BehaviorTypeCategory[];
  behaviorDescription: string;
  emotionLevel?: string;
  planSections: PlanSection[];
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

function renderBodyHtml(contents: string[], { active = false }: { active?: boolean } = {}): string {
  const lines = normalizeLines(contents);
  if (lines.length === 0) {
    return active
      ? '<span class="plan-section-placeholder">（待生成）</span><span class="stream-cursor"></span>'
      : '<span class="plan-section-placeholder">（待生成）</span>';
  }

  const html = lines
    .map((line, idx) => {
      const isLast = idx === lines.length - 1;
      const cursor = active && isLast ? '<span class="stream-cursor"></span>' : '';
      if (isQuotedLine(line)) {
        return `<div class="soothe-quote"><p>${stripQuotes(line)}${cursor}</p></div>`;
      }
      return `<p>${line}${cursor}</p>`;
    })
    .join('');

  return html;
}

interface SectionItem {
  type: SectionType;
  section?: PlanSection;
}

function buildSections(planSections: PlanSection[]): SectionItem[] {
  const byType = new Map<SectionType, PlanSection>();
  planSections.forEach((sec) => {
    const type = inferSectionType(sec.title);
    // 优先保留有内容的同名段落
    if (!byType.has(type) || (sec.contents.length > 0 && !byType.get(type)!.contents.length)) {
      byType.set(type, sec);
    }
  });
  return SECTION_ORDER.map((type) => ({ type, section: byType.get(type) }));
}

export default function StreamingPanel({
  behaviorTypeSelection,
  behaviorDescription,
  emotionLevel,
  planSections,
}: StreamingPanelProps) {
  const sections = buildSections(planSections);
  const activeKey: SectionType | undefined = sections.find((s) => !s.section?.isCompleted)?.type;

  return (
    <div className="state-panel active" data-testid="consult-streaming">
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
        {sections.map(({ type, section }, idx) => {
          const isActive = activeKey === type;
          const _hasContent = (section?.contents.length ?? 0) > 0;
          void _hasContent;
          const showCheck = (section?.isCompleted ?? false) || isActive;
          const bodyHtml = renderBodyHtml(section?.contents ?? [], { active: isActive });

          return (
            <div
              key={type}
              className={`plan-section ${type} streaming-sec${section?.isCompleted ? ' done' : ''}`}
              data-testid={`consult-plan-section-${idx}`}
              data-section={type}
            >
              <div className="plan-section-head">
                <span className="plan-section-label">{SECTION_LABELS[type]}</span>
                <span className={`plan-section-check${showCheck ? ' visible' : ''}`}>✓</span>
              </div>
              <div className="plan-section-body" dangerouslySetInnerHTML={{ __html: bodyHtml }} />
            </div>
          );
        })}
      </div>

      <div className="action-area" data-testid="consult-actions">
        <button className="btn btn-primary" disabled>生成中…</button>
      </div>
      <div className="disclaimer" data-testid="consult-disclaimer">基于归档案例的 AI 生成建议，不构成医疗诊断。严重情况请咨询专业医生。</div>
    </div>
  );
}
