import { Link } from 'react-router-dom';
import { useHomePage } from '@/logics/shared/hooks/useHomePage';
import { formatRelativeTime } from '@/logics/shared/utils/timeFormat';
import type { ConsultationHistoryListItem } from '@/logics/consult';
import type { ProfileListItem } from '@/logics/profiles';
import {
  SectionHeader,
  ErrorBanner,
  EmptyState,
  GlowLoading,
  Tag,
} from '@/views/_shared/components';
import './HomePage.css';

/* ── Time-based greeting ── */
function getGreeting(): string {
  const h = new Date().getHours();
  if (h >= 5 && h < 12) return '早上好';
  if (h >= 12 && h < 18) return '下午好';
  return '晚上好';
}

/* ═══════════════════════════════════════════════════════════════════
   Sub-components
   ═══════════════════════════════════════════════════════════════════ */

function GreetingSection({ hasProfiles }: { hasProfiles: boolean }) {
  return (
    <div className="home-greeting" data-testid="home-greeting">
      <div className="home-greeting__brand">
        <div className="home-greeting__flame" data-testid="home-greeting-brand">
          <svg viewBox="0 0 28 28" fill="none">
            <path d="M14 2 C8 10 6 14 6 18 A8 8 0 0 0 22 18 C22 14 20 10 14 2Z"
              fill="var(--cf-accent)" opacity="0.25" />
            <path d="M14 7 C10 12 9 15 9 18 A5 5 0 0 0 19 18 C19 15 18 12 14 7Z"
              fill="var(--cf-accent)" opacity="0.45" />
            <circle cx="14" cy="18" r="2.5" fill="var(--cf-accent)" />
          </svg>
        </div>
        <span className="home-greeting__brand-name">篝火智答</span>
      </div>
      <h1 className="home-greeting__title" data-testid="home-greeting-title">
        {getGreeting()}
      </h1>
      <p className="home-greeting__subtitle" data-testid="home-greeting-subtitle">
        {hasProfiles ? '今天孩子状态怎么样？' : '欢迎开始使用篝火智答'}
      </p>
    </div>
  );
}

function EmergencyEntryCard() {
  return (
    <Link className="home-emergency" to="/consult" data-testid="home-emergency">
      <div className="home-emergency__icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round">
          <path d="M12 9v5" /><circle cx="12" cy="16" r="1" fill="currentColor" stroke="none" />
          <circle cx="12" cy="12" r="9" />
        </svg>
      </div>
      <h2 className="home-emergency__title">应急咨询</h2>
      <p className="home-emergency__desc">
        遇到紧急情况？描述当前状况，AI 将在几秒内生成个性化建议
      </p>
      <span className="home-emergency__cta" data-testid="home-emergency-btn">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round">
          <rect x="9" y="1" width="6" height="11" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0" />
          <line x1="12" y1="18" x2="12" y2="23" />
          <line x1="8" y1="23" x2="16" y2="23" />
        </svg>
        立即咨询
      </span>
    </Link>
  );
}

function ConsultPreviewCard({ item }: { item: ConsultationHistoryListItem }) {
  return (
    <Link
      className="home-consult-card"
      to={`/consult/${item.id}`}
      data-testid="home-consult-card"
    >
      <div className="home-consult-card__header">
        <span className="home-consult-card__level">
          <span className="home-consult-card__dot" />
          咨询记录
        </span>
        <span className="home-consult-card__time">
          {formatRelativeTime(item.consultation_time)}
        </span>
      </div>
      <p className="home-consult-card__summary">{item.behavior_description}</p>
      <div className="home-consult-card__tags">
        <Tag label="自伤行为" variant="active" />
      </div>
    </Link>
  );
}

function ProfilePreviewCard({ profile }: { profile: ProfileListItem }) {
  return (
    <Link
      className="home-profile-card"
      to="/profiles"
      data-testid="home-profile-card"
    >
      <div className="home-profile-card__avatar">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="1.8" strokeLinecap="round">
          <circle cx="12" cy="9" r="4" />
          <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" />
        </svg>
      </div>
      <div className="home-profile-card__info">
        <div className="home-profile-card__name-row">
          <span className="home-profile-card__name">{profile.nickname}</span>
          <Tag label={profile.age_range ?? ''} />
          <Tag label={profile.diagnosis_type ?? ''} variant="success" />
        </div>
        <div className="home-profile-card__stats">
          <span>档案已建立</span>
        </div>
      </div>
      <span className="home-profile-card__link">查看</span>
    </Link>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   Page Container
   ═══════════════════════════════════════════════════════════════════ */

export default function HomePage() {
  const { loading, hasError, consultHistory, profiles, profilesLoading, load } =
    useHomePage();
  const hasProfiles = (profiles ?? []).length > 0;
  const latestConsult = consultHistory?.[0];

  return (
    <>
      <GreetingSection hasProfiles={hasProfiles} />

      {hasError && (
        <ErrorBanner
          message="数据加载失败"
          onRetry={load}
        />
      )}

      <EmergencyEntryCard />

      <SectionHeader title="最近咨询" linkTo="/consult/history" />

      {loading ? (
        <GlowLoading />
      ) : latestConsult ? (
        <ConsultPreviewCard item={latestConsult} />
      ) : (
        <EmptyState
          title="暂无咨询记录"
          hint="点击上方「立即咨询」开始第一次对话"
        />
      )}

      <SectionHeader title="个人档案" linkTo="/profiles" />

      {profilesLoading ? (
        <GlowLoading />
      ) : hasProfiles ? (
        <ProfilePreviewCard profile={profiles[0]} />
      ) : (
        <Link className="home-create-card" to="/profiles/edit" data-testid="home-profile-create">
          <div className="home-create-card__icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2" strokeLinecap="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="12" y1="18" x2="12" y2="12" />
              <line x1="9" y1="15" x2="15" y2="15" />
            </svg>
          </div>
          <div className="home-create-card__text">
            <h4>创建孩子的第一份档案</h4>
            <p>完善的档案能帮助 AI 更精准地匹配案例</p>
          </div>
          <span className="home-create-card__link">创建档案 →</span>
        </Link>
      )}
    </>
  );
}
