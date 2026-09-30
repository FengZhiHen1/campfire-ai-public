/**
 * 模块: features/library/application/usecases
 * 职责: 案例与资料的浏览/检索用例与 deep-link 单条解析
 * 数据来源:
 *   - docs/技术设计/面/profile/资料库面HTTP契约.md: MUST — 第 3、4、5 节
 *   - docs/design/pages/案例库浏览页.md: MUST — 状态覆盖表（空态两句、deep-link 三态）
 * 边界:
 *   - 依赖: shared/types/library、features/library/domain、features/library/application/ports
 *   - 被依赖: features/library 的 viewModel
 * 禁止行为:
 *   - 禁止把 deep-link 的 404 转成错误态（契约第 5 节：按普通进入处理）
 *   - 禁止在此持有 UI 状态
 */

import type { ExpandedLibraryItem, LibraryKind } from '../../../shared/types/library';
import { type DeepLinkOutcome, deepLinkOutcome } from '../domain/deepLink';
import type { LibraryPort } from './ports';

/** 一页结果。 */
export interface LibraryPage {
  library: LibraryKind;
  items: ExpandedLibraryItem[];
  nextCursor: string | null;
}

/** 浏览或检索一页。 */
export class SearchLibraryUseCase {
  constructor(private readonly port: LibraryPort) {}

  /**
   * 前置: query 可以为空串——空检索词即全量浏览流（契约第 3 节）
   * 后置: 返回本页条目与下一页游标；无命中时返回空数组（不是失败）
   * @throws 端口异常原样抛出（503 由调用方分类成「检索暂时不可用」）
   */
  async execute(params: {
    library: LibraryKind;
    query: string;
    cursor?: string;
    expand?: string;
  }): Promise<LibraryPage> {
    const response = await this.port.listItems(params);
    return { library: response.library, items: response.items, nextCursor: response.next_cursor };
  }
}

/** deep-link 单条查询。 */
export class ResolveDeepLinkUseCase {
  constructor(private readonly port: LibraryPort) {}

  /**
   * 前置: itemId 来自 URL 查询串（不由使用者直接输入）
   * 后置: 返回在库 / 已撤下 / 不存在三态之一；已撤下时只带标题
   * @throws 端口异常原样抛出——404（不存在或非法 id）由调用方按普通进入处理，
   *      不在这里转成一个「错误态」，因为按契约它不是错误（第 5 节）
   */
  async execute(itemId: string): Promise<DeepLinkOutcome> {
    return deepLinkOutcome(await this.port.getItem(itemId));
  }
}
