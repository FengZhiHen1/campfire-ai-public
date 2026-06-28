import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';
import './CaseNarrativeSubmitPage.css';

export default function CaseNarrativeSubmitPage() {
  const navigate = useNavigate();
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [openDD, setOpenDD] = useState(false);
  const [source, setSource] = useState('咨询记录');
  const [extracting, setExtracting] = useState(false);

  const handleSubmit = () => {
    if (!title.trim() || !body.trim()) return;
    setExtracting(true);
    setTimeout(() => navigate('/cases/extraction/1'), 3000);
  };

  if (extracting) {
    return (
      <>
        <div className="nav"><button className="nav-back" onClick={() => navigate(-1)}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg></button><span className="nav-title">AI 正在提取</span></div>
        <div className="extract-state active">
          <div className="glow" /><h2>正在分析叙事…</h2><p>AI 正在提取干预卡片，预计需要 10-30 秒</p>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="nav"><button className="nav-back" onClick={() => navigate(-1)}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg></button><span className="nav-title">提交叙事</span></div>
      <PageContent>
        <div className="field"><label>案例标题</label><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="为这个案例起一个标题" maxLength={50} /><div className="counter">{title.length}/50</div></div>
        <div className="field"><label>来源类型</label>
          <div className={`dd-wrap${openDD ? ' open' : ''}`}>
            <button className="dd-btn" onClick={() => setOpenDD(!openDD)}>{source}</button>
            <div className="dd-menu">
              {['咨询记录','专家录入','文献提取'].map((s) => (
                <button key={s} className={`dd-opt${source === s ? ' selected' : ''}`} onClick={() => { setSource(s); setOpenDD(false); }}>{s}</button>
              ))}
            </div>
          </div>
        </div>
        <div className="field"><label>叙事正文</label><textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="请详细描述事件经过，包括：人物背景、触发情境、行为表现、持续时间、干预措施、结果与后续…" /><div className="counter">{body.length}/2000</div></div>
        <button className="btn" onClick={handleSubmit}>提交并提取卡片</button>
        <button className="btn btn-s" onClick={() => navigate(-1)}>保存草稿</button>
      </PageContent>
    </>
  );
}
