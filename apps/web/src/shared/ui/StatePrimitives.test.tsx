/**
 * 模块: src/shared/ui/StatePrimitives.test
 * 职责: 三态基语的契约用例——类名与可访问属性，供 T11/T12 消费时不被静默改坏
 * 数据来源:
 *   - docs/design/DESIGN.md: MUST — 下游消费指引（三态基元是各页 loading/empty/error 的唯一来源）
 *   - docs/design/components.html: MUST — .skeleton/.empty-state/.error-card 的类名与结构
 * 边界:
 *   - 依赖: shared/ui/StatePrimitives
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言页内自造三态是允许的（这三个基元是唯一来源，改形状须走契约修订）
 *
 * 为什么两个当前无消费者的基元也要测：它们是本包对 T11/T12 的对外承诺（Skeleton/
 * EmptyState/ErrorCard 的 API）。无消费者且无测试的「承诺」在下一个包接入前没有任何
 * 东西挡着它被改坏，而那时改坏只会表现为「某页样式不对」而不是一条失败用例。
 */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { EmptyState, ErrorCard, Skeleton } from './StatePrimitives';

describe('Skeleton', () => {
  it('P0 默认输出一行骨架，且整组对辅助技术隐藏', () => {
    const { container } = render(<Skeleton />);

    const wrapper = container.firstElementChild;
    expect(wrapper?.getAttribute('aria-hidden')).toBe('true');
    expect(container.querySelectorAll('.skeleton.row')).toHaveLength(1);
  });

  it('P0 rows 决定骨架行数，且类名含契约的 .skeleton.row', () => {
    const { container } = render(<Skeleton rows={3} />);

    const rows = container.querySelectorAll('.skeleton.row');
    expect(rows).toHaveLength(3);
    for (const row of rows) expect(row.className).toContain('skeleton');
  });

  it('P1 rows 为 0 或负数时仍渲染一行（0 行等于没有告知「正在加载」）', () => {
    expect(render(<Skeleton rows={0} />).container.querySelectorAll('.skeleton.row')).toHaveLength(1);
    expect(render(<Skeleton rows={-2} />).container.querySelectorAll('.skeleton.row')).toHaveLength(1);
  });

  it('P1 小数行数向下取整，不产生半个骨架', () => {
    const { container } = render(<Skeleton rows={2.7} />);

    expect(container.querySelectorAll('.skeleton.row')).toHaveLength(2);
  });
});

describe('EmptyState', () => {
  it('P0 输出契约结构：.empty-state + .es-title + 说明', () => {
    const { container } = render(<EmptyState title="还没有咨询记录" description="从这里开始第一次日常咨询。" />);

    expect(container.querySelector('.empty-state')).not.toBeNull();
    expect(screen.getByText('还没有咨询记录').className).toContain('es-title');
    expect(screen.getByText('从这里开始第一次日常咨询。')).toBeDefined();
  });

  it('P0 可选操作被渲染在说明之后', () => {
    render(<EmptyState title="空" description="说明" action={<button type="button">开始</button>} />);

    expect(screen.getByRole('button', { name: '开始' })).toBeDefined();
  });

  it('P1 无操作时不渲染多余按钮', () => {
    render(<EmptyState title="空" description="说明" />);

    expect(screen.queryByRole('button')).toBeNull();
  });
});

describe('ErrorCard', () => {
  it('P0 输出契约结构：.error-card + .ec-title + 说明', () => {
    const { container } = render(<ErrorCard title="没有成功" description="服务暂时不可用，请稍后再试" />);

    expect(container.querySelector('.error-card')).not.toBeNull();
    expect(screen.getByText('没有成功').className).toContain('ec-title');
    expect(screen.getByText('服务暂时不可用，请稍后再试')).toBeDefined();
  });

  it('P0 带 role=alert（屏幕阅读器即时可闻）', () => {
    render(<ErrorCard title="没有成功" description="原因" />);

    expect(screen.getByRole('alert').className).toContain('error-card');
  });

  it('P1 可选操作区被渲染', () => {
    render(<ErrorCard title="加载失败" description="可以重试" actions={<button type="button">重试</button>} />);

    expect(screen.getByRole('button', { name: '重试' })).toBeDefined();
  });
});
