import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';
import {
  useProfile,
  DIAGNOSIS_OPTIONS,
  DIAGNOSIS_VALUES,
  BEHAVIOR_OPTIONS,
  BEHAVIOR_VALUES,
  SENSORY_FEATURE_TAGS,
  SENSORY_FEATURE_LABELS,
  TRIGGER_TAGS,
  TRIGGER_LABELS,
  NICKNAME_MAX_LENGTH,
  TRIGGER_MAX_COUNT,
} from '@/logics/profiles';
import * as eventApi from '@/logics/profiles/services/eventApi';
import type { ProfileCreate, ProfileUpdate, EventListItem } from '@/logics/profiles';
import './ProfileEditPage.css';

interface FormState {
  nickname: string;
  birth_date: string;
  diagnosis_idx: number;
  behavior_idx: number;
  sensory_features: string[];
  triggers: string[];
}

const EMPTY_FORM: FormState = {
  nickname: '',
  birth_date: '',
  diagnosis_idx: 0,
  behavior_idx: 0,
  sensory_features: [],
  triggers: [],
};

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function formatEventTime(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

function eventTitle(ev: EventListItem): string {
  return `${formatEventTime(ev.event_time)} ${ev.behavior_type}`;
}

const CheckIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12" />
  </svg>
);

const UserIcon = () => (
  <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="24" cy="18" r="8" />
    <path d="M10 42v-2a10 10 0 0 1 10-10h8a10 10 0 0 1 10 10v2" />
  </svg>
);

const CameraIcon = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2l-6 10-4-3" />
  </svg>
);

const TagIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" />
    <line x1="7" y1="7" x2="7.01" y2="7" />
  </svg>
);

