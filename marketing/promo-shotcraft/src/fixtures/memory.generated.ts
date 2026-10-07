// ⚠️ 自动生成,请勿手改 —— 由 verify/memory-episodes.py export 导出。
// 重新生成: uv run python marketing/promo-shotcraft/verify/memory-episodes.py export
//
// 数据来源:**本地 demo 种子数据**。这些条目由 verify/memory-episodes.py write
// 经**产品的真实写入路径**(core.pending_write.enqueue →
// modules.memory.consumer.consume_memory_episode → Graphiti add_episode)落库,
// 其 source 自描述为 `session=fixture-memory-seed` —— 即它们是**演示用种子数据,
// 不是真实使用者的记录**(与 data.generated.ts 的 demo 种子同一口径)。
// 交付文档必须按同一口径登记,不得声称记忆段内容来自真实使用者。
import type {MemoryEpisode} from '../../../../apps/web/src/shared/types/memory';

export const MEMORY_EPISODES: readonly MemoryEpisode[] = [
  {
    episode_key: "REDACTED-SET-VIA-ENV",
    occurred_at: "2026-10-06T14:40:00+00:00",
    content: "现场那种时候我读不进去长句子,希望给我的建议短一点、少一点术语。",
    source_session_id: "fixture-memory-seed",
  },
  {
    episode_key: "REDACTED-SET-VIA-ENV",
    occurred_at: "2026-10-06T01:20:00+00:00",
    content: "我很少跟别人说这些,连我父母都不太清楚我们每天是怎么过的。",
    source_session_id: "fixture-memory-seed",
  },
  {
    episode_key: "REDACTED-SET-VIA-ENV",
    occurred_at: "2026-10-03T13:30:00+00:00",
    content: "晚上他睡着以后才有我自己的时间,我习惯把白天的事记一遍,不然下次又说不上来。",
    source_session_id: "fixture-memory-seed",
  },
];
