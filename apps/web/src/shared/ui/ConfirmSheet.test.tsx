/**
 * 模块: shared/ui/ConfirmSheet.test
 * 职责: 确认单的模态可达性回归——初始焦点、焦点陷阱、Esc 关闭、背景 inert、遮罩与 aria-modal
 * 数据来源:
 *   - docs/design/components.html: MUST — `.confirm-sheet` 的契约结构与 ::backdrop
 *   - .tmp/dev-orchestrator/20261002-001/tasks/T07.md: MUST — ② 的五条验收判据
 *   - .tmp/dev-orchestrator/20261002-001/feedback/T07-review-rulings.md: MUST — r2 的 inert 要求
 * 边界:
 *   - 依赖: shared/ui/ConfirmSheet、@testing-library/react
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止把 Tab 断言写成「不报错即通过」——必须逐步骤核对 activeElement 的身份
 *   - 禁止用 jsdom 的原生行为冒充浏览器行为（见下方 pressTab 的说明）
 *   - 禁止用 `el.inert = true` 施加 inert（jsdom 无属性反射，断言会看不到变化）
 *
 * 为什么这些用例测的是共享组件而不是五处调用点：五处（SettingsPage 登出、
 * MemoryPage 删除、ProfilePage 删除/对象菜单/对象表单）都渲染同一个 ConfirmSheet；
 * 逐处重复同一组焦点断言只会得到五份同样的证据。调用点各自的接线由那三张页面
 * 自己的用例覆盖（`getByRole('dialog')` 的正反向断言）。
 */

import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';

import { ConfirmSheet } from './ConfirmSheet';

/** 渲染一张带三个可聚焦元素的确认单（首/中/尾，够验环绕）。 */
function renderSheet(onDismiss?: () => void) {
  const view = render(
    <ConfirmSheet labelledBy="sheet-title" {...(onDismiss === undefined ? {} : { onDismiss })}>
      <h2 id="sheet-title">删除这条记录？</h2>
      <p>删除后咨询和检索都不会再用到它</p>
      <div className="button-row">
        <button type="button">取消</button>
        <button type="button">删除</button>
      </div>
    </ConfirmSheet>,
  );
  const sheet = view.container.querySelector('.confirm-sheet') as HTMLElement;
  const [first, last] = Array.from(sheet.querySelectorAll('button'));
  if (first === undefined || last === undefined) throw new Error('确认单里没有找到两个按钮');
  return { ...view, sheet, first, last };
}

/**
 * 模拟浏览器的一次 Tab 按键。
 *
 * 为什么需要模拟而不是直接 fireEvent.keyDown：jsdom 不实现 Tab 的默认焦点移动
 * （它没有焦点顺序的布局概念），只派发事件。若直接派发一个 keydown 就断言焦点变了，
 * 断言的是「我的处理器有没有手动搬焦点」，而不是「真实浏览器里会不会逃出单外」。
 * 这里显式补上浏览器默认行为那一半（未被 preventDefault 时移到文档序的下一个
 * 可聚焦元素），于是「陷阱」的判据变成与真机同义：默认移动被拦下且焦点仍在单内。
 *
 * @param from 当前焦点元素（调用方保证它是 document.activeElement）
 * @param shift 是否 Shift+Tab
 */
