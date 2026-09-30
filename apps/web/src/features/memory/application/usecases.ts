/**
 * 模块: features/memory/application/usecases
 * 职责: 记忆页用例——时间线读取与触底分页、删除、纠正（保留两步语义）
 * 数据来源:
 *   - docs/技术设计/面/profile/记忆面HTTP契约.md: MUST — 第 3、4、5 节
 *   - docs/design/pages/记忆页.md: MUST — 状态覆盖表（中间态、写入失败保留已填内容）
 * 边界:
 *   - 依赖: features/memory/domain、features/memory/application/ports
 *   - 被依赖: features/memory 的 viewModel
 * 禁止行为:
 *   - 禁止在此持有 UI 状态（busy/error 归 viewModel）
 *   - 禁止把纠正两步的结果压成一个布尔（「撤下了但没写成」必须可表达）
 */

import type { DeleteMemoryEpisodeResponse, MemoryEpisode } from '../../../shared/types/memory';
import { type CorrectionOutcome, correctionOutcome } from '../domain/failures';
import { type CorrectionDraft, validateCorrectionDraft } from '../domain/formValidation';
import type { MemoryPort } from './ports';

/** 一页时间线。 */
export interface EpisodePage {
  items: MemoryEpisode[];
  nextCursor: string | null;
}

/** 读取时间线（第一页或下一页）。 */
export class LoadEpisodesUseCase {
  constructor(private readonly port: MemoryPort) {}

  /**
   * 前置: 无
   * 后置: 返回本页条目与下一页游标；查询为空时返回空数组（空不是失败）
   * @throws 端口异常原样抛出（503 图库不可用由调用方分类成「暂时无法读取」）
   */
  async execute(cursor?: string): Promise<EpisodePage> {
    const response = await this.port.listEpisodes(cursor === undefined ? undefined : { cursor });
    return { items: response.items, nextCursor: response.next_cursor };
  }
}

/** 删除一条记忆。 */
export class DeleteEpisodeUseCase {
  constructor(private readonly port: MemoryPort) {}

  /**
   * 前置: episodeKey 非空（来自列表，不由使用者输入）
   * 后置: 成功后该记忆在两条读路径都不再返回；重复删除幂等（`newly_deleted: false`）
   * @throws 端口异常原样抛出
   */
  async execute(episodeKey: string): Promise<DeleteMemoryEpisodeResponse> {
    return this.port.deleteEpisode(episodeKey);
  }
}

/** 纠正一条记忆。 */
export class CorrectEpisodeUseCase {
  constructor(private readonly port: MemoryPort) {}

  /**
   * 前置: 草稿通过校验（内容非空且与原内容不同、发生时间可解析）
   * 后置: 返回判别联合——`written`（新记忆已写入）或 `superseded-only`（只撤下了旧的）
   * @throws CorrectionValidationError（未发起请求）；端口异常原样抛出
   */
  async execute(episodeKey: string, draft: CorrectionDraft, originalContent: string): Promise<CorrectionOutcome> {
    const occurredAt = validateCorrectionDraft(draft, originalContent);
    const response = await this.port.correctEpisode(episodeKey, { occurred_at: occurredAt, content: draft.content });
    return correctionOutcome(response);
  }
}
