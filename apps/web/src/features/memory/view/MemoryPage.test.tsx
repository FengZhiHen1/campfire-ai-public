/**
 * 模块: features/memory/view/MemoryPage.test
 * 职责: 记忆页组件用例——归属呈现、空与失败可区分、删除二次确认、纠正两步中间态
 * 数据来源:
 *   - docs/design/pages/记忆页.md: MUST — 放置与进入方式、状态覆盖表、文案口径
 *   - docs/技术设计/面/profile/记忆面HTTP契约.md: MUST — 第 6 节（空与失败必须可区分）
 * 边界:
 *   - 依赖: features/memory/view/MemoryPage 与一个端口替身、react-router 内存路由
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言页面上出现会话标识（它不该被渲染）
 *   - 禁止把 503 断言成空态
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

import type { MemoryEpisode } from '../../../shared/types/memory';
import type { MemoryPort } from '../application/ports';
import { MemoryPage } from './MemoryPage';

/** 造一条记忆。 */
function episode(overrides: Partial<MemoryEpisode> = {}): MemoryEpisode {
  return {
    episode_key: 'e1',
    occurred_at: '2026-10-02T09:30:00+08:00',
    content: '今天在超市里人很多，我有点撑不住',
    source_session_id: 'session-abc',
    ...overrides,
  };
}

/** 记忆端口替身。 */
function port(overrides: Partial<MemoryPort> = {}): MemoryPort {
  return {
    listEpisodes: vi.fn(async () => ({ items: [episode()], next_cursor: null })),
    deleteEpisode: vi.fn(async (episodeKey: string) => ({
      episode_key: episodeKey,
      newly_deleted: true,
      reason: 'user_request' as const,
    })),
    correctEpisode: vi.fn(async (episodeKey: string) => ({
      superseded: true,
      new_episode_written: true,
      episode_key: 'new1',
      supersedes: episodeKey,
    })),
    ...overrides,
  };
}

/** 渲染记忆页。 */
function renderPage(memoryPort: MemoryPort) {
  return render(
    <MemoryRouter initialEntries={['/settings/memory']}>
      <MemoryPage port={memoryPort} />
    </MemoryRouter>,
  );
}

/** 取第一个同名按钮；找不到即显式失败（不用类型逃逸换掉失败）。 */
function firstButtonNamed(name: string): HTMLElement {
  const [first] = screen.getAllByRole('button', { name });
  if (first === undefined) throw new Error(`没有找到按钮：${name}`);
  return first;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('记忆页 · 放置与归属', () => {
  it('P0 是次级页：有返回与标题，不渲染 tab 栏，也不出现对象切换器', async () => {
    renderPage(port());
    await screen.findByText('今天在超市里人很多，我有点撑不住');

    expect(screen.getByRole('link', { name: '← 返回' })).toBeDefined();
    expect(screen.getByText('我提过的事')).toBeDefined();
    // 切换器的缺席本身在传达「记忆属账号、不随对象分区」。
    expect(screen.queryByRole('navigation', { name: '一级导航' })).toBeNull();
    expect(screen.queryByRole('group', { name: '支持对象' })).toBeNull();
  });

  it('P0 归属说明行常驻，且不依赖是否加载完成', async () => {
    let finishLoading!: () => void;
    const listEpisodes = vi.fn(async () => {
      await new Promise<void>((resolve) => {
        finishLoading = resolve;
      });
      return { items: [episode()], next_cursor: null };
    });
    renderPage(port({ listEpisodes }));

    expect(
      screen.getByText('这些是你自己在咨询中说过或经历过的事，关于你本人；与支持对象的档案分开保存，不随切换对象变化。'),
    ).toBeDefined();

    finishLoading();
    await screen.findByText('今天在超市里人很多，我有点撑不住');
    expect(
      screen.getByText('这些是你自己在咨询中说过或经历过的事，关于你本人；与支持对象的档案分开保存，不随切换对象变化。'),
    ).toBeDefined();
  });

  it('P0 行内不出现会话标识，只写「来自一次咨询」', async () => {
    renderPage(port());
    await screen.findByText('今天在超市里人很多，我有点撑不住');

    expect(screen.getByText(/来自一次咨询/)).toBeDefined();
    expect(screen.queryByText(/session-abc/)).toBeNull();
  });

  it('P1 按发生时间倒序、按日期分组', async () => {
    renderPage(
      port({
        listEpisodes: vi.fn(async () => ({
          items: [
            episode({ episode_key: 'old', occurred_at: '2026-10-01T09:00:00+08:00', content: '前一天的事' }),
            episode({ episode_key: 'new', occurred_at: '2026-10-02T09:00:00+08:00', content: '当天的事' }),
          ],
          next_cursor: null,
        })),
      }),
    );
    await screen.findByText('当天的事');

    const headings = screen.getAllByText(/月\d+日（\d+）/).map((node) => node.textContent);
    expect(headings[0]).toBe('10月2日（1）');
    expect(headings[1]).toBe('10月1日（1）');
  });
});

describe('记忆页 · 空与失败必须可区分', () => {
  it('P0 查询为空 → 空态，不是错误', async () => {
    renderPage(port({ listEpisodes: vi.fn(async () => ({ items: [], next_cursor: null })) }));

    expect(await screen.findByText('还没有记录')).toBeDefined();
    expect(screen.getByText('你在咨询中说过的事，会记在这里')).toBeDefined();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('P0 图库不可用（503）→ 错误卡写「暂时无法读取记录」，绝不当成没有记忆', async () => {
    renderPage(
      port({
        listEpisodes: vi.fn(async () => {
          throw { status: 503 };
        }),
      }),
    );

    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText('暂时无法读取记录')).toBeDefined();
    expect(screen.queryByText('还没有记录')).toBeNull();
    expect(screen.getByRole('button', { name: '重试' })).toBeDefined();
  });

  it('P1 重试成功后展示时间线', async () => {
    let attempt = 0;
    renderPage(
      port({
        listEpisodes: vi.fn(async () => {
          attempt += 1;
          if (attempt === 1) throw { status: 503 };
          return { items: [episode()], next_cursor: null };
        }),
      }),
    );
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: '重试' }));

    expect(await screen.findByText('今天在超市里人很多，我有点撑不住')).toBeDefined();
  });
});

