import { useState, useEffect } from 'react';
import { View, Text, Button, Input } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { consultApi } from '../../../logics/consult';
import type { ConsultationHistoryListItem, CrisisLevel } from '../../../logics/consult';
import './history.scss';

// 前端本地扩展：后端列表接口暂未返回 behavior_types / trust_label，
// 预留字段以便未来契约升级后自动展示，当前降级为基于 crisis_level 的默认映射。
interface HistoryListItem extends ConsultationHistoryListItem {
  behavior_types?: string[];
  trust_label?: string;
}

export default function ConsultHistory() {
  const [list, setList] = useState<HistoryListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await consultApi.fetchHistoryList(1, 20);
      // 将原始数据映射为本地扩展类型（预留字段自动为 undefined）
      setList(res.items as HistoryListItem[]);
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

  const getLevelClass = (level: CrisisLevel) => {
    if (level === 'severe') return 'high';
    if (level === 'moderate') return 'medium';
    return 'low';
  };

  const getLevelText = (level: CrisisLevel) => {
    if (level === 'severe') return '重度';
    if (level === 'moderate') return '中度';
    return '轻度';
  };

  // 可信标签默认映射（视觉降级，待后端提供真实 trust_label 后移除）
  const getTrustLabel = (item: HistoryListItem) => {
    if (item.trust_label) return item.trust_label;
    if (item.crisis_level === 'mild') return '高可信';
    if (item.crisis_level === 'moderate') return '中可信';
    return '需复核';
  };

  const getTrustClass = (level: CrisisLevel) => {
    if (level === 'mild') return 'trust-high';
    if (level === 'moderate') return 'trust-medium';
    return 'trust-low';
  };

  const filteredList = list.filter((item) =>
    item.behavior_description.toLowerCase().includes(searchQuery.toLowerCase()),
  );

  return (
    <View className="history-page">
      {/* 搜索栏 */}
      <View className="history-search">
        <View className="history-search__input-wrap">
          <Text className="history-search__icon">🔍</Text>
          <Input
            className="history-search__input"
            type="text"
            placeholder="搜索历史咨询记录…"
            value={searchQuery}
            onInput={(e) => setSearchQuery(e.detail.value)}
          />
        </View>
      </View>

      {/* 列表区域 */}
      <View className="history-list">
        {/* 加载中 */}
        {loading && list.length === 0 && (
          <View className="history-loading">
            <View className="history-loading__skeleton" />
            <View className="history-loading__skeleton" />
            <View className="history-loading__skeleton" />
            <Text className="history-loading__text">正在整理您的咨询记录…</Text>
          </View>
        )}

        {/* 错误 */}
        {error && (
          <View className="history-error">
            <Text className="history-error__icon">📡</Text>
            <Text className="history-error__title">无法加载记录</Text>
            <Text className="history-error__subtitle">请检查网络连接后重试</Text>
            <Button className="history-error__retry-btn" onClick={load}>
              重新加载
            </Button>
          </View>
        )}

        {/* 空状态 */}
        {!loading && !error && list.length === 0 && (
          <View className="history-list__empty">
            <View className="history-list__empty-icon">🔥</View>
            <Text className="history-list__empty-title">暂无咨询记录</Text>
            <Text className="history-list__empty-subtitle">
              当需要应急建议时，前往应急咨询页面发起对话
            </Text>
            <Button
              className="history-list__empty-btn"
              onClick={() => Taro.redirectTo({ url: '/views/consult/pages/index' })}
            >
              前往咨询
            </Button>
          </View>
        )}

        {/* 列表 */}
        {!loading && !error && list.length > 0 && (
          <>
            {filteredList.map((item) => {
              const levelKey = getLevelClass(item.crisis_level);
              const levelText = getLevelText(item.crisis_level);
              const trustLabel = getTrustLabel(item);
              const trustClass = getTrustClass(item.crisis_level);
              return (
                <View
                  key={item.id}
                  className="history-card"
                  onClick={() => goDetail(item.id)}
                >
                  {/* 第一行：危机等级 + 时间 + 可信标签 */}
                  <View className="history-card__header">
                    <View className="history-card__level">
                      <View className={`history-card__level-dot history-card__level-dot--${levelKey}`} />
                      <Text className={`history-card__level-text history-card__level-text--${levelKey}`}>
                        {levelText}
                      </Text>
                      <Text className="history-card__time">{item.consultation_time}</Text>
                    </View>
                    <View className={`history-card__trust history-card__trust--${trustClass}`}>
                      <Text className="history-card__trust-text">{trustLabel}</Text>
                      <Text className="history-card__trust-dot">●</Text>
                    </View>
                  </View>

                  {/* 第二行：行为标签 */}
                  {item.behavior_types && item.behavior_types.length > 0 && (
                    <View className="history-card__tags">
                      {item.behavior_types.map((tag) => (
                        <View key={tag} className="history-card__tag">
                          <Text className="history-card__tag-text">{tag}</Text>
                        </View>
                      ))}
                    </View>
                  )}

                  {/* 第三行：摘要 */}
                  <Text className="history-card__summary">
                    {item.behavior_description.slice(0, 50)}
                    {item.behavior_description.length > 50 ? '…' : ''}
                  </Text>
                </View>
              );
            })}

            {/* 刷新按钮 */}
            <Button className="history-list__refresh-btn" onClick={load}>
              刷新列表
            </Button>
          </>
        )}
      </View>
    </View>
  );
}
