import { useParams, useNavigate } from 'react-router-dom';
import { useCaseDetail } from '@/logics/cases/hooks/useCaseDetail';
import PageContent from '@/views/_shared/layout/PageContent';

export default function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { detail, loading } = useCaseDetail(id ?? '');

  return (
    <>
      <div className="nav"><button className="nav-back" onClick={() => navigate(-1)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 18l-6-6 6-6"/></svg></button>
        <span className="nav-title">案例详情</span></div>
      <PageContent>
        {loading ? <div className="glow-loading" /> : detail ? (
          <div className="detail"><h2>{detail.title}</h2><p>{detail.content}</p></div>
        ) : <p>案例不存在</p>}
      </PageContent>
    </>
  );
}
