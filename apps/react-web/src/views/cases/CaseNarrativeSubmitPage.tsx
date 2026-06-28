import { useNavigate } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';

export default function CaseNarrativeSubmitPage() {
  const navigate = useNavigate();
  return (
    <>
      <div className="nav"><button className="nav-cancel" onClick={() => navigate(-1)}>取消</button>
        <span className="nav-title">叙事提交</span><button className="nav-submit">提交</button></div>
      <PageContent><p>叙事提交表单（待实现）</p></PageContent>
    </>
  );
}
