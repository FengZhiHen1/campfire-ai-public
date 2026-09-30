/**
 * 模块: features/library/domain/deepLink
 * 职责: deep-link 三态的判定与检索参数解析——在库 / 已撤下 / 不存在
 * 数据来源:
 *   - docs/技术设计/面/profile/资料库面HTTP契约.md: MUST — 第 5 节（三态与撤下只带标题）
 *   - docs/design/pages/案例库浏览页.md: MUST — 第 17、53 行（定位高亮、撤下卡、非法 id 按普通进入）
 * 边界:
 *   - 依赖: shared/types/library
 *   - 被依赖: features/library 的 viewModel
 * 禁止行为:
 *   - 禁止由前端猜测撤下状态（撤下判定来自服务端，契约第 5 节）
 *   - 禁止在已撤下时显示正文或其他字段（只带标题）
 */

import type { GetLibraryItemResponse, LibraryItem, LibraryKind } from '../../../shared/types/library';

/** 从 URL 查询串解析出的进入方式。 */
export interface DeepLinkRequest {
  /** 要定位的条目标识；没有就是普通进入。 */
  itemId: string | null;
  /** 要落的库别分区（`?section=library`，编排器 2026-09-30 裁决的参数名）。 */
  section: LibraryKind | null;
}

/**
 * 解析进入参数。
 *
 * `section` 的取值用库别原值（`case` / `knowledge`）；写成别名的都当作没给——
 * 不认识的值静默退回默认分区，而不是报错：一个查询参数不该让整页不可用。
 */
export function parseDeepLink(search: string): DeepLinkRequest {
  const params = new URLSearchParams(search);
  const rawItem = params.get('item');
  const rawSection = params.get('section');
  return {
    itemId: rawItem !== null && rawItem.trim() !== '' ? rawItem.trim() : null,
    section: rawSection === 'case' || rawSection === 'knowledge' ? rawSection : null,
  };
}

/**
 * deep-link 的结果。
 *
 * 三态是判别联合而不是「item | null + 布尔」：撤下态要渲染的是另一张卡（只带标题），
 * 用布尔表达时界面就得在渲染里再拼一次条件。
 */
export type DeepLinkOutcome =
  | { kind: 'none' }
  | { kind: 'in-library'; item: LibraryItem }
  | { kind: 'withdrawn'; title: string }
  | { kind: 'missing' };

/**
 * 把单条查询响应判成三态。
 *
 * - `item` 非空 → 在库；
 * - `item` 为空且 `withdrawn` 为真 → 已撤下（只带标题，不带正文与其他字段）；
 * - 其余（含服务端返回 200 空体这种不该发生的情形）→ 按不存在处理，
 *   页面按普通进入，不报错、不留在空页。
 *
 * 前置: 响应来自 `GET /library/items/{item_id}` 且状态码为 200
 * 后置: 返回三态之一，不会返回「既不在库也不知是否撤下」的第四种
 * 异常: 无
 */
export function deepLinkOutcome(response: GetLibraryItemResponse): DeepLinkOutcome {
  if (response.item !== null && response.item !== undefined) {
    return { kind: 'in-library', item: response.item };
  }
  if (response.withdrawn === true) {
    // 标题可能缺失（契约只承诺带标题）；缺失时如实写「这条来源」而不是编一个标题。
    return { kind: 'withdrawn', title: response.title !== undefined && response.title !== '' ? response.title : '这条来源' };
  }
  return { kind: 'missing' };
}
