/**
 * 模块: view/MessageParts/CitationPart.test
 * 职责: 依据区的回归守卫——深链目标从哪来、什么时候不给链接、标题用哪一段
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 契约修订 5（依据区收起、标题整体可点、跳 /cases?item=）
 *   - apps/api/src/campfire/tools/library.py: MUST — `reference` 的线格式是 `<库别>:<条目 id>`
 *   - apps/web/src/features/library/view/LibraryPage.test.tsx: 判据依据（`?item=` 可定位资料分区条目）
 * 边界:
 *   - 依赖: testing-library、MemoryRouter（Link 需要路由上下文）
 *   - 被依赖: 无（`pnpm test` 收集）
 * 禁止行为:
 *   - 禁止只断言「渲染出了东西」：这里的判据是**链接目标**与**标题文本**，不是元素存在
 *   - 禁止在用例里写死 uuid 之外的 id 形状（id 是什么由后端决定，前端只认前缀）
 */

import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';

import { CitationPart, citationDeepLink, citationTitle } from './CitationPart';
import type { CitationRecord } from '../../../../shared/types/sse';

/** 一条线格式的引用记录（形状与 `shared/types/sse.ts` 的 citation 记录一致）。 */
function citation(overrides: Partial<CitationRecord> = {}): CitationRecord {
  return {
    citation_id: 'c1',
    run_id: 'r1',
    source: 'knowledge',
    reference: 'knowledge:28b9c955-48fb-4752-8897-e4aee5930f79',
    recorded_at: '2026-10-28T00:00:00.000Z',
    summary: '0～6 岁儿童孤独症筛查干预服务规范（试行）',
    ...overrides,
  };
}

function renderPart(items: readonly CitationRecord[]) {
  return render(
    <MemoryRouter initialEntries={['/consult/sessions/s1']}>
      <CitationPart items={items} />
    </MemoryRouter>,
  );
}

describe('citationDeepLink — 深链目标只从可解析的标识来', () => {
  it('`knowledge:<id>` ⇒ /cases?item=<id>（资料分区由案例库页自己判定）', () => {
    expect(citationDeepLink(citation())).toBe('/cases?item=28b9c955-48fb-4752-8897-e4aee5930f79');
  });

  it('`case:<id>` 也走同一条路径（两个库共用案例库浏览页）', () => {
    expect(citationDeepLink(citation({ source: 'case', reference: 'case:c-42' }))).toBe('/cases?item=c-42');
  });

  it('载荷显式带 item_id 时以它为准（设计第 5 节的完整载荷会带）', () => {
    const withItemId = { ...citation(), item_id: 'explicit-9' } as CitationRecord;
    expect(citationDeepLink(withItemId)).toBe('/cases?item=explicit-9');
  });

  it('前缀不认识 ⇒ 不给链接（猜错库比不跳转更糟）', () => {
    expect(citationDeepLink(citation({ reference: 'internal:abc' }))).toBeNull();
    expect(citationDeepLink(citation({ reference: '28b9c955-48fb-4752-8897-e4aee5930f79' }))).toBeNull();
  });

  it('标识里带分隔符 ⇒ 不给链接（不是我们认得的形状）', () => {
    expect(citationDeepLink(citation({ reference: 'knowledge:a/b' }))).toBeNull();
    expect(citationDeepLink(citation({ reference: 'knowledge:?x=1' }))).toBeNull();
  });
});

describe('citationTitle — 人能读的那一段', () => {
  it('有摘要就用摘要（后端写入时摘要取的是条目标题）', () => {
    expect(citationTitle(citation())).toBe('0～6 岁儿童孤独症筛查干预服务规范（试行）');
  });

  it('没有摘要退回 reference（不可读，但比空白强）', () => {
    expect(citationTitle(citation({ summary: null }))).toBe('knowledge:28b9c955-48fb-4752-8897-e4aee5930f79');
    expect(citationTitle(citation({ summary: '   ' }))).toBe('knowledge:28b9c955-48fb-4752-8897-e4aee5930f79');
  });
});

describe('CitationPart — 渲染', () => {
  it('标题是链接，指向 deep-link；来源行不再说「不能跳转」', () => {
    renderPart([citation()]);
    const link = screen.getByRole('link', { name: '0～6 岁儿童孤独症筛查干预服务规范（试行）' });
    expect(link.getAttribute('href')).toBe('/cases?item=28b9c955-48fb-4752-8897-e4aee5930f79');
    expect(screen.getByText(/来源：knowledge/)).toBeDefined();
    expect(screen.queryByText(/本条暂不能跳转到来源条目/)).toBeNull();
  });

  it('拿不到标识时是纯文本标题，并如实说明不能跳转', () => {
    renderPart([citation({ reference: 'internal:abc', summary: '内部条目' })]);
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByText('内部条目')).toBeDefined();
    expect(screen.getByText(/本条暂不能跳转到来源条目/)).toBeDefined();
  });

  it('摘要就是标题时不重复渲染一行同样的字', () => {
    const { container } = renderPart([citation()]);
    const titleText = '0～6 岁儿童孤独症筛查干预服务规范（试行）';
    expect(container.textContent?.split(titleText).length).toBe(2);
  });

  it('多条依据逐条渲染，标题各是各自的（防止把第一条套到所有条目上）', () => {
    renderPart([
      citation(),
      citation({ citation_id: 'c2', reference: 'case:c-42', source: 'case', summary: '从强迫到尊重' }),
    ]);
    expect(screen.getByRole('link', { name: '0～6 岁儿童孤独症筛查干预服务规范（试行）' })).toBeDefined();
    expect(screen.getByRole('link', { name: '从强迫到尊重' })).toBeDefined();
  });

  it('空数组不渲染折叠头（不留一个「依据 0 条」的空壳）', () => {
    const { container } = renderPart([]);
    expect(container.querySelector('.citation-block')).toBeNull();
  });
});
