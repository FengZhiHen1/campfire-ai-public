import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import PageContent from '@/views/_shared/layout/PageContent';
import {
  useProfile,
  DIAGNOSIS_OPTIONS,
  DIAGNOSIS_VALUES,
  BEHAVIOR_OPTIONS,
  BEHAVIOR_VALUES,
  LANGUAGE_OPTIONS,
  LANGUAGE_VALUES,
  SENSORY_FEATURE_TAGS,
  TRIGGER_TAGS,
} from '@/logics/profiles';
import type { ProfileCreate, ProfileUpdate } from '@/logics/profiles';
import './ProfileEditPage.css';

interface FormState {
  nickname: string;
  birth_date: string;
  diagnosis_idx: number;
  behavior_idx: number;
  language_idx: number;
  sensory_features: string[];
  triggers: string[];
  medication_notes: string;
}

const EMPTY_FORM: FormState = {
  nickname: '',
  birth_date: '',
  diagnosis_idx: 0,
  behavior_idx: 0,
  language_idx: -1,
  sensory_features: [],
  triggers: [],
  medication_notes: '',
};

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export default function ProfileEditPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { profiles, getProfile, createProfile, updateProfile } = useProfile();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [customTrigger, setCustomTrigger] = useState('');
  const [openDD, setOpenDD] = useState<string | null>(null);

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
          language_idx: p.language_level ? LANGUAGE_VALUES.indexOf(p.language_level) : -1,
          sensory_features: p.sensory_features ?? [],
          triggers: p.triggers ?? [],
          medication_notes: p.medication_notes ?? '',
        });
      })
      .catch(() => setError('加载档案失败'))
      .finally(() => setLoading(false));
  }, [id, existingFromList, getProfile]);

  useEffect(() => {
    if (!id || !existingFromList) return;
    // 如果从列表已有数据，先用列表数据填充，避免白等
    setForm({
      nickname: existingFromList.nickname ?? '',
      birth_date: '', // 列表项没有生日，需要重新拉详情
      diagnosis_idx: Math.max(0, DIAGNOSIS_VALUES.indexOf(existingFromList.diagnosis_type)),
      behavior_idx: Math.max(0, BEHAVIOR_VALUES.indexOf(existingFromList.primary_behavior)),
      language_idx: -1,
      sensory_features: [],
      triggers: [],
      medication_notes: '',
    });
  }, [id, existingFromList]);

  const toggleArray = (field: 'sensory_features' | 'triggers', value: string) => {
    setForm((prev) => {
      const arr = prev[field];
      const next = arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value];
      return { ...prev, [field]: next };
    });
  };

  const addCustomTrigger = () => {
    const v = customTrigger.trim();
    if (!v) return;
    if (form.triggers.includes(v)) return;
    setForm((prev) => ({ ...prev, triggers: [...prev.triggers, v] }));
    setCustomTrigger('');
  };

  const removeTrigger = (value: string) => {
    setForm((prev) => ({ ...prev, triggers: prev.triggers.filter((t) => t !== value) }));
  };

  const validate = (): boolean => {
    if (!form.nickname.trim()) {
      setError('请输入昵称');
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
      language_level: form.language_idx >= 0 ? (LANGUAGE_VALUES[form.language_idx] as ProfileCreate['language_level']) : null,
      sensory_features: form.sensory_features,
      triggers: form.triggers,
      medication_notes: form.medication_notes.trim() || null,
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

  const renderDropdown = (
    ddId: string,
    label: string,
    required: boolean,
    value: string,
    options: readonly string[],
    onSelect: (idx: number) => void,
  ) => (
    <div className="field">
      <label>{required && <span className="req">*</span>} {label}</label>
      <div className={`dd-wrap${openDD === ddId ? ' open' : ''}`}>
        <button className="dd-btn" type="button" onClick={() => setOpenDD(openDD === ddId ? null : ddId)}>{value || '请选择'}</button>
        <div className="dd-menu">
          {options.map((opt, idx) => (
            <button
              key={opt}
              type="button"
              className="dd-opt"
              onClick={() => { onSelect(idx); setOpenDD(null); }}
            >
              {opt}
            </button>
          ))}
        </div>
      </div>
    </div>
  );

  const selectedLanguage = form.language_idx >= 0 ? LANGUAGE_OPTIONS[form.language_idx] : '请选择（可选）';

  if (loading) {
    return (
      <>
        <div className="nav">
          <button className="nav-cancel" onClick={() => navigate(-1)}>取消</button>
          <span className="nav-title">{isEdit ? '编辑档案' : '创建档案'}</span>
        </div>
        <PageContent><div style={{ textAlign: 'center', padding: 40, color: 'var(--cf-muted)' }}>加载中…</div></PageContent>
      </>
    );
  }

  return (
    <>
      <div className="nav">
        <button className="nav-cancel" onClick={() => navigate(-1)}>取消</button>
        <span className="nav-title">{isEdit ? '编辑档案' : '创建档案'}</span>
        <button className="nav-save" onClick={() => void handleSave()} disabled={saving}>
          {saving ? '保存中…' : '保存'}
        </button>
      </div>
      <PageContent>
        {error && <div className="form-error">{error}</div>}

        <div className="field">
          <label><span className="req">*</span> 昵称</label>
          <input
            value={form.nickname}
            onChange={(e) => setForm((p) => ({ ...p, nickname: e.target.value }))}
            placeholder="如：小宝"
            maxLength={20}
          />
        </div>

        <div className="field">
          <label><span className="req">*</span> 出生日期</label>
          <input
            type="date"
            value={form.birth_date}
            max={todayStr()}
            onChange={(e) => setForm((p) => ({ ...p, birth_date: e.target.value }))}
          />
        </div>

        <div className="row">
          {renderDropdown('diagnosis', '诊断类型', true, DIAGNOSIS_OPTIONS[form.diagnosis_idx], DIAGNOSIS_OPTIONS, (idx) =>
            setForm((p) => ({ ...p, diagnosis_idx: idx }))
          )}
          {renderDropdown('behavior', '主要行为类型', true, BEHAVIOR_OPTIONS[form.behavior_idx], BEHAVIOR_OPTIONS, (idx) =>
            setForm((p) => ({ ...p, behavior_idx: idx }))
          )}
        </div>

        {renderDropdown('language', '语言水平', false, selectedLanguage, LANGUAGE_OPTIONS, (idx) =>
          setForm((p) => ({ ...p, language_idx: idx }))
        )}

        <div className="field">
          <label>感官特征</label>
          <div className="chip-grid">
            {SENSORY_FEATURE_TAGS.map((tag) => (
              <button
                key={tag}
                type="button"
                className={`chip-btn${form.sensory_features.includes(tag) ? ' selected' : ''}`}
                onClick={() => toggleArray('sensory_features', tag)}
              >
                {tag}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <label>常见触发因素</label>
          <div className="chip-grid">
            {TRIGGER_TAGS.map((tag) => (
              <button
                key={tag}
                type="button"
                className={`chip-btn${form.triggers.includes(tag) ? ' selected' : ''}`}
                onClick={() => toggleArray('triggers', tag)}
              >
                {tag}
              </button>
            ))}
          </div>
          {form.triggers.filter((t) => !TRIGGER_TAGS.includes(t)).length > 0 && (
            <div className="tag-list">
              {form.triggers.filter((t) => !TRIGGER_TAGS.includes(t)).map((t) => (
                <span key={t} className="tag">
                  {t}
                  <button type="button" onClick={() => removeTrigger(t)}>×</button>
                </span>
              ))}
            </div>
          )}
          <div className="custom-tag-row">
            <input
              value={customTrigger}
              onChange={(e) => setCustomTrigger(e.target.value)}
              placeholder="输入自定义触发因素"
              maxLength={10}
            />
            <button type="button" className="btn btn-s" onClick={addCustomTrigger}>添加</button>
          </div>
        </div>

        <div className="field">
          <label>用药/就医备注</label>
          <textarea
            value={form.medication_notes}
            onChange={(e) => setForm((p) => ({ ...p, medication_notes: e.target.value }))}
            placeholder="如正在服用的药物、过敏史、就诊医院等（可选）"
            rows={3}
          />
        </div>
      </PageContent>
    </>
  );
}
