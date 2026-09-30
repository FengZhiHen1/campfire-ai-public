/**
 * 模块: infrastructure/http/libraryPort
 * 职责: 资料库端口的 HTTP 实现——浏览/检索、展开参数与 deep-link 单条查询
 * 数据来源:
 *   - docs/技术设计/面/profile/资料库面HTTP契约.md: MUST — 第 3、4、5 节（路径与查询参数）
 *   - docs/项目结构设计.md: MUST — 第 9 节（端口实现在 infrastructure）
 * 边界:
 *   - 依赖: infrastructure/http/client、shared/types/library
 *   - 被依赖: app/routes 装配后经 props 注入页面
 * 禁止行为:
 *   - 禁止实现写端点（本面只有读端点，契约第 1 节）
 *   - 禁止把条目标识直接拼进路径而不转义
 */

import type { GetLibraryItemResponse, ListLibraryItemsResponse } from '../../shared/types/library';
import type { LibraryPort } from '../../features/library/application/ports';
import { request } from './client';

/** 拼查询串；省略的参数不出现（空检索词是合法的「全量浏览流」，因此 query 照发）。 */
function query(entries: ReadonlyArray<[string, string | undefined]>): string {
  const parts = entries
    .filter((entry): entry is [string, string] => entry[1] !== undefined && entry[1] !== '')
    .map(([key, value]) => `${key}=${encodeURIComponent(value)}`);
  return parts.length === 0 ? '' : `?${parts.join('&')}`;
}

/** 资料库端口的 HTTP 实现（契约第 3、4、5 节）。 */
export const httpLibraryPort: LibraryPort = {
  listItems: (params) =>
    request<ListLibraryItemsResponse>(
      `/library/items${query([
        ['library', params.library],
        // 空词也要发：契约第 3 节的空 query 即全量浏览流；不发也能得到同样的结果，
        // 但显式发出让服务端的行为选择是调用方的意图而不是默认值的巧合。
        ['query', params.query],
        ['cursor', params.cursor],
        ['expand', params.expand],
      ])}`,
    ),

  getItem: (itemId: string) => request<GetLibraryItemResponse>(`/library/items/${encodeURIComponent(itemId)}`),
};
