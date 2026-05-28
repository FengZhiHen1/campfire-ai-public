import { useState, useEffect } from 'react';
import { View, Text, Button, Picker } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { listCases } from '../../../logics/cases/services/caseApi';
import './index.scss';

interface CaseItem {
  case_id: string;
  title: string;
  status: string;
  behavior_type?: string;
  evidence_level?: string;
  created_at?: string;
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

export default function CasesIndex() {
  const [items, setItems] = useState<CaseItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusIdx, setStatusIdx] = useState(0);
  const [behaviorTypeIdx, setBehaviorTypeIdx] = useState(0);
  const [activeTab, setActiveTab] = useState<'public' | 'my'>('public');

  const load = async () => {
    setLoading(true);
    try {
      const scope = activeTab === 'public' ? 'public' : 'my';
      const status = activeTab === 'my' && statusIdx > 0 ? statusOptions[statusIdx].value || undefined : undefined;
      const behaviorType = behaviorTypeOptions[behaviorTypeIdx].value || undefined;
      const res = await listCases(status, behaviorType, 1, 20, scope);
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

  useEffect(() => {
    load();
  }, [activeTab, statusIdx, behaviorTypeIdx]);

  const goDetail = (caseId: string) => {
    Taro.navigateTo({ url: `/views/cases/pages/detail?caseId=${caseId}` });
  };

  const goSubmit = () => {
    Taro.navigateTo({ url: '/views/cases/pages/submit' });
  };

  const getEvidenceClass = (level?: string) => {
    const first = (level || 'D').charAt(0).toUpperCase();
    if (first === 'A') return 'a';
    if (first === 'B') return 'b';
    if (first === 'C') return 'c';
    return 'd';
  };

  return (
    <View className="cases-page">
      {/* 顶部导航栏 */}
      <View className="cases-navbar">
        <Text className="cases-navbar__title">{activeTab === 'public' ? '公共案例库' : '我的提交'}</Text>
      </View>

      {/* Tab 切换 */}
      <View className="cases-tabs">
        <Button
          className={`cases-tabs__btn ${activeTab === 'public' ? 'cases-tabs__btn--active' : ''}`}
          onClick={() => { setActiveTab('public'); setStatusIdx(0); }}
        >
          公共案例库
        </Button>
        <Button
          className={`cases-tabs__btn ${activeTab === 'my' ? 'cases-tabs__btn--active' : ''}`}
          onClick={() => setActiveTab('my')}
        >
          我的提交
        </Button>
      </View>

      {/* 搜索栏 */}
      <View className="cases-search">
        <View className="cases-search__input-wrap">
          <Text className="cases-search__icon">🔍</Text>
          <Text className="cases-search__input">搜索案例库…</Text>
        </View>
      </View>

      {/* 筛选栏 */}
      <View className="cases-filters">
        <Picker
          mode="selector"
          range={behaviorTypeOptions.map((o) => o.label)}
          value={behaviorTypeIdx}
          onChange={(e) => setBehaviorTypeIdx(Number(e.detail.value))}
        >
          <Button className={`cases-filters__picker ${behaviorTypeIdx > 0 ? 'cases-filters__picker--active' : ''}`}>
            <Text className="cases-filters__picker-text">{behaviorTypeOptions[behaviorTypeIdx].label}</Text>
            <Text className="cases-filters__picker-chevron">▼</Text>
          </Button>
        </Picker>
        {activeTab === 'my' && (
          <Picker
            mode="selector"
            range={statusOptions.map((o) => o.label)}
            value={statusIdx}
            onChange={(e) => setStatusIdx(Number(e.detail.value))}
          >
            <Button className={`cases-filters__picker ${statusIdx > 0 ? 'cases-filters__picker--active' : ''}`}>
              <Text className="cases-filters__picker-text">{statusOptions[statusIdx].label}</Text>
              <Text className="cases-filters__picker-chevron">▼</Text>
            </Button>
          </Picker>
        )}
      </View>

      {/* 列表区域 */}
      <View className="cases-list">
        {loading && items.length === 0 && (
          <View className="cases-loading">
            <View className="cases-loading__skeleton" />
            <View className="cases-loading__skeleton" />
            <View className="cases-loading__skeleton" />
          </View>
        )}

        {!loading && items.length === 0 && (
          <View className="cases-empty">
            <View className="cases-empty__icon">📚</View>
            <Text className="cases-empty__title">暂无案例</Text>
            <Text className="cases-empty__subtitle">案例库正在建设中，敬请期待</Text>
            <Button className="cases-empty__btn" onClick={load}>
              刷新
            </Button>
          </View>
        )}

        {items.map((item) => {
          const evClass = getEvidenceClass(item.evidence_level);
          const evLetter = (item.evidence_level || 'D').charAt(0).toUpperCase();
          const stClass = statusClassMap[item.status] || 'draft';
          const stText = statusTextMap[item.status] || item.status;
          return (
            <View
              key={item.case_id}
              className="case-card"
              onClick={() => goDetail(item.case_id)}
            >
              <View className={`case-card__accent case-card__accent--${evClass}`} />
              <View className="case-card__body">
                <View className="case-card__header">
                  <Text className="case-card__title">{item.title}</Text>
                  <View className={`case-card__badge case-card__badge--${evClass}`}>
                    <Text className="case-card__badge-letter">{evLetter}</Text>
                    <Text className="case-card__badge-level">级</Text>
                  </View>
                </View>
                <View className="case-card__tags">
                  {item.behavior_type && (
                    <Text className="case-card__tag case-card__tag--primary">{item.behavior_type}</Text>
                  )}
                </View>
                <View className="case-card__footer">
                  <View className={`case-card__status-dot case-card__status-dot--${stClass}`} />
                  <Text className="case-card__status-text">{stText}</Text>
                  {item.created_at && (
                    <Text className="case-card__time">{item.created_at}</Text>
                  )}
                </View>
              </View>
            </View>
          );
        })}
      </View>

      {/* FAB */}
      <Button className="cases-fab" onClick={goSubmit}>+</Button>
    </View>
  );
}
