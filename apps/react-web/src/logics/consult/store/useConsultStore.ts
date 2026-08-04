/**
 * 应急咨询会话 store（Zustand）——消息列表与会话阶段。
 */

import { create } from 'zustand';
import type { ConsultMessage, ConsultPhase } from '../types';

interface ConsultStoreState {
  sessionId: string | null;
  phase: ConsultPhase;
  messages: ConsultMessage[];
  streamingText: string; // 生成中的增量文本（plan_chunk 聚合）
  lastEventId: number;
}

interface ConsultStoreActions {
  startSession: (sessionId: string) => void;
  setPhase: (phase: ConsultPhase) => void;
  appendMessage: (message: ConsultMessage) => void;
  appendChunk: (text: string) => void;
  flushChunk: () => void;
  setLastEventId: (id: number) => void;
  reset: () => void;
}

export type ConsultStore = ConsultStoreState & ConsultStoreActions;

let messageSeq = 0;
function nextMessageId(): string {
  messageSeq += 1;
  return `msg-${messageSeq}`;
}

export const useConsultStore = create<ConsultStore>()((set, get) => ({
  sessionId: null,
  phase: 'bucket_select',
  messages: [],
  streamingText: '',
  lastEventId: 0,

  startSession: (sessionId) => {
    set({ sessionId, messages: [], streamingText: '', phase: 'stage_qa', lastEventId: 0 });
  },

  setPhase: (phase) => set({ phase }),

  appendMessage: (message) => {
    set((s) => ({ messages: [...s.messages, message] }));
  },

  appendChunk: (text) => {
    set((s) => ({ streamingText: s.streamingText + text }));
  },

  flushChunk: () => {
    const text = get().streamingText;
    if (text) {
      set((s) => ({
        streamingText: '',
        messages: [...s.messages, { kind: 'plan_chunk', id: nextMessageId(), text }],
      }));
    }
  },

  setLastEventId: (id) => set({ lastEventId: id }),

  reset: () => {
    set({ sessionId: null, phase: 'bucket_select', messages: [], streamingText: '', lastEventId: 0 });
  },
}));

export { nextMessageId };
