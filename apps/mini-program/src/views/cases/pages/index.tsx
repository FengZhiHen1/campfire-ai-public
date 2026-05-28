import { useState, useEffect } from 'react';
import { View, Text, Button, Picker } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { listCases } from '../../../logics/cases/services/caseApi';

interface CaseItem {
  case_id: string;
  title: string;
  status: string;
  behavior_type?: string;
}

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '草稿', value: 'draft' },
  { label: '待审核', value: 'pending_review' },
  { label: '已通过', value: 'approved' },
  { label: '已驳回', value: 'rejected' },
];

const behaviorTypeOptions = [
  { label: '全部类型', value: '' },
  { label: '自伤', value: '自伤' },
  { label: '攻击', value: '攻击' },
  { label: '刻板', value: '刻板' },
  { label: '逃跑', value: '逃跑' },
  { label: '情绪崩溃', value: '情绪崩溃' },
  { label: '其他', value: '其他' },
];

export default function CasesIndex() {
  const [items, setItems] = useState<CaseItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusIdx, setStatusIdx] = useState(0);
  const [behaviorTypeIdx, setBehaviorTypeIdx] = useState(0);

  const load = async () => {
    setLoading(true);
    try {
      const status = statusOptions[statusIdx].value || undefined;
      const behaviorType = behaviorTypeOptions[behaviorTypeIdx].value || undefined;
      const res = await listCases(status, behaviorType, 1, 20);
      setItems(res.items as CaseItem[]);
    } catch {
      Taro.showToast({ title: '加载失败', icon: 'none' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  // 筛选条件变化时自动刷新
  useEffect(() => {
    load();
  }, [statusIdx, behaviorTypeIdx]);

  const goDetail = (caseId: string) => {
    Taro.navigateTo({ url: `/views/cases/pages/detail?caseId=${caseId}` });
  };

  const goSubmit = () => {
    Taro.navigateTo({ url: '/views/cases/pages/submit' });
  };

  return (
    <View>
      <Text>案例库</Text>

      <Text>状态筛选</Text>
      <Picker
        mode="selector"
        range={statusOptions.map((o) => o.label)}
        value={statusIdx}
        onChange={(e) => setStatusIdx(Number(e.detail.value))}
      >
        <View>{statusOptions[statusIdx].label}</View>
      </Picker>

      <Text>行为类型筛选</Text>
      <Picker
        mode="selector"
        range={behaviorTypeOptions.map((o) => o.label)}
        value={behaviorTypeIdx}
        onChange={(e) => setBehaviorTypeIdx(Number(e.detail.value))}
      >
        <View>{behaviorTypeOptions[behaviorTypeIdx].label}</View>
      </Picker>

      {loading && <Text>加载中...</Text>}
      {items.length === 0 && !loading && <Text>暂无案例</Text>}
      {items.map((item) => (
        <View key={item.case_id} onClick={() => goDetail(item.case_id)}>
          <Text>{item.title}</Text>
          <Text>状态: {item.status}</Text>
          {item.behavior_type && <Text>类型: {item.behavior_type}</Text>}
        </View>
      ))}
      <Button onClick={goSubmit}>提交新案例</Button>
      <Button onClick={load}>刷新</Button>
    </View>
  );
}
