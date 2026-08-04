/**
 * 应急咨询会话 Hook——编排入口（桶选择/阶段回答/追问/兜底/SSE 事件驱动）。
 *
 * 事件 → 消息映射（统一聊天容器）：
 * - safety_card / stage_question / redline_guide / fallback_notice → 分级消息
 * - chunk → 聚合到 streamingText，done 时固化
 * - result → 四段式方案消息（契约校验后）
 */

import { useCallback, useEffect, useRef } from 'react';
import { consultApi } from '../services/consultApi';
import { streamConsultEvents } from '../services/sseClient';
import { nextMessageId, useConsultStore } from '../store/useConsultStore';
import type {
  EmergencyPlanPayload,
  FallbackNoticePayload,
  RedlineGuidePayload,
  SafetyCardPayload,
  StageQuestionPayload,
} from '../types';

export function useConsultSession() {
  const store = useConsultStore();
  const cancelStreamRef = useRef<(() => void) | null>(null);

  const stopStream = useCallback(() => {
    cancelStreamRef.current?.();
    cancelStreamRef.current = null;
  }, []);

  /** 订阅事件流（Last-Event-Id 续传） */
  const attachStream = useCallback(
    (sessionId: string) => {
      stopStream();
      cancelStreamRef.current = streamConsultEvents(sessionId, {
        onFrame: (frame) => {
          const s = useConsultStore.getState();
          s.setLastEventId(frame.id);
          switch (frame.type) {
            case 'safety_card': {
              const card = (frame.data as { card: SafetyCardPayload }).card;
              if (card.variant === 'redline') s.setPhase('redline');
              s.appendMessage({ kind: 'safety_card', id: nextMessageId(), card });
              break;
            }
            case 'stage_question': {
              const question = (frame.data as { question: StageQuestionPayload }).question;
              s.appendMessage({ kind: 'stage_question', id: nextMessageId(), question });
              break;
            }
            case 'redline_guide': {
              const guide = (frame.data as { guide: RedlineGuidePayload }).guide;
              s.appendMessage({ kind: 'redline_guide', id: nextMessageId(), guide });
              s.setPhase('redline');
              break;
            }
            case 'chunk': {
              const text = String((frame.data as { text?: string }).text ?? '');
              if (text) s.appendChunk(text);
              break;
            }
            case 'result': {
              const payload = (frame.data as { payload?: EmergencyPlanPayload }).payload;
              if (payload) {
                s.flushChunk();
                s.appendMessage({ kind: 'plan_result', id: nextMessageId(), plan: payload });
              }
              break;
            }
            case 'fallback_notice': {
              const notice = (frame.data as { notice: FallbackNoticePayload }).notice;
              s.appendMessage({ kind: 'fallback_notice', id: nextMessageId(), notice });
              break;
            }
            case 'done': {
              s.flushChunk();
              if (useConsultStore.getState().phase !== 'redline') {
                s.setPhase('followup');
              }
              break;
            }
            case 'error': {
              s.flushChunk();
              break;
            }
            default:
              break;
          }
        },
      });
    },
    [stopStream],
  );

  /** 桶选择创建会话 */
  const startWithBucket = useCallback(
    async (bucket: string, profileId?: string) => {
      store.reset();
      const sessionId = await consultApi.createSession(bucket, profileId);
      store.startSession(sessionId);
      attachStream(sessionId);
      return sessionId;
    },
    [store, attachStream],
  );

  /** 阶段回答（quick-reply） */
  const answerQuestion = useCallback(
    async (answer: string) => {
      const sessionId = useConsultStore.getState().sessionId;
      if (!sessionId) return;
      useConsultStore.getState().appendMessage({ kind: 'user_answer', id: nextMessageId(), text: answer });
      await consultApi.answerStage(sessionId, answer);
    },
    [],
  );

  /** 追问 */
  const followup = useCallback(async (text: string) => {
    const sessionId = useConsultStore.getState().sessionId;
    if (!sessionId) return;
    useConsultStore.getState().appendMessage({ kind: 'user_answer', id: nextMessageId(), text });
    await consultApi.followup(sessionId, text);
  }, []);

  /** 未解决标记 */
  const markUnresolved = useCallback(async () => {
    const sessionId = useConsultStore.getState().sessionId;
    if (!sessionId) return;
    await consultApi.markUnresolved(sessionId);
  }, []);

  useEffect(() => stopStream, [stopStream]);

  return {
    sessionId: store.sessionId,
    phase: store.phase,
    messages: store.messages,
    streamingText: store.streamingText,
    startWithBucket,
    answerQuestion,
    followup,
    markUnresolved,
    attachStream,
    reset: store.reset,
  };
}
