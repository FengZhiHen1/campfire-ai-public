/**
 * 模块: shared/ui/ConfirmSheet
 * 职责: 底部确认单的模态可达性——遮罩、初始焦点、焦点陷阱、Esc 关闭与焦点归还
 * 数据来源:
 *   - docs/design/components.html: MUST — `.confirm-sheet` 的契约结构（`<dialog>` + `::backdrop`）
 *   - docs/design/pages/档案页.md: MUST — 第 45 行（背景遮罩、tap 关闭、滑入 240ms）
 *   - docs/design/pages/设置页.md: MUST — 状态覆盖表（登出失败不自动关闭，保留操作上下文）
 * 边界:
 *   - 依赖: react
 *   - 被依赖: features/{accounts,profile,memory}/view 的三张页面（五处确认单）
 * 禁止行为:
 *   - 禁止在陷阱里吞掉 Tab 的默认行为（只在两端 preventDefault，否则单内向前导航失效）
 *   - 禁止让 Esc 与遮罩点击走两条不同的状态路径（都走 onDismiss）
 *   - 禁止把遮罩做成可被读屏读到的内容（它是纯视觉遮挡层）
 *
 * 为什么不用原生 `dialog.showModal()`（本组件存在的理由）
 *
 * showModal() 把元素放进 top layer，而 top layer 元素的包含块是视口，不再受
 * 祖先 .device 的 transform 约束——那条 transform 是 global.css 的承重属性
 * （DESIGN.md 第 32 行明文：移除它 .tab-bar 与 .confirm-sheet 立刻逃到视口）。
 * 实测（1280×1000，设置页登出确认单，真实产物）：原地 div 的 rect 是
 * left 445 / width 390（与屏幕内容区 390 对齐），showModal 后变成
 * left 400 / width 480——横向偏移 45px 并甩出手机外壳；窄视口 390 下两者恰好相同
 * （视口宽等于屏幕宽），因此这个缺陷只在宽视口暴露。
 * 消融证明它是因果而非相关：在现状 div 上注入 .device{transform:none}，得到的 rect
 * 与 showModal 臂逐字段相同，撤销注入后精确回到原值。
 * 另：jsdom（本项目前端测试环境）未实现 showModal/close/show，全部为 undefined。
 * 保留 div（在包含块内），在此手工补上模态语义。
 */

import { useEffect, useRef, type ReactNode } from 'react';

/**
 * 单内可聚焦元素的选择器。
 *
 * `[tabindex="-1"]` 被排除：它是「可编程聚焦但不在 Tab 序」的元素（本组件自身的
 * 容器就用它做初始焦点的兜底），把它算进循环会让 Tab 停在一个不该停的位置。
 */
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'textarea:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/** 确认单 props。 */
export interface ConfirmSheetProps {
  /** 标题元素 id（`aria-labelledby` 的指向）。 */
  labelledBy: string;
  /** 使用者主动关闭（Esc 或点遮罩）。省略时不注册这两条关闭路径。 */
  onDismiss?: () => void;
  /** 单内内容（标题、说明、操作按钮行）。 */
  children: ReactNode;
}

/**
 * 把「单之外的一切」标记为 inert，返回本次真正加过 inert 的元素（用于精确恢复）。
 *
 * 为什么必须遍历祖先链的兄弟而不是只标记 body 的直接子节点：本组件没有 portal，
 * 单渲染在 React 树原位（页面容器深处），body 的直接子里包含其它页面结构；
 * 只处理 body 一层会让「单所在子树之外的兄弟」漏网。
 * 做法是自单向上逐级走到 body，每一级把「不在路径上」的兄弟标 inert。
 *
 * 为什么按 DOM 结构遍历而不是靠盒几何（getBoundingClientRect / offsetParent）：
 * 窄视口下 `.device`、`.device-screen` 是 `display: contents`（global.css 第 118 行），
 * 不生成盒子，一切几何量都是 0。靠几何找兄弟在窄视口会全部落空——
 * 而窄视口恰恰是没有外壳、最需要 inert 兜底的形态。
 *
 * 为什么用 setAttribute('inert','') 而不是 `el.inert = true`：
 * jsdom（本项目前端测试环境）没有 inert 的属性反射——实测
 * `el.inert = true` 之后 `hasAttribute('inert')` 仍为 false，于是回归断言看不到任何变化；
 * 而 `setAttribute('inert','')` / `removeAttribute('inert')` 在 jsdom 下可观测。
 * 两者在真实浏览器里等价（属性都在），因此选可测试的那一种。
 *
 * 为什么跳过 scrim：inert 会禁用指针事件，遮罩是「点击关闭」的落点，
 * 把它一起 inert 掉会让 tap 关闭失效。
 *
 * 已知边界：本函数是快照式的——只在挂载那一刻遍历一次 DOM。
 * 因此挂载之后才加进 body 的可聚焦元素不在这次遍历里，不受 inert 保护。
 * 实测（复验探针，真实 Chromium）：迟到的可聚焦元素 lateIsInert=false、
 * 可被程序化聚焦、真实 Enter 会把 /settings 导航到 /settings/memory（单仍开着）。
 * 但当前不可由使用者触发：在五条真实流程（记忆页删除、档案页条目删除、
 * 对象菜单就地换单、登出失败、记忆页空转）上用 MutationObserver 实测逃逸 0 次，
 * 且本产品无 portal（已 grep 确认）。
 * 将来若出现 portal 化 toast、嵌套模态、或任何「模态打开期间动态挂载背景可聚焦元素」
 * 的形态，这里必须升级：用 MutationObserver 在新节点上重施 inert，
 * 或把焦点陷阱的监听器移到 document 级（那才能覆盖「焦点已在单外」）。
 *
 * @param sheet 确认单根元素
 * @param skip 不参与 inert 的元素（遮罩层）
 * @returns 本次真正被加上 inert 的元素列表（原本已 inert 的不计入，恢复时不动它们）
 */
