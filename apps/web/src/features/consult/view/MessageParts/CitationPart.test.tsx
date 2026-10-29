/**
 * 模块: view/MessageParts/CitationPart.test
 * 职责: 依据区的回归守卫——深链目标从哪来、什么时候不给链接、标题用哪一段、
 *       状态徽章/适用范围/撤下标注怎么显示（DEMO-03）
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 契约修订 5（依据区收起、标题整体可点、跳 /cases?item=、状态徽章、撤下标注）
 *   - docs/技术设计/technical-details/资料与案例检索.md: MUST — 第 3 节（status/applicable_scope 随结果传递）、
 *     第 4 节（历史引用保留，但不得再作为当前依据，标注「该来源已撤下」）
 *   - apps/api/src/campfire/tools/library.py: MUST — `reference` 的线格式是 `<库别>:<条目 id>`
 *   - apps/web/src/features/library/view/LibraryPage.test.tsx: 判据依据（`?item=` 可定位资料分区条目）
 * 边界:
 *   - 依赖: testing-library、MemoryRouter（Link 需要路由上下文）
 *   - 被依赖: 无（`pnpm test` 收集）
 * 禁止行为:
 *   - 禁止只断言「渲染出了东西」：这里的判据是**链接目标**、**标题文本**与**徽章文案**
 *   - 禁止在用例里写死 uuid 之外的 id 形状（id 是什么由后端决定，前端只认前缀）
 *   - 禁止放过「缺状态时显示成已发表」这类回归：那正是本包要修的缺陷
 */

import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';

import {
  CITATION_STATUS_LABELS,
  CitationPart,
  citationDeepLink,
  citationIsWithdrawn,
  citationScopeText,
  citationStatusLabel,
  citationTitle,
} from './CitationPart';
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

/**
 * DEMO-03 的判据：状态、适用范围与撤下标注必须**照载荷显示**，缺就显示未知。
 *
 * 这些用例都建立在同一条纪律上：**界面不补值**。补值的方向恰好是「让界面好看、让
 * 依据显得权威」——那正是本缺陷要修的形态（缺失被当成已知，等于替查不到的来源背书）。
 */
describe('citationStatusLabel — 状态徽章照载荷显示，缺就未知', () => {
  it('三个已知取值各有中文文案（真实与虚构样例必须可辨）', () => {
    expect(citationStatusLabel(citation({ status: 'published' }))).toBe('已发表');
    expect(citationStatusLabel(citation({ status: 'internal' }))).toBe('内部');
    expect(citationStatusLabel(citation({ status: 'fictional' }))).toBe('虚构样例');
    // 词表本身就是契约：改了文案就等于改了界面上的词。
    expect(CITATION_STATUS_LABELS).toEqual({ published: '已发表', internal: '内部', fictional: '虚构样例' });
  });

  it('★ 状态缺失/空白/null ⇒ 「状态未知」，绝不默认成「已发表」', () => {
    // 旧历史（2026-10-29 之前的注解）没有这个键——这正是缺省路径，必须显示未知。
    expect(citationStatusLabel(citation())).toBe('状态未知');
    expect(citationStatusLabel(citation({ status: null }))).toBe('状态未知');
    expect(citationStatusLabel(citation({ status: '   ' }))).toBe('状态未知');
    expect(citationStatusLabel(citation())).not.toBe('已发表');
  });

  it('词表外的取值原样显示（不认识 ≠ 已发表，也不吞掉后端给的词）', () => {
    expect(citationStatusLabel(citation({ status: 'deprecated' }))).toBe('deprecated');
  });
});

describe('citationScopeText — 适用范围照载荷显示，缺就写未知', () => {
  it('有值就原样显示（首尾空白去掉）', () => {
    expect(citationScopeText(citation({ applicable_scope: '学龄前·家庭场景' }))).toBe('学龄前·家庭场景');
    expect(citationScopeText(citation({ applicable_scope: '  学龄前  ' }))).toBe('学龄前');
  });

  it('★ 缺失/空白 ⇒ 「适用范围未知」（留白会让人以为这条依据没有适用条件）', () => {
    expect(citationScopeText(citation())).toBe('适用范围未知');
    expect(citationScopeText(citation({ applicable_scope: null }))).toBe('适用范围未知');
    expect(citationScopeText(citation({ applicable_scope: '  ' }))).toBe('适用范围未知');
  });
});

describe('citationIsWithdrawn — 只认严格的 true', () => {
  it('true 是已撤下；false 是在库；null/缺省是无法核对（两者都不是撤下）', () => {
    expect(citationIsWithdrawn(citation({ withdrawn: true }))).toBe(true);
    expect(citationIsWithdrawn(citation({ withdrawn: false }))).toBe(false);
    expect(citationIsWithdrawn(citation({ withdrawn: null }))).toBe(false);
    expect(citationIsWithdrawn(citation())).toBe(false);
  });
});

describe('CitationPart — 徽章与撤下标注的渲染', () => {
  it('状态徽章用契约类名 .tag.meta 渲染文案（不是自己发明的字）', () => {
    const { container } = renderPart([citation({ status: 'fictional' })]);
    const badge = container.querySelector('.citation-badges .tag.meta');
    expect(badge?.textContent).toBe('虚构样例');
  });

  it('★ 状态缺失时界面上出现「状态未知」而不是「已发表」', () => {
    const { container } = renderPart([citation()]);
    expect(container.textContent).toContain('状态未知');
    expect(container.textContent).not.toContain('已发表');
  });

  it('来源行同时给出适用范围（RQ-CON-03 的界面落点）', () => {
    renderPart([citation({ applicable_scope: '学龄前·家庭场景' })]);
    expect(screen.getByText(/适用范围：学龄前·家庭场景/)).toBeDefined();
  });

  it('★ 已撤下：标题不跳转、灰调标注「该来源已撤下」、并说明不再作为依据', () => {
    const { container } = renderPart([citation({ withdrawn: true, status: 'published' })]);
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByText('该来源已撤下')).toBeDefined();
    expect(screen.getByText(/不再作为当前依据/)).toBeDefined();
    expect(container.querySelector('.citation-item.is-withdrawn')).not.toBeNull();
    // 快照状态仍然显示：它与「现在还能不能引用」是两个事实，不互相顶替。
    expect(screen.getByText('已发表')).toBeDefined();
  });

  it('★ 无法核对（withdrawn=null）仍给链接，但**不**打撤下标注', () => {
    const { container } = renderPart([citation({ withdrawn: null })]);
    expect(screen.getByRole('link', { name: '0～6 岁儿童孤独症筛查干预服务规范（试行）' })).toBeDefined();
    expect(screen.queryByText('该来源已撤下')).toBeNull();
    expect(container.querySelector('.citation-item.is-withdrawn')).toBeNull();
  });

  it('在库（withdrawn=false）与旧载荷（无该键）行为相同：给链接、无撤下标注', () => {
    for (const withdrawn of [false, undefined]) {
      const { container, unmount } = renderPart([citation({ withdrawn })]);
      expect(container.querySelector('.citation-item.is-withdrawn')).toBeNull();
      expect(container.textContent).not.toContain('该来源已撤下');
      unmount();
    }
  });
});
