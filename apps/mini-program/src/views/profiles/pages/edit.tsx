import { useState, useEffect, useMemo, useCallback } from 'react';
import { View, Text, Button, Input, Picker } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { useProfile } from '../../../logics/profiles';
import {
  listEvents,
  deleteEvent as deleteEventApi,
} from '../../../logics/profiles/services/eventApi';
import { DIAGNOSIS_OPTIONS, BEHAVIOR_OPTIONS, PRESET_TAGS } from '../../../logics/profiles/constants';
import type { ProfileResponse, EventListItem } from '../../../logics/profiles/types';
import './edit.scss';

// ============================================================================
// 事件类型（已由后端真实接口提供，本地 Mock 类型已移除）
// ============================================================================

// ============================================================================
// 辅助函数
// ============================================================================

function formatDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function validateForm(values: {
  nickname: string;
  birthDate: string;
  diagnosisType: string;
  primaryBehavior: string;
}): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!values.nickname.trim()) {
    errors.nickname = '昵称不能为空';
  } else if (values.nickname.trim().length < 2 || values.nickname.trim().length > 20) {
    errors.nickname = '昵称长度为 2-20 个字符';
  }
  if (!values.birthDate) {
    errors.birthDate = '请选择出生日期';
  } else if (new Date(values.birthDate) > new Date()) {
    errors.birthDate = '日期不能晚于今天';
  }
  if (!values.diagnosisType) {
    errors.diagnosisType = '请选择诊断类型';
  }
  if (!values.primaryBehavior) {
    errors.primaryBehavior = '请选择主要行为类型';
  }
  return errors;
}

// ============================================================================
// 组件
// ============================================================================