function inertOutside(sheet: HTMLElement, skip: readonly (HTMLElement | null)[]): HTMLElement[] {
  const applied: HTMLElement[] = [];
  let node: HTMLElement | null = sheet;

  while (node !== null && node.parentElement !== null) {
    const parent: HTMLElement = node.parentElement;
    for (const sibling of Array.from(parent.children)) {
      if (sibling === node || !(sibling instanceof HTMLElement)) continue;
      if (skip.includes(sibling)) continue;
      // 原本就 inert 的元素不记入 applied：恢复时不该由我们把它摘掉。
      if (sibling.hasAttribute('inert')) continue;
      sibling.setAttribute('inert', '');
      applied.push(sibling);
    }
    node = parent;
    if (node === document.body) break;
  }

  return applied;
}

/** 恢复：只摘掉本组件加的那些 inert。 */
function restoreInert(applied: readonly HTMLElement[]): void {
  for (const el of applied) {
    // 元素可能已被 React 从 DOM 摘掉；摘掉的无需恢复（也不该报错）。
    if (el.isConnected) el.removeAttribute('inert');
  }
}

/** 单内可聚焦元素（按文档序）。 */
function focusablesIn(sheet: HTMLElement): HTMLElement[] {
  return Array.from(sheet.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
}

/**
 * 处理单内的一次按键。
 *
 * 为什么把 Tab 逻辑放到模块级函数而不是留在组件里：组件本体的规模一旦越过
 * 质量地板的软阈值（80 逻辑行），信号会被淹没在「这个组件是不是太大了」的噪声里；
 * 把这段独立的键盘语义分出去，组件本体回到「装配 + 生命周期」的本职。
 *
 * @param event 键盘事件
 * @param sheet 单根元素
 * @param dismiss 关闭回调；undefined 表示不响应 Esc
 * @returns 无
 */
function handleSheetKeyDown(event: KeyboardEvent, sheet: HTMLElement, dismiss: (() => void) | undefined): void {
  if (event.key === 'Escape') {
    if (dismiss === undefined) return;
    event.preventDefault();
    dismiss();
    return;
  }
  if (event.key !== 'Tab') return;

  const items = focusablesIn(sheet);
  const first = items[0];
  const last = items[items.length - 1];
  // 单内没有可聚焦元素时按住 Tab 不放。这一分支同样只在「事件经过本单」时可达
  // （真实按键下焦点必为单内某元素或单自身），此处把焦点留在单上而不是让默认行为
  // 把焦点交给浏览器界面。
  if (first === undefined || last === undefined) {
    event.preventDefault();
    sheet.focus({ preventScroll: true });
    return;
  }

  const active = document.activeElement;
  if (!sheet.contains(active)) {
    // 这个分支在真实按键路径下不可达。它不是「焦点逃逸的兜底机制」——
    // 事件从 document.activeElement 冒泡，焦点在单外时其传播路径不经过本单
    // （capture 相也不经过），挂在本单上的监听器收不到。实测（jsdom 事件路径）：
    // 焦点在背景、事件从背景元素派发 ⇒ 本监听器触发 0 次；同一探针在焦点位于单内时
    // 触发 1 次（通道 canary），证明「0 次」是路径问题而不是监听器没装上。
    // 唯一可达的情形是把 KeyboardEvent 程序化派发到本单自身——使用者产生不了这种路径。
    //
    // 保留它的理由只剩两条：
    //   1. 防御性：若将来把焦点陷阱的监听器移到 document 级（见 inertOutside 的
    //      「已知边界」——那是覆盖「焦点已在单外」的正确修法），本分支立刻变成
    //      真正生效的那种机制，无需再改逻辑；
    //   2. 成本极低，且删它会让「单外焦点」这个语义在代码里彻底消失。
    //
    // 注意：Shift+Tab 的反向环绕不由本分支提供，而是由下面 event.shiftKey &&
    // active === first 那条分支提供（焦点已经在单内时走的是那条）。
    // 消融实测：把本分支改成死代码后，ConfirmSheet 的 12 条用例（含 Shift+Tab 环绕）
    // 全部仍通过 ⇒ 不能拿「反向环绕靠它」当保留理由。
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
    return;
  }
  if (event.shiftKey && active === first) {
    event.preventDefault();
    last.focus();
    return;
  }
  if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}

/**
 * 渲染底部确认单（契约组件 `.confirm-sheet`）。
 *
 * 前置: labelledBy 指向单内真实存在的元素
 * 后置: 挂载即打开；焦点进入单内首个可聚焦元素；Tab/Shift+Tab 在单内循环；
 *       Esc 与遮罩点击都调用 onDismiss；单之外的兄弟被标记 inert；卸载时恢复并归还焦点
 * 异常: 无
 *
 * 为什么挂载即打开而不是受 open 属性控制：本组件的调用方都是「有 target 才渲染」
 * 的条件渲染，挂载本身就是打开事件；加一层 open 会多一个可与 target 不同步的状态源。
 */
export function ConfirmSheet({ labelledBy, onDismiss, children }: ConfirmSheetProps) {
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const scrimRef = useRef<HTMLDivElement | null>(null);
  // 关闭回调放 ref：把它写进 effect 依赖会让每次父级重渲染都重跑一遍
  // 「聚焦 + 归还焦点」，于是单内已经移动过的焦点被拽回第一个元素。
  const dismissRef = useRef(onDismiss);
  useEffect(() => {
    dismissRef.current = onDismiss;
  }, [onDismiss]);

  useEffect(() => {
    const sheet = sheetRef.current;
    if (sheet === null) return;

    // 焦点归还需要记住打开前的落点：卸载时它可能已被 React 从 DOM 摘掉，
    // 因此这里先做 isConnected 判定再决定是否归还。
    const returnTo = document.activeElement;

    // 让界面只能由单的后代操作（ARIA 1.2 对模态是 MUST，不只是 SHOULD）。
    // 没有这一步时，背景仍可聚焦、且焦点落到背景后按 Enter 真的会导航——
    // 实测（改动前，终局产物）：背景「我提过的事」链接可聚焦，Enter 使
    // /settings 变成 /settings/memory。焦点陷阱挂在单自身的 keydown 上，
    // 「焦点已经在背景」是它的结构性盲区，补齐靠 inert。
    const inerted = inertOutside(sheet, [scrimRef.current]);

    const [firstFocusable] = focusablesIn(sheet);
    // preventScroll 是防御性选项，不是对某个已复现回归的修复（四臂对照：吞掉它滚动量同为 0；
    // 那 81px 来自 Playwright 点击前的 scroll-into-view，改前产物同样复现）。
    // 保留理由：本元素 position:fixed 钉在外壳底部，滚动不会让更多内容进入视野。
    (firstFocusable ?? sheet).focus({ preventScroll: true });

    // 用 ref 里的最新回调，而不是闭包捕获的 onDismiss：否则父级换回调后仍走旧的。
    const onKeyDown = (event: KeyboardEvent): void => {
      handleSheetKeyDown(event, sheet, dismissRef.current);
    };

    sheet.addEventListener('keydown', onKeyDown);
    return () => {
      sheet.removeEventListener('keydown', onKeyDown);
      // 四条关闭路径（Esc / 遮罩点击 / 取消 / 确认）都经由卸载走到这里，
      // 因此这一处恢复就覆盖了全部路径；不残留 inert 由用例与浏览器探针各测一遍。
      restoreInert(inerted);
      if (returnTo instanceof HTMLElement && returnTo.isConnected && !returnTo.hasAttribute('disabled')) {
        returnTo.focus();
      }
    };
  }, []);

  return (
    <>
      {/* 遮罩层：契约 .confirm-sheet::backdrop 的等价物。::backdrop 只在 top layer
          元素上生成盒子，本实现不是 top layer（见文件头说明），因此用一个真实元素承担。
          aria-hidden：它是纯视觉遮挡，读屏不应读它。
          不被 inert：inert 会禁用指针事件，把它一起 inert 掉会让 tap 关闭失效。 */}
      <div
        aria-hidden="true"
        className="confirm-sheet-scrim"
        onClick={onDismiss === undefined ? undefined : onDismiss}
        ref={scrimRef}
      />
      <div
        aria-labelledby={labelledBy}
        aria-modal="true"
        className="confirm-sheet"
        ref={sheetRef}
        role="dialog"
        tabIndex={-1}
      >
        {children}
      </div>
    </>
  );
}
