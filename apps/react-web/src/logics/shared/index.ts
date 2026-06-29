/**
 * Shared 域公共入口。
 *
 * View 层通过此入口消费共享 Hook、工具函数与组件，
 * 禁止直接引用 shared/hooks/、shared/utils/、shared/components/ 下的内部文件。
 */

export { useHomePage } from './hooks/useHomePage';
export { formatRelativeTime, formatDateStr } from './utils/timeFormat';
export { default as MarkdownRenderer } from './components/MarkdownRenderer';
