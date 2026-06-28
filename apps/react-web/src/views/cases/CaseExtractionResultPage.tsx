import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';
import './CaseExtractionResultPage.css';

export default function CaseExtractionResultPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [infOpen, setInfOpen] = useState(false);
  const [phase, setPhase] = useState<'result' | 'extracting' | 'error'>('result');

  if (phase === 'extracting') {
    return (
      <>
        <div className="nav"><button className="nav-back" onClick={() => navigate(-1)}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg></button><span className="nav-title">提取结果</span></div>
        <div className="extracting active">
          <div className="ext-ring" /><h3>AI 正在分析叙事内容…</h3><p>预计需要 10–30 秒</p><div className="ext-progress" />
        </div>
      </>
    );
  }

  if (phase === 'error') {
    return (
      <>
        <div className="nav"><button className="nav-back" onClick={() => navigate(-1)}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg></button><span className="nav-title">提取结果</span></div>
        <div className="error-state active">
          <div className="err-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div>
          <h3>提取失败</h3><p>AI 处理过程中出现异常，请返回重试</p>
          <div className="error-actions"><button className="btn btn-p" onClick={() => setPhase('result')}>重试</button><button className="btn btn-s" onClick={() => navigate(-1)}>返回修改叙事</button></div>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="nav">
        <button className="nav-back" onClick={() => navigate(-1)}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg></button>
        <span className="nav-title">提取结果</span>
      </div>
      <PageContent>
        <div className="banner"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>AI 从叙事中提取了 <strong>4</strong> 张干预卡片</div>
        <div className="tab-scroll">
          {['卡片 1', '卡片 2', '卡片 3', '卡片 4'].map((t, i) => (
            <button key={i} className={`tab-chip${i === 0 ? ' active' : ''}`}>{t}</button>
          ))}
        </div>
        <div className="form-wrap">
          <div className="field"><div className="field-label">卡片标题</div><input defaultValue="即时环境隔离与缓冲保护" /></div>
          <div className="field"><div className="field-label">适用场景</div><textarea defaultValue="商场、餐厅等高噪音公共场合" /></div>
          <div className="field"><div className="field-label">行为类型</div>
            <div className="chip-grid">{['自伤行为','攻击行为','出走/逃跑','情绪崩溃','刻板行为','用药相关','其他'].map((b) => (
              <button key={b} className={`chip-btn${b === '自伤行为' ? ' selected' : ''}`}>{b}</button>
            ))}</div>
          </div>
          <div className="field"><div className="field-label">严重程度</div>
            <div className="chip-grid">{['轻度','中度','重度'].map((s) => (
              <button key={s} className={`chip-btn${s === '中度' ? ' selected' : ''}`}>{s}</button>
            ))}</div>
          </div>
          <div className="qrt-section">
            {[{ key: 'action', label: '即时安全干预', accent: 'action', content: '1. 立即将孩子移至安静环境\n2. 移除周围尖锐物品\n3. 蹲下与孩子平视，低沉平稳喊名\n4. 用外套或靠垫做缓冲保护' },
              { key: 'soothe', label: '情绪安抚话术', accent: 'soothe', content: '"我听到了，这里太吵了对不对？我们先去一个安静的地方。"\n• 语速放慢至正常语速的 60%\n• 如拒绝言语接触，保持安静陪伴' },
              { key: 'observe', label: '观察指标', accent: 'observe', content: '• 自伤行为是否在 5 分钟内减弱\n• 是否有向他人攻击的转向行为\n• 尖叫是否在 3 分钟内停止\n• 呼吸是否逐渐平稳' },
              { key: 'medical', label: '就医判断', accent: 'medical', content: '• 如 10 分钟后未减弱，联系值班专家\n• 如意识模糊/呕吐，立即拨打 120\n• 如头部明显肿胀或流血，前往急诊' },
            ].map((s) => (
              <div key={s.key} className={`qrt-card ${s.accent}`}>
                <h5>{s.label}</h5>
                <textarea defaultValue={s.content} />
              </div>
            ))}
          </div>
        </div>
        <div className="inf-panel">
          <button className={`inf-toggle${infOpen ? ' open' : ''}`} onClick={() => setInfOpen(!infOpen)}>AI 推断说明</button>
          <div className={`inf-body${infOpen ? ' open' : ''}`}>
            <div className="inf-item"><span className="inf-field">行为类型</span><span className="inf-reason">AI从原文&ldquo;蹲下尖叫、躺地上打滚&rdquo;推断为自伤行为</span></div>
            <div className="inf-item"><span className="inf-field">循证等级</span><span className="inf-reason">基于单次叙事提取，未经过专家交叉验证</span></div>
          </div>
        </div>
      </PageContent>
      <div className="footer-bar">
        <button className="btn btn-p">保存当前卡片</button>
        <button className="btn btn-outline" onClick={() => navigate('/cases')}>全部提交审核</button>
      </div>
    </>
  );
}
