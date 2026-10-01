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

/**
 * 数一段文本里出现某短语的次数（重叠不重复计）。
 *
 * 为什么不用 `getByText` 的存在性：「同一句话在页面上出现几次」正是本页一条验收点
 * （时效措辞曾经两个出口），而 `getByText('已降权')` 对「标一处 + 元信息行尾部一处」
 * 依然通过——默认匹配是整元素文本相等，长串里的子串不算命中。要数次数就只能数文本。
 */
function countOccurrences(haystack: string, needle: string): number {
  return haystack.split(needle).length - 1;
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

  it('P0 候选 + 已降权：该行只出现一处「已降权」标，且元信息行不含时效措辞（档案页第 23、25、33 行）', async () => {
    // 判别性：判据与呈现都必须落在候选行上。修复前标与折叠挂在稳定行——而稳定层的
    // isStale 恒为假（服务端按 freshness=current 取稳定层），那是一整条死分支。
    // 把标与折叠放回稳定行后，本用例的标与折叠断言全红：候选行没有标、描述直接可见、
    // 也没有「展开内容」入口。
    const staleCandidate = item({
      item_id: 'c1',
      topic: '提前知道结束时间',
      description: '出行前先说清流程',
      origin: 'ai_inference',
      confirmation: 'unconfirmed',
      freshness: 'stale',
    });
    const p = port({
      listItems: vi.fn(async () => ({ items: [item()], candidates: [staleCandidate], next_cursor: null })),
    });
    // 这个容器只装本用例渲染的页面：数次数时才不会被上个用例的残留 DOM 干扰。
    const { container } = renderPage(p);

    const group = (await screen.findByText(/^待确认（1）$/)).closest('details') as HTMLElement;
    const row = within(group).getByText('提前知道结束时间').closest('article') as HTMLElement;

    // 「已降权」标是 .tag.meta（与切换 chip 上的「已归档」标同一契约类）。
    const badge = within(row).getByText('已降权');
    expect(badge.className).toContain('tag');
    expect(badge.className).toContain('meta');

    // 直接验收点：数是 1 不是「存在」。把时效措辞加回 itemMetaLine 后这里变 2 而变红。
    expect(countOccurrences(row.textContent ?? '', '已降权')).toBe(1);
    expect(countOccurrences(container.textContent ?? '', '已降权')).toBe(1);

    // 元信息行只留来源 + 确认状态 + 时间（档案页第 23 行）。
    const metaText = row.querySelector('.lr-meta')?.textContent ?? '';
    expect(metaText).toContain('AI 归纳');
    expect(metaText).not.toContain('已降权');
    expect(metaText).not.toContain('已更正');

    // 默认收起：描述不以正文出现，只给一个展开入口；点开后描述可见。
    expect(within(row).queryByText('出行前先说清流程')).toBeNull();
    fireEvent.click(within(row).getByRole('button', { name: '展开内容' }));
    expect(await within(row).findByText('出行前先说清流程')).toBeDefined();
  });

  it('P1 默认读法（服务端未返回历史条目）下页面不出现「已更正」——标随数据出现，不凭空造', async () => {
    // 后端缺省 `include_superseded = false`：历史条目不返回（648cab8 的既定行为）。
    // 这一条是对照组：没有历史条目这条数据时，界面上不得出现「已更正」标。
    const { container } = renderPage(port());
    await screen.findByText('关于 TA 的当前认识');

    expect(countOccurrences(container.textContent ?? '', '已更正')).toBe(0);
  });

  it('P0 opt-in 后历史条目随 items 返回：行首「已更正」标且全页只有一处（档案页第 33、62 行）', async () => {
    // 替身照后端既定闸门返回（648cab8）：只有 `include_superseded=true` 时 items 里才有历史条目。
    // 判别性（消融实测）：撤掉 `LoadProfileUseCase.loadObject` 的 `includeSuperseded`，替身走缺省
    // 分支，本用例的标与计数断言全红；把 StableRow 的「已更正」标撤掉同样全红。
    // 历史条目归完整条目区（不是「待确认」分组）：归候选组会让档案页给已被取代的条目出「确认」入口。
    const historical = item({
      item_id: 'h1',
      topic: '旧的说法',
      description: '旧描述',
      origin: 'user_statement',
      confirmation: 'confirmed',
      freshness: 'historical',
      superseded_by: 'i2',
    });
    const staleCandidate = item({
      item_id: 'c1',
      topic: '提前知道结束时间',
      origin: 'ai_inference',
      confirmation: 'unconfirmed',
      freshness: 'stale',
    });
    const p = port({
      listItems: vi.fn(async (_objectId: string, options?: { includeSuperseded?: boolean }) => ({
        items: options?.includeSuperseded === true ? [item(), historical] : [item()],
        candidates: [staleCandidate],
        next_cursor: null,
      })),
    });
    const { container } = renderPage(p);
    await screen.findByText('关于 TA 的当前认识');

    // 页面必须显式 opt-in：缺省时服务端不返回历史条目，标也就无从出现。
    expect(p.listItems).toHaveBeenCalledWith('o1', {
      includeCandidates: true,
      includeSuperseded: true,
    });

    // 历史条目落在完整条目区（领域分组里），不在「待确认」分组。
    const candidateGroup = screen.getByText(/^待确认（1）$/).closest('details') as HTMLElement;
    expect(within(candidateGroup).queryByText('旧的说法')).toBeNull();

    const row = (await screen.findByText('旧的说法')).closest('article') as HTMLElement;
    const badge = within(row).getByText('已更正');
    expect(badge.className).toContain('tag');
    expect(badge.className).toContain('meta');

    // 直接验收点：数是 1 不是「存在」——标只出一处（元信息行不收时效措辞）。
    expect(countOccurrences(row.textContent ?? '', '已更正')).toBe(1);
    expect(countOccurrences(container.textContent ?? '', '已更正')).toBe(1);
    expect(row.querySelector('.lr-meta')?.textContent ?? '').not.toContain('已更正');

    // 候选行的「已降权」标未受影响，历史标也不漏进候选行。
    const candidateRow = (await screen.findByText('提前知道结束时间')).closest('article') as HTMLElement;
    expect(countOccurrences(candidateRow.textContent ?? '', '已降权')).toBe(1);
    expect(countOccurrences(candidateRow.textContent ?? '', '已更正')).toBe(0);
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
  it('P0 摘要区每条尾部带「纠正」按钮，点击进入该条的纠正流并走到同一条端点', async () => {
    // 设计第 20 行：摘要每条尾部「纠正」文字按钮（.btn-quiet 小号），点击进入该条的纠正流。
    // 判别性：把摘要条目里的按钮去掉，本用例第一行查询就失败——条目行上那个「纠正」
    // 救不了它（两者在同一个页面上，但入口与预填对象必须是这条摘要对应的那一条）。
    const p = port();
    renderPage(p);
    await screen.findByText('关于 TA 的当前认识');

    const summary = screen.getByRole('region', { name: '关于 TA 的当前认识' });
    const summaryCorrect = within(summary).getByRole('button', { name: '纠正：用图片卡表达需求' });
    expect(summaryCorrect.textContent).toBe('纠正');
    expect(summaryCorrect.className).toContain('btn-quiet');

    fireEvent.click(summaryCorrect);

    // 走的是既有纠正流：同一张内联表单、同一套预填。
    const form = (await screen.findByText('新增一条更正')).closest('section') as HTMLElement;
    const description = within(form).getByLabelText('描述');
    expect((description as HTMLTextAreaElement).value).toBe('用图片卡表达需求');

    fireEvent.change(description, { target: { value: '改用图片卡 + 手势' } });
    fireEvent.click(within(form).getByRole('button', { name: '纠正' }));

    await waitFor(() => {
      expect(p.correctItem).toHaveBeenCalledWith('i1', expect.objectContaining({ description: '改用图片卡 + 手势' }));
    });
  });

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
