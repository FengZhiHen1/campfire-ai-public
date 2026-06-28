import { useNavigate } from 'react-router-dom';
import { useConsult } from '@/logics/consult';
import type { BehaviorTypeCategory, EmotionLevel } from '@/logics/consult';
import PageContent from '@/views/_shared/layout/PageContent';
import './ConsultSelectPage.css';

const BEHAVIOR_TYPES: { value: BehaviorTypeCategory; label: string }[] = [
  { value: 'SELF_INJURY', label: '自伤行为' },
  { value: 'AGGRESSION', label: '攻击行为' },
  { value: 'ELOPEMENT', label: '出走/逃跑' },
  { value: 'EMOTIONAL_MELTDOWN', label: '情绪崩溃' },
  { value: 'STEREOTYPY', label: '刻板行为' },
  { value: 'MEDICATION', label: '用药相关' },
  { value: 'OTHER', label: '其他' },
];

export default function ConsultSelectPage() {
  const navigate = useNavigate();
  const consult = useConsult();

  const handleSubmit = () => {
    consult.submitConsult();
    navigate('/consult');
  };

  return (
    <>
      <div className="nav">
        <button className="nav-back" onClick={() => navigate(-1)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
        </button>
        <span className="nav-title">描述行为</span>
      </div>
      <PageContent>
        <div className="block-header">
          <h2>描述孩子当前的行为</h2>
          <p>选择行为类型并描述具体情况</p>
        </div>

        <div className="block-types">
          <p className="block-label">行为类型<span className="req">*</span></p>
          <div className="chip-grid">
            {BEHAVIOR_TYPES.map((bt) => (
              <button key={bt.value} className={`e-chip${consult.behaviorTypeSelection.includes(bt.value) ? ' selected' : ''}`}
                onClick={() => consult.setBehaviorTypes(
                  consult.behaviorTypeSelection.includes(bt.value)
                    ? consult.behaviorTypeSelection.filter((t) => t !== bt.value)
                    : [...consult.behaviorTypeSelection, bt.value]
                )}>
                {bt.label}
              </button>
            ))}
          </div>
        </div>

        <div className="block-emotion">
          <p className="block-label">情绪等级</p>
          <div className="segmented">
            {(['轻', '中', '重'] as EmotionLevel[]).map((level) => (
              <button key={level} className={`seg-btn${consult.emotionLevel === level ? ' selected' : ''}`}
                onClick={() => consult.setEmotionLevel(level)}>
                {level}度
              </button>
            ))}
          </div>
        </div>

        <div className="block-desc">
          <p className="block-label">行为描述<span className="req">*</span></p>
          <textarea className="f-textarea" placeholder="描述孩子正在发生的情况…"
            value={consult.behaviorDescription}
            onChange={(e) => consult.setBehaviorDescription(e.target.value)}
            rows={5} />
        </div>

        <div className="action-wrap">
          <button className="btn-submit" disabled={!consult.isInputValid} onClick={handleSubmit}>
            提交咨询
          </button>
        </div>
      </PageContent>
    </>
  );
}
