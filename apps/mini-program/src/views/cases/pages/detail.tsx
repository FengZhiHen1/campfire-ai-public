import { useState, useEffect } from 'react';
import { View, Text, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { getCase, submitCase } from '../../../logics/cases/services/caseApi';

interface CaseDetail {
  case_id: string;
  title: string;
  status: string;
  scene?: string;
  immediate_action?: string;
  comforting_phrase?: string;
  observation_metrics?: string;
  medical_criteria?: string;
}

export default function CasesDetail() {
  const [data, setData] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const params = Taro.getCurrentInstance().router?.params;
    const caseId = params?.caseId;
    if (!caseId) return;

    setLoading(true);
    getCase(caseId)
      .then((res) => setData(res as unknown as CaseDetail))
      .catch(() => Taro.showToast({ title: '加载失败', icon: 'none' }))
      .finally(() => setLoading(false));
  }, []);

  const handleSubmit = async () => {
    if (!data) return;
    try {
      await submitCase(data.case_id);
      Taro.showToast({ title: '提交审核成功' });
      // 刷新
      const res = await getCase(data.case_id);
      setData(res as unknown as CaseDetail);
    } catch {
      Taro.showToast({ title: '提交失败', icon: 'none' });
    }
  };

  return (
    <View>
      <Text>案例详情</Text>
      {loading && <Text>加载中...</Text>}
      {data && (
        <View>
          <Text>标题: {data.title}</Text>
          <Text>状态: {data.status}</Text>
          <Text>场景: {data.scene || '无'}</Text>
          <Text>即时干预: {data.immediate_action || '无'}</Text>
          <Text>安抚话术: {data.comforting_phrase || '无'}</Text>
          <Text>观察指标: {data.observation_metrics || '无'}</Text>
          <Text>就医标准: {data.medical_criteria || '无'}</Text>

          {data.status === 'draft' && (
            <Button onClick={handleSubmit}>提交审核</Button>
          )}
        </View>
      )}
    </View>
  );
}
