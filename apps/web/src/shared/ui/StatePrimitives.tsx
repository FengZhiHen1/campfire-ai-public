/**
 * 模块: shared/ui/StatePrimitives
 * 职责: loading / empty / error 三态的契约基元——各页三态形态的唯一来源
 * 数据来源:
 *   - docs/design/DESIGN.md: MUST — 下游消费指引（三态基元是唯一来源，禁止页内自造）
 *   - docs/design/components.html: MUST — .skeleton / .empty-state / .error-card 的类名与结构
 * 边界:
 *   - 依赖: shared/styles/components.css 的契约类名（无框架依赖）
 *   - 被依赖: 各特性的 view 层
 * 禁止行为:
 *   - 禁止页内自造骨架/空/错样式（改形态须走契约修订，改本组件）
 *   - 禁止在基元里塞业务文案判断（文案由调用方传入）
 */

import type { ReactNode } from 'react';

/** 骨架屏 props：行数决定骨架行数量。 */
export interface SkeletonProps {
  /** 骨架行数；至少 1（0 行等于没有告知「正在加载」，与不放骨架等价）。 */
  rows?: number;
}

/**
 * 渲染加载骨架。
 *
 * 前置: rows ≥ 1
 * 后置: 输出 rows 个 .skeleton.row，且整组对辅助技术隐藏（加载语义由调用方的 live region 承担）
 * 异常: 无
 */
export function Skeleton({ rows = 1 }: SkeletonProps) {
  const count = Math.max(1, Math.trunc(rows));
  return (
    <div className="stack" aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        // key 用序号而非内容：骨架行没有身份，且行数恒定不变（不因内容增删重排）。
        <div className="skeleton row" key={`skeleton-${index}`} />
      ))}
    </div>
  );
}

/** 空态 props。 */
export interface EmptyStateProps {
  /** 空态标题（中文），说明「这里为什么没有内容」。 */
  title: string;
  /** 一句说明：内容会如何出现、或下一步可以做什么。 */
  description: string;
  /** 可选的操作（通常是主按钮或链接）。 */
  action?: ReactNode;
}

/**
 * 渲染空态。
 *
 * 前置: title 与 description 非空（空态必须解释自己，而不是留一片白）
 * 后置: 输出 .empty-state 容器、标题、说明与可选操作
 * 异常: 无
 */
export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <strong className="es-title">{title}</strong>
      <p>{description}</p>
      {action}
    </div>
  );
}

/** 错误卡形态：'form' = 表单内错误横幅，追加契约的间距变体 .form-feedback。 */
export type ErrorCardVariant = 'form';

/** 错误卡 props。 */
export interface ErrorCardProps {
  /** 错误标题：说清哪件事没成功（不写「出错了」这类无信息量的句子）。 */
  title: string;
  /** 一句用户可读的原因与可行下一步。 */
  description: string;
  /** 可选操作区（重试、返回等）。 */
  actions?: ReactNode;
  /** 形态；省略即整块错误态。'form' 对应契约里唯一的横幅变体（components.html 的 .form-feedback）。 */
  variant?: ErrorCardVariant;
}

/**
 * 渲染错误卡。
 *
 * 前置: title 与 description 非空
 * 后置: 输出 .error-card 容器（variant='form' 时并带 .form-feedback）；作为告警语义暴露给辅助技术（role="alert"）
 * 异常: 无
 *
 * 为什么带 role="alert"：错误卡是「操作没有成功」的即时告知，屏幕阅读器用户
 * 若只在视觉上看到红色边框，会以为提交仍在进行。
 *
 * 为什么把变体做成参数而不是由页面拼类名：契约只为「表单内横幅」定义了间距变体，
 * 形态归组件，页面就不必知道变体的类名（也避免下一处表单各拼各的）。
 */
export function ErrorCard({ title, description, actions, variant }: ErrorCardProps) {
  const className = variant === 'form' ? 'error-card form-feedback' : 'error-card';
  return (
    <div className={className} role="alert">
      <strong className="ec-title">{title}</strong>
      <p>{description}</p>
      {actions}
    </div>
  );
}
