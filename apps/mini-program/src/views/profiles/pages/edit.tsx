import { useState, useEffect } from 'react';
import { View, Text, Button, Input } from '@tarojs/components';
import Taro from '@tarojs/taro';
import {
  listProfiles,
  createProfile,
  updateProfile,
  deleteProfile,
} from '../../../logics/profiles/services/profileApi';

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

  const load = async () => {
    try {
      const data = await listProfiles();
      setProfiles(data as Profile[]);
    } catch {
      Taro.showToast({ title: '加载失败', icon: 'none' });
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
  };

  const handleSave = async () => {
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
    }
  };

  const handleEdit = (p: Profile) => {
    setEditingId(p.profile_id);
    setNickname(p.nickname);
    setBirthDate(p.birth_date || '');
    setDiagnosisType(p.diagnosis_type || '');
    setPrimaryBehavior(p.primary_behavior || '');
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteProfile(id);
      Taro.showToast({ title: '删除成功' });
      load();
    } catch {
      Taro.showToast({ title: '删除失败', icon: 'none' });
    }
  };

  return (
    <View>
      <Text>档案管理</Text>

      {/* 现有档案列表 */}
      {profiles.map((p) => (
        <View key={p.profile_id}>
          <Text>
            {p.nickname}
            {p.diagnosis_type ? ` (${p.diagnosis_type})` : ''}
          </Text>
          <Button onClick={() => handleEdit(p)}>编辑</Button>
          <Button onClick={() => handleDelete(p.profile_id)}>删除</Button>
        </View>
      ))}

      {/* 表单 */}
      <Text>{editingId ? '编辑档案' : '新建档案'}</Text>
      <Text>昵称</Text>
      <Input
        value={nickname}
        onInput={(e) => setNickname(e.detail.value)}
        placeholder="孩子昵称"
      />
      <Text>出生日期</Text>
      <Input
        value={birthDate}
        onInput={(e) => setBirthDate(e.detail.value)}
        placeholder="YYYY-MM-DD"
      />
      <Text>诊断类型</Text>
      <Input
        value={diagnosisType}
        onInput={(e) => setDiagnosisType(e.detail.value)}
        placeholder="如：孤独症谱系障碍"
      />
      <Text>主要行为</Text>
      <Input
        value={primaryBehavior}
        onInput={(e) => setPrimaryBehavior(e.detail.value)}
        placeholder="如：情绪崩溃"
      />

      <Button onClick={handleSave}>保存</Button>
      {editingId && <Button onClick={resetForm}>取消编辑</Button>}
    </View>
  );
}
