import type { ReactNode } from 'react';

interface ReasoningDisclosureProps {
  label: string;
  running: boolean;
  children: ReactNode;
}

/** 相邻的过程与工具事件共享同一个入口，正文和依据继续独立呈现。 */
export function ReasoningDisclosure({ label, running, children }: ReasoningDisclosureProps) {
  return (
    <details className="reasoning-row conversation-disclosure" data-running={running || undefined}>
      <summary>
        <span>{label}</span>
        <span className="disclosure-chevron" aria-hidden="true" />
      </summary>
      <div className="process-body">
        {children}
        <p className="process-note">分析说明是中间状态，不作为结论或依据。</p>
      </div>
    </details>
  );
}
