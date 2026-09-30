/**
 * 模块: features/library/view/LibraryPage.test
 * 职责: 案例库浏览页组件用例——库别切换、检索三态、就地展开、deep-link 三态与分页
 * 数据来源:
 *   - docs/design/pages/案例库浏览页.md: MUST — 状态覆盖表与 token 使用节
 *   - docs/技术设计/面/profile/资料库面HTTP契约.md: MUST — 第 3、4、5、6 节
 * 边界:
 *   - 依赖: features/library/view/LibraryPage 与一个端口替身、react-router 内存路由
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言检索失败呈现成「没有找到相关内容」
 *   - 禁止断言已撤下的来源显示正文
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

import type { ExpandedLibraryItem } from '../../../shared/types/library';
import type { LibraryPort } from '../application/ports';
import { LibraryPage } from './LibraryPage';

/**
 * 造一条带展开内容的条目。
 *
 * 默认给空的展开内容：`ExpandedLibraryItem` 的 narrative 与 cards 是必填字段
 * （写进类型的就是「带展开内容的条目」这件事本身），而页面只在展开态渲染它们——
 * 因此空展开内容既满足类型，也不影响未展开用例的真实性。
 */
function item(overrides: Partial<ExpandedLibraryItem> = {}): ExpandedLibraryItem {
  return {
    item_id: 'c1',
    library: 'case',
    title: '超市哭闹时的分流做法',
    snippet: '先把人带到安静处，再给两个可选的做法',
    source: '某机构公开材料',
    applicable_scope: '学龄前经验（家长自述）',
    status: 'published',
    locator: 'section-3',
    ranking: { rank: 1, channels: ['vector'] },
    narrative: { sections: [] },
    cards: [],
    ...overrides,
  };
}

/** 资料库端口替身。 */
function port(overrides: Partial<LibraryPort> = {}): LibraryPort {
  return {
    listItems: vi.fn(async (params: { library: 'case' | 'knowledge' }) => ({
      library: params.library,
      items: [item()],
      next_cursor: null,
    })),
    getItem: vi.fn(async () => ({ item: item() })),
    ...overrides,
  };
}

