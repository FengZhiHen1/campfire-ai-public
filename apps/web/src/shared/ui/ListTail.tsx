/**
 * 模块: shared/ui/ListTail
 * 职责: 列表尾部的触底分页基元——自动加载（IntersectionObserver）与降级按钮
 * 数据来源:
 *   - docs/design/pages/记忆页.md: MUST — 第 28 行（触底自动分页、12px 呼吸点）
 *   - docs/design/pages/案例库浏览页.md: MUST — 第 23 行（触底分页加载，同会话列表模式）
 * 边界:
 *   - 依赖: shared/styles/components.css 的契约类名（.flame-dot.sm / .btn-quiet）
 *   - 被依赖: features/memory/view、features/library/view
 * 禁止行为:
 *   - 禁止页内自造第二套分页尾部（形态的唯一来源在这里）
 *   - 禁止在缺 IntersectionObserver 时静默失去分页能力（必须给显式入口）
 */

import { useEffect, useRef } from 'react';

/** 触底分页尾部 props。 */
export interface ListTailProps {
  /** 正在加载下一页；为真时显示呼吸点或禁用按钮。 */
  loading: boolean;
  /** 触底或点击时的加载动作。 */
  onReachEnd(): Promise<void>;
  /** 加载中文案（各页措辞不同，由调用方给）。 */
  loadingLabel: string;
  /** 降级按钮文案（缺少 IntersectionObserver 时使用）。 */
  loadMoreLabel: string;
}

/**
 * 渲染列表尾部分页。
 *
 * 为什么在 `IntersectionObserver` 不可用时给一个显式按钮：自动分页在缺少该 API 的
 * 环境里（jsdom、以及部分老浏览器）会静默失去「还有下一页」的能力——使用者看到的
 * 是一条没有尽头的短列表，而数据其实还有。给按钮是让这份能力在降级环境下仍然存在，
 * 不是给设计加装饰；有 Observer 时按钮不渲染（设计只写呼吸点）。
 *
 * 前置: 调用方只在「还有下一页」时渲染它
 * 后置: 有 Observer 时挂哨兵自动触发；无 Observer 时渲染按钮
 * 异常: 无（`onReachEnd` 的异常由调用方处置）
 */
export function ListTail({ loading, onReachEnd, loadingLabel, loadMoreLabel }: ListTailProps) {
  const sentinel = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = sentinel.current;
    if (node === null || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void onReachEnd();
    });
    observer.observe(node);
    return () => {
      observer.disconnect();
    };
  }, [onReachEnd]);

  if (typeof IntersectionObserver === 'undefined') {
    return (
      <div className="list-tail">
        <button
          className="btn btn-quiet"
          disabled={loading}
          onClick={() => {
            void onReachEnd();
          }}
          type="button"
        >
          {loading ? loadingLabel : loadMoreLabel}
        </button>
      </div>
    );
  }

  return (
    <div className="list-tail" ref={sentinel}>
      {loading && (
        <span className="meta">
          <span className="flame-dot sm" aria-hidden="true" /> {loadingLabel}
        </span>
      )}
    </div>
  );
}
