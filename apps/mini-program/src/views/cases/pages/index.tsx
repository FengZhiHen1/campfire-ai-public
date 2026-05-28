import { useState, useEffect } from 'react';
import { View, Text, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { listCases } from '../../../logics/cases/services/caseApi';

interface CaseItem {
  case_id: string;
  title: string;
  status: string;
}

export default function CasesIndex() {
  const [items, setItems] = useState<CaseItem[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await listCases(undefined, 1, 20);
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

  const goDetail = (caseId: string) => {
    Taro.navigateTo({ url: `/views/cases/pages/detail?caseId=${caseId}` });
  };

  const goSubmit = () => {
    Taro.navigateTo({ url: '/views/cases/pages/submit' });
  };

  return (
    <View>
      <Text>案例库</Text>
      {loading && <Text>加载中...</Text>}
      {items.length === 0 && !loading && <Text>暂无案例</Text>}
      {items.map((item) => (
        <View key={item.case_id} onClick={() => goDetail(item.case_id)}>
          <Text>{item.title}</Text>
          <Text>状态: {item.status}</Text>
        </View>
      ))}
      <Button onClick={goSubmit}>提交新案例</Button>
      <Button onClick={load}>刷新</Button>
    </View>
  );
}
