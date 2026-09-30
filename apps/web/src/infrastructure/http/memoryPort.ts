/**
 * 模块: infrastructure/http/memoryPort
 * 职责: 记忆端口的 HTTP 实现——路径、方法与查询参数
 * 数据来源:
 *   - docs/技术设计/面/profile/记忆面HTTP契约.md: MUST — 第 3、4、5 节（路径与载荷）
 *   - docs/项目结构设计.md: MUST — 第 9 节（端口实现在 infrastructure）
 * 边界:
 *   - 依赖: infrastructure/http/client、shared/types/memory
 *   - 被依赖: app/routes 装配后经 props 注入页面
 * 禁止行为:
 *   - 禁止传入账号或分区键（分区取登录态，契约第 2 节）
 *   - 禁止把 episode_key 直接拼进路径而不转义
 */

import type {
  CorrectMemoryEpisodeRequest,
  CorrectMemoryEpisodeResponse,
  DeleteMemoryEpisodeResponse,
  ListMemoryEpisodesResponse,
} from '../../shared/types/memory';
import type { MemoryPort } from '../../features/memory/application/ports';
import { request } from './client';

/** 把 episode 标识安全地拼进路径。 */
function episodePath(episodeKey: string): string {
  return `/memory/episodes/${encodeURIComponent(episodeKey)}`;
}

/** 记忆端口的 HTTP 实现（记忆面契约第 3～5 节）。 */
export const httpMemoryPort: MemoryPort = {
  listEpisodes: (options) => {
    const cursor = options?.cursor;
    return request<ListMemoryEpisodesResponse>(
      cursor === undefined || cursor === '' ? '/memory/episodes' : `/memory/episodes?cursor=${encodeURIComponent(cursor)}`,
    );
  },

  deleteEpisode: (episodeKey: string) =>
    request<DeleteMemoryEpisodeResponse>(episodePath(episodeKey), { method: 'DELETE' }),

  correctEpisode: (episodeKey: string, body: CorrectMemoryEpisodeRequest) =>
    request<CorrectMemoryEpisodeResponse>(`${episodePath(episodeKey)}/correct`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};
