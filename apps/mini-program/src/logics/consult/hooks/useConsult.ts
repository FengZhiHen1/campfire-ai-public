/**
 * CSLT-08 useConsult Hook —— CSLT-07 应急咨询界面的唯一桥接接口。
 *
 * 职责：
 * - 通过 Zustand selector 读取 Store 状态（细粒度订阅，避免无关字段触发重渲染）
 * - 计算派生状态（isInputValid, isConsultActive）
 * - 返回 UseConsultReturn 接口（20 个字段/方法）
 *
 * 设计依据：CSLT-08 落地规范 §1.4（UseConsultReturn 定义）§1.6.1（接口契约）
 * 契约对齐：consult.contract.ts（品牌类型 + 类型守卫）
 *
 * 绝对约束：
 * - Hook 本身是纯 selector 封装，不包含 useEffect 或其他副作用
 * - 副作用统一在 Store action 或 SSE 事件回调中执行
 * - 所有输入校验由 Store 层通过契约守卫（isValidConsultSubmitRequest）执行
 */

import { useMemo } from 'react';
import { useConsultStore, getErrorMessage } from '../store/useConsultStore';
import { consultApi } from '../services/consultApi';
import type {
  UseConsultReturn,
  BehaviorTypeCategory,
  ConsultationHistoryListItem,
  ConsultationHistoryDetail,
} from '../types/index';

/**
 * 应急咨询编排逻辑的对外接口 Hook。
 * CSLT-07 应急咨询界面通过此 Hook 获取全部咨询状态与操作方法。
 *
 * @returns UseConsultReturn - 包含只读状态和操作方法的完整接口（20 个字段/方法）
 *
 * @sideEffects
 *   - 不直接产生副作用（纯 selector 封装）
 *   - submitConsult() / retrySubmit() / retryStream() 内部发起 HTTP 请求和 SSE 连接
 *   - startNewConsult() 清空当前会话状态
 */
export function useConsult(): UseConsultReturn {
  // ==========================================================================
  // Zustand Store Selector（细粒度订阅）
  // ==========================================================================

  const sessionState = useConsultStore((s) => s.sessionState);
  const messages = useConsultStore((s) => s.messages);
  const planSections = useConsultStore((s) => s.planSections);
  const accumulatedText = useConsultStore((s) => s.accumulatedText);
  const ticketGuide = useConsultStore((s) => s.ticketGuide);
  const errorCode = useConsultStore((s) => s.errorCode);
  const behaviorTypeSelection = useConsultStore((s) => s.behaviorTypeSelection);
  const behaviorDescription = useConsultStore((s) => s.behaviorDescription);
  const emotionLevel = useConsultStore((s) => s.emotionLevel);
  const selectedProfileId = useConsultStore((s) => s.selectedProfileId);
  const referencedCases = useConsultStore((s) => s.referencedCases);
  const crisisLevel = useConsultStore((s) => s.crisisLevel);

  // ==========================================================================
  // 派生状态（computed selectors）
  // ==========================================================================

  /** 输入是否有效：行为类型 ≥1 且描述去除首尾空白后非空 */
  const isInputValid: boolean = useMemo(
    () => (behaviorTypeSelection ?? []).length >= 1 && (behaviorDescription ?? '').trim() !== '',
    [behaviorTypeSelection, behaviorDescription],
  );

  /** 是否处于活跃咨询中：submitting 或 streaming 状态 */
  const isConsultActive: boolean = useMemo(
    () => sessionState === 'submitting' || sessionState === 'streaming',
    [sessionState],
  );

  // ==========================================================================
  // Actions（从 Store 获取稳定引用）
  // ==========================================================================

  const store = useConsultStore;

  // ==========================================================================
  // 组装返回值（useMemo 避免每次渲染创建新对象）
  // ==========================================================================

  return useMemo<UseConsultReturn>(
    () => ({
      sessionState,
      behaviorTypeSelection,
      behaviorDescription,
      messages,
      planSections,
      accumulatedText,
      ticketGuide,
      errorCode,
      isInputValid,
      isConsultActive,
      emotionLevel,
      selectedProfileId,
      referencedCases,
      crisisLevel: crisisLevel as UseConsultReturn['crisisLevel'],

      // 操作方法
      startConsult: store.getState().startConsult,
      setBehaviorTypes: (types: BehaviorTypeCategory[]) =>
        store.getState().setBehaviorTypes(types),
      setBehaviorDescription: (desc: string) =>
        store.getState().setBehaviorDescription(desc),
      setEmotionLevel: (level) =>
        store.getState().setEmotionLevel(level),
      setSelectedProfile: (profileId) =>
        store.getState().setSelectedProfile(profileId),
      submitConsult: () => store.getState().submitConsult(),
      cancelSelection: () => store.getState().cancelSelection(),
      retrySubmit: () => store.getState().retrySubmit(),
      goBackToSelecting: () => store.getState().goBackToSelecting(),
      retryStream: () => store.getState().retryStream(),
      startNewConsult: () => store.getState().startNewConsult(),
      goToTicket: () => store.getState().goToTicket(),
      getErrorMessage,

      fetchHistoryList: (page: number, pageSize: number): Promise<ConsultationHistoryListItem[]> =>
        consultApi.fetchHistoryList(page, pageSize).then((res) => res.items),
      fetchHistoryDetail: (consultationId: string): Promise<ConsultationHistoryDetail> =>
        consultApi.fetchHistoryDetail(consultationId),
    }),
    [
      sessionState, behaviorTypeSelection, behaviorDescription, messages,
      planSections, accumulatedText, ticketGuide, errorCode,
      isInputValid, isConsultActive, emotionLevel, selectedProfileId,
      referencedCases, crisisLevel,
    ],
  );
}