function pressTab(from: HTMLElement, shift = false): void {
  const notPrevented = fireEvent.keyDown(from, { key: 'Tab', shiftKey: shift, bubbles: true, cancelable: true });
  if (!notPrevented) return; // 处理器已 preventDefault 并自行搬焦点：浏览器不会再移动

  // 浏览器默认行为：按 Tab 序移动。这里用文档序近似，并排除 inert 子树——
  // 真实浏览器里 inert 元素不在 Tab 序内。本组件对单之外的兄弟施加了 inert，
  // 因此背景不再参与模拟的 Tab 序；若陷阱失效，越界仍会把焦点交给 body
  // （真实逃逸形态之一），判据与真机同义。
  const focusables = Array.from(
    document.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((el) => el.closest('[inert]') === null);
  const index = focusables.indexOf(from);
  const next = focusables[shift ? index - 1 : index + 1];
  // 越界即浏览器把焦点交给浏览器界面（body）——真实逃逸形态。
  if (next === undefined) {
    document.body.focus();
    return;
  }
  next.focus();
}

describe('确认单 — 模态可达性', () => {
  it('P0 挂载后焦点进入单内（不留在背景）', () => {
    const { sheet, first } = renderSheet();

    expect(sheet.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toBe(first);
  });

  it('P0 aria-modal 如实声称模态，且 role="dialog" 可查询（现有 8 处断言依赖它）', () => {
    renderSheet();

    const sheet = screen.getByRole('dialog');
    expect(sheet.getAttribute('aria-modal')).toBe('true');
    expect(sheet.getAttribute('aria-labelledby')).toBe('sheet-title');
  });

  it('P0 焦点陷阱：连续 6 次 Tab 全部留在单内（含两次环绕）', () => {
    const { sheet, first, last } = renderSheet();

    const trail: string[] = [document.activeElement?.textContent ?? ''];
    expect(document.activeElement).toBe(first);

    for (let step = 0; step < 6; step += 1) {
      const from = document.activeElement as HTMLElement;
      pressTab(from);
      const active = document.activeElement;
      // 每一步都断言「仍在单内」——一次逃出就失败，而不是只看最后一步。
      expect(sheet.contains(active), `第 ${String(step + 1)} 步 Tab 后焦点逃出了确认单`).toBe(true);
      trail.push(active?.textContent ?? '');
    }

    // 逐步骤核对序列：2→3→(环绕)1→2→3→(环绕)1
    expect(trail).toEqual(['取消', '删除', '取消', '删除', '取消', '删除', '取消']);
    expect(last).toBeDefined();
  });

  it('P0 焦点陷阱：Shift+Tab 从首个元素环绕到单内最后一个（不逃到背景）', () => {
    const { sheet, first, last } = renderSheet();

    expect(document.activeElement).toBe(first);
    pressTab(first, true);

    expect(document.activeElement).toBe(last);
    expect(sheet.contains(document.activeElement)).toBe(true);
  });

  it('P0 Esc 关闭：调用 onDismiss（且不让浏览器继续冒泡处理）', () => {
    const onDismiss = vi.fn();
    const { sheet } = renderSheet(onDismiss);

    const notPrevented = fireEvent.keyDown(sheet, { key: 'Escape', bubbles: true, cancelable: true });

    expect(onDismiss).toHaveBeenCalledTimes(1);
    // 返回 false = preventDefault 已被调用（Esc 不该再触发别的默认行为）。
    expect(notPrevented).toBe(false);
  });

  it('P0 遮罩层存在、对读屏隐藏、点击即关闭', () => {
    const onDismiss = vi.fn();
    const { container } = renderSheet(onDismiss);

    const scrim = container.querySelector('.confirm-sheet-scrim');
    expect(scrim).not.toBeNull();
    expect(scrim?.getAttribute('aria-hidden')).toBe('true');

    fireEvent.click(scrim as Element);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('P0 初始焦点带 preventScroll（防御性选项，靠本用例防误删）', () => {
    // jsdom 不做布局、不实现滚动，因此这里无法断言滚动行为，只能断言「调用时带了
    // preventScroll 选项」。别把这条用例读成「滚动行为已被验证」——那个结论由浏览器探针给，
    // 且探针的当前结论是「没有可复现的回归证明它必需」。
    const focusSpy = vi.spyOn(HTMLElement.prototype, 'focus');
    renderSheet();

    const withPreventScroll = focusSpy.mock.calls.filter(
      (call) => (call[0] as FocusOptions | undefined)?.preventScroll === true,
    );
    expect(withPreventScroll.length).toBeGreaterThan(0);
    focusSpy.mockRestore();
  });

  it('P0 焦点归还：卸载后回到打开前的元素（连续操作不丢键盘位置）', () => {
    const trigger = document.createElement('button');
    trigger.textContent = '退出登录';
    document.body.append(trigger);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    const view = render(
      <ConfirmSheet labelledBy="t2">
        <h2 id="t2">退出登录？</h2>
        <button type="button">取消</button>
      </ConfirmSheet>,
    );
    expect(document.activeElement).not.toBe(trigger);

    view.unmount();
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });

  it('P0 打开时给单之外的兄弟加 inert（界面只能由单的后代操作）', () => {
    /**
     * 判别性：这条用例专抓「背景仍可操作」这个 P1。
     * 实测失效形态（改动前，真实 Chromium）：背景「我提过的事」链接可聚焦，
     * 且焦点落在它上面时按真实 Enter 会把 /settings 变成 /settings/memory——
     * 焦点陷阱挂在单自身 keydown 上，「焦点已经在背景」是它的结构性盲区。
     *
     * 用 setAttribute 而非 el.inert：jsdom 无 inert 属性反射
     * （el.inert = true 之后 hasAttribute('inert') 仍为 false），
     * 写属性赋值会让这条断言看不到任何变化。
     */
    const background = document.createElement('a');
    background.href = '/settings/memory';
    background.textContent = '我提过的事';
    document.body.append(background);

    const { container, sheet, unmount } = renderSheet();

    expect(background.hasAttribute('inert')).toBe(true);
    // 单自身与遮罩不被 inert：单被 inert 就没法操作，遮罩被 inert 则 tap 关闭失效。
    expect(sheet.hasAttribute('inert')).toBe(false);
    expect(container.querySelector('.confirm-sheet-scrim')?.hasAttribute('inert')).toBe(false);

    unmount();
    background.remove();
  });

  it('P0 关闭后不残留 inert（四条关闭路径共用同一个卸载恢复点）', () => {
    const background = document.createElement('div');
    background.textContent = '背景内容';
    document.body.append(background);

    const view = render(
      <ConfirmSheet labelledBy="t3">
        <h2 id="t3">退出登录？</h2>
        <button type="button">取消</button>
      </ConfirmSheet>,
    );
    expect(background.hasAttribute('inert')).toBe(true);

    view.unmount();

    // Esc / 遮罩点击 / 取消 / 确认 四条路径都经父级卸载走到同一个 cleanup，
    // 因此这里测的是那个恢复点；四条路径各自的触发由下面的用例与页面用例覆盖。
    expect(background.hasAttribute('inert')).toBe(false);
    expect(document.querySelectorAll('[inert]').length).toBe(0);
    background.remove();
  });

  it('P0 恢复只摘自己加的 inert：原本就 inert 的元素不被误摘', () => {
    // 页面上可能已有别处（未来的嵌套模态、或页面自身的 inert 区块）。
    // 我们的恢复若不区分归属，会把它一起摘掉——那是破坏别人的状态。
    const preInert = document.createElement('div');
    preInert.setAttribute('inert', '');
    preInert.textContent = '本来就不该被操作';
    document.body.append(preInert);

    const view = render(
      <ConfirmSheet labelledBy="t4">
        <h2 id="t4">退出登录？</h2>
        <button type="button">取消</button>
      </ConfirmSheet>,
    );
    expect(preInert.hasAttribute('inert')).toBe(true);

    view.unmount();

    expect(preInert.hasAttribute('inert')).toBe(true);
    preInert.remove();
  });

  it('P0 背景 re-render 不会抹掉 inert（React 19 的 inert 是它认识的 prop）', async () => {
    /**
     * 判别性：inert 是命令式加在兄弟元素上的，不在 React 的 props 里。
     * 风险是 React 19 已把 `inert` 作为正式 prop——若它在 re-render 时按「本次没有 inert
     * prop」去写 `inert={false}`，我们加的属性会被抹掉，模态就在不知不觉间失效。
     * 用一次真实的背景状态更新来验：re-render 后 inert 必须还在。
     */
    function Host(): React.ReactElement {
      const [tick, setTick] = useState(0);
      return (
        <div>
          <button type="button" onClick={() => setTick((n) => n + 1)}>
            背景按钮 {tick}
          </button>
          <ConfirmSheet labelledBy="t5">
            <h2 id="t5">删除？</h2>
            <button type="button">取消</button>
          </ConfirmSheet>
        </div>
      );
    }

    const { container } = render(<Host />);
    const bg = container.querySelector('div > button');
    expect(bg?.hasAttribute('inert')).toBe(true);

    // 触发一次真实 re-render（用 act 包住状态更新）
    await act(async () => {
      fireEvent.click(within(container).getByText(/背景按钮/));
    });

    expect(bg?.hasAttribute('inert')).toBe(true);
  });
});
