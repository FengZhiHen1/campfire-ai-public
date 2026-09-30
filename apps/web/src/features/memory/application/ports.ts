/**
 * 模块: features/memory/application/ports
 * 职责: 记忆用例依赖的端口声明（HTTP 实现归 infrastructure）
 * 数据来源:
 *   - docs/技术设计/面/profile/记忆面HTTP契约.md: MUST — 第 3、4、5 节
 *   - docs/项目结构设计.md: MUST — 第 9 节（application 不导入框架与 HTTP 库）
 * 边界:
 *   - 依赖: shared/types/memory
 *   - 被依赖: features/memory 的用例
 * 禁止行为:
 *   - 禁止在此 import fetch、react 或任何框架模块
 *   - 禁止让调用方传入分区键或账号（分区取登录态，契约第 2 节）
 */

import type {
  CorrectMemoryEpisodeRequest,
  CorrectMemoryEpisodeResponse,
  DeleteMemoryEpisodeResponse,
  ListMemoryEpisodesResponse,
} from '../../../shared/types/memory';

/**
 * 记忆端口：记忆面契约第 3～5 节的三个端点。
 *
 * 列表端点还支持 `since/until/query`，但本页刻意不做关键词搜索框（记忆页第 30 行），
 * 因此端口只暴露游标——少一个用不到的参数，就少一份「以为搜索没生效」的误解。
 */
export interface MemoryPort {
  /** 查看时间线；不传游标即第一页。 */
  listEpisodes(options?: { cursor?: string }): Promise<ListMemoryEpisodesResponse>;
  /** 删除一条记忆（写删除账本，不是图库物理删除）。 */
  deleteEpisode(episodeKey: string): Promise<DeleteMemoryEpisodeResponse>;
  /** 纠正 = 删旧 + 写新。 */
  correctEpisode(episodeKey: string, body: CorrectMemoryEpisodeRequest): Promise<CorrectMemoryEpisodeResponse>;
}
