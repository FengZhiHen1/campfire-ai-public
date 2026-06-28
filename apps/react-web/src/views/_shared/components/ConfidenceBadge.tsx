export interface ConfidenceBadgeProps {
  level: 'high' | 'medium' | 'low';
  caseCount: number;
}

const LABELS: Record<ConfidenceBadgeProps['level'], string> = {
  high: '高可信',
  medium: '中可信',
  low: '需人工复核',
};

/**
 * 信心徽章 — 药丸形，三档信任等级。
 * OD 规格：8px 圆角，8×12px 内边距。低信任自动触发人工升级。
 */
export default function ConfidenceBadge({ level, caseCount }: ConfidenceBadgeProps) {
  return (
    <span className={`cf-confidence cf-confidence--${level}`}>
      <span className="cf-confidence__dot" />
      {`基于 ${caseCount} 个相似案例 · ${LABELS[level]}`}
    </span>
  );
}
