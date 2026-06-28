import { useNavigate, useParams } from 'react-router-dom';
import { useProfile } from '@/logics/profiles';
import PageContent from '@/views/_shared/layout/PageContent';
import './ProfileEditPage.css';

export default function ProfileEditPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { profiles, createProfile } = useProfile();
  const isEdit = Boolean(id);
  const existing = id ? (profiles ?? []).find((p) => p.profile_id === id) : null;

  return (
    <>
      <div className="nav">
        <button className="nav-cancel" onClick={() => navigate(-1)}>取消</button>
        <span className="nav-title">{isEdit ? '编辑档案' : '创建档案'}</span>
        <button className="nav-save" onClick={() => navigate(-1)}>保存</button>
      </div>
      <PageContent>
        <div className="field"><label>昵称<span className="req">*</span></label>
          <input placeholder="请输入昵称" defaultValue={existing?.nickname ?? ''} /></div>
        <div className="field"><label>年龄范围</label>
          <input placeholder="如 4-6 岁" defaultValue={existing?.age_range ?? ''} /></div>
        <div className="field"><label>诊断类型</label>
          <input placeholder="如 ASD" defaultValue={existing?.diagnosis_type ?? ''} /></div>
        <div className="field"><label>主要行为类型</label>
          <input placeholder="可选" defaultValue={existing?.primary_behavior ?? ''} /></div>
      </PageContent>
    </>
  );
}
