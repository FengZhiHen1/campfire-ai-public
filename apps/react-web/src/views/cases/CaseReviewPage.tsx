import { useNavigate } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';

export default function CaseReviewPage() {
  const navigate = useNavigate();
  return (
    <>
      <div className="nav"><button className="nav-back" onClick={() => navigate(-1)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 18l-6-6 6-6"/></svg></button>
        <span className="nav-title">审核工作台</span></div>
      <PageContent><p>审核工作台（待实现）</p></PageContent>
    </>
  );
}
