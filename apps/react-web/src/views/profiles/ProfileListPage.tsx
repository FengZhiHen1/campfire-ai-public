import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useProfile } from '@/logics/profiles';
import { useQuickRecord } from '@/logics/profiles/hooks/useQuickRecord';
import { listEvents } from '@/logics/profiles/services/eventApi';
import {
  BEHAVIOR_OPTIONS,
  BEHAVIOR_VALUES,
  DIAGNOSIS_SHORT_LABELS,
} from '@/logics/profiles/constants';
import type { EventListItem } from '@campfire/ts-shared';
import PageContent from '@/views/_shared/layout/PageContent';
import './ProfileListPage.css';

const OD_BEHAVIOR_OPTIONS = ['自伤行为', '攻击行为', '刻板行为', '情绪崩溃', '社交退缩', '多动'];
const SEVERITY_OPTIONS = ['轻度', '中度', '重度'];
const SETTING_OPTIONS: { label: string; value: string }[] = [
  { label: '不限', value: '' },
  { label: '家庭', value: '家庭' },
  { label: '学校', value: '学校' },
  { label: '公共场合', value: '公共场合' },
];

function formatEventTime(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function formatEventText(evt: EventListItem): string {
  const parts: string[] = [];
  if (evt.trigger_description) parts.push(evt.trigger_description);
  if (evt.manifestation) parts.push(evt.manifestation);
  const base = parts.join('，');
  const suffix = `情绪等级：${evt.severity_level}`;
  return base ? `${base}。${suffix}` : suffix;
}

function behaviorLabel(value: string): string {
  const idx = BEHAVIOR_VALUES.indexOf(value as (typeof BEHAVIOR_VALUES)[number]);
  return idx >= 0 ? BEHAVIOR_OPTIONS[idx] : value;
}

export default function ProfileListPage() {
  const { profiles, isLoading, error, fetchProfiles } = useProfile();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [events, setEvents] = useState<EventListItem[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [collapseOpen, setCollapseOpen] = useState(false);
  const [toastMsg, setToastMsg] = useState<string | null>(null);

  const list = profiles ?? [];

  useEffect(() => {
    void fetchProfiles();
  }, [fetchProfiles]);

  useEffect(() => {
    const first = (profiles ?? [])[0];
    if (activeId === null && first) {
      setActiveId(first.profile_id);
    }
  }, [profiles, activeId]);

  const activeProfile = list.find((p) => p.profile_id === activeId) ?? list[0];

  useEffect(() => {
    const profileId = activeProfile?.profile_id;
    if (!profileId) return;

    let cancelled = false;
    setEventsLoading(true);
    listEvents(profileId)
      .then((items) => {
        if (!cancelled) setEvents(items);
      })
      .catch(() => {
        if (!cancelled) setEvents([]);
      })
      .finally(() => {
        if (!cancelled) setEventsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeProfile?.profile_id]);

  const sortedEvents = useMemo(
    () => [...events].sort((a, b) => new Date(b.event_time).getTime() - new Date(a.event_time).getTime()),
    [events],
  );

  const record = useQuickRecord(activeProfile?.profile_id ?? '', (newEvents) => {
    setEvents(newEvents);
    setSheetOpen(false);
    setToastMsg('记录已保存');
    window.setTimeout(() => setToastMsg((msg) => (msg === '记录已保存' ? null : msg)), 1800);
  });
  const { reset: resetRecord } = record;

  useEffect(() => {
    if (sheetOpen) {
      resetRecord();
      setCollapseOpen(false);
    }
  }, [sheetOpen, resetRecord]);

  const canSubmit =
    Boolean(record.form.behaviorType) &&
    Boolean(record.form.severity) &&
    record.form.trigger.trim().length > 0 &&
    record.form.manifest.trim().length > 0 &&
    !record.isSubmitting;

  return (
    <>
      <div className="nav">
        <div className="nav-brand"><span>个人档案</span></div>
        <Link
          className="nav-edit"
          to={activeProfile ? `/profiles/edit/${activeProfile.profile_id}` : '/profiles/edit'}
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M11 2l3 3-9 9H2v-3l9-9z" />
          </svg>
          编辑
        </Link>
      </div>

      <PageContent>
        {isLoading ? (
          <div className="glow-loading" />
        ) : error ? (
          <div className="cold">
            <h2>加载失败</h2>
            <p>{error.message}</p>
            <button className="btn btn-p" onClick={() => void fetchProfiles()}>重试</button>
          </div>
        ) : list.length > 0 ? (
          <>
            <div className="chip-scroll">
              {list.map((p, i) => (
                <button
                  key={p.profile_id}
                  className={`chip${p.profile_id === activeId ? ' active' : ''}`}
                  onClick={() => setActiveId(p.profile_id)}
                >
                  <div className="chip-avatar">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                      <circle cx="12" cy="9" r="4" />
                      <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" />
                    </svg>
                  </div>
                  <span className="chip-name">{p.nickname ?? `档案${i + 1}`}</span>
                </button>
              ))}
              {list.length < 5 && (
                <Link className="chip chip-add" to="/profiles/edit">
                  <div className="chip-avatar">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <line x1="12" y1="5" x2="12" y2="19" />
                      <line x1="5" y1="12" x2="19" y2="12" />
                    </svg>
                  </div>
                  <span className="chip-name">添加</span>
                </Link>
              )}
            </div>

            {activeProfile && (
              <>
                <div className="info-card">
                  <div className="info-head">
                    <div className="info-avatar">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                        <circle cx="12" cy="9" r="4" />
                        <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" />
                      </svg>
                    </div>
                    <div className="info-meta">
                      <h3>{activeProfile.nickname ?? '未命名档案'}</h3>
                      <span>{activeProfile.age_range} 岁</span>
                    </div>
                  </div>
                  <div className="info-tags">
                    <span className="info-tag d">
                      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                        <rect x="3" y="1" width="10" height="14" rx="2" />
                        <line x1="3" y1="5" x2="13" y2="5" />
                      </svg>
                      {activeProfile.birth_date ?? '—'}
                    </span>
                    <span className="info-tag p">
                      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                        <path d="M2 4h2l1 8h6l1-8h2" />
                      </svg>
                      {DIAGNOSIS_SHORT_LABELS[activeProfile.diagnosis_type] ?? activeProfile.diagnosis_type}
                    </span>
                    <span className="info-tag r">
                      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                        <polygon points="8 2 10 6 14 7 11 10 12 14 8 12 4 14 5 10 2 7 6 6" />
                      </svg>
                      {behaviorLabel(activeProfile.primary_behavior)}
                    </span>
                  </div>
                </div>

                <div className="tl-head">
                  <h4>事件记录（共 {sortedEvents.length} 条）</h4>
                </div>

                {eventsLoading ? (
                  <div className="glow-loading" style={{ marginTop: 12 }} />
                ) : sortedEvents.length > 0 ? (
                  <div className="timeline">
                    {sortedEvents.map((evt, idx) => (
                      <div
                        key={evt.event_id}
                        className="tl-item"
                        style={{ '--tl-index': idx } as React.CSSProperties}
                      >
                        <div className="tl-dot" />
                        <div className="tl-date">{formatEventTime(evt.event_time)}</div>
                        <div className="tl-text">{formatEventText(evt)}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty">
                    <div className="emp-icon">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                      </svg>
                    </div>
                    <h3>暂无事件记录</h3>
                    <p>记录行为事件以追踪变化趋势</p>
                  </div>
                )}
              </>
            )}
          </>
        ) : (
          <div className="cold">
            <div className="cold-illust">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <circle cx="12" cy="9" r="4" />
                <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" />
              </svg>
            </div>
            <h2>创建孩子的第一份档案</h2>
            <p>完善的档案能帮助 AI 更精准地匹配案例</p>
            <Link className="btn btn-p" to="/profiles/edit">创建档案</Link>
          </div>
        )}
      </PageContent>

      {activeProfile && (
        <button
          className="fab"
          type="button"
          aria-label="记录行为事件"
          onClick={() => setSheetOpen(true)}
        >
          +
        </button>
      )}

      <div
        className={`overlay${sheetOpen ? ' open' : ''}`}
        onClick={() => setSheetOpen(false)}
        aria-hidden="true"
      />

      <div className={`sheet${sheetOpen ? ' open' : ''}`} role="dialog" aria-modal="true" aria-labelledby="record-sheet-title">
        <div className="sheet-scroll">
          <div className="sheet-handle-wrap"><div className="sheet-handle" /></div>
          <h2 id="record-sheet-title" className="sheet-title">记录行为事件</h2>
          <p className="sheet-subtitle">完整记录有助于 AI 精准匹配案例</p>

          <div className="sec-div">事件分类</div>
          <p className="f-label">行为类型<span className="req">*</span></p>
          <div className="chip-grid">
            {OD_BEHAVIOR_OPTIONS.map((label) => (
              <button
                key={label}
                type="button"
                className={`e-chip${record.form.behaviorType === label ? ' selected' : ''}`}
                onClick={() => record.setField('behaviorType', label)}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="f-group">
            <p className="f-label">严重程度<span className="req">*</span></p>
            <div className="segmented">
              {SEVERITY_OPTIONS.map((label) => (
                <button
                  key={label}
                  type="button"
                  className={`seg-btn${record.form.severity === label ? ' selected' : ''}`}
                  onClick={() => record.setField('severity', label)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="sec-div">发生场景</div>
          <p className="f-label">发生场景（可选）</p>
          <div className="chip-row">
            {SETTING_OPTIONS.map(({ label, value }) => (
              <button
                key={label}
                type="button"
                className={`e-chip${record.form.setting === value ? ' selected' : ''}`}
                onClick={() => record.setField('setting', value)}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="sec-div">事件描述</div>
          <div className="f-group">
            <p className="f-label">触发因素<span className="req">*</span></p>
            <input
              className="f-input"
              value={record.form.trigger}
              onChange={(e) => record.setField('trigger', e.target.value)}
              placeholder="如：在超市遇到噪音刺激…"
            />
          </div>
          <div className="f-group">
            <p className="f-label">具体表现<span className="req">*</span></p>
            <textarea
              className="f-textarea"
              value={record.form.manifest}
              onChange={(e) => record.setField('manifest', e.target.value)}
              placeholder="如：突然捂耳蹲下，持续约3分钟…"
            />
          </div>

          <button
            type="button"
            className={`collapse-tgl${collapseOpen ? ' open' : ''}`}
            onClick={() => setCollapseOpen((v) => !v)}
          >
            干预记录（可选）<span className="c-arrow">▶</span>
          </button>
          <div className={`c-body${collapseOpen ? ' open' : ''}`}>
            <div className="f-group">
              <p className="f-label">尝试的干预措施</p>
              <input
                className="f-input"
                value={record.form.intervention}
                onChange={(e) => record.setField('intervention', e.target.value)}
                placeholder="如：带离现场，使用降噪耳机…"
              />
            </div>
            <div className="f-group">
              <p className="f-label">干预结果</p>
              <input
                className="f-input"
                value={record.form.result}
                onChange={(e) => record.setField('result', e.target.value)}
                placeholder="如：情绪逐渐平复…"
              />
            </div>
          </div>

          <button
            className={`btn-submit${record.isSubmitting ? ' loading' : ''}`}
            disabled={!canSubmit}
            onClick={() => void record.submit()}
          >
            {record.isSubmitting ? '保存中…' : '保存记录'}
          </button>
        </div>
      </div>

      <div className={`toast${toastMsg ? ' show' : ''}`}>{toastMsg}</div>
    </>
  );
}
