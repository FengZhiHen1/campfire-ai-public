import { useState, useEffect } from 'react';
import { View, Text, Button, Input } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { getCase, submitCase, reviewCase } from '../../../logics/cases/services/caseApi';

interface CaseDetail {
  case_id: string;
  title: string;
  status: string;
  behavior_type?: string;
  severity?: string;
  scene?: string;
  immediate_action?: string;
  comforting_phrase?: string;
  observation_metrics?: string;
  medical_criteria?: string;
  evidence_level?: string;
}

export default function CasesDetail() {
  const [data, setData] = useState<CaseDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [reviewComment, setReviewComment] = useState('');
  const [showRejectInput, setShowRejectInput] = useState(false);

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
      const res = await getCase(data.case_id);
      setData(res as unknown as CaseDetail);
    } catch {
      Taro.showToast({ title: '提交失败', icon: 'none' });
    }
  };

  const handleApprove = async () => {
    if (!data) return;
    try {
      await reviewCase(data.case_id, 'approved');
      Taro.showToast({ title: '审核通过' });
      const res = await getCase(data.case_id);
      setData(res as unknown as CaseDetail);
    } catch {
      Taro.showToast({ title: '审核失败', icon: 'none' });
    }
  };

  const handleReject = async () => {
    if (!data) return;
    if (!reviewComment.trim() || reviewComment.trim().length < 10) {
      Taro.showToast({ title: '驳回意见至少10字', icon: 'none' });
      return;
    }
    try {
      await reviewCase(data.case_id, 'rejected', reviewComment.trim());
      Taro.showToast({ title: '已驳回' });
      setShowRejectInput(false);
      setReviewComment('');
      const res = await getCase(data.case_id);
      setData(res as unknown as CaseDetail);
    } catch {
      Taro.showToast({ title: '驳回失败', icon: 'none' });
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
          <Text>行为类型: {data.behavior_type || '无'}</Text>
          <Text>严重程度: {data.severity || '无'}</Text>
          <Text>场景: {data.scene || '无'}</Text>
          <Text>循证等级: {data.evidence_level || '无'}</Text>
          <Text>即时干预: {data.immediate_action || '无'}</Text>
          <Text>安抚话术: {data.comforting_phrase || '无'}</Text>
          <Text>观察指标: {data.observation_metrics || '无'}</Text>
          <Text>就医标准: {data.medical_criteria || '无'}</Text>

          {data.status === 'draft' && (
            <Button onClick={handleSubmit}>提交审核</Button>
          )}

          {data.status === 'pending_review' && (
            <View>
              <Button onClick={handleApprove}>审核通过</Button>
              {!showRejectInput && (
                <Button onClick={() => setShowRejectInput(true)}>驳回</Button>
              )}
              {showRejectInput && (
                <View>
                  <Input
                    value={reviewComment}
                    onInput={(e) => setReviewComment(e.detail.value)}
                    placeholder="请输入驳回意见（至少10字）"
                  />
                  <Button onClick={handleReject}>确认驳回</Button>
                  <Button onClick={() => setShowRejectInput(false)}>取消</Button>
                </View>
              )}
            </View>
          )}
        </View>
      )}
    </View>
  );
}
