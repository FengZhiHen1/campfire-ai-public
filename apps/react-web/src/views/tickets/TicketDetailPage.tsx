import { useNavigate, useParams } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';
import './TicketDetailPage.css';

export default function TicketDetailPage() {
  const { id: _id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  return (
    <>
      <div className="nav">
        <button className="nav-back" onClick={() => navigate(-1)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
        </button>
        <span className="nav-title">人工咨询</span>
      </div>
      <PageContent>
        <div className="ticket-content">
          <div className="icon">
            <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <rect x="8" y="6" width="32" height="36" rx="4"/><line x1="24" y1="14" x2="24" y2="18"/>
              <circle cx="24" cy="26" r="3"/><line x1="24" y1="32" x2="24" y2="36"/>
            </svg>
          </div>
          <h2>人工咨询通道建设中</h2>
          <p>人工咨询通道正在建设中，敬请期待。如情况紧急，请直接联系专业医疗机构。</p>
          <button className="btn btn-p" onClick={() => navigate(-1)}>返回</button>
        </div>
      </PageContent>
    </>
  );
}
