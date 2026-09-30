/**
 * 模块: shared/types/memory
 * 职责: 记忆面 HTTP 载荷的线格式类型——episode 时间线、删除与纠正
 * 数据来源:
 *   - docs/技术设计/面/profile/记忆面HTTP契约.md: MUST — 第 3、4、5 节
 *   - docs/技术设计/technical-details/通用记忆.md: MUST — 第 7 节删除账本与原因词表
 * 边界:
 *   - 依赖: 无
 *   - 被依赖: features/memory 的 domain 与 infrastructure
 * 禁止行为:
 *   - 禁止在本文件暴露派生事实与 derived_uuids（记忆面契约第 8 节：不向前端暴露）
 *   - 禁止让调用方传入分区键（group_id 取登录态，见记忆面契约第 2 节）
 */

/**
 * 删除账本的原因词表。
 * 形状见记忆面契约第 4 节与通用记忆第 7 节（词表落 CHECK 约束，迁移 760b797c8bab）。
 */
export type MemoryDeletionReason = 'user_request' | 'correction' | 'account_deletion';

/**
 * 记忆时间线里的一条 episode 原文。
 * 形状见记忆面契约第 3 节；episode_key 是「列表 → 指认 → 删除」所需稳定标识。
 */
export interface MemoryEpisode {
  episode_key: string;
  occurred_at: string;
  content: string;
  source_session_id: string;
}

/** 时间线响应。形状见记忆面契约第 3 节；已删除与在途记录都不返回。 */
export interface ListMemoryEpisodesResponse {
  items: MemoryEpisode[];
  next_cursor: string | null;
}

/**
 * 删除响应。
 * 形状见记忆面契约第 4 节：reason 如实回报账本里的原原因——幂等命中不改变原记录。
 */
export interface DeleteMemoryEpisodeResponse {
  episode_key: string;
  newly_deleted: boolean;
  reason: MemoryDeletionReason;
}

/** 纠正请求；纠正 = 删旧 + 写新，不是「改」。形状见记忆面契约第 5 节。 */
export interface CorrectMemoryEpisodeRequest {
  occurred_at: string;
  content: string;
}

/**
 * 纠正响应。形状见记忆面契约第 5 节：先撤下旧记忆再写新的，两步失败语义不同，
 * 因此响应必须让调用方知道自己处在哪一步——旧记忆已撤下但新记忆未写入时，
 * 两者都要显式呈现，不得笼统报成功或笼统报失败。
 */
export interface CorrectMemoryEpisodeResponse {
  episode_key: string | null;
  supersedes: string;
  new_episode_written: boolean;
}
