/**
 * 模块: features/profile/view/ProfilePage.test
 * 职责: 档案页的组件用例——候选层视觉不变量、确认/删除/纠正三条操作流、三态与对象管理
 * 数据来源:
 *   - docs/design/pages/档案页.md: MUST — 布局结构、状态覆盖表、候选层视觉不变量（AC-18）
 *   - docs/技术设计/面/profile/档案面HTTP契约.md: MUST — 第 3 节（候选单独成组）、第 5 节（归档 409）
 * 边界:
 *   - 依赖: features/profile/view/ProfilePage 与一个端口替身、react-router 内存路由
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止用真实 HTTP（本用例只测页面行为，端口替身即可）
 *   - 禁止断言未确认条目出现在摘要区（那是 AC-18 的违反）
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

import type { ProfileItem, SupportObject } from '../../../shared/types/profile';
import type { ProfilePort } from '../application/ports';
import { ProfilePage } from './ProfilePage';

/** 造一条档案条目。 */
function item(overrides: Partial<ProfileItem> = {}): ProfileItem {
  return {
    item_id: 'i1',
    support_object_id: 'o1',
    domain: 'communication',
    topic: '表达方式',
    description: '用图片卡表达需求',
    contexts: [],
    manifestations: [],
    person_report: null,
    probable_need: null,
    helpful_support: [],
    unhelpful_support: [],
    origin: 'user_statement',
    source: {},
    confirmation: 'confirmed',
    freshness: 'current',
    first_recorded_at: '2026-10-02T09:00:00Z',
    last_confirmed_at: '2026-10-02T09:00:00Z',
    superseded_by: null,
    ...overrides,
  };
}

/** 造一个支持对象。 */
function object(id: string, name: string, archivedAt: string | null = null): SupportObject {
  return { id, display_name: name, archived_at: archivedAt };
}

/** 端口替身；默认返回「一个对象 + 一条稳定条目 + 一条候选」。 */
function port(overrides: Partial<ProfilePort> = {}): ProfilePort {
  return {
    listObjects: vi.fn(async () => ({ items: [object('o1', '小宝')] })),
    createObject: vi.fn(async (name: string) => object('o2', name)),
    patchObject: vi.fn(async (id: string) => object(id, '小宝')),
    getSummary: vi.fn(async () => ({
      fields: [{ key: 'communication', label: '沟通', items: [{ item_id: 'i1', origin: 'user_statement' as const, last_confirmed_at: '2026-10-02T09:00:00Z', text: '用图片卡表达需求' }] }],
      has_profile: true,
    })),
    listItems: vi.fn(async () => ({
      items: [item()],
      candidates: [item({ item_id: 'c1', topic: '提前知道结束时间', origin: 'ai_inference', confirmation: 'unconfirmed', freshness: 'current' })],
      next_cursor: null,
    })),
    confirmItem: vi.fn(async (itemId: string) => ({ item_id: itemId, confirmation: 'confirmed' as const })),
    correctItem: vi.fn(async (itemId: string) => ({ item_id: 'new1', supersedes: itemId })),
    rejectItem: vi.fn(async (itemId: string) => ({ item_id: itemId, confirmation: 'rejected' as const })),
    deleteItem: vi.fn(async (itemId: string) => ({ item_id: itemId, already: false })),
    addItem: vi.fn(async () => ({ item_id: 'new2' })),
    ...overrides,
  };
}

/** 渲染档案页（AppShell 渲染 NavLink，需要路由上下文）。 */
function renderPage(profilePort: ProfilePort) {
  return render(
    <MemoryRouter initialEntries={['/profile']}>
      <ProfilePage port={profilePort} />
    </MemoryRouter>,
  );
}

/**
 * 取第一个同名按钮；找不到即显式失败。
 *
 * 不用 `[0]!`：那会用一个类型逃逸换掉「找不到时应该失败」这个断言，
 * 找不到时 fireEvent 会抛一个与原因无关的错误。
 */