export default function ProfileEdit() {
  const { getProfile, createProfile, updateProfile, deleteProfile } = useProfile();

  // --------------------------------------------------------------------------
  // 路由参数
  // --------------------------------------------------------------------------
  const [routeParams] = useState(() => {
    const router = Taro.getCurrentInstance().router;
    return {
      mode: (router?.params?.mode as 'create' | 'edit') || 'create',
      profileId: router?.params?.profileId || '',
    };
  });
  const { mode, profileId } = routeParams;
  const isEdit = mode === 'edit';

  // --------------------------------------------------------------------------
  // 表单状态
  // --------------------------------------------------------------------------
  const [nickname, setNickname] = useState('');
  const [birthDate, setBirthDate] = useState('');
  const [diagnosisType, setDiagnosisType] = useState('');
  const [primaryBehavior, setPrimaryBehavior] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});

  // 原始值，用于检测修改
  const [originalValues, setOriginalValues] = useState({
    nickname: '', birthDate: '', diagnosisType: '', primaryBehavior: '',
  });

  // --------------------------------------------------------------------------
  // 标签状态（Mock）
  // --------------------------------------------------------------------------
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [customTagInput, setCustomTagInput] = useState('');
  const [customTags, setCustomTags] = useState<string[]>([]);

  // --------------------------------------------------------------------------
  // 事件状态（真实数据）
  // --------------------------------------------------------------------------
  const [events, setEvents] = useState<EventListItem[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsExpanded, setEventsExpanded] = useState(true);

  // --------------------------------------------------------------------------
  // UI 状态
  // --------------------------------------------------------------------------
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [menuVisible, setMenuVisible] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteConfirmName, setDeleteConfirmName] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);

  // --------------------------------------------------------------------------
  // 加载档案数据
  // --------------------------------------------------------------------------
  useEffect(() => {
    if (isEdit && profileId) {
      setLoading(true);
      getProfile(profileId)
        .then((data: ProfileResponse) => {
          setNickname(data.nickname || '');
          setBirthDate(data.birth_date || '');
          setDiagnosisType(data.diagnosis_type || '');
          setPrimaryBehavior(data.primary_behavior || '');
          setOriginalValues({
            nickname: data.nickname || '',
            birthDate: data.birth_date || '',
            diagnosisType: data.diagnosis_type || '',
            primaryBehavior: data.primary_behavior || '',
          });
          // 从后端标签映射到前端标签
          setSelectedTags(data.sensory_features || []);
          setCustomTags(data.triggers || []);

          // 加载真实事件列表
          setEventsLoading(true);
          listEvents(profileId)
            .then((items) => {
              setEvents(items);
            })
            .catch(() => {
              setEvents([]);
            })
            .finally(() => {
              setEventsLoading(false);
            });
        })
        .catch(() => {
          Taro.showToast({ title: '加载失败', icon: 'none' });
        })
        .finally(() => setLoading(false));
    }
  }, [isEdit, profileId]);

  // --------------------------------------------------------------------------
  // 修改检测
  // --------------------------------------------------------------------------
  const isDirty = useMemo(() => {
    return (
      nickname !== originalValues.nickname ||
      birthDate !== originalValues.birthDate ||
      diagnosisType !== originalValues.diagnosisType ||
      primaryBehavior !== originalValues.primaryBehavior ||
      selectedTags.length > 0 ||
      customTags.length > 0
    );
  }, [nickname, birthDate, diagnosisType, primaryBehavior, originalValues, selectedTags, customTags]);

  const canSave = useMemo(() => {
    if (saving) return false;
    if (isEdit) return isDirty;
    return true;
  }, [saving, isEdit, isDirty]);

  // --------------------------------------------------------------------------
  // 保存
  // --------------------------------------------------------------------------
  const handleSave = async () => {
    if (saving) return;

    const formErrors = validateForm({ nickname, birthDate, diagnosisType, primaryBehavior });
    setErrors(formErrors);
    if (Object.keys(formErrors).length > 0) {
      // 滚动到第一个错误字段
      return;
    }

    const payload = {
      nickname,
      birth_date: birthDate,
      diagnosis_type: diagnosisType,
      primary_behavior: primaryBehavior,
      // Mock: 将标签合并提交
      sensory_features: selectedTags,
      triggers: customTags,
    };

    setSaving(true);
    setSaveError(null);
    try {
      if (isEdit && profileId) {
        await updateProfile(profileId, payload);
      } else {
        await createProfile(payload);
      }
      Taro.navigateBack();
    } catch {
      setSaveError('保存失败，请检查网络后重试');
      setTimeout(() => setSaveError(null), 3000);
    } finally {
      setSaving(false);
    }
  };

  // --------------------------------------------------------------------------
  // 删除档案
  // --------------------------------------------------------------------------
  const handleDelete = async () => {
    if (!profileId || deleteConfirmName !== nickname) return;
    setShowDeleteModal(false);
    setSaving(true);
    try {
      await deleteProfile(profileId);
      Taro.navigateBack();
    } catch {
      Taro.showToast({ title: '删除失败', icon: 'none' });
      setSaving(false);
    }
  };

  // --------------------------------------------------------------------------
  // 标签操作
  // --------------------------------------------------------------------------
  const toggleTag = (tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  };

  const addCustomTag = () => {
    const tag = customTagInput.trim();
    if (!tag || tag.length > 10 || customTags.includes(tag)) return;
    setCustomTags((prev) => [...prev, tag]);
    setCustomTagInput('');
  };

  const removeCustomTag = (tag: string) => {
    setCustomTags((prev) => prev.filter((t) => t !== tag));
  };

  // --------------------------------------------------------------------------
  // 事件操作（真实 API）
  // --------------------------------------------------------------------------
  const handleDeleteEvent = async (eventId: string) => {
    if (!profileId) return;
    try {
      await deleteEventApi(profileId, eventId);
      setEvents((prev) => prev.filter((e) => e.event_id !== eventId));
      Taro.showToast({ title: '已删除', icon: 'success' });
    } catch {
      Taro.showToast({ title: '删除失败', icon: 'none' });
    }
  };

  // --------------------------------------------------------------------------
  // 渲染
  // --------------------------------------------------------------------------
  if (loading) {
    return (
      <View className="profile-edit-page">
        <View className="profile-edit-navbar">
          <Text className="profile-edit-navbar__title">{isEdit ? '编辑档案' : '新建档案'}</Text>
        </View>
        <View className="profile-edit-loading">
          <View className="profile-edit-loading__skeleton" />
          <Text className="profile-edit-loading__text">加载中...</Text>
        </View>
      </View>
    );
  }

  return (
    <View className="profile-edit-page">
      {/* 导航栏 */}
      <View className="profile-edit-navbar">
        <Button className="profile-edit-navbar__cancel" onClick={() => Taro.navigateBack()}>
          取消
        </Button>
        <Text className="profile-edit-navbar__title">{isEdit ? '编辑档案' : '新建档案'}</Text>

        {isEdit && (
          <Button className="profile-edit-navbar__menu" onClick={() => setMenuVisible(!menuVisible)}>
            ···
          </Button>
        )}

        <Button
          className={`profile-edit-navbar__save ${!canSave ? 'profile-edit-navbar__save--disabled' : ''}`}
          onClick={handleSave}
          disabled={!canSave}
        >
          <Text className="profile-edit-navbar__save-icon">✓</Text>
        </Button>

        {/* 菜单 */}
        {menuVisible && (
          <View className="profile-edit-navbar__menu-panel">
            <View className="profile-edit-navbar__menu-item" onClick={() => { setMenuVisible(false); }}>
              <Text>解除专家关联</Text>
            </View>
            <View className="profile-edit-navbar__menu-item" onClick={() => { setMenuVisible(false); }}>
              <Text>隐私设置</Text>
            </View>
            <View className="profile-edit-navbar__menu-divider" />
            <View
              className="profile-edit-navbar__menu-item profile-edit-navbar__menu-item--danger"
              onClick={() => { setMenuVisible(false); setShowDeleteModal(true); }}
            >
              <Text>删除此档案</Text>
            </View>
          </View>
        )}
      </View>

      {/* 菜单/遮罩 */}
      {(menuVisible || showDeleteModal) && (
        <View
          className="profile-edit-overlay"
          onClick={() => { setMenuVisible(false); setShowDeleteModal(false); }}
        />
      )}

      {/* 新建提示条 */}
      {!isEdit && (
        <View className="profile-edit-tip">
          <Text>请填写孩子的基本信息（*为必填）</Text>
        </View>
      )}

      {/* 保存失败通知 */}
      {saveError && (
        <View className="profile-edit-notice">
          <Text className="profile-edit-notice__text">{saveError}</Text>
          <Text className="profile-edit-notice__close" onClick={() => setSaveError(null)}>×</Text>
        </View>
      )}

      {/* 表单区 */}
      <View className="profile-edit-form">
        {/* 头像 */}
        <View className="profile-edit-avatar">
          <View className="profile-edit-avatar__wrapper">
            <View className="profile-edit-avatar__circle">
              <Text className="profile-edit-avatar__icon">👤</Text>
            </View>
            <View className="profile-edit-avatar__edit-badge">
              <Text className="profile-edit-avatar__edit-badge-icon">✎</Text>
            </View>
          </View>
        </View>

        {/* 昵称 */}
        <View className="profile-edit-field">
          <Text className="profile-edit-field__label">
            <Text className="profile-edit-field__required">*</Text>
            档案昵称
          </Text>
          <Input
            className={`profile-edit-field__input ${errors.nickname ? 'profile-edit-field__input--error' : ''}`}
            value={nickname}
            onInput={(e) => { setNickname(e.detail.value); setErrors((p) => ({ ...p, nickname: '' })); }}
            placeholder="如：小明"
            maxlength={20}
          />
          {errors.nickname && <Text className="profile-edit-field__error">{errors.nickname}</Text>}
        </View>

        {/* 出生日期 */}
        <View className="profile-edit-field">
          <Text className="profile-edit-field__label">
            <Text className="profile-edit-field__required">*</Text>
            出生日期
          </Text>
          <Picker
            mode="date"
            value={birthDate || formatDate(new Date())}
            end={formatDate(new Date())}
            onChange={(e) => { setBirthDate(e.detail.value); setErrors((p) => ({ ...p, birthDate: '' })); }}
          >
            <View className={`profile-edit-field__picker ${errors.birthDate ? 'profile-edit-field__input--error' : ''} ${!birthDate ? 'profile-edit-field__picker--placeholder' : ''}`}>
              <Text>{birthDate || '请选择日期'}</Text>
              <Text className="profile-edit-field__picker-arrow">▼</Text>
            </View>
          </Picker>
          {errors.birthDate && <Text className="profile-edit-field__error">{errors.birthDate}</Text>}
        </View>

        {/* 诊断类型 */}
        <View className="profile-edit-field">
          <Text className="profile-edit-field__label">
            <Text className="profile-edit-field__required">*</Text>
            诊断类型
          </Text>
          <Picker
            mode="selector"
            range={DIAGNOSIS_OPTIONS}
            value={DIAGNOSIS_OPTIONS.indexOf(diagnosisType)}
            onChange={(e) => { setDiagnosisType(DIAGNOSIS_OPTIONS[e.detail.value]); setErrors((p) => ({ ...p, diagnosisType: '' })); }}
          >
            <View className={`profile-edit-field__picker ${errors.diagnosisType ? 'profile-edit-field__input--error' : ''} ${!diagnosisType ? 'profile-edit-field__picker--placeholder' : ''}`}>
              <Text>{diagnosisType || '请选择类型'}</Text>
              <Text className="profile-edit-field__picker-arrow">▼</Text>
            </View>
          </Picker>
          {errors.diagnosisType && <Text className="profile-edit-field__error">{errors.diagnosisType}</Text>}
        </View>

        {/* 主要行为 */}
        <View className="profile-edit-field">
          <Text className="profile-edit-field__label">
            <Text className="profile-edit-field__required">*</Text>
            主要行为类型
          </Text>
          <Picker
            mode="selector"
            range={BEHAVIOR_OPTIONS}
            value={BEHAVIOR_OPTIONS.indexOf(primaryBehavior)}
            onChange={(e) => { setPrimaryBehavior(BEHAVIOR_OPTIONS[e.detail.value]); setErrors((p) => ({ ...p, primaryBehavior: '' })); }}
          >
            <View className={`profile-edit-field__picker ${errors.primaryBehavior ? 'profile-edit-field__input--error' : ''} ${!primaryBehavior ? 'profile-edit-field__picker--placeholder' : ''}`}>
              <Text>{primaryBehavior || '请选择类型'}</Text>
              <Text className="profile-edit-field__picker-arrow">▼</Text>
            </View>
          </Picker>
          {errors.primaryBehavior && <Text className="profile-edit-field__error">{errors.primaryBehavior}</Text>}
        </View>
      </View>

      {/* 标签选择区（仅编辑模式，新建时折叠提示） */}
      <View className={`profile-tag-section ${!isEdit ? 'profile-tag-section--disabled' : ''}`}>
        <Text className="profile-tag-section__title">标签体系</Text>
        <Text className="profile-tag-section__subtitle">帮助孩子获得更精准的案例匹配</Text>

        {!isEdit && (
          <Text className="profile-tag-section__hint">创建档案后可添加标签和事件记录</Text>
        )}

        {isEdit && (
          <>
            {/* 预设标签 */}
            <View className="profile-tag-grid">
              {PRESET_TAGS.map((tag) => (
                <View
                  key={tag}
                  className={`profile-tag-grid__item ${selectedTags.includes(tag) ? 'profile-tag-grid__item--active' : ''}`}
                  onClick={() => toggleTag(tag)}
                >
                  <Text>{tag}</Text>
                  {selectedTags.includes(tag) && <Text className="profile-tag-grid__check">✓</Text>}
                </View>
              ))}
            </View>

            {/* 自定义标签 */}
            <Text className="profile-tag-section__sub-title">自定义标签</Text>
            <View className="profile-custom-tag">
              <Input
                className="profile-custom-tag__input"
                value={customTagInput}
                onInput={(e) => setCustomTagInput(e.detail.value)}
                placeholder="输入自定义标签（最多10个字）"
                maxlength={10}
              />
              <Button className="profile-custom-tag__add" onClick={addCustomTag}>
                +
              </Button>
            </View>
            <Text className="profile-custom-tag__count">{customTagInput.length}/10</Text>

            {/* 已添加自定义标签 */}
            <View className="profile-custom-tag__list">
              {customTags.map((tag) => (
                <View key={tag} className="profile-custom-tag__pill">
                  <Text>{tag}</Text>
                  <Text className="profile-custom-tag__remove" onClick={() => removeCustomTag(tag)}>✕</Text>
                </View>
              ))}
            </View>
          </>
        )}
      </View>

      {/* 事件记录区（仅编辑模式） */}
      {isEdit && (
        <View className="profile-event-section">
          <View className="profile-event-section__header">
            <Text className="profile-event-section__title">
              📋 事件记录（共 {events.length} 条）
            </Text>
            <Text
              className="profile-event-section__toggle"
              onClick={() => setEventsExpanded(!eventsExpanded)}
            >
              {eventsExpanded ? '折叠 ▲' : '展开 ▼'}
            </Text>
          </View>

          {eventsLoading && (
            <Text className="profile-event-list__loading">加载中…</Text>
          )}

          {eventsExpanded && !eventsLoading && (
            <View className="profile-event-list">
              {events.length === 0 && (
                <Text className="profile-event-list__empty">暂无事件记录</Text>
              )}
              {events.map((event) => (
                <View key={event.event_id} className="profile-event-list__item">
                  <View className="profile-event-list__summary">
                    <View className="profile-event-list__summary-header">
                      <Text className="profile-event-list__time">
                        {new Date(event.event_time).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                      </Text>
                      <View className="profile-event-list__badges">
                        {event.has_professional_note && (
                          <Text className="profile-event-list__eval">已评估</Text>
                        )}
                        <Text className="profile-event-list__severity">{event.severity_level}</Text>
                      </View>
                      <View className="profile-event-list__actions">
                        <Text onClick={() => handleDeleteEvent(event.event_id)}>🗑</Text>
                      </View>
                    </View>
                    <View className="profile-event-list__tag">
                      <Text>{event.behavior_type}</Text>
                    </View>
                  </View>
                </View>
              ))}
            </View>
          )}
        </View>
      )}

      {/* 删除确认对话框 */}
      {showDeleteModal && (
        <View className="profile-delete-modal">
          <View className="profile-delete-modal__content">
            <View className="profile-delete-modal__icon">
              <Text>⚠</Text>
            </View>
            <Text className="profile-delete-modal__title">确定删除此档案？</Text>
            <Text className="profile-delete-modal__subtitle">
              档案内的所有事件记录和标签数据将被永久删除，无法恢复
            </Text>
            <Text className="profile-delete-modal__hint">
              请输入档案昵称 "{nickname}" 以确认删除
            </Text>
            <Input
              className="profile-delete-modal__input"
              value={deleteConfirmName}
              onInput={(e) => setDeleteConfirmName(e.detail.value)}
              placeholder="输入档案昵称"
            />
            <View className="profile-delete-modal__actions">
              <Button
                className="profile-delete-modal__btn profile-delete-modal__btn--cancel"
                onClick={() => setShowDeleteModal(false)}
              >
                取消
              </Button>
              <Button
                className={`profile-delete-modal__btn profile-delete-modal__btn--delete ${deleteConfirmName !== nickname ? 'profile-delete-modal__btn--disabled' : ''}`}
                onClick={handleDelete}
                disabled={deleteConfirmName !== nickname}
              >
                删除
              </Button>
            </View>
          </View>
        </View>
      )}
    </View>
  );
}
