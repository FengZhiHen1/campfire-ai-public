import { useState, useEffect } from 'react';
import { View, Text, Button } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { consultApi } from '../../../logics/consult';
import type { ConsultationHistoryListItem, CrisisLevel } from '../../../logics/consult';
import './history.scss';

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

  return (
    <View className="history-page">
      {/* 顶部导航栏 */}
      <View className="history-navbar">
        <Button className="history-navbar__back" onClick={() => Taro.navigateBack()}>
          ←
        </Button>
        <Text className="history-navbar__title">咨询历史</Text>
      </View>

      {/* 搜索栏 */}
      <View className="history-search">
        <View className="history-search__input-wrap">
          <Text className="history-search__icon">🔍</Text>
          <Text className="history-search__input">搜索历史咨询记录…</Text>
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
            {list.map((item) => {
              const levelKey = getLevelClass(item.crisis_level);
              const levelText = getLevelText(item.crisis_level);
              return (
                <View
                  key={item.id}
                  className="history-card"
                  onClick={() => goDetail(item.id)}
                >
                  {/* 第一行：危机等级 + 时间 */}
                  <View className="history-card__header">
                    <View className="history-card__level">
                      <View className={`history-card__level-dot history-card__level-dot--${levelKey}`} />
                      <Text className={`history-card__level-text history-card__level-text--${levelKey}`}>
                        {levelText}
                      </Text>
                      <Text className="history-card__time">{item.consultation_time}</Text>
                    </View>
                  </View>

                  {/* 第二行：摘要 */}
                  <Text className="history-card__summary">
                    {item.behavior_description.slice(0, 40)}
                    {item.behavior_description.length > 40 ? '…' : ''}
                  </Text>
                </View>
              );
            })}

            {/* 刷新按钮 */}
            <Button className="history-list__empty-btn" onClick={load}>
              刷新列表
            </Button>
          </>
        )}
      </View>
    </View>
  );
}
