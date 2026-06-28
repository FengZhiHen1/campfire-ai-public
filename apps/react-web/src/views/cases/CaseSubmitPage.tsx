import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';
import './CaseSubmitPage.css';

type DropdownState = { open: string | null };

export default function CaseSubmitPage() {
  const navigate = useNavigate();
  const [openDD, setOpenDD] = useState<string | null>(null);
  const toggle = (id: string) => setOpenDD((p) => p === id ? null : id);
  const [type, setType] = useState('自伤行为');

  return (
    <>
      <div className="nav">
        <button className="nav-cancel" onClick={() => navigate(-1)}>取消</button>
        <span className="nav-title">提交案例</span>
        <button className="nav-submit" onClick={() => navigate(-1)}>提交</button>
      </div>
      <PageContent>
        <div className="cover">
          <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <rect x="2" y="6" width="28" height="20" rx="2"/><circle cx="11" cy="14" r="2"/><path d="M2 22l8-6 6 4 6-6 8 8"/>
          </svg>
          <span>点击上传封面图（可选）</span>
        </div>
        <div className="field"><label><span className="req">*</span> 案例标题</label><input placeholder="请输入案例标题" /></div>
        <div className="row">
          <div className="field"><label><span className="req">*</span> 行为类型</label>
            <div className={`dd-wrap${openDD === 'type' ? ' open' : ''}`}>
              <button className="dd-btn" onClick={() => toggle('type')}>{type}</button>
              <div className="dd-menu">
                {['自伤行为','攻击行为','出走/逃跑','用药相关','情绪崩溃','刻板行为'].map((t) => (
                  <button key={t} className={`dd-opt${type === t ? ' selected' : ''}`} onClick={() => { setType(t); setOpenDD(null); }}>{t}</button>
                ))}
              </div>
            </div>
          </div>
          <div className="field"><label><span className="req">*</span> 严重程度</label>
            <div className={`dd-wrap${openDD === 'severity' ? ' open' : ''}`}>
              <button className="dd-btn" onClick={() => toggle('severity')}>中度</button>
              <div className="dd-menu">
                {['轻度','中度','重度'].map((s) => (
                  <button key={s} className="dd-opt" onClick={() => setOpenDD(null)}>{s}</button>
                ))}
              </div>
            </div>
          </div>
        </div>
        <div className="row">
          <div className="field"><label><span className="req">*</span> 发生场景</label>
            <div className={`dd-wrap${openDD === 'scene' ? ' open' : ''}`}>
              <button className="dd-btn" onClick={() => toggle('scene')}>公共场合</button>
              <div className="dd-menu">
                {['家庭','学校','公共场合','机构'].map((s) => (
                  <button key={s} className="dd-opt" onClick={() => setOpenDD(null)}>{s}</button>
                ))}
              </div>
            </div>
          </div>
          <div className="field"><label>证据等级</label>
            <div className={`dd-wrap${openDD === 'evidence' ? ' open' : ''}`}>
              <button className="dd-btn" onClick={() => toggle('evidence')}>基于叙事</button>
              <div className="dd-menu">
                {['基于叙事','专家验证','文献支持'].map((e) => (
                  <button key={e} className="dd-opt" onClick={() => setOpenDD(null)}>{e}</button>
                ))}
              </div>
            </div>
          </div>
        </div>
        <div className="field"><label><span className="req">*</span> 叙事正文</label><textarea placeholder="请详细描述事件经过…" /></div>
      </PageContent>
    </>
  );
}