export default function ProfileEditPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { profiles, getProfile, createProfile, updateProfile, deleteProfile } = useProfile();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [customTrigger, setCustomTrigger] = useState('');
  const [openDD, setOpenDD] = useState<string | null>(null);
  const [triggerAtLimit, setTriggerAtLimit] = useState(false);

  // 达到上限时的闪烁提示，1.5s 后自动消失
  useEffect(() => {
    if (!triggerAtLimit) return;
    const t = setTimeout(() => setTriggerAtLimit(false), 1500);
    return () => clearTimeout(t);
  }, [triggerAtLimit]);

  const [events, setEvents] = useState<EventListItem[]>([]);
  const [eventsExpanded, setEventsExpanded] = useState(true);
  const [eventsLoading, setEventsLoading] = useState(false);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const isEdit = Boolean(id);
  const existingFromList = id ? (profiles ?? []).find((p) => p.profile_id === id) : null;

  useEffect(() => {
    if (!id) return;
    if (existingFromList) return;
    setLoading(true);
    getProfile(id)
      .then((p) => {
        setForm({
          nickname: p.nickname ?? '',
          birth_date: p.birth_date ?? '',
          diagnosis_idx: Math.max(0, DIAGNOSIS_VALUES.indexOf(p.diagnosis_type)),
          behavior_idx: Math.max(0, BEHAVIOR_VALUES.indexOf(p.primary_behavior)),
          sensory_features: p.sensory_features ?? [],
          triggers: p.triggers ?? [],
        });
      })
      .catch(() => setError('加载档案失败'))
      .finally(() => setLoading(false));
  }, [id, existingFromList, getProfile]);

  useEffect(() => {
    if (!id || !existingFromList) return;
    setForm({
      nickname: existingFromList.nickname ?? '',
      birth_date: '',
      diagnosis_idx: Math.max(0, DIAGNOSIS_VALUES.indexOf(existingFromList.diagnosis_type)),
      behavior_idx: Math.max(0, BEHAVIOR_VALUES.indexOf(existingFromList.primary_behavior)),
      sensory_features: [],
      triggers: [],
    });
  }, [id, existingFromList]);

  useEffect(() => {
    if (!id) return;
    setEventsLoading(true);
    eventApi
      .listEvents(id)
      .then((items) => setEvents(items))
      .catch(() => setEvents([]))
      .finally(() => setEventsLoading(false));
  }, [id]);

  useEffect(() => {
    function closeDropdown(e: MouseEvent) {
      const target = e.target as HTMLElement;
      if (!target.closest('.dd-wrap')) {
        setOpenDD(null);
      }
    }
    document.addEventListener('click', closeDropdown);
    return () => document.removeEventListener('click', closeDropdown);
  }, []);

  const toggleArray = (field: 'sensory_features' | 'triggers', value: string) => {
    setForm((prev) => {
      const arr = prev[field];
      if (field === 'triggers' && !arr.includes(value) && arr.length >= TRIGGER_MAX_COUNT) {
        setTriggerAtLimit(true);
        return prev;
      }
      const next = arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value];
      return { ...prev, [field]: next };
    });
  };

  const addCustomTrigger = () => {
    const v = customTrigger.trim();
    if (!v) return;
    if (form.triggers.includes(v)) return;
    if (form.triggers.length >= TRIGGER_MAX_COUNT) {
      setTriggerAtLimit(true);
      return;
    }
    setForm((prev) => ({ ...prev, triggers: [...prev.triggers, v] }));
    setCustomTrigger('');
  };

  const removeTrigger = (value: string) => {
    setForm((prev) => ({ ...prev, triggers: prev.triggers.filter((t) => t !== value) }));
  };

  const handleDeleteEvent = async (eventId: string) => {
    if (!id) return;
    try {
      await eventApi.deleteEvent(id, eventId);
      setEvents((prev) => prev.filter((ev) => ev.event_id !== eventId));
    } catch {
      setError('删除事件失败');
    }
  };

  const validate = (): boolean => {
    if (!form.nickname.trim()) {
      setError('请输入昵称');
      return false;
    }
    if (form.nickname.trim().length > NICKNAME_MAX_LENGTH) {
      setError(`昵称最多 ${NICKNAME_MAX_LENGTH} 个字符`);
      return false;
    }
    if (!form.birth_date) {
      setError('请选择出生日期');
      return false;
    }
    if (form.diagnosis_idx < 0) {
      setError('请选择诊断类型');
      return false;
    }
    if (form.behavior_idx < 0) {
      setError('请选择主要行为类型');
      return false;
    }
    if (form.triggers.length > TRIGGER_MAX_COUNT) {
      setError(`触发标签最多 ${TRIGGER_MAX_COUNT} 个`);
      return false;
    }
    return true;
  };

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    setError(null);

    const payload = {
      nickname: form.nickname.trim() || null,
      birth_date: form.birth_date,
      diagnosis_type: DIAGNOSIS_VALUES[form.diagnosis_idx] as ProfileCreate['diagnosis_type'],
      primary_behavior: BEHAVIOR_VALUES[form.behavior_idx] as ProfileCreate['primary_behavior'],
      sensory_features: form.sensory_features,
      triggers: form.triggers,
    };

    try {
      if (id) {
        await updateProfile(id, payload as ProfileUpdate);
      } else {
        await createProfile(payload as ProfileCreate);
      }
      navigate('/profiles');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '保存失败';
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteProfile = async () => {
    if (!id) return;
    if (deleteConfirm !== form.nickname) {
      setDeleteError('昵称不匹配');
      return;
    }
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteProfile(id);
      navigate('/profiles');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '删除失败';
      setDeleteError(msg);
      setDeleting(false);
    }
  };

  const renderDropdown = (
    ddId: string,
    label: string,
    required: boolean,
    value: string,
    options: readonly string[],
    onSelect: (idx: number) => void,
  ) => (
    <div className="field">
      <label>
        {required && <span className="req">*</span>} {label}
      </label>
      <div className={`dd-wrap${openDD === ddId ? ' open' : ''}`}>
        <button className="dd-btn" type="button" onClick={() => setOpenDD(openDD === ddId ? null : ddId)}>
          {value || '请选择'}
        </button>
        <div className="dd-menu">
          {options.map((opt, idx) => (
            <button
              key={opt}
              type="button"
              className={`dd-opt${opt === value ? ' selected' : ''}`}
              onClick={() => {
                onSelect(idx);
                setOpenDD(null);
              }}
            >
              {opt}
            </button>
          ))}
        </div>
      </div>
    </div>
  );

  const pageTitle = useMemo(() => (isEdit ? '编辑档案' : '创建档案'), [isEdit]);

  if (loading) {
    return (
      <>
        <div className="nav">
          <button className="nav-cancel" onClick={() => navigate(-1)}>
            取消
          </button>
          <span className="nav-title">{pageTitle}</span>
        </div>
        <PageContent>
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--cf-muted)' }}>加载中…</div>
        </PageContent>
      </>
    );
  }

  return (
    <>
      <div className="nav">
        <button className="nav-cancel" onClick={() => navigate(-1)}>
          取消
        </button>
        <span
          className="nav-title"
          onDoubleClick={() => {
            if (!isEdit) return;
            setDeleteConfirm('');
            setDeleteError(null);
            setDeleteOpen(true);
          }}
        >
          {pageTitle}
        </span>
        <button className="nav-save" onClick={() => void handleSave()} disabled={saving} aria-label="保存">
          {saving ? (
            <span className="save-spinner" />
          ) : (
            <CheckIcon />
          )}
        </button>
      </div>

      <PageContent className="profile-edit-content">
        {error && <div className="form-error">{error}</div>}

        <div className="tip">带 * 的项目为必填，保存后可在事件记录中继续补充。</div>

        <div className="card">
          <div className="avatar-row">
            <div className="avatar">
              <UserIcon />
              <div className="avatar-badge">
                <CameraIcon />
              </div>
            </div>
          </div>

          <div className="field">
            <label>
              <span className="req">*</span> 档案昵称
            </label>
            <input
              value={form.nickname}
              onChange={(e) => setForm((p) => ({ ...p, nickname: e.target.value }))}
              placeholder="如：小明"
              maxLength={NICKNAME_MAX_LENGTH}
            />
          </div>

          <div className="field">
            <label>
              <span className="req">*</span> 出生日期
            </label>
            <input
              type="date"
              value={form.birth_date}
              max={todayStr()}
              onChange={(e) => setForm((p) => ({ ...p, birth_date: e.target.value }))}
            />
          </div>

          {renderDropdown(
            'diagnosis',
            '诊断类型',
            true,
            DIAGNOSIS_OPTIONS[form.diagnosis_idx],
            DIAGNOSIS_OPTIONS,
            (idx) => setForm((p) => ({ ...p, diagnosis_idx: idx })),
          )}

          {renderDropdown(
            'behavior',
            '主要行为类型',
            true,
            BEHAVIOR_OPTIONS[form.behavior_idx],
            BEHAVIOR_OPTIONS,
            (idx) => setForm((p) => ({ ...p, behavior_idx: idx })),
          )}
        </div>

        <div className="section-title">
          <TagIcon />
          <span>感觉特征（可多选）</span>
        </div>
        <div className="tag-row">
          {SENSORY_FEATURE_TAGS.map((tag) => (
            <button
              key={tag}
              type="button"
              className={`t-chip${form.sensory_features.includes(tag) ? ' selected' : ''}`}
              onClick={() => toggleArray('sensory_features', tag)}
            >
              {SENSORY_FEATURE_LABELS[tag] ?? tag}
            </button>
          ))}
        </div>

        <div className="section-title">
          <TagIcon />
          <span>
            触发标签
            <em className={`tag-count${form.triggers.length >= TRIGGER_MAX_COUNT ? ' full' : ''}`}>
              {form.triggers.length}/{TRIGGER_MAX_COUNT}
            </em>
          </span>
        </div>
        <div className="tag-row">
          {TRIGGER_TAGS.map((tag) => {
            const selected = form.triggers.includes(tag);
            const atLimit = !selected && form.triggers.length >= TRIGGER_MAX_COUNT;
            return (
              <button
                key={tag}
                type="button"
                className={`t-chip${selected ? ' selected' : ''}${atLimit ? ' disabled' : ''}`}
                onClick={() => toggleArray('triggers', tag)}
                disabled={atLimit}
              >
                {TRIGGER_LABELS[tag] ?? tag}
              </button>
            );
          })}
        </div>

        <div className={`add-tag${form.triggers.length >= TRIGGER_MAX_COUNT ? ' disabled' : ''}`}>
          <input
            value={customTrigger}
            onChange={(e) => setCustomTrigger(e.target.value)}
            placeholder={form.triggers.length >= TRIGGER_MAX_COUNT ? '已达上限' : '自定义标签…'}
            maxLength={10}
            disabled={form.triggers.length >= TRIGGER_MAX_COUNT}
            onKeyDown={(e) => e.key === 'Enter' && addCustomTrigger()}
          />
          <button
            type="button"
            onClick={addCustomTrigger}
            disabled={form.triggers.length >= TRIGGER_MAX_COUNT}
          >
            添加
          </button>
        </div>
        {triggerAtLimit && <p className="field-hint at-limit">触发标签已达上限（{TRIGGER_MAX_COUNT} 个）</p>}

        {form.triggers.filter((t) => !TRIGGER_TAGS.includes(t)).length > 0 && (
          <div className="tag-row custom-tags">
            {form.triggers
              .filter((t) => !TRIGGER_TAGS.includes(t))
              .map((t) => (
                <button key={t} type="button" className="t-chip selected" onClick={() => removeTrigger(t)}>
                  {t}
                </button>
              ))}
          </div>
        )}

        {isEdit && (
          <>
            <div className="events-header">
              <span>事件记录（共 {events.length} 条）</span>
              <button type="button" onClick={() => setEventsExpanded((v) => !v)}>
                {eventsExpanded ? '收起' : '展开'}
              </button>
            </div>
            {eventsExpanded && (
              <div className="event-list">
                {eventsLoading ? (
                  <div className="event-empty">加载中…</div>
                ) : events.length === 0 ? (
                  <div className="event-empty">暂无事件记录</div>
                ) : (
                  events.map((ev) => (
                    <div key={ev.event_id} className="event-row">
                      <span>{eventTitle(ev)}</span>
                      <button type="button" className="del" onClick={() => void handleDeleteEvent(ev.event_id)}>
                        删除
                      </button>
                    </div>
                  ))
                )}
              </div>
            )}
          </>
        )}
      </PageContent>

      {deleteOpen && (
        <div className="modal open">
          <div className="modal-bg" onClick={() => setDeleteOpen(false)} />
          <div className="modal-box">
            <h3>确认删除</h3>
            <p>输入档案昵称以确认删除</p>
            <input
              value={deleteConfirm}
              onChange={(e) => {
                setDeleteConfirm(e.target.value);
                if (deleteError) setDeleteError(null);
              }}
              placeholder="输入昵称"
            />
            {deleteError && <div className="modal-error">{deleteError}</div>}
            <div className="modal-acts">
              <button type="button" className="modal-cancel" onClick={() => setDeleteOpen(false)}>
                取消
              </button>
              <button type="button" className="modal-del" onClick={() => void handleDeleteProfile()} disabled={deleting}>
                {deleting ? '删除中…' : '删除'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