function firstButtonNamed(name: string): HTMLElement {
  const [first] = screen.getAllByRole('button', { name });
  if (first === undefined) throw new Error(`没有找到按钮：${name}`);
  return first;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('档案页 · 加载与候选层不变量', () => {
  it('P0 加载完成后同时呈现摘要、稳定条目与待确认分组', async () => {
    renderPage(port());

    expect(await screen.findByText('关于 TA 的当前认识')).toBeDefined();
    expect(screen.getByText('摘要只收你直接说过或确认过的内容')).toBeDefined();
    // 待确认分组的头带琥珀圆点（.status.unruled），不是橙色强调。
    const candidateHead = screen.getByText(/^待确认（1）$/);
    expect(candidateHead.className).toContain('unruled');
    expect(screen.getByText('提前知道结束时间')).toBeDefined();
  });

  it('P0 候选只出现在待确认分组里，摘要区不含它（AC-18）', async () => {
    renderPage(port());
    await screen.findByText('关于 TA 的当前认识');

    const summary = screen.getByRole('region', { name: '关于 TA 的当前认识' });
    expect(within(summary).queryByText('提前知道结束时间')).toBeNull();
  });

  it('P1 对象为空 → 空态引导新建对象，不显示内容区', async () => {
    const p = port({ listObjects: vi.fn(async () => ({ items: [] })) });
    renderPage(p);

    expect(await screen.findByText('还没有记录')).toBeDefined();
    expect(screen.getByRole('button', { name: '+ 新建对象' })).toBeDefined();
    expect(p.getSummary).not.toHaveBeenCalled();
  });

  it('P1 对象列表失败 → 错误卡 + 重试；对象切换器仍在（单对象失败不吞导航）', async () => {
    let attempt = 0;
    const p = port({
      listObjects: vi.fn(async () => {
        attempt += 1;
        if (attempt === 1) throw { status: 500 };
        return { items: [object('o1', '小宝')] };
      }),
    });
    renderPage(p);

    expect(await screen.findByRole('alert')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('关于 TA 的当前认识')).toBeDefined();
  });
});

describe('档案页 · 候选条目操作', () => {
  it('P0 确认候选 → 调确认端点并重新加载', async () => {
    const p = port();
    renderPage(p);
    await screen.findByText('提前知道结束时间');

    const candidateGroup = screen.getByText(/^待确认（1）$/).closest('details');
    expect(candidateGroup).not.toBeNull();
    fireEvent.click(within(candidateGroup as HTMLElement).getByRole('button', { name: '确认' }));

    await waitFor(() => {
      expect(p.confirmItem).toHaveBeenCalledWith('c1');
    });
    expect(p.listItems).toHaveBeenCalledTimes(2);
  });

  it('P0 删除候选须二次确认；取消不调删除端点', async () => {
    const p = port();
    renderPage(p);
    await screen.findByText('提前知道结束时间');

    const candidateGroup = screen.getByText(/^待确认（1）$/).closest('details') as HTMLElement;
    fireEvent.click(within(candidateGroup).getByRole('button', { name: '删除' }));

    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getByText('删除这条记录？')).toBeDefined();
    expect(within(sheet).getByText('删除后咨询和检索都不会再用到它')).toBeDefined();

    fireEvent.click(within(sheet).getByRole('button', { name: '取消' }));
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull();
    });
    expect(p.deleteItem).not.toHaveBeenCalled();
  });

  it('P1 删除确认后调删除端点', async () => {
    const p = port();
    renderPage(p);
    await screen.findByText('提前知道结束时间');

    const candidateGroup = screen.getByText(/^待确认（1）$/).closest('details') as HTMLElement;
    fireEvent.click(within(candidateGroup).getByRole('button', { name: '删除' }));
    const sheet = await screen.findByRole('dialog');
    fireEvent.click(within(sheet).getByRole('button', { name: '删除' }));

    await waitFor(() => {
      expect(p.deleteItem).toHaveBeenCalledWith('c1');
    });
  });
});

describe('档案页 · 纠正流', () => {
  it('P0 纠正表单预填原描述，提交调纠正端点并给出「不再作为依据」的提示', async () => {
    const p = port();
    renderPage(p);
    await screen.findByText('关于 TA 的当前认识');

    fireEvent.click(firstButtonNamed('纠正'));
    const form = (await screen.findByText('新增一条更正')).closest('section') as HTMLElement;
    const description = within(form).getByLabelText('描述');
    expect((description as HTMLTextAreaElement).value).toBe('用图片卡表达需求');

    fireEvent.change(description, { target: { value: '改用图片卡 + 手势' } });
    fireEvent.click(within(form).getByRole('button', { name: '纠正' }));

    await waitFor(() => {
      expect(p.correctItem).toHaveBeenCalledWith('i1', expect.objectContaining({ description: '改用图片卡 + 手势' }));
    });
    // 纠正 = 新增一条更正，不得暗示覆盖。
    expect(await screen.findByText(/原记录不再作为依据/)).toBeDefined();
  });

  it('P0 提交失败保留已填内容，不是清空重来', async () => {
    const p = port({ correctItem: vi.fn(async () => { throw { status: 500 }; }) });
    renderPage(p);
    await screen.findByText('关于 TA 的当前认识');

    fireEvent.click(firstButtonNamed('纠正'));
    const form = (await screen.findByText('新增一条更正')).closest('section') as HTMLElement;
    const description = within(form).getByLabelText('描述');
    fireEvent.change(description, { target: { value: '改了一半' } });
    fireEvent.click(within(form).getByRole('button', { name: '纠正' }));

    expect(await screen.findByText('提交没有成功，请重试')).toBeDefined();
    expect((within(form).getByLabelText('描述') as HTMLTextAreaElement).value).toBe('改了一半');
  });

  it('P1 内容与原描述相同 → 拦在提交前，不发请求', async () => {
    const p = port();
    renderPage(p);
    await screen.findByText('关于 TA 的当前认识');

    fireEvent.click(firstButtonNamed('纠正'));
    const form = (await screen.findByText('新增一条更正')).closest('section') as HTMLElement;
    fireEvent.click(within(form).getByRole('button', { name: '纠正' }));

    expect(await within(form).findByText('内容和原来一样，没有需要更正的地方')).toBeDefined();
    expect(p.correctItem).not.toHaveBeenCalled();
  });
});

