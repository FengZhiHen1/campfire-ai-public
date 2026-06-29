import { useNavigate, useParams } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';
import {
  useCaseCardDetail,
  BEHAVIOR_TYPE_OPTIONS,
  BEHAVIOR_TYPE_VALUES,
  SEVERITY_OPTIONS,
  SEVERITY_VALUES,
  SCENE_OPTIONS,
  SCENE_VALUES,
  EVIDENCE_LEVEL_OPTIONS,
  EVIDENCE_LEVEL_VALUES,
} from '@/logics/cases';
import './CaseCardDetailPage.css';

const BEHAVIOR_LABEL_MAP: Record<string, string> = BEHAVIOR_TYPE_VALUES.reduce(
  (acc, val, idx) => ({ ...acc, [val]: BEHAVIOR_TYPE_OPTIONS[idx] }),
  {},
);
const SEVERITY_LABEL_MAP: Record<string, string> = SEVERITY_VALUES.reduce(
  (acc, val, idx) => ({ ...acc, [val]: SEVERITY_OPTIONS[idx] }),
  {},
);
const SCENE_LABEL_MAP: Record<string, string> = SCENE_VALUES.reduce(
  (acc, val, idx) => ({ ...acc, [val]: SCENE_OPTIONS[idx] }),
  {},
);
const EVIDENCE_LABEL_MAP: Record<string, string> = EVIDENCE_LEVEL_VALUES.reduce(
  (acc, val, idx) => ({ ...acc, [val]: EVIDENCE_LEVEL_OPTIONS[idx] }),
  {},
);

export default function CaseCardDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data, loading, error, refetch } = useCaseCardDetail();

  if (loading) {
    return (
      <>
        <div className="nav">
          <button className="nav-back" onClick={() => navigate(-1)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
          </button>
          <span className="nav-title">干预卡片</span>
        </div>
        <PageContent><div style={{ textAlign: 'center', padding: 40, color: 'var(--cf-muted)' }}>加载中…</div></PageContent>
      </>
    );
  }

  if (error || !data) {
    return (
      <>
        <div className="nav">
          <button className="nav-back" onClick={() => navigate(-1)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
          </button>
          <span className="nav-title">干预卡片</span>
        </div>
        <PageContent>
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--cf-danger)' }}>
            {error ?? '卡片不存在'}
          </div>
          <button className="btn" onClick={refetch}>重试</button>
        </PageContent>
      </>
    );
  }

  const ageLabel = data.age_range && data.age_range.length === 2
    ? `${data.age_range[0]}-${data.age_range[1]}岁`
    : '';

  return (
    <>
      <div className="nav">
        <button className="nav-back" onClick={() => navigate(-1)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
        </button>
        <span className="nav-title">干预卡片</span>
      </div>
      <PageContent>
        <div className="meta">
          <span>{BEHAVIOR_LABEL_MAP[data.behavior_type] ?? data.behavior_type}</span>
          <span>{SEVERITY_LABEL_MAP[data.severity] ?? data.severity}</span>
          <span>{SCENE_LABEL_MAP[data.scene] ?? data.scene}</span>
          {ageLabel && <span>{ageLabel}</span>}
        </div>
        <div className="quartet">
          <h3>{data.title}</h3>
          {data.scenario && (
            <div className="q-section observation">
              <div className="q-head">适用场景</div>
              <div className="q-body">{data.scenario}</div>
            </div>
          )}
          <div className="q-section immediate">
            <div className="q-head">即时安全干预动作</div>
            <div className="q-body">{data.immediate_action}</div>
          </div>
          <div className="q-section comforting">
            <div className="q-head">情绪安抚话术</div>
            <div className="q-body">{data.comforting_phrase}</div>
          </div>
          <div className="q-section observation">
            <div className="q-head">后续观察指标</div>
            <div className="q-body">{data.observation_metrics}</div>
          </div>
          <div className="q-section medical">
            <div className="q-head">就医判断标准</div>
            <div className="q-body">{data.medical_criteria}</div>
          </div>
          {data.caution_notes && (
            <div className="q-note info">{data.caution_notes}</div>
          )}
        </div>
        <div className="footer-label">
          <span>证据等级</span>
          <span style={{ fontWeight: 600 }}>{EVIDENCE_LABEL_MAP[data.evidence_level] ?? data.evidence_level}</span>
        </div>
      </PageContent>
    </>
  );
}
