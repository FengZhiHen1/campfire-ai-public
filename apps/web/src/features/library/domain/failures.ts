/**
 * 模块: features/library/domain/failures
 * 职责: 资料库面失败的分类与文案——「检索暂时不可用」不得伪装成「没有找到相关内容」
 * 数据来源:
 *   - docs/技术设计/面/profile/资料库面HTTP契约.md: MUST — 第 2 节错误码、第 6 节失败语义
 *   - docs/design/pages/案例库浏览页.md: MUST — 第 41、49 行（检索失败语义、空态两句）
 * 边界:
 *   - 依赖: 无（只收状态码，不 import 传输实现）
 *   - 被依赖: features/library 的 viewModel 与 view
 * 禁止行为:
 *   - 禁止把 503 呈现成「没有找到相关内容」
 *   - 禁止为「库为空」与「无命中」编造同一句文案（前者是准备中，后者是换个说法）
 */

/** 资料库面失败的分类。 */
export type LibraryFailure =
  | { kind: 'unauthorized' }
  | { kind: 'invalid-payload' }
  | { kind: 'search-unavailable' }
  | { kind: 'unknown' };

/** 从任意异常对象里取 HTTP 状态码；取不到返回 null。 */
function statusOf(error: unknown): number | null {
  if (typeof error !== 'object' || error === null) return null;
  const status = (error as { status?: unknown }).status;
  return typeof status === 'number' ? status : null;
}

/** 按 HTTP 状态码分类（404 不在此列：deep-link 目标不存在按普通进入处理）。 */
export function classifyLibraryFailure(status: number): LibraryFailure {
  switch (status) {
    case 401:
      return { kind: 'unauthorized' };
    case 422:
      return { kind: 'invalid-payload' };
    case 503:
      return { kind: 'search-unavailable' };
    default:
      return { kind: 'unknown' };
  }
}

/** 把任意异常分类成资料库面失败。 */
export function failureFromError(error: unknown): LibraryFailure {
  return classifyLibraryFailure(statusOf(error) ?? 0);
}

/**
 * 失败对应的界面标题。
 *
 * 检索失败与空结果必须可区分（契约第 6 节）：这里给的是「检索暂时不可用」，
 * 而空结果是另一条路径（`emptyStateKind`）。
 */
export function libraryFailureTitle(failure: LibraryFailure): string {
  switch (failure.kind) {
    case 'unauthorized':
      return '登录状态已失效';
    case 'invalid-payload':
      return '这次检索的条件不合法';
    case 'search-unavailable':
      return '检索暂时不可用';
    case 'unknown':
      return '检索暂时不可用';
  }
}

/** 失败对应的说明与下一步。 */
export function libraryFailureDescription(failure: LibraryFailure): string {
  switch (failure.kind) {
    case 'unauthorized':
      return '请重新登录后再试。';
    case 'invalid-payload':
      return '请调整检索条件后重试。';
    case 'search-unavailable':
      return '这次没有取到结果，但这不等于没有内容；请稍后重试。';
    case 'unknown':
      return '这次没有取到结果，但这不等于没有内容；请稍后重试。';
  }
}

/** 空态的种类。与失败分开：两者都是「没有条目」，但原因与下一步不同。 */
export type EmptyStateKind = 'no-results' | 'library-not-ready';

/**
 * 判定该显示哪一种空态。
 *
 * 判据是「有没有检索词」而不是条目数之外的东西：
 * - 有检索词却没有命中 → 「没有找到相关内容」+ 换个说法（口语化措辞的引导）；
 * - 没有检索词（全量浏览流为空）→ 「案例库还在准备中」——一期两库在录入前为空，
 *   如实呈现准备中，不放假数据（`EVID-F`）。
 *
 * 为什么不做成布尔：这两句的下一步完全不同，压成一个布尔后界面只能再猜一次。
 */
export function emptyStateKind(query: string): EmptyStateKind {
  return query.trim() === '' ? 'library-not-ready' : 'no-results';
}
