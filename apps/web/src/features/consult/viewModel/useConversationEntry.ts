/** 首页的日常咨询入口：只建会话，草稿交给对话页，失败时保留输入。 */
import { useRef, useState } from 'react';

import type { ConsultPort } from '../application/ports';
import { CreateSessionUseCase } from '../application/usecases';
import { failureViewFor, type ConsultFailureView } from '../domain/errors';

export function useConversationEntry(consult: ConsultPort, onCreated: (sessionId: string, draft: string) => void) {
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
      onCreated(response.session_id, draft.trim());
    } catch (caught) {
      setFailure(failureViewFor(caught));
    } finally {
      inFlight.current = false;
      setCreating(false);
    }
  };

  return { draft, setDraft, creating, failure, start };
}
