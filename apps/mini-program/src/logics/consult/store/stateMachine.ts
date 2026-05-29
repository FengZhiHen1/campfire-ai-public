/**
 * CSLT-08 状态转换守卫 —— LEGAL_TRANSITIONS 查找表 + transitionTo() 纯函数。
 *
 * 职责：
 * - LEGAL_TRANSITIONS：记录 14 条合法状态转换路径
 * - transitionTo(current, newState)：校验合法性，非法抛 StateTransitionError
 * - getErrorMessage(code)：错误码 → 中文文案映射（唯一文案来源）
 * - createMessageItem(sender, content, messageType, metadata?)：消息工厂函数
 *
 * 设计依据：CSLT-08 落地规范 §1.8（状态机） §1.9（异常文案）
 * 绝对约束：所有 sessionState 变更必须通过 transitionTo()，禁止直接 set()。
 * 12 条合法路径见 LEGAL_TRANSITIONS 定义。
 */

import {
  type ConsultSessionState,
  type MessageItem,
  type MessageSender,
  type MessageType,
  ConsultErrorCode,
  StateTransitionError,
} from '../types/index';

// ============================================================================
// 合法状态转换表
// ============================================================================

/**
 * 咨询会话状态转换查找表。
 * 14 条合法转换路径，严格按照落地规范 §1.8 定义。
 *
 * 使用 Record<ConsultSessionState, ConsultSessionState[]> 格式：
 * - key = 当前状态
 * - value = 允许转换到的下一状态列表
 * - 同状态转换在 transitionTo() 中静默忽略
 */
export const LEGAL_TRANSITIONS: Record<ConsultSessionState, ConsultSessionState[]> = {
  idle: ['selecting_behavior'],
  selecting_behavior: ['idle', 'submitting', 'streaming'],
  submitting: ['streaming', 'submit_failed'],
  streaming: ['completed', 'stream_failed'],
  completed: ['ticket_guide', 'selecting_behavior'],
  ticket_guide: ['selecting_behavior'],
  submit_failed: ['submitting', 'idle', 'selecting_behavior'],
  stream_failed: ['submitting', 'idle', 'selecting_behavior'],
};

// ============================================================================
// transitionTo —— 状态转换纯函数
// ============================================================================

/**
 * 执行状态转换校验。
 *
 * 规则：
 * 1. 若 newState === currentState → 静默忽略（不抛异常，不记录日志）
 * 2. 若 newState 不在 LEGAL_TRANSITIONS[currentState] 中 → 抛出 StateTransitionError
 * 3. 校验通过 → 返回 newState（供 caller 调用 set()）
 *
 * @param current - 当前状态
 * @param newState - 目标状态
 * @returns 目标状态（校验通过时）
 * @throws {StateTransitionError} 非法转换路径
 */
export function transitionTo(
  current: ConsultSessionState,
  newState: ConsultSessionState,
): ConsultSessionState {
  // 同状态静默忽略
  if (current === newState) {
    return newState;
  }

  // 检查目标状态是否在合法列表中
  const allowedTransitions: ConsultSessionState[] = LEGAL_TRANSITIONS[current];
  if (!allowedTransitions || !allowedTransitions.includes(newState)) {
    throw new StateTransitionError(current, newState);
  }

  return newState;
}

// ============================================================================
// getErrorMessage —— 错误码 → 中文文案映射
// ============================================================================

/**
 * 根据错误码获取对应的中文提示文案。
 *
 * 设计依据：落地规范 §1.7 待裁决项 3（默认文案清单）
 * 所有中文文案集中在此映射表中管理，禁止在 Store/Hook/组件中硬编码。
 *
 * @param code - 前端异常错误码
 * @returns 中文提示文案
 */
export function getErrorMessage(code: ConsultErrorCode): string {
  const messageMap: Record<ConsultErrorCode, string> = {
    [ConsultErrorCode.INPUT_VALIDATION_FAILED]:
      '请至少选择一种行为类型，并填写行为描述',
    [ConsultErrorCode.SUBMIT_NETWORK_ERROR]:
      '网络连接失败，请检查网络后重试',
    [ConsultErrorCode.SUBMIT_SERVER_ERROR]:
      '服务暂时不可用，请稍后重试',
    [ConsultErrorCode.SSE_CONNECTION_BROKEN]:
      '生成中断，以下为不完整建议，可能缺失部分段落',
    [ConsultErrorCode.SSE_NO_DATA_TIMEOUT]:
      '正在生成建议，请稍候',
    [ConsultErrorCode.CONCURRENT_SUBMIT_BLOCKED]:
      '当前正在生成建议，请等待完成后再发起新的咨询',
    [ConsultErrorCode.TICKET_CREATION_FAILED]:
      '如需专家帮助，可手动发起工单',
  };
  return messageMap[code] ?? '未知错误，请稍后重试';
}

// ============================================================================
// createMessageItem —— 消息工厂函数
// ============================================================================

/**
 * 创建 MessageItem 实例。
 * id 生成策略：msg-${crypto.randomUUID}（优先）→ msg-{random+timestamp}（降级）。
 *
 * @param sender - 发送方（user | system）
 * @param content - 消息文本内容
 * @param messageType - 消息类型
 * @param metadata - 可选元数据
 * @returns 新的 MessageItem
 */
export function createMessageItem(
  sender: MessageSender,
  content: string,
  messageType: MessageType,
  metadata?: MessageItem['metadata'],
): MessageItem {
  // 生成唯一消息 ID
  const id: string = `msg-${
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : Math.random().toString(36).substring(2) + Date.now().toString(36)
  }`;

  return {
    id,
    sender,
    content,
    timestamp: new Date().toISOString(),
    messageType,
    ...(metadata ? { metadata } : {}),
  };
}