describe('记忆页 · 删除', () => {
  it('P0 删除须二次确认，文案与档案页同源但语义不同', async () => {
    renderPage(port());
    await screen.findByText('今天在超市里人很多，我有点撑不住');

    fireEvent.click(firstButtonNamed('删除'));
    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getByText('删除这条记录？')).toBeDefined();
    expect(within(sheet).getByText('删除后咨询和历史都不会再用到它')).toBeDefined();
  });

  it('P0 取消不调删除端点；确认才调，并立即从列表移除', async () => {
    const p = port();
    renderPage(p);
    await screen.findByText('今天在超市里人很多，我有点撑不住');

    fireEvent.click(firstButtonNamed('删除'));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '取消' }));
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull();
    });
    expect(p.deleteEpisode).not.toHaveBeenCalled();

    fireEvent.click(firstButtonNamed('删除'));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '删除' }));

    await waitFor(() => {
      expect(p.deleteEpisode).toHaveBeenCalledWith('e1');
    });
    await waitFor(() => {
      expect(screen.queryByText('今天在超市里人很多，我有点撑不住')).toBeNull();
    });
  });
});

describe('记忆页 · 纠正', () => {
  it('P0 表单预填原文与发生时间；提交成功给出「不再作为依据」的提示', async () => {
    const p = port();
    renderPage(p);
    await screen.findByText('今天在超市里人很多，我有点撑不住');

    fireEvent.click(firstButtonNamed('纠正'));
    const form = (await screen.findByText('新增一条更正')).closest('section') as HTMLElement;
    expect((within(form).getByLabelText('内容') as HTMLTextAreaElement).value).toBe(
      '今天在超市里人很多，我有点撑不住',
    );
    expect((within(form).getByLabelText('发生时间') as HTMLInputElement).value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);

    fireEvent.change(within(form).getByLabelText('内容'), { target: { value: '那天在超市里人很多' } });
    fireEvent.click(within(form).getByRole('button', { name: '更正' }));

    await waitFor(() => {
      expect(p.correctEpisode).toHaveBeenCalledWith(
        'e1',
        expect.objectContaining({ content: '那天在超市里人很多' }),
      );
    });
    expect(await screen.findByText(/已新增一条更正，原记录不再作为依据/)).toBeDefined();
  });

  it('P0 中间态（旧已撤下、新没写成）逐字呈现前端文案，不笼统报成功或失败', async () => {
    const p = port({
      correctEpisode: vi.fn(async (episodeKey: string) => ({
        superseded: true,
        new_episode_written: false,
        episode_key: null,
        supersedes: episodeKey,
      })),
    });
    renderPage(p);
    await screen.findByText('今天在超市里人很多，我有点撑不住');

    fireEvent.click(firstButtonNamed('纠正'));
    const form = (await screen.findByText('新增一条更正')).closest('section') as HTMLElement;
    fireEvent.change(within(form).getByLabelText('内容'), { target: { value: '改了一版' } });
    fireEvent.click(within(form).getByRole('button', { name: '更正' }));

    expect(await screen.findByText(/原记录已不再作为依据，但新记录没写成，请重试/)).toBeDefined();
    // 旧记录已撤下 → 立即从列表移除（不再作为依据）。
    await waitFor(() => {
      expect(screen.queryByText('今天在超市里人很多，我有点撑不住')).toBeNull();
    });
  });

  it('P0 提交失败保留已填内容，不清空重来', async () => {
    const p = port({
      correctEpisode: vi.fn(async () => {
        throw { status: 503 };
      }),
    });
    renderPage(p);
    await screen.findByText('今天在超市里人很多，我有点撑不住');

    fireEvent.click(firstButtonNamed('纠正'));
    const form = (await screen.findByText('新增一条更正')).closest('section') as HTMLElement;
    fireEvent.change(within(form).getByLabelText('内容'), { target: { value: '改了一半' } });
    fireEvent.click(within(form).getByRole('button', { name: '更正' }));

    expect(await within(form).findByText('暂时无法读取记录')).toBeDefined();
    expect((within(form).getByLabelText('内容') as HTMLTextAreaElement).value).toBe('改了一半');
  });

  it('P1 内容与原内容相同 → 拦在提交前，不发请求', async () => {
    const p = port();
    renderPage(p);
    await screen.findByText('今天在超市里人很多，我有点撑不住');

    fireEvent.click(firstButtonNamed('纠正'));
    const form = (await screen.findByText('新增一条更正')).closest('section') as HTMLElement;
    fireEvent.click(within(form).getByRole('button', { name: '更正' }));

    expect(await within(form).findByText('内容和原来一样，没有需要更正的地方')).toBeDefined();
    expect(p.correctEpisode).not.toHaveBeenCalled();
  });
});

