import { useState, useMemo } from 'react';
import { View, Text, Button, Input, Textarea, ScrollView } from '@tarojs/components';
import Taro from '@tarojs/taro';
import { useReviewPage } from '../../../logics/cases';
import './review.scss';

// ============================================================================
// 组件：案例审核工作台（纯渲染层）
//
// 所有业务逻辑在 useReviewPage Hook 中。
// 本组件负责 JSX 渲染、局部 UI 状态（筛选、多选、面板开关）和事件绑定。
// ============================================================================

const FILTER_TAGS = ['全部', '自伤', '攻击', '逃跑', '服药', '情绪', '其他'];

/** AI 预审 overall → 通过项数/总项数 的映射（视觉展示用） */
function getAiProgress(overall: string): { passed: number; total: number } {
  switch (overall) {
    case 'pass': return { passed: 4, total: 4 };
    case 'annotated': return { passed: 3, total: 4 };
    case 'hard_block': return { passed: 1, total: 4 };
    default: return { passed: 2, total: 4 };
  }
}

/** 格式化日期 */
function fmtDate(iso: string): string {
  return iso?.slice(0, 10) ?? '--';
}

export default function ReviewPage() {
  // ---- Hook 业务逻辑 ----
  const {
    queue, isLoading, error, total, hasMore, actionState, canReview,
    fetchQueue, handleApprove, handleReject, loadMore,
    getAiReviewText, getTimeoutText,
  } = useReviewPage();

  // ---- 局部 UI 状态 ----
  const [activeFilter, setActiveFilter] = useState('全部');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [sheetVisible, setSheetVisible] = useState(false);
  const [sheetCaseId, setSheetCaseId] = useState<string | null>(null);
  const [rejectModalVisible, setRejectModalVisible] = useState(false);
  const [rejectComment, setRejectComment] = useState('');
  const [singleRejectCaseId, setSingleRejectCaseId] = useState<string | null>(null);
  const [sheetExpandedReject, setSheetExpandedReject] = useState(false);
  const [sheetRejectComment, setSheetRejectComment] = useState('');

  // ---- 筛选后队列 ----
  const filteredQueue = useMemo(() => {
    if (activeFilter === '全部') return queue;
    return queue.filter((item) => item.behavior_type === activeFilter);
  }, [queue, activeFilter]);

  // ---- 当前面板案例 ----
  const sheetCase = useMemo(
    () => queue.find((i) => i.narrative_id === sheetCaseId) ?? null,
    [queue, sheetCaseId]
  );

  // ---- 多选操作 ----
  const toggleSelect = (caseId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(caseId)) next.delete(caseId);
      else next.add(caseId);
      return next;
    });
  };

  const selectAll = () => {
    setSelectedIds(new Set(filteredQueue.map((i) => i.narrative_id)));
  };

  const clearSelection = () => {
    setSelectedIds(new Set());
  };

  const isAllSelected = filteredQueue.length > 0 && selectedIds.size === filteredQueue.length;

  // ---- 批量通过 ----
  const onBatchApprove = async () => {
    if (selectedIds.size === 0) return;
    const res = await Taro.showModal({
      title: '确认批量通过',
      content: `确定批量通过 ${selectedIds.size} 条案例？`,
      confirmColor: '#059669',
    });
    if (!res.confirm) return;

    const ids = Array.from(selectedIds);
    let successCount = 0;
    for (const id of ids) {
      try {
        await handleApprove(id);
        successCount++;
      } catch {
        // 单条错误已在内层 Toast
      }
    }
    setSelectedIds(new Set());
    Taro.showToast({ title: `${successCount} 条案例已审核通过`, icon: 'success' });
  };

  // ---- 批量驳回弹窗 ----
  const onBatchReject = () => {
    if (selectedIds.size === 0) return;
    setRejectComment('');
    setRejectModalVisible(true);
  };

  const confirmBatchReject = async () => {
    const comment = rejectComment.trim();
    if (comment.length < 5) {
      Taro.showToast({ title: '驳回意见至少 5 个字', icon: 'none' });
      return;
    }
    const ids = Array.from(selectedIds);
    let successCount = 0;
    for (const id of ids) {
      try {
        await handleReject(id, comment);
        successCount++;
      } catch {
        // 单条错误已在内层 Toast
      }
    }
    setRejectModalVisible(false);
    setSelectedIds(new Set());
    Taro.showToast({ title: `${successCount} 条案例已驳回`, icon: 'success' });
  };

  // ---- 单条审核 ----
  const openSheet = (caseId: string) => {
    setSheetCaseId(caseId);
    setSheetExpandedReject(false);
    setSheetRejectComment('');
    setSheetVisible(true);
  };

  const closeSheet = () => {
    setSheetVisible(false);
    setTimeout(() => setSheetCaseId(null), 300);
  };

  const onSingleApprove = async (caseId: string) => {
    await handleApprove(caseId);
    closeSheet();
  };

  const onSingleReject = async () => {
    if (!sheetCase) return;
    const comment = sheetRejectComment.trim();
    if (comment.length < 5) {
      Taro.showToast({ title: '驳回意见至少 5 个字', icon: 'none' });
      return;
    }
    await handleReject(sheetCase.narrative_id, comment);
    setSheetExpandedReject(false);
    setSheetRejectComment('');
    closeSheet();
  };

  // ---- 统计 ----
  const todayHandled = 0; // TODO: 后端暂无该字段，留空

  // ---- 门禁：无权限时 Hook 已自动返回，此处兜底 ----
  if (!canReview) {
    return (
      <View className="review-page">
        <View className="review-empty">
          <Text className="review-empty__title">暂无审核权限</Text>
          <Button className="review-empty__btn" onClick={() => Taro.navigateBack()}>
            返回
          </Button>
        </View>
      </View>
    );
  }

  return (
    <View className={`review-page ${selectedIds.size > 0 ? 'review-page--batch' : ''}`}>
      {/* ========== 顶部导航栏 ========== */}
      <View className="review-navbar">
        <Button className="review-navbar__back" onClick={() => Taro.navigateBack()}>
          &#8249;
        </Button>
        <Text className="review-navbar__title">审核工作台</Text>
        <Button className="review-navbar__stats-btn">统计</Button>
      </View>

      {/* ========== 统计概览区 ========== */}
      <View className="review-stats">
        <View className="review-stats__item">
          <Text className="review-stats__label">待审核</Text>
          <Text className={`review-stats__num ${total > 0 ? 'review-stats__num--alert' : ''}`}>
            {total}
          </Text>
        </View>
        <View className="review-stats__item">
          <Text className="review-stats__label">今日已处理</Text>
          <Text className="review-stats__num review-stats__num--success">{todayHandled}</Text>
        </View>
      </View>

      {/* ========== 快速筛选标签栏 ========== */}
      <ScrollView className="review-filters" scrollX showScrollbar={false}>
        {FILTER_TAGS.map((tag) => (
          <Button
            key={tag}
            className={`review-filters__tag ${activeFilter === tag ? 'review-filters__tag--active' : ''}`}
            onClick={() => {
              setActiveFilter(tag);
              clearSelection();
            }}
          >
            {tag}
          </Button>
        ))}
      </ScrollView>

      {/* ========== 列表区域 ========== */}
      <ScrollView
        className="review-list"
        scrollY
        lowerThreshold={80}
        onScrollToLower={loadMore}
      >
        {/* 骨架屏 */}
        {isLoading && filteredQueue.length === 0 && (
          <View className="review-loading">
            <View className="review-loading__skeleton" />
            <View className="review-loading__skeleton" />
            <View className="review-loading__skeleton" />
          </View>
        )}

        {/* 错误态 */}
        {error && filteredQueue.length === 0 && (
          <View className="review-empty">
            <Text className="review-empty__title">无法加载待审列表</Text>
            <Text className="review-empty__subtitle">{error}</Text>
            <Button className="review-empty__btn" onClick={() => fetchQueue(1)}>
              重新加载
            </Button>
          </View>
        )}

        {/* 空状态 */}
        {!isLoading && !error && filteredQueue.length === 0 && (
          <View className="review-empty">
            <View className="review-empty__icon">
              <Text className="review-empty__icon-emoji">&#127881;</Text>
            </View>
            <Text className="review-empty__title">
              {activeFilter === '全部' ? '所有案例已审核完毕！' : '没有符合条件的待审案例'}
            </Text>
            <Text className="review-empty__subtitle">
              {activeFilter === '全部'
                ? '暂无待审核案例，您可以休息一下'
                : '尝试更换筛选条件'}
            </Text>
            {activeFilter !== '全部' && (
              <Button className="review-empty__btn review-empty__btn--text" onClick={() => setActiveFilter('全部')}>
                清除筛选
              </Button>
            )}
            {activeFilter === '全部' && (
              <Button className="review-empty__btn" onClick={() => Taro.navigateBack()}>
                返回案例库
              </Button>
            )}
          </View>
        )}

        {/* 案例列表 */}
        {filteredQueue.map((item) => {
          const aiProgress = getAiProgress(item.ai_review_overall);
          const isSelected = selectedIds.has(item.narrative_id);
          const isSubmitting = actionState.isSubmitting && actionState.targetCaseId === item.narrative_id;

          return (
            <View
              key={item.narrative_id}
              className={`review-row ${isSubmitting ? 'review-row--exiting' : ''}`}
            >
              {/* 左侧状态条 */}
              <View
                className={`review-row__accent ${aiProgress.passed <= 1 ? 'review-row__accent--error' : ''}`}
              />

              {/* 复选框 */}
              <View className="review-row__checkbox" onClick={() => toggleSelect(item.narrative_id)}>
                <View className={`review-row__checkbox-box ${isSelected ? 'review-row__checkbox-box--checked' : ''}`}>
                  {isSelected && <Text className="review-row__checkbox-tick">&#10003;</Text>}
                </View>
              </View>

              {/* 内容区 */}
              <View className="review-row__body">
                <Text className="review-row__title">{item.title}</Text>
                <View className="review-row__meta">
                  <Text className="review-row__behavior">{item.behavior_type}</Text>
                  <Text className="review-row__author">{item.author_name}</Text>
                </View>
                {/* AI 预审进度 */}
                <View className="review-row__ai">
                  <View className="review-row__ai-bar">
                    <View
                      className="review-row__ai-bar-fill"
                      style={{
                        width: `${(aiProgress.passed / aiProgress.total) * 100}%`,
                        backgroundColor:
                          aiProgress.passed === aiProgress.total ? '#059669' : '#DC2626',
                      }}
                    />
                  </View>
                  <Text className="review-row__ai-text">
                    {aiProgress.passed}/{aiProgress.total}
                  </Text>
                </View>
                {/* 超时状态 */}
                {item.timeout_status !== 'normal' && (
                  <Text className={`review-row__timeout review-row__timeout--${item.timeout_status}`}>
                    {getTimeoutText(item.timeout_status)}
                  </Text>
                )}
              </View>

              {/* 去审核按钮 */}
              <Button
                className="review-row__action"
                onClick={() => openSheet(item.narrative_id)}
              >
                审核
              </Button>
            </View>
          );
        })}

        {/* 加载更多 */}
        {isLoading && filteredQueue.length > 0 && (
          <View className="review-load-more">
            <View className="review-load-more__spinner" />
            <Text className="review-load-more__text">加载中…</Text>
          </View>
        )}

        {!hasMore && !isLoading && filteredQueue.length > 0 && (
          <Text className="review-no-more">—— 已展示全部待审案例 ——</Text>
        )}
      </ScrollView>

      {/* ========== 批量操作栏 ========== */}
      {selectedIds.size > 0 && (
        <View className="review-batch">
          <View className="review-batch__header">
            <Text className="review-batch__count">已选择 {selectedIds.size} 条</Text>
            <Button className="review-batch__toggle" onClick={isAllSelected ? clearSelection : selectAll}>
              {isAllSelected ? '取消全选' : '全选'}
            </Button>
          </View>
          <View className="review-batch__actions">
            <Button className="review-batch__btn review-batch__btn--pass" onClick={onBatchApprove}>
              &#10003; 批量通过
            </Button>
            <Button className="review-batch__btn review-batch__btn--reject" onClick={onBatchReject}>
              &#10007; 批量驳回
            </Button>
          </View>
        </View>
      )}

      {/* ========== 审核面板遮罩 ========== */}
      {sheetVisible && (
        <View className="review-sheet-overlay" onClick={closeSheet} />
      )}

      {/* ========== 审核面板（Bottom Sheet） ========== */}
      {sheetVisible && sheetCase && (
        <View className="review-sheet">
          {/* 手柄 */}
          <View className="review-sheet__handle" onClick={closeSheet}>
            <View className="review-sheet__handle-bar" />
          </View>

          {/* 关闭按钮 */}
          <Button className="review-sheet__close" onClick={closeSheet}>
            &#10005;
          </Button>

          {/* 标题 */}
          <Text className="review-sheet__title">{sheetCase.title}</Text>
          <Text className="review-sheet__meta">
            {sheetCase.behavior_type} · {sheetCase.author_name} · {fmtDate(sheetCase.submitted_at)}
          </Text>

          {/* AI 预审结果 */}
          <View className="review-sheet__ai">
            <Text className="review-sheet__ai-title">AI 预审结果</Text>
            <View className="review-sheet__ai-status">
              <Text
                className={`review-sheet__ai-badge review-sheet__ai-badge--${sheetCase.ai_review_overall}`}
              >
                {getAiReviewText(sheetCase.ai_review_overall)}
              </Text>
            </View>
          </View>

          {/* 查看完整案例 */}
          <Button
            className="review-sheet__link"
            onClick={() => {
              closeSheet();
              Taro.navigateTo({ url: `/views/cases/pages/detail?narrativeId=${sheetCase.narrative_id}` });
            }}
          >
            查看完整案例 &#8250;
          </Button>

          {/* 底部操作区 */}
          <View className="review-sheet__actions">
            <Button
              className="review-sheet__btn review-sheet__btn--pass"
              onClick={() => onSingleApprove(sheetCase.narrative_id)}
            >
              &#10003; 通过
            </Button>
            {!sheetExpandedReject && (
              <Button
                className="review-sheet__btn review-sheet__btn--reject"
                onClick={() => setSheetExpandedReject(true)}
              >
                &#10007; 驳回
              </Button>
            )}
            {sheetExpandedReject && (
              <>
                <View className="review-sheet__reject-input">
                  <Textarea
                    className="review-sheet__reject-field"
                    placeholder="请输入驳回原因，将反馈给作者…"
                    value={sheetRejectComment}
                    onInput={(e) => setSheetRejectComment(e.detail.value)}
                  />
                </View>
                <Button
                  className="review-sheet__btn review-sheet__btn--reject"
                  onClick={onSingleReject}
                >
                  确认驳回
                </Button>
                <Button
                  className="review-sheet__btn review-sheet__btn--cancel"
                  onClick={() => {
                    setSheetExpandedReject(false);
                    setSheetRejectComment('');
                  }}
                >
                  取消驳回
                </Button>
              </>
            )}
          </View>
        </View>
      )}

      {/* ========== 批量驳回弹窗 ========== */}
      {rejectModalVisible && (
        <View className="review-modal">
          <View className="review-modal__overlay" onClick={() => setRejectModalVisible(false)} />
          <View className="review-modal__content">
            <Text className="review-modal__title">批量驳回 {selectedIds.size} 条案例</Text>
            <Text className="review-modal__subtitle">
              统一驳回意见将发送给所有被选中案例的作者
            </Text>
            <View className="review-modal__input-wrap">
              <Textarea
                className="review-modal__input"
                placeholder="请输入统一驳回原因…"
                value={rejectComment}
                onInput={(e) => setRejectComment(e.detail.value)}
              />
              <Text className="review-modal__count">{rejectComment.length}/200</Text>
            </View>
            <View className="review-modal__actions">
              <Button
                className="review-modal__btn review-modal__btn--cancel"
                onClick={() => setRejectModalVisible(false)}
              >
                取消
              </Button>
              <Button
                className="review-modal__btn review-modal__btn--confirm"
                onClick={confirmBatchReject}
              >
                确认驳回
              </Button>
            </View>
          </View>
        </View>
      )}
    </View>
  );
}
