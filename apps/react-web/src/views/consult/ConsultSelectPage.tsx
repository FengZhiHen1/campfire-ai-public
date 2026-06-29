import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useConsult } from '@/logics/consult';
import { useProfile } from '@/logics/profiles';
import type { BehaviorTypeCategory } from '@/logics/consult';
import PageContent from '@/views/_shared/layout/PageContent';
import './ConsultSelectPage.css';

const BEHAVIOR_TYPES: {
  value: BehaviorTypeCategory;
  label: string;
  desc: string;
  icon: React.FC;
}[] = [
  { value: 'SELF_INJURY', label: '自伤行为', desc: '咬手、撞头、抓挠自己等', icon: SelfInjuryIcon },
  { value: 'AGGRESSION', label: '攻击行为', desc: '打人、摔东西、破坏物品等', icon: AggressionIcon },
  { value: 'ELOPEMENT', label: '出走/逃跑', desc: '试图离开安全区域、走失等', icon: ElopementIcon },
  { value: 'MEDICATION', label: '用药相关', desc: '拒绝服药、误服、过量等', icon: MedicationIcon },
  { value: 'EMOTIONAL_MELTDOWN', label: '情绪崩溃', desc: '大哭、尖叫、无法安抚等', icon: MeltdownIcon },
  { value: 'STEREOTYPY', label: '刻板行为', desc: '重复动作、摇晃、排列物品等', icon: StereotypyIcon },
  { value: 'OTHER', label: '其他', desc: '以上都不是，请在下方描述', icon: OtherIcon },
];

function SelfInjuryIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="7" r="2.5" />
      <path d="M5 22v-6a4 4 0 0 1 4-4h1" />
      <path d="M15 12h1a4 4 0 0 1 4 4v6" />
      <line x1="9" y1="16" x2="9" y2="12" />
      <circle cx="12" cy="3" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}

function AggressionIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="9" r="3" />
      <circle cx="16" cy="7" r="3" />
      <path d="M12 12v6" />
      <line x1="8" y1="9" x2="12" y2="12" />
      <line x1="16" y1="7" x2="12" y2="12" />
      <path d="M8 18l-1 4" />
      <path d="M16 18l1 4" />
    </svg>
  );
}

function ElopementIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="5" r="2.5" />
      <path d="M8 16l-1 5h3l1-4" />
      <path d="M16 16l1 5h-3l-1-4" />
      <path d="M9 20h6" />
      <line x1="4" y1="11" x2="6" y2="9" />
      <line x1="6" y1="9" x2="10" y2="10" />
      <path d="M16 7l4 4-4 4" />
    </svg>
  );
}

function MedicationIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="8" y="2" width="8" height="4" rx="1" />
      <line x1="12" y1="2" x2="12" y2="6" />
      <rect x="6" y="6" width="12" height="16" rx="2" />
      <line x1="12" y1="10" x2="12" y2="18" />
      <line x1="8" y1="14" x2="16" y2="14" />
    </svg>
  );
}

function MeltdownIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="8" r="1.5" />
      <circle cx="16" cy="8" r="1.5" />
      <path d="M5 14c0 0 2-4 7-4s7 4 7 4" />
      <path d="M8 14c0 0 2 3 4 3s4-3 4-3" />
      <path d="M7 18c0 0 2 3 5 3s5-3 5-3" />
      <path d="M9 7l2-3 2 3" />
    </svg>
  );
}

function StereotypyIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="8" />
      <path d="M12 4v2" />
      <path d="M12 18v2" />
      <path d="M4 12h2" />
      <path d="M18 12h2" />
      <path d="M7 7l1.5 1.5" />
      <path d="M15.5 15.5L17 17" />
      <path d="M7 17l1.5-1.5" />
      <path d="M15.5 8.5L17 7" />
      <circle cx="12" cy="12" r="2" fill="currentColor" stroke="none" />
    </svg>
  );
}

function OtherIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="6" cy="12" r="2" />
      <circle cx="12" cy="12" r="2" />
      <circle cx="18" cy="12" r="2" />
    </svg>
  );
}

