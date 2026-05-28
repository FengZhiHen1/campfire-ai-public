import { useState, useEffect } from 'react';
import { View, Text, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { listNarratives, type NarrativeListItem } from '../../../logics/cases/services/narrativeApi';
import './index.scss';

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '草稿', value: 'draft' },
  { label: '待审核', value: 'pending_review' },
  { label: '已通过', value: 'approved' },
  { label: '已驳回', value: 'rejected' },
];

const sourceTypeLabel: Record<string, string> = {
  '专家撰写': '专家',
  '机构脱敏': '机构',
  '工单沉淀': '工单',
};

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
  const [items, setItems] = useState<NarrativeListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'public' | 'my'>('public');

  const load = async () => {
    setLoading(true);
    try {
      const scope = activeTab === 'public' ? 'public' : 'my';
      const res = await listNarratives(scope, 1, 20);
      setItems(res.items);
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
  }, [activeTab]);

  const goDetail = (narrativeId: string) => {
    Taro.navigateTo({ url: `/views/cases/pages/detail?caseId=${narrativeId}` });
  };

  const goSubmit = () => {
    Taro.navigateTo({ url: '/views/cases/pages/narrative-submit' });
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
            <Text className="cases-empty__subtitle">
              {activeTab === 'public' ? '案例库正在建设中，敬请期待' : '你还没有提交过案例'}
            </Text>
            <Button className="cases-empty__btn" onClick={load}>
              刷新
            </Button>
          </View>
        )}

        {items.map((item) => {
          const stClass = statusClassMap[item.status] || 'draft';
          const stText = statusTextMap[item.status] || item.status;
          const srcLabel = sourceTypeLabel[item.source_type] || item.source_type;
          return (
            <View
              key={item.narrative_id}
              className="case-card"
              onClick={() => goDetail(item.narrative_id)}
            >
              <View className={`case-card__accent case-card__accent--${stClass}`} />
              <View className="case-card__body">
                <View className="case-card__header">
                  <Text className="case-card__title">{item.title}</Text>
                  <View className="case-card__badge">
                    <Text className="case-card__badge-text">{item.card_count} 卡片</Text>
                  </View>
                </View>
                <View className="case-card__tags">
                  <Text className="case-card__tag case-card__tag--source">{srcLabel}</Text>
                </View>
                <View className="case-card__footer">
                  <View className={`case-card__status-dot case-card__status-dot--${stClass}`} />
                  <Text className="case-card__status-text">{stText}</Text>
                  {item.created_at && (
                    <Text className="case-card__time">{item.created_at?.slice(0, 10)}</Text>
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
