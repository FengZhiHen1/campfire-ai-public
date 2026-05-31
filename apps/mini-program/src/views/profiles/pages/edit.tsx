import { useState, useEffect, useMemo } from 'react';
import { View, Text, Button, Input, Picker } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { useProfile } from '../../../logics/profiles';
import { listEvents, deleteEvent as deleteEventApi } from '../../../logics/profiles/services/eventApi';
import { DIAGNOSIS_OPTIONS, BEHAVIOR_OPTIONS, SENSORY_FEATURE_TAGS, TRIGGER_TAGS, CUSTOM_TAG_MAX_LENGTH, NICKNAME_MAX_LENGTH, ERROR_AUTO_DISMISS_MS } from '../../../logics/profiles/constants';
import { validateProfileForm } from '../../../logics/profiles/utils/validateForm';
import { formatDateStr } from '../../../logics/shared/utils/timeFormat';
import TagSection from '../components/TagSection';
import DeleteConfirmModal from '../components/DeleteConfirmModal';
import EventListSection from '../components/EventListSection';
import type { ProfileResponse, EventListItem } from '../../../logics/profiles/types';
import type { DiagnosisType, ProfileBehaviorType, SensoryFeature } from '@campfire/ts-shared';
import './edit.scss';

export default function ProfileEdit() {
  const { getProfile, createProfile, updateProfile, deleteProfile } = useProfile();

  // 路由参数
  const [routeParams] = useState(() => {
    const router = Taro.getCurrentInstance().router;
    return {
      mode: (router?.params?.mode as 'create' | 'edit') || 'create',
      profileId: router?.params?.profileId || '',
    };
  });
  const { mode, profileId } = routeParams;
  const isEdit = mode === 'edit';

  // 表单状态
  const [nickname, setNickname] = useState('');
  const [birthDate, setBirthDate] = useState('');
  const [diagnosisType, setDiagnosisType] = useState('');
  const [primaryBehavior, setPrimaryBehavior] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [originalValues, setOriginalValues] = useState({
    nickname: '', birthDate: '', diagnosisType: '', primaryBehavior: '',
  });

  // 标签状态
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [customTagInput, setCustomTagInput] = useState('');
  const [customTags, setCustomTags] = useState<string[]>([]);

  // 事件状态
  const [events, setEvents] = useState<EventListItem[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsExpanded, setEventsExpanded] = useState(true);

  // UI 状态
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [menuVisible, setMenuVisible] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteConfirmName, setDeleteConfirmName] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);

  // 加载档案数据
  useEffect(() => {
    if (!isEdit || !profileId) return;

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
        setSelectedTags(data.sensory_features || []);
        setCustomTags(data.triggers || []);

        setEventsLoading(true);
        listEvents(profileId)
          .then(setEvents)
          .catch(() => setEvents([]))
          .finally(() => setEventsLoading(false));
      })
      .catch(() => {
        Taro.showToast({ title: '加载失败', icon: 'none' });
      })
      .finally(() => setLoading(false));
  }, [isEdit, profileId, getProfile]);

  // 修改检测
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

  const canSave = !saving && (isEdit ? isDirty : true);

  // 标签操作
  const toggleTag = (tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  };

  const addCustomTag = () => {
    const tag = customTagInput.trim();
    if (!tag || tag.length > CUSTOM_TAG_MAX_LENGTH || customTags.includes(tag)) return;
    setCustomTags((prev) => [...prev, tag]);
    setCustomTagInput('');
  };

  const removeCustomTag = (tag: string) => {
    setCustomTags((prev) => prev.filter((t) => t !== tag));
  };

  // 保存
  const handleSave = async () => {
    if (saving) return;

    const formErrors = validateProfileForm({ nickname, birthDate, diagnosisType, primaryBehavior });
    setErrors(formErrors);
    if (Object.keys(formErrors).length > 0) return;

    const payload = {
      nickname,
      birth_date: birthDate,
      diagnosis_type: diagnosisType as DiagnosisType,
      primary_behavior: primaryBehavior as ProfileBehaviorType,
      sensory_features: selectedTags.filter((t) => SENSORY_FEATURE_TAGS.includes(t)) as SensoryFeature[],
      triggers: [
        ...selectedTags.filter((t) => TRIGGER_TAGS.includes(t)),
        ...customTags,
      ],
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
      setTimeout(() => setSaveError(null), ERROR_AUTO_DISMISS_MS);
    } finally {
      setSaving(false);
    }
  };

  // 删除
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

  // 删除事件
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

  // 加载中
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
            <View
              className="profile-edit-navbar__menu-item profile-edit-navbar__menu-item--danger"
              onClick={() => { setMenuVisible(false); setShowDeleteModal(true); }}
            >
              <Text>删除此档案</Text>
            </View>
          </View>
        )}
      </View>

      {/* 遮罩 */}
      {(menuVisible || showDeleteModal) && (
        <View className="profile-edit-overlay" onClick={() => { setMenuVisible(false); setShowDeleteModal(false); }} />
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

      {/* 内容区 */}
      <View className="profile-edit-main">
        {/* 基础信息 */}
        <View>
          <View className="profile-edit-section-title">
            <Text className="profile-edit-section-title__icon">👤</Text>
            <Text>基础信息</Text>
          </View>
          <View className="profile-edit-card">
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
                  <Text className="profile-edit-field__required">*</Text>档案昵称
                </Text>
                <Input
                  className={`profile-edit-field__input ${errors.nickname ? 'profile-edit-field__input--error' : ''}`}
                  value={nickname}
                  onInput={(e) => { setNickname(e.detail.value); setErrors((p) => ({ ...p, nickname: '' })); }}
                  placeholder="如：小明"
                  maxlength={NICKNAME_MAX_LENGTH}
                />
                {errors.nickname && <Text className="profile-edit-field__error">{errors.nickname}</Text>}
              </View>

              {/* 出生日期 */}
              <View className="profile-edit-field">
                <Text className="profile-edit-field__label">
                  <Text className="profile-edit-field__required">*</Text>出生日期
                </Text>
                <Picker
                  mode="date"
                  value={birthDate || formatDateStr(new Date())}
                  end={formatDateStr(new Date())}
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
                  <Text className="profile-edit-field__required">*</Text>诊断类型
                </Text>
                <Picker
                  mode="selector"
                  range={[...DIAGNOSIS_OPTIONS]}
                  value={DIAGNOSIS_OPTIONS.indexOf(diagnosisType)}
                  onChange={(e) => { setDiagnosisType(DIAGNOSIS_OPTIONS[e.detail.value as number]); setErrors((p) => ({ ...p, diagnosisType: '' })); }}
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
                  <Text className="profile-edit-field__required">*</Text>主要行为类型
                </Text>
                <Picker
                  mode="selector"
                  range={[...BEHAVIOR_OPTIONS]}
                  value={BEHAVIOR_OPTIONS.indexOf(primaryBehavior)}
                  onChange={(e) => { setPrimaryBehavior(BEHAVIOR_OPTIONS[e.detail.value as number]); setErrors((p) => ({ ...p, primaryBehavior: '' })); }}
                >
                  <View className={`profile-edit-field__picker ${errors.primaryBehavior ? 'profile-edit-field__input--error' : ''} ${!primaryBehavior ? 'profile-edit-field__picker--placeholder' : ''}`}>
                    <Text>{primaryBehavior || '请选择类型'}</Text>
                    <Text className="profile-edit-field__picker-arrow">▼</Text>
                  </View>
                </Picker>
                {errors.primaryBehavior && <Text className="profile-edit-field__error">{errors.primaryBehavior}</Text>}
              </View>
            </View>
          </View>
        </View>

        <TagSection
          selectedTags={selectedTags}
          customTags={customTags}
          customTagInput={customTagInput}
          onToggleTag={toggleTag}
          onCustomTagInputChange={setCustomTagInput}
          onAddCustomTag={addCustomTag}
          onRemoveCustomTag={removeCustomTag}
        />

        {isEdit && (
          <EventListSection
            events={events}
            isLoading={eventsLoading}
            expanded={eventsExpanded}
            onToggle={() => setEventsExpanded(!eventsExpanded)}
            onDeleteEvent={handleDeleteEvent}
          />
        )}
      </View>

      <DeleteConfirmModal
        visible={showDeleteModal}
        nickname={nickname}
        confirmName={deleteConfirmName}
        onConfirmNameChange={setDeleteConfirmName}
        onCancel={() => setShowDeleteModal(false)}
        onDelete={handleDelete}
      />
    </View>
  );
}
