import { useParams, useNavigate } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';

export default function CaseCardDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  return (
    <>
      <div className="nav"><button className="nav-back" onClick={() => navigate(-1)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 18l-6-6 6-6"/></svg></button>
        <span className="nav-title">案例卡片</span></div>
      <PageContent><p>案例卡片 {id}</p></PageContent>
    </>
  );
}
