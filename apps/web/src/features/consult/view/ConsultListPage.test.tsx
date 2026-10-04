/**
 * 模块: features/consult/view/ConsultListPage.test
 * 职责: 会话列表页的组件用例——三态逐格、字段渲染、新对话入口与触底分页
 * 数据来源:
 *   - docs/design/pages/会话列表页.md: MUST — 状态覆盖表（loading/empty/error/edge）
 * 边界:
 *   - 依赖: view/ConsultListPage、test/{fixtures,consultPortStub}
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止把取数失败断言成空列表（错误与空是两种状态）
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ConsultListPage } from './ConsultListPage';
import { ConsultError } from '../domain/errors';
import { createConsultPortStub, type ConsultPortStub } from '../test/consultPortStub';
import { sessionSummary } from '../test/fixtures';

/** jsdom 没有 IntersectionObserver：用一个「观察即触发」的替身驱动触底加载。 */
class ImmediateIntersectionObserver {
  readonly root = null;
  readonly rootMargin = '';
  readonly thresholds: readonly number[] = [];

  constructor(private readonly callback: (entries: { isIntersecting: boolean }[]) => void) {}

  observe(): void {
    this.callback([{ isIntersecting: true }]);
  }

  unobserve(): void {
    // 替身：无需处理。
  }

  disconnect(): void {
    // 替身：无需处理。
  }

  takeRecords(): { isIntersecting: boolean }[] {
    return [];
  }
}

/** 渲染会话列表页（点击会话行跳对话页占位）。 */
function renderList(port: ConsultPortStub) {
  return render(
    <MemoryRouter initialEntries={['/consult']}>
      <Routes>
        <Route path="/consult" element={<ConsultListPage consult={port} />} />
        <Route path="/consult/sessions/:sessionId" element={<p>对话页已到达</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  // 触底观察者只在需要分页的用例里用；这里统一装上替身，未使用时不会被 observe。
  (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver =
    ImmediateIntersectionObserver as unknown as typeof IntersectionObserver;
});

afterEach(() => {
  delete (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver;
});

describe('会话列表页 — 三态', () => {
  it('loading：同形骨架且新对话入口已可用', async () => {
    const port = createConsultPortStub();
    vi.mocked(port.listSessions).mockReturnValue(new Promise(() => undefined));
    renderList(port);

    expect(screen.getByText('开始新的日常咨询')).toBeDefined();
    expect(document.querySelectorAll('.skeleton.row')).toHaveLength(4);
  });

  it('empty：空态说明而不是一片白', async () => {
    renderList(createConsultPortStub());
    expect(await screen.findByText('还没有咨询记录')).toBeDefined();
    expect(screen.getByText('从上面开始第一次咨询')).toBeDefined();
  });

  it('error：错误卡 + 重试；重试成功后渲染列表（不把失败显示成空列表）', async () => {
    const port = createConsultPortStub();
    vi.mocked(port.listSessions).mockRejectedValueOnce(new ConsultError('unavailable', '服务暂时不可用'));
    renderList(port);

    expect(await screen.findByText('服务暂时不可用')).toBeDefined();
    expect(screen.queryByText('还没有咨询记录')).toBeNull();

    vi.mocked(port.listSessions).mockResolvedValue({ items: [sessionSummary()], next_cursor: null });
    fireEvent.click(screen.getByRole('button', { name: '重试' }));

    expect(await screen.findByText('等候时的沟通')).toBeDefined();
  });
});

describe('会话列表页 — 列表与入口', () => {
  it('四个契约字段按三行结构渲染', async () => {
    const port = createConsultPortStub({
      sessions: { items: [sessionSummary()], next_cursor: null },
    });
    renderList(port);

    expect(await screen.findByText('等候时的沟通')).toBeDefined();
    const row = document.querySelector('.list-row');
    expect(row?.querySelector('.lr-title')?.textContent).toBe('等候时的沟通');
    expect(row?.querySelector('.lr-sub')?.textContent).toContain('虚构对象');
    expect(row?.querySelector('.lr-meta')?.textContent).toBe('可以试试减少人数');
  });

  it('对象名缺失时该段不渲染（不留占位符）', async () => {
    const port = createConsultPortStub({
      sessions: { items: [sessionSummary({ support_object_name: null, last_message_preview: null })], next_cursor: null },
    });
    renderList(port);

    await screen.findByText('等候时的沟通');
    const row = document.querySelector('.list-row');
    expect(row?.querySelector('.lr-sub')?.textContent).not.toContain('null');
    expect(row?.querySelector('.lr-meta')).toBeNull();
  });

  it('点击会话行进对话页', async () => {
    const port = createConsultPortStub({ sessions: { items: [sessionSummary()], next_cursor: null } });
    renderList(port);

    fireEvent.click(await screen.findByText('等候时的沟通'));
    expect(await screen.findByText('对话页已到达')).toBeDefined();
  });

  it('新对话入口建会话后跳转；建会话失败时给错误且入口保持可用', async () => {
    const port = createConsultPortStub({
      sessions: { items: [], next_cursor: null },
      createSession: { session_id: 's-new', support_object_id: null, onboarding_pending: false },
    });
    renderList(port);

    await act(async () => {
      fireEvent.click(screen.getByText('开始新的日常咨询'));
    });
    expect(await screen.findByText('对话页已到达')).toBeDefined();
    expect(port.createSession).toHaveBeenCalledTimes(1);
  });

  it('建会话失败：错误卡呈现，入口仍可再次点击', async () => {
    const port = createConsultPortStub({
      sessions: { items: [], next_cursor: null },
      createSession: new ConsultError('busy', '会话上已有正在进行的运行'),
    });
    renderList(port);

    await act(async () => {
      fireEvent.click(screen.getByText('开始新的日常咨询'));
    });

    expect(await screen.findByText('这个会话正在处理上一条消息')).toBeDefined();
    expect(screen.getByText('开始新的日常咨询')).toBeDefined();
  });

  it('触底自动加载下一页并把新行追加在末尾', async () => {
    const port = createConsultPortStub({
      sessions: { items: [sessionSummary({ session_id: 's1', title: '第一条' })], next_cursor: 'cursor-2' },
    });
    vi.mocked(port.listSessions).mockImplementation(async (input) =>
      input.cursor === 'cursor-2'
        ? { items: [sessionSummary({ session_id: 's2', title: '第二条' })], next_cursor: null }
        : { items: [sessionSummary({ session_id: 's1', title: '第一条' })], next_cursor: 'cursor-2' },
    );
    renderList(port);

    expect(await screen.findByText('第一条')).toBeDefined();
    expect(await screen.findByText('第二条')).toBeDefined();
    await waitFor(() => expect(vi.mocked(port.listSessions).mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(vi.mocked(port.listSessions).mock.calls[1]?.[0]).toEqual({ cursor: 'cursor-2', limit: 20 });
  });
});
