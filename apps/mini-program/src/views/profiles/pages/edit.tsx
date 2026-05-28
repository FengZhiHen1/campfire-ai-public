import { useState, useEffect, useMemo } from 'react';
import { View, Text, Button, Input } from '@tarojs/components';
import Taro from '@tarojs/taro';
import {
  listProfiles,
  createProfile,
  updateProfile,
  deleteProfile,
} from '../../../logics/profiles/services/profileApi';
import './edit.scss';

interface Profile {
  profile_id: string;
  nickname: string;
  birth_date?: string;
  diagnosis_type?: string;
  primary_behavior?: string;
}

export default function ProfileEdit() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [nickname, setNickname] = useState('');
  const [birthDate, setBirthDate] = useState('');
  const [diagnosisType, setDiagnosisType] = useState('');
  const [primaryBehavior, setPrimaryBehavior] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [saving, setSaving] = useState(false);

  // 原始值，用于检测表单是否被修改
  const [originalValues, setOriginalValues] = useState({
    nickname: '',
    birthDate: '',
    diagnosisType: '',
    primaryBehavior: '',
  });

  const load = async () => {
    setLoading(true);
    setError(false);
    try {
      const data = await listProfiles();
      setProfiles(data as Profile[]);
    } catch {
      setError(true);
      Taro.showToast({ title: '加载失败', icon: 'none' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const resetForm = () => {
    setNickname('');
    setBirthDate('');
    setDiagnosisType('');
    setPrimaryBehavior('');
    setEditingId(null);
    setOriginalValues({ nickname: '', birthDate: '', diagnosisType: '', primaryBehavior: '' });
  };

  const isDirty = useMemo(() => {
    return (
      nickname !== originalValues.nickname ||
      birthDate !== originalValues.birthDate ||
      diagnosisType !== originalValues.diagnosisType ||
      primaryBehavior !== originalValues.primaryBehavior
    );
  }, [nickname, birthDate, diagnosisType, primaryBehavior, originalValues]);

  const canSave = useMemo(() => {
    if (saving) return false;
    if (!editingId) return true; // 新建模式，只要有内容就可以保存
    return isDirty;
  }, [saving, editingId, isDirty]);

  const handleSave = async () => {
    if (saving) return;
    if (!nickname.trim()) {
      Taro.showToast({ title: '请输入昵称', icon: 'none' });
      return;
    }
    const payload = {
      nickname,
      birth_date: birthDate || undefined,
      diagnosis_type: diagnosisType || undefined,
      primary_behavior: primaryBehavior || undefined,
    };
    setSaving(true);
    try {
      if (editingId) {
        await updateProfile(editingId, payload);
      } else {
        await createProfile(payload as any);
      }
      Taro.showToast({ title: '保存成功' });
      resetForm();
      load();
    } catch {
      Taro.showToast({ title: '保存失败', icon: 'none' });
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (p: Profile) => {
    setEditingId(p.profile_id);
    setNickname(p.nickname);
    setBirthDate(p.birth_date || '');
    setDiagnosisType(p.diagnosis_type || '');
    setPrimaryBehavior(p.primary_behavior || '');
    setOriginalValues({
      nickname: p.nickname,
      birthDate: p.birth_date || '',
      diagnosisType: p.diagnosis_type || '',
      primaryBehavior: p.primary_behavior || '',
    });
  };

  const handleDelete = async (id: string) => {
    if (saving) return;
    setSaving(true);
    try {
      await deleteProfile(id);
      Taro.showToast({ title: '删除成功' });
      if (editingId === id) {
        resetForm();
      }
      load();
    } catch {
      Taro.showToast({ title: '删除失败', icon: 'none' });
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (editingId) {
      resetForm();
    } else {
      Taro.navigateBack();
    }
  };

  // 加载中
  if (loading && profiles.length === 0) {
    return (
      <View className="profile-edit-page">
        <View className="profile-edit-navbar">
          <Text className="profile-edit-navbar__title">档案管理</Text>
        </View>
        <View className="profile-edit-loading">
          <View className="profile-edit-loading__skeleton" />
          <Text className="profile-edit-loading__text">加载中...</Text>
        </View>
      </View>
    );
  }

  // 错误
  if (error && profiles.length === 0) {
    return (
      <View className="profile-edit-page">
        <View className="profile-edit-navbar">
          <Text className="profile-edit-navbar__title">档案管理</Text>
        </View>
        <View className="profile-edit-error">
          <View className="profile-edit-error__icon">⚠️</View>
          <Text className="profile-edit-error__title">加载失败</Text>
          <Button className="profile-edit-error__retry-btn" onClick={load}>
            重新加载
          </Button>
        </View>
      </View>
    );
  }

  return (
    <View className="profile-edit-page">
      {/* 顶部导航栏 */}
      <View className="profile-edit-navbar">
        <Button className="profile-edit-navbar__cancel" onClick={handleCancel}>
          取消
        </Button>
        <Text className="profile-edit-navbar__title">
          {editingId ? '编辑档案' : '新建档案'}
        </Text>
        <Button
          className={`profile-edit-navbar__save ${!canSave ? 'profile-edit-navbar__save--disabled' : ''}`}
          onClick={handleSave}
          disabled={!canSave}
        >
          <Text className="profile-edit-navbar__save-icon">✓</Text>
        </Button>
      </View>

      {/* 现有档案列表 */}
      {!editingId && profiles.length > 0 && (
        <View className="profile-edit-list">
          <Text className="profile-edit-list__title">已有档案</Text>
          {profiles.map((p) => (
            <View key={p.profile_id} className="profile-edit-list__item">
              <View className="profile-edit-list__item-info">
                <Text className="profile-edit-list__item-name">{p.nickname}</Text>
                <Text className="profile-edit-list__item-meta">
                  {p.diagnosis_type || '未填写诊断'}
                  {p.primary_behavior ? ` · ${p.primary_behavior}` : ''}
                </Text>
              </View>
              <View className="profile-edit-list__item-actions">
                <Button
                  className="profile-edit-list__action-btn profile-edit-list__action-btn--edit"
                  onClick={() => handleEdit(p)}
                  disabled={saving}
                >
                  编辑
                </Button>
                <Button
                  className="profile-edit-list__action-btn profile-edit-list__action-btn--delete"
                  onClick={() => handleDelete(p.profile_id)}
                  disabled={saving}
                >
                  删除
                </Button>
              </View>
            </View>
          ))}
        </View>
      )}

      {/* 表单区 */}
      <View className="profile-edit-form">
        {/* 头像占位 */}
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
            className="profile-edit-field__input"
            value={nickname}
            onInput={(e) => setNickname(e.detail.value)}
            placeholder="如：小明"
            maxlength={20}
          />
        </View>

        {/* 出生日期 */}
        <View className="profile-edit-field">
          <Text className="profile-edit-field__label">
            <Text className="profile-edit-field__required">*</Text>
            出生日期
          </Text>
          <Input
            className="profile-edit-field__input"
            value={birthDate}
            onInput={(e) => setBirthDate(e.detail.value)}
            placeholder="YYYY-MM-DD"
          />
        </View>

        {/* 诊断类型 */}
        <View className="profile-edit-field">
          <Text className="profile-edit-field__label">
            <Text className="profile-edit-field__required">*</Text>
            诊断类型
          </Text>
          <Input
            className="profile-edit-field__input"
            value={diagnosisType}
            onInput={(e) => setDiagnosisType(e.detail.value)}
            placeholder="如：ASD / ADHD / 发育迟缓"
          />
        </View>

        {/* 主要行为 */}
        <View className="profile-edit-field">
          <Text className="profile-edit-field__label">
            <Text className="profile-edit-field__required">*</Text>
            主要行为类型
          </Text>
          <Input
            className="profile-edit-field__input"
            value={primaryBehavior}
            onInput={(e) => setPrimaryBehavior(e.detail.value)}
            placeholder="如：自伤行为 / 情绪崩溃"
          />
        </View>
      </View>

      {/* 底部保存按钮 */}
      <View className="profile-edit-submit">
        <Button
          className="profile-edit-submit__btn"
          onClick={handleSave}
          disabled={!canSave}
        >
          {saving ? '保存中...' : '保存'}
        </Button>
      </View>
    </View>
  );
}
