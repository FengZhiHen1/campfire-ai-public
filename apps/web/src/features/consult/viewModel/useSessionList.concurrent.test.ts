import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { deferred } from '../../../test/deferred';
import { createConsultPortStub } from '../test/consultPortStub';
import { useSessionList } from './useSessionList';

describe('新咨询入口的并发防重', () => {
  it('同一事件批次重复调用仍只创建一个会话', async () => {
    const port = createConsultPortStub();
    const gate = deferred<{ session_id: string; support_object_id: null; onboarding_pending: boolean }>();
    vi.mocked(port.createSession).mockReturnValue(gate.promise);
    const created = vi.fn();
    const { result } = renderHook(() => useSessionList(port, created));
    act(() => {
      void result.current.startNewConversation();
      void result.current.startNewConversation();
    });
    expect(port.createSession).toHaveBeenCalledTimes(1);
    await act(async () => { gate.resolve({ session_id: 'new-session', support_object_id: null, onboarding_pending: false }); });
    expect(created).toHaveBeenCalledOnce();
  });
});
