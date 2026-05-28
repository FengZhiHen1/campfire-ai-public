import { useState, useEffect } from 'react';
import { View, Text, Button, Input } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { getCase, submitCase, reviewCase } from '../../../logics/cases/services/caseApi';
import './detail.scss';

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

const statusTextMap: Record<string, string> = {
  draft: '草稿',
  pending_review: '待审核',
  approved: '已通过',
  rejected: '已驳回',
};

const statusClassMap: Record<string, string> = {
  draft: 'draft',
  pending_review: 'pending',
  approved: 'approved',
  rejected: 'rejected',
};

const quartetConfig = [
  {
    key: 'scene' as const,
    title: '场景描述',
    accent: 'scene',
    color: 'scene',
  },
  {
    key: 'comforting_phrase' as const,
    title: '行为表现',
    accent: 'behavior',
    color: 'behavior',
  },
  {
    key: 'immediate_action' as const,
    title: '干预动作',
    accent: 'action',
    color: 'action',
  },
  {
    key: 'result' as const,
    title: '结果反馈',
    accent: 'result',
    color: 'result',
  },
];

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

  const reviewCommentLength = reviewComment.trim().length;

  const handleReject = async () => {
    if (!data) return;
    if (reviewCommentLength < 5) {
      Taro.showToast({ title: '驳回意见至少5字', icon: 'none' });
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

  const getEvidenceClass = (level?: string) => {
    const first = (level || 'D').charAt(0).toUpperCase();
    if (first === 'A') return 'a';
    if (first === 'B') return 'b';
    if (first === 'C') return 'c';
    return 'd';
  };

  const getEvidenceLetter = (level?: string) => {
    return (level || 'D').charAt(0).toUpperCase();
  };

  const getSectionValue = (key: string) => {
    if (!data) return '';
    if (key === 'scene') return data.scene || '';
    if (key === 'result') {
      const parts = [data.observation_metrics, data.medical_criteria].filter(Boolean);
      return parts.join('\n\n') || '';
    }
    return (data as any)[key] || '';
  };

  if (loading) {
    return (
      <View className="detail-page">
        <View className="detail-navbar">
          <Button className="detail-navbar__back" onClick={() => Taro.navigateBack()}>←</Button>
          <Text className="detail-navbar__title">案例详情</Text>
        </View>
        <View className="detail-loading">
          <View className="detail-loading__skeleton" />
          <Text className="detail-loading__text">加载中...</Text>
        </View>
      </View>
    );
  }

  if (!data) {
    return (
      <View className="detail-page">
        <View className="detail-navbar">
          <Button className="detail-navbar__back" onClick={() => Taro.navigateBack()}>←</Button>
          <Text className="detail-navbar__title">案例详情</Text>
        </View>
        <View className="detail-loading">
          <Text className="detail-loading__text">未找到案例</Text>
        </View>
      </View>
    );
  }

  const evClass = getEvidenceClass(data.evidence_level);
  const evLetter = getEvidenceLetter(data.evidence_level);
  const stClass = statusClassMap[data.status] || 'draft';
  const stText = statusTextMap[data.status] || data.status;

  return (
    <View className="detail-page">
      {/* 顶部导航栏 */}
      <View className="detail-navbar">
        <Button className="detail-navbar__back" onClick={() => Taro.navigateBack()}>←</Button>
        <Text className="detail-navbar__title">案例详情</Text>
      </View>

      {/* 封面图占位 */}
      <View className="detail-cover">
        <Text className="detail-cover__icon">🖼️</Text>
        <Text className="detail-cover__text">本案例未上传封面图</Text>
      </View>

      {/* 概览信息 */}
      <View className="detail-overview">
        <Text className="detail-overview__title">{data.title}</Text>
        <View className="detail-overview__tags">
          {data.behavior_type && (
            <Text className="detail-overview__tag detail-overview__tag--primary">{data.behavior_type}</Text>
          )}
          {data.severity && (
            <Text className="detail-overview__tag detail-overview__tag--default">{data.severity}</Text>
          )}
          {data.scene && (
            <Text className="detail-overview__tag detail-overview__tag--default">{data.scene}</Text>
          )}
        </View>
        <View className="detail-overview__meta">
          <View className={`detail-overview__badge detail-overview__badge--${evClass}`}>
            <Text className="detail-overview__badge-letter">{evLetter}</Text>
            <Text className="detail-overview__badge-level">级</Text>
          </View>
          <View className="detail-overview__status">
            <View className={`detail-overview__status-dot detail-overview__status-dot--${stClass}`} />
            <Text className="detail-overview__status-text">{stText}</Text>
          </View>
        </View>
      </View>

      {/* 四段式内容 */}
      <View className="detail-quartet">
        {quartetConfig.map((cfg) => {
          const value = getSectionValue(cfg.key);
          return (
            <View key={cfg.key} className="detail-card">
              <View className={`detail-card__accent detail-card__accent--${cfg.accent}`} />
              <View className="detail-card__body">
                <Text className={`detail-card__title detail-card__title--${cfg.color}`}>
                  {cfg.title}
                </Text>
                {value ? (
                  <Text className="detail-card__content">{value}</Text>
                ) : (
                  <Text className="detail-card__empty">（暂无内容）</Text>
                )}
              </View>
            </View>
          );
        })}
      </View>

      {/* 审核操作 */}
      <View className="detail-actions">
        {data.status === 'draft' && (
          <View className="detail-actions__panel">
            <Text className="detail-actions__panel-title">审核操作</Text>
            <Button className="detail-actions__btn detail-actions__btn--primary" onClick={handleSubmit}>
              提交审核
            </Button>
          </View>
        )}

        {data.status === 'pending_review' && (
          <View className="detail-actions__panel">
            <Text className="detail-actions__panel-title">审核操作</Text>
            {!showRejectInput && (
              <View className="detail-actions__row">
                <Button className="detail-actions__btn detail-actions__btn--tertiary" onClick={handleApprove}>
                  <Text className="detail-actions__btn-icon">✓</Text>
                  <Text>审核通过</Text>
                </Button>
                <Button className="detail-actions__btn detail-actions__btn--error" onClick={() => setShowRejectInput(true)}>
                  <Text className="detail-actions__btn-icon">✗</Text>
                  <Text>驳回</Text>
                </Button>
              </View>
            )}
            {showRejectInput && (
              <>
                <View className="detail-actions__input-wrap">
                  <Input
                    className="detail-actions__input"
                    value={reviewComment}
                    onInput={(e) => setReviewComment(e.detail.value)}
                    placeholder="请输入驳回原因，将反馈给作者…"
                  />
                  <Text className={`detail-actions__char-count ${reviewCommentLength < 5 ? 'detail-actions__char-count--error' : ''}`}>
                    {reviewCommentLength}/200
                  </Text>
                </View>
                <View className="detail-actions__row">
                  <Button
                    className={`detail-actions__btn detail-actions__btn--error ${reviewCommentLength < 5 ? 'detail-actions__btn--disabled' : ''}`}
                    onClick={handleReject}
                    disabled={reviewCommentLength < 5}
                  >
                    确认驳回
                  </Button>
                  <Button className="detail-actions__btn detail-actions__btn--secondary" onClick={() => { setShowRejectInput(false); setReviewComment(''); }}>
                    取消
                  </Button>
                </View>
              </>
            )}
          </View>
        )}

        {data.status === 'approved' && (
          <View className="detail-actions__result detail-actions__result--approved">
            <Text className="detail-actions__result-icon">✓</Text>
            <Text className="detail-actions__result-text detail-actions__result-text--approved">该案例已通过审核</Text>
          </View>
        )}

        {data.status === 'rejected' && (
          <View className="detail-actions__result detail-actions__result--rejected">
            <Text className="detail-actions__result-icon">✗</Text>
            <Text className="detail-actions__result-text detail-actions__result-text--rejected">该案例已被驳回</Text>
          </View>
        )}
      </View>
    </View>
  );
}
