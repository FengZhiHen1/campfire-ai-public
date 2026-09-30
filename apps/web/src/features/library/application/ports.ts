/**
 * 模块: features/library/application/ports
 * 职责: 案例与资料浏览/检索的端口声明（HTTP 实现归 infrastructure）
 * 数据来源:
 *   - docs/技术设计/面/profile/资料库面HTTP契约.md: MUST — 第 3、4、5 节
 *   - docs/项目结构设计.md: MUST — 第 9 节（application 不导入框架与 HTTP 库）
 * 边界:
 *   - 依赖: shared/types/library
 *   - 被依赖: features/library 的用例
 * 禁止行为:
 *   - 禁止定义写端点载荷（本面只有读端点，契约第 1 节）
 *   - 禁止 import fetch、react 或任何框架模块
 */

import type { GetLibraryItemResponse, LibraryKind, ListLibraryItemsResponse } from '../../../shared/types/library';

/**
 * 资料库端口：契约第 3、4、5 节的端点。
 *
 * 只有两个方法，因为本面只有读端点（`RQ-KB-03`/`AC-29`：导入与审核只能经应用内 CLI）。
 * 展开内容随列表一并返回（契约第 4 节：一次只展开一条），因此不需要第三个「取详情」方法
 * ——`expanded` 的语义已经由 `listItems` 的 `expand` 参数承担。
 */
export interface LibraryPort {
  /** 浏览/检索；`expand` 命中的那一条额外带 narrative 与 cards。 */
  listItems(params: {
    library: LibraryKind;
    query: string;
    cursor?: string;
    /** 一次只展开一条（页面是单条就地展开）。 */
    expand?: string;
  }): Promise<ListLibraryItemsResponse>;
  /** deep-link 的单条查询（契约第 5 节）。 */
  getItem(itemId: string): Promise<GetLibraryItemResponse>;
}
