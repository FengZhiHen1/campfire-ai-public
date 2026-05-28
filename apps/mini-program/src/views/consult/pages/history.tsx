import { useState, useEffect } from 'react';
import { View, Text, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { consultApi } from '../../../logics/consult/services/consultApi';
import type { ConsultationHistoryListItem } from '../../../logics/consult/types';

export default function ConsultHistory() {
  const [list, setList] = useState<ConsultationHistoryListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await consultApi.fetchHistoryList(1, 20);
      setList(res.items);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const goDetail = (id: string) => {
    Taro.navigateTo({ url: `/views/consult/pages/detail?id=${id}` });
  };

  return (
    <View>
      <Text>咨询历史</Text>
      {loading && <Text>加载中...</Text>}
      {error && <Text>错误: {error}</Text>}
      {list.length === 0 && !loading && <Text>暂无历史记录</Text>}
      {list.map((item) => (
        <View key={item.id} onClick={() => goDetail(item.id)}>
          <Text>{item.behavior_description.slice(0, 40)}...</Text>
          <Text>{item.consultation_time}</Text>
          <Text>危机等级: {item.crisis_level}</Text>
        </View>
      ))}
      <Button onClick={load}>刷新</Button>
    </View>
  );
}