export default function ConsultSelectPage() {
  const navigate = useNavigate();
  const consult = useConsult();
  const { profiles, fetchProfiles } = useProfile();

  useEffect(() => {
    void fetchProfiles();
  }, [fetchProfiles]);

  const handleToggleType = (value: BehaviorTypeCategory) => {
    const current = consult.behaviorTypeSelection;
    const next = current.includes(value)
      ? current.filter((t) => t !== value)
      : [...current, value];
    consult.setBehaviorTypes(next);
  };

  const handleProfileClick = (profileId: string | undefined) => {
    consult.setSelectedProfile(profileId);
  };

  const handleSubmit = () => {
    void consult.submitConsult();
    navigate('/consult');
  };

  return (
    <>
      <div className="nav">
        <button className="nav-back" onClick={() => navigate(-1)} aria-label="返回">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <span className="nav-title">应急咨询</span>
      </div>

      <PageContent>
        <div className="content-wrap">
          <div className="block-header">
            <h2>描述当前行为</h2>
            <p>选择行为类型，以便匹配最相似的案例</p>
          </div>

          {profiles?.length > 0 && (
            <div className="block-profiles">
              <p className="block-profiles-label">关联档案（可选）</p>
              <div className="chip-scroll">
                <button
                  className={`chip${consult.selectedProfileId === undefined ? ' selected' : ''}`}
                  onClick={() => handleProfileClick(undefined)}
                >
                  不关联
                </button>
                {(profiles ?? []).map((p) => (
                  <button
                    key={p.profile_id}
                    className={`chip${consult.selectedProfileId === p.profile_id ? ' selected' : ''}`}
                    onClick={() => handleProfileClick(p.profile_id)}
                  >
                    {p.nickname ?? '未命名'}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="block-types">
            <p className="block-label">行为类型（可多选）</p>
            <div className="type-list" role="group" aria-label="行为类型">
              {BEHAVIOR_TYPES.map((bt) => {
                const selected = consult.behaviorTypeSelection.includes(bt.value);
                const Icon = bt.icon;
                return (
                  <div
                    key={bt.value}
                    className={`type-item${selected ? ' selected' : ''}`}
                    onClick={() => handleToggleType(bt.value)}
                    role="button"
                    tabIndex={0}
                    aria-pressed={selected}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        handleToggleType(bt.value);
                      }
                    }}
                  >
                    <div className="type-icon">
                      <Icon />
                    </div>
                    <div className="type-text">
                      <div className="type-name">{bt.label}</div>
                      <div className="type-desc">{bt.desc}</div>
                    </div>
                    <div className="type-indicator" />
                  </div>
                );
              })}
            </div>
          </div>

          <div className="block-emotion">
            <p className="block-label">情绪等级</p>
            <div className="segmented" role="group" aria-label="情绪等级">
              {(['轻', '中', '重'] as const).map((level) => (
                <button
                  key={level}
                  className={`seg-btn${consult.emotionLevel === level ? ' selected' : ''}`}
                  onClick={() => consult.setEmotionLevel(level)}
                  aria-pressed={consult.emotionLevel === level}
                >
                  {level}度
                </button>
              ))}
            </div>
          </div>

          <div className="block-desc">
            <p className="block-label">补充描述</p>
            <textarea
              className="desc-textarea"
              placeholder="例如：孩子在商场突然捂住耳朵蹲下尖叫，持续了约5分钟…"
              maxLength={2000}
              value={consult.behaviorDescription}
              onChange={(e) => consult.setBehaviorDescription(e.target.value)}
              rows={5}
            />
            <p className="desc-counter">{consult.behaviorDescription.length} / 2000</p>
          </div>

          <div className="block-actions">
            <button
              className="btn btn-primary"
              disabled={!consult.isInputValid}
              onClick={handleSubmit}
            >
              获取应急建议
            </button>
          </div>
        </div>
      </PageContent>
    </>
  );
}
