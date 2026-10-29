/** 首页的日常咨询入口：只建会话，草稿交给对话页，失败时保留输入。 */
import { useRef, useState } from 'react';

import type { ConsultPort } from '../application/ports';
import { CreateSessionUseCase } from '../application/usecases';
import { failureViewFor, type ConsultFailureView } from '../domain/errors';

export function useConversationEntry(
  consult: ConsultPort,
  /** 建会话成功的回调；`onboardingPending` 来自服务端响应（`onboarding_pending`），决定是否显示跳过入口。 */
  onCreated: (sessionId: string, draft: string, onboardingPending: boolean) => void,
) {
  const [draft, setDraft] = useState('');
  const [creating, setCreating] = useState(false);
  const [failure, setFailure] = useState<ConsultFailureView | null>(null);
  const inFlight = useRef(false);

  const start = async (): Promise<void> => {
    if (inFlight.current || draft.trim() === '') return;
    inFlight.current = true;
    setCreating(true);
    setFailure(null);
    try {
      const response = await new CreateSessionUseCase(consult).execute();
      onCreated(response.session_id, draft.trim(), response.onboarding_pending);
    } catch (caught) {
      setFailure(failureViewFor(caught));
    } finally {
      inFlight.current = false;
      setCreating(false);
    }
  };

  return { draft, setDraft, creating, failure, start };
}