describe('记忆页 · 触底分页', () => {
  it('P0 触底加载下一页失败 → 列表尾部给出可见的失败与重试，不静默吞掉', async () => {
    // 判别性：把分页失败只写进行内状态（没有对应行）或只设 failure 而不改渲染条件时，
    // alert 永不出现，本用例在 `findByRole('alert')` 处超时失败。
    let attempt = 0;
    const p = port({
      listEpisodes: vi.fn(async (options?: { cursor?: string }) => {
        if (options?.cursor === undefined) {
          return { items: [episode({ episode_key: 'e1', content: '第一页的事' })], next_cursor: '20' };
        }
        attempt += 1;
        if (attempt === 1) throw { status: 503 };
        return { items: [episode({ episode_key: 'e2', content: '第二页的事' })], next_cursor: null };
      }),
    });
    renderPage(p);
    await screen.findByText('第一页的事');

    fireEvent.click(screen.getByRole('button', { name: '加载更多' }));

    // 失败必须可见（本项目明令禁止静默兜底）：行内错误卡 + 重试。
    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText('暂时无法读取记录')).toBeDefined();
    // 已加载的内容仍在：分页失败不改整页。
    expect(screen.getByText('第一页的事')).toBeDefined();

    // 重试走同一个游标，成功后追加。
    fireEvent.click(within(alert).getByRole('button', { name: '重试' }));
    expect(await screen.findByText('第二页的事')).toBeDefined();
    expect(screen.getByText('第一页的事')).toBeDefined();
    expect(p.listEpisodes).toHaveBeenLastCalledWith({ cursor: '20' });
  });

  it('P1 还有下一页时给出加载入口，加载后追加而不是替换', async () => {
    const p = port({
      listEpisodes: vi.fn(async (options?: { cursor?: string }) =>
        options?.cursor === undefined
          ? { items: [episode({ episode_key: 'e1', content: '第一页的事' })], next_cursor: '20' }
          : { items: [episode({ episode_key: 'e2', content: '第二页的事' })], next_cursor: null },
      ),
    });
    renderPage(p);
    await screen.findByText('第一页的事');

    // jsdom 没有 IntersectionObserver，页面按降级路径给显式按钮（能力不静默丢失）。
    fireEvent.click(screen.getByRole('button', { name: '加载更多' }));

    expect(await screen.findByText('第二页的事')).toBeDefined();
    expect(screen.getByText('第一页的事')).toBeDefined();
    expect(p.listEpisodes).toHaveBeenLastCalledWith({ cursor: '20' });
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '加载更多' })).toBeNull();
    });
  });
});