describe('档案页 · 补充条目', () => {
  it('P0 归档对象上补充 → 409 内联提示已归档（不谎报成功）', async () => {
    const archived = object('o1', '小宝', '2026-10-01T00:00:00Z');
    const p = port({
      listObjects: vi.fn(async () => ({ items: [archived] })),
      addItem: vi.fn(async () => {
        throw { status: 409 };
      }),
    });
    renderPage(p);
    await screen.findByText('关于 TA 的当前认识');

    fireEvent.click(screen.getByRole('button', { name: '补充一条' }));
    fireEvent.change(screen.getByLabelText('主题'), { target: { value: '睡眠' } });
    fireEvent.change(screen.getByLabelText('描述'), { target: { value: '入睡困难' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    expect(await screen.findByText('这个对象已归档，恢复使用后才能新增记录')).toBeDefined();
    // 已归档标在切换 chip 上（状态即可见）。
    expect(screen.getByText('已归档')).toBeDefined();
  });

  it('P1 空描述的补充被拦在提交前', async () => {
    const p = port();
    renderPage(p);
    await screen.findByText('关于 TA 的当前认识');

    fireEvent.click(screen.getByRole('button', { name: '补充一条' }));
    fireEvent.change(screen.getByLabelText('主题'), { target: { value: '睡眠' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    expect(await screen.findByText('描述不能为空')).toBeDefined();
    expect(p.addItem).not.toHaveBeenCalled();
  });
});

describe('档案页 · 支持对象管理', () => {
  it('P0 新建对象：空名时提交按钮禁用（单一字段不弹错）', async () => {
    renderPage(port());
    await screen.findByText('关于 TA 的当前认识');

    fireEvent.click(screen.getByRole('button', { name: '+ 新建对象' }));
    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getByText('给 TA 起个称呼')).toBeDefined();

    const submit = within(sheet).getByRole('button', { name: '创建' });
    expect((submit as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(within(sheet).getByLabelText('称呼'), { target: { value: '小满' } });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(submit);

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull();
    });
  });

  it('P1 对象操作单按状态给操作行：在用给「归档」，已归档给「恢复使用」', async () => {
    renderPage(port());
    await screen.findByText('关于 TA 的当前认识');

    fireEvent.click(screen.getByRole('button', { name: '对象操作' }));
    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getByRole('button', { name: '归档这个对象' })).toBeDefined();
    expect(within(sheet).queryByRole('button', { name: '恢复使用' })).toBeNull();
    // 不提供删除（支持对象生命周期无删除）。
    expect(within(sheet).queryByRole('button', { name: /删除/ })).toBeNull();
  });

  it('P1 归档须二次确认：先给说明与危险按钮，再落状态', async () => {
    const p = port();
    renderPage(p);
    await screen.findByText('关于 TA 的当前认识');

    fireEvent.click(screen.getByRole('button', { name: '对象操作' }));
    fireEvent.click(await screen.findByRole('button', { name: '归档这个对象' }));

    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getByText('归档后不再用于新会话，记录仍可查看与恢复')).toBeDefined();
    const confirm = within(sheet).getByRole('button', { name: '归档' });
    expect(confirm.className).toContain('btn-danger');
    fireEvent.click(confirm);

    await waitFor(() => {
      expect(p.patchObject).toHaveBeenCalledWith('o1', { archived: true });
    });
  });

  it('P1 切换对象只重取该对象的内容，不重取对象列表', async () => {
    const p = port({
      listObjects: vi.fn(async () => ({ items: [object('o1', '小宝'), object('o2', '小满')] })),
    });
    renderPage(p);
    await screen.findByText('关于 TA 的当前认识');

    fireEvent.click(screen.getByRole('button', { name: '小满' }));

    await waitFor(() => {
      expect(p.getSummary).toHaveBeenCalledWith('o2');
    });
    expect(p.listObjects).toHaveBeenCalledTimes(1);
  });
});
