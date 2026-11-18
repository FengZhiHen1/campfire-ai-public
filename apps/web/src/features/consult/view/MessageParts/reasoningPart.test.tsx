import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ReasoningDisclosure } from './ReasoningDisclosure';

describe('思考过程折叠区', () => {
  it('默认收起，说明与结论的边界留在折叠区内', () => {
    render(<ReasoningDisclosure label="思考过程" running={false}><p>正在核对情境。</p></ReasoningDisclosure>);
    const summary = screen.getByText('思考过程');
    const details = summary.closest('details');
    expect(details?.open).toBe(false);
    expect(details?.textContent).toContain('不作为结论或依据');
  });

  it('运行结束只更新标签，保留原先手动展开的状态', () => {
    const { rerender } = render(<ReasoningDisclosure label="正在查阅案例…" running><p>已收到记录。</p></ReasoningDisclosure>);
    const details = screen.getByText('正在查阅案例…').closest('details');
    expect(details).not.toBeNull();
    details!.open = true;
    rerender(<ReasoningDisclosure label="思考过程" running={false}><p>已收到记录。</p></ReasoningDisclosure>);
    expect(screen.getByText('思考过程').closest('details')).toBe(details);
    expect(details?.open).toBe(true);
  });
});