/** 渲染案例库浏览页。 */
function renderPage(libraryPort: LibraryPort, search = '') {
  return render(
    <MemoryRouter initialEntries={[`/cases${search}`]}>
      <LibraryPage port={libraryPort} searchOverride={search} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('案例库浏览页 · 结构与库别', () => {
  it('P0 是次级页：有返回与标题，不渲染 tab 栏', async () => {
    renderPage(port());
    await screen.findByText('超市哭闹时的分流做法');

    expect(screen.getByRole('link', { name: '← 返回' })).toBeDefined();
    expect(screen.getByText('案例与资料')).toBeDefined();
    expect(screen.queryByRole('navigation', { name: '一级导航' })).toBeNull();
  });

  it('P0 默认落在案例分区，检索行与两个库切换 chip 常驻', async () => {
    const p = port();
    renderPage(p);
    await screen.findByText('超市哭闹时的分流做法');

    expect(p.listItems).toHaveBeenCalledWith(expect.objectContaining({ library: 'case', query: '' }));
    expect(screen.getByPlaceholderText('搜案例、搜资料')).toBeDefined();
    const tabs = screen.getByRole('group', { name: '检索范围' });
    expect(within(tabs).getByRole('button', { name: '案例' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('P0 状态三态直出文字：已发表 / 虚构样例', async () => {
    renderPage(
      port({
        listItems: vi.fn(async () => ({
          library: 'case' as const,
          items: [item(), item({ item_id: 'c2', title: '虚构的示例', status: 'fictional' as const })],
          next_cursor: null,
        })),
      }),
    );
    await screen.findByText('虚构的示例');

    expect(screen.getByText('已发表')).toBeDefined();
    const fictional = screen.getByText('虚构样例');
    // 虚构标识走灰调（.status.off），且文字直出——可辨性不建立在色觉上。
    expect(fictional.className).toContain('off');
  });

  it('P1 切到资料分区会带新库别重新检索', async () => {
    const p = port();
    renderPage(p);
    await screen.findByText('超市哭闹时的分流做法');

    fireEvent.click(screen.getByRole('button', { name: '资料' }));

    await waitFor(() => {
      expect(p.listItems).toHaveBeenLastCalledWith(expect.objectContaining({ library: 'knowledge' }));
    });
  });

  it('P1 输入检索词后按防抖发起新检索，词留在输入框里', async () => {
    const p = port();
    renderPage(p);
    await screen.findByText('超市哭闹时的分流做法');

    fireEvent.change(screen.getByPlaceholderText('搜案例、搜资料'), { target: { value: '超市哭闹' } });

    await waitFor(
      () => {
        expect(p.listItems).toHaveBeenLastCalledWith(expect.objectContaining({ query: '超市哭闹' }));
      },
      { timeout: 2000 },
    );
    expect((screen.getByPlaceholderText('搜案例、搜资料') as HTMLInputElement).value).toBe('超市哭闹');
  });
});

describe('案例库浏览页 · 空与失败', () => {
  it('P0 有检索词但无命中 → 「没有找到相关内容」+ 换个说法的建议', async () => {
    const p = port({ listItems: vi.fn(async () => ({ library: 'case' as const, items: [], next_cursor: null })) });
    renderPage(p);

    // 空态两句由「有没有检索词」决定，因此这里必须真的输入一次——
    // 页面不从 URL 读 query（契约的进入参数只有 item 与库别）。
    fireEvent.change(await screen.findByPlaceholderText('搜案例、搜资料'), { target: { value: '超市哭闹' } });

    expect(await screen.findByText('没有找到相关内容')).toBeDefined();
    expect(screen.getByText(/试试更日常的措辞/)).toBeDefined();
    expect(screen.queryByText('案例库还在准备中')).toBeNull();
  });

  it('P0 无检索词且库为空 → 「案例库还在准备中」，不放假数据', async () => {
    renderPage(port({ listItems: vi.fn(async () => ({ library: 'case' as const, items: [], next_cursor: null })) }));
    expect(await screen.findByText('案例库还在准备中')).toBeDefined();
    expect(screen.queryByText('没有找到相关内容')).toBeNull();
  });

  it('P0 检索不可用（503）→ 「检索暂时不可用」，绝不当成没有内容，且保留已输入词', async () => {
    renderPage(
      port({
        listItems: vi.fn(async () => {
          throw { status: 503 };
        }),
      }),
    );

    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText('检索暂时不可用')).toBeDefined();
    expect(screen.queryByText('没有找到相关内容')).toBeNull();
    expect(screen.queryByText('案例库还在准备中')).toBeNull();
    expect(screen.getByRole('button', { name: '重试' })).toBeDefined();
  });
});

describe('案例库浏览页 · 就地展开', () => {
  it('P0 点击卡片带 expand 重新取该条，展开内容随列表返回', async () => {
    const p = port({
      listItems: vi.fn(async (params: { library: 'case' | 'knowledge'; expand?: string }) => ({
        library: params.library,
        items:
          params.expand === 'c1'
            ? [
                item({
                  narrative: { sections: [{ key: 's1', heading: '情境', text: '超市人多时' }] },
                  cards: [
                    {
                      card_id: 'card-1',
                      scenario: '孩子在超市突然哭闹',
                      immediate_action: '先带到安静处',
                      inferred_fields: ['情绪触发点'],
                      risk_class: 'mixed' as const,
                    },
                  ],
                }),
              ]
            : [item()],
        next_cursor: null,
      })),
    });
    renderPage(p);
    await screen.findByText('超市哭闹时的分流做法');

    fireEvent.click(screen.getByRole('button', { name: /超市哭闹时的分流做法/ }));

    expect(await screen.findByText('情境')).toBeDefined();
    expect(screen.getByText('超市人多时')).toBeDefined();
    expect(screen.getByText('案例卡片')).toBeDefined();
    expect(screen.getByText(/风险混合/)).toBeDefined();
    // 推断字段只作呈现标注。
    expect(screen.getByText(/含推断字段：情绪触发点/)).toBeDefined();
    expect(p.listItems).toHaveBeenLastCalledWith(expect.objectContaining({ expand: 'c1' }));
  });

  it('P1 卡片上的展开/收起提示随展开态切换（整卡可点的可读提示不得是死分支）', async () => {
    // 判别性：ItemRow 不把 onToggle 传给 ItemRowBody 时，onToggle !== undefined 恒假，
    // 「展开内容」永不出现，本用例第一条断言即失败。
    const p = port({
      listItems: vi.fn(async (params: { library: 'case' | 'knowledge'; expand?: string }) => ({
        library: params.library,
        items:
          params.expand === 'c1'
            ? [
                item({
                  narrative: { sections: [{ key: 's1', heading: '情境', text: '超市人多时' }] },
                }),
              ]
            : [item()],
        next_cursor: null,
      })),
    });
    renderPage(p);
    await screen.findByText('超市哭闹时的分流做法');

    // 未展开：提示「展开内容」；展开后：提示「收起」。
    expect(within(screen.getByRole('button', { name: /超市哭闹时的分流做法/ })).getByText('展开内容')).toBeDefined();

    fireEvent.click(screen.getByRole('button', { name: /超市哭闹时的分流做法/ }));
    expect(await screen.findByText('收起')).toBeDefined();
    expect(screen.queryByText('展开内容')).toBeNull();
  });
});

describe('案例库浏览页 · deep-link 三态', () => {
  it('P0 目标在库：按它的库别切分区并高亮定位', async () => {
    const p = port({
      getItem: vi.fn(async () => ({ item: item({ item_id: 'k9', library: 'knowledge' as const, title: '一篇资料' }) })),
      listItems: vi.fn(async (params: { library: 'case' | 'knowledge' }) => ({
        library: params.library,
        items: [item({ item_id: 'k9', library: 'knowledge' as const, title: '一篇资料' })],
        next_cursor: null,
      })),
    });
    renderPage(p, '?item=k9');

    await screen.findByText('一篇资料');
    await waitFor(() => {
      expect(p.listItems).toHaveBeenLastCalledWith(expect.objectContaining({ library: 'knowledge' }));
    });
  });

  it('P0 目标在库：定位并带 expand 重取本页，展开正文真的渲染出来', async () => {
    // 「定位并展开」的展开那一半：只切分区、只置 expandedId 而不带 expand 重取列表时，
    // 展开内容永远不出现（展开内容随列表返回，契约第 4 节）。
    // 判别性：去掉 `load({ library, expand })` 里的 expand（或去掉 deep-link 那次重取），
    // 「资料正文」查不到，本用例立刻失败。
    const focused = item({ item_id: 'k9', library: 'knowledge' as const, title: '一篇资料' });
    const p = port({
      getItem: vi.fn(async () => ({ item: focused })),
      listItems: vi.fn(async (params: { library: 'case' | 'knowledge'; expand?: string }) => ({
        library: params.library,
        items:
          params.expand === 'k9'
            ? [
                item({
                  item_id: 'k9',
                  library: 'knowledge' as const,
                  title: '一篇资料',
                  narrative: { sections: [{ key: 's1', heading: '情境', text: '资料正文' }] },
                }),
              ]
            : [focused],
        next_cursor: null,
      })),
    });
    renderPage(p, '?item=k9');

    expect(await screen.findByText('资料正文')).toBeDefined();
    await waitFor(() => {
      expect(p.listItems).toHaveBeenLastCalledWith(expect.objectContaining({ library: 'knowledge', expand: 'k9' }));
    });
  });

  it('P0 目标已撤下：单条撤下卡只带标题，不显示正文', async () => {
    renderPage(
      port({
        getItem: vi.fn(async () => ({ item: null, withdrawn: true, title: '某个已撤下的案例' })),
        listItems: vi.fn(async () => ({ library: 'case' as const, items: [], next_cursor: null })),
      }),
      '?item=gone',
    );

    expect(await screen.findByText('该来源已撤下')).toBeDefined();
    expect(screen.getByText('某个已撤下的案例')).toBeDefined();
    expect(screen.getByText('这条资料已不再作为依据使用')).toBeDefined();
    // 撤下条目不进列表（RQ-KB-04：撤下即消失，无「已撤下」幽灵条目）。
    expect(screen.queryByText('超市哭闹时的分流做法')).toBeNull();
  });

  it('P1 非法 id（单条查询失败）→ 按普通进入处理，不显示错误', async () => {
    renderPage(
      port({
        getItem: vi.fn(async () => {
          throw { status: 404 };
        }),
      }),
      '?item=bogus',
    );

    expect(await screen.findByText('超市哭闹时的分流做法')).toBeDefined();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText('该来源已撤下')).toBeNull();
  });
});

describe('案例库浏览页 · 触底分页', () => {
  it('P0 触底加载下一页失败 → 列表尾部给出可见的失败与重试，不静默吞掉', async () => {
    // 判别性：分页失败只写进 failure 而 status 仍为 ready（页面只在 status==='error'
    // 渲染错误卡）时，alert 永不出现，本用例在 `findByRole('alert')` 处超时失败。
    let attempt = 0;
    const p = port({
      listItems: vi.fn(async (params: { library: 'case' | 'knowledge'; cursor?: string }) => {
        if (params.cursor === undefined) {
          return { library: params.library, items: [item({ item_id: 'c1', title: '第一条' })], next_cursor: '20' };
        }
        attempt += 1;
        if (attempt === 1) throw { status: 503 };
        return { library: params.library, items: [item({ item_id: 'c2', title: '第二条' })], next_cursor: null };
      }),
    });
    renderPage(p);
    await screen.findByText('第一条');

    fireEvent.click(screen.getByRole('button', { name: '加载更多' }));

    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText('检索暂时不可用')).toBeDefined();
    // 已取到的结果仍在：分页失败不改整页。
    expect(screen.getByText('第一条')).toBeDefined();

    fireEvent.click(within(alert).getByRole('button', { name: '重试' }));
    expect(await screen.findByText('第二条')).toBeDefined();
    expect(screen.getByText('第一条')).toBeDefined();
    expect(p.listItems).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: '20' }));
  });

  it('P1 还有下一页时给出加载入口，加载后追加而不是替换', async () => {
    const p = port({
      listItems: vi.fn(async (params: { cursor?: string }) =>
        params.cursor === undefined
          ? { library: 'case' as const, items: [item({ item_id: 'c1', title: '第一条' })], next_cursor: '20' }
          : { library: 'case' as const, items: [item({ item_id: 'c2', title: '第二条' })], next_cursor: null },
      ),
    });
    renderPage(p);
    await screen.findByText('第一条');

    // jsdom 没有 IntersectionObserver，页面按降级路径给显式按钮。
    fireEvent.click(screen.getByRole('button', { name: '加载更多' }));

    expect(await screen.findByText('第二条')).toBeDefined();
    expect(screen.getByText('第一条')).toBeDefined();
    expect(p.listItems).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: '20' }));
  });
});
