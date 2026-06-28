export interface TicketGuidePanelProps {
  onGoToTicket: () => void;
  onNewConsult: () => void;
}

export default function TicketGuidePanel({ onGoToTicket, onNewConsult }: TicketGuidePanelProps) {
  return (
    <div className="state-panel active">
      <div className="ticket-guide-area">
        <div className="guide-graphic">
          <svg viewBox="0 0 48 48" fill="none" stroke="var(--cf-accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="24" cy="15" r="6" />
            <path d="M12 42v-8a4 4 0 0 1 4-4h16a4 4 0 0 1 4 4v8" />
            <circle cx="19" cy="14" r="2" fill="var(--cf-accent)" stroke="none" />
            <circle cx="29" cy="14" r="2" fill="var(--cf-accent)" stroke="none" />
            <path d="M14 39c0 0 4-8 10-8s10 8 10 8" />
          </svg>
        </div>
        <h2 className="guide-title">建议联系专家</h2>
        <p className="guide-desc">AI 对当前情况的置信度较低，<br />建议通过人工咨询获取更准确建议</p>
        <div className="guide-actions">
          <button className="btn btn-primary" onClick={onGoToTicket}>联系专家</button>
          <button className="btn btn-secondary" onClick={onNewConsult}>开始新咨询</button>
        </div>
      </div>
      <div className="disclaimer">基于归档案例的 AI 生成建议，不构成医疗诊断。严重情况请咨询专业医生。</div>
    </div>
  );
}
