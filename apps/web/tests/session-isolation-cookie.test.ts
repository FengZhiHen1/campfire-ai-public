import { describe, expect, it, vi } from 'vitest';

vi.mock('../e2e-real/support/real', () => ({ BASE_URL: '', waitMounted: vi.fn() }));
import { readSessionCookieFacts } from '../e2e-real/support/sessionIsolation';

describe('readSessionCookieFacts', () => {
  it('只把 access/refresh 归为凭据，并保留 JS 可见的 front token 分类', async () => {
    const context = {
      cookies: async () => [
        { name: 'sAccessToken', httpOnly: true, path: '/', value: '' },
        { name: 'sRefreshToken', httpOnly: true, path: '/', value: '' },
        { name: 'sFrontToken', httpOnly: false, path: '/', value: '' },
        { name: 'sOtherToken', httpOnly: false, path: '/', value: '' },
      ],
    };
    const page = {
      evaluate: async () => ['sFrontToken', 'sOtherToken'],
    };

    const facts = await readSessionCookieFacts(
      context as never,
      page as never,
    );

    expect(facts.tokenCookies).toEqual([
      { name: 'sAccessToken', httpOnly: true, path: '/' },
      { name: 'sRefreshToken', httpOnly: true, path: '/' },
    ]);
    expect(facts.jsVisibleCookieNames).toContain('sFrontToken');
    expect(facts.tokenCookies.map((cookie) => cookie.name)).not.toContain('sFrontToken');
  });
});
