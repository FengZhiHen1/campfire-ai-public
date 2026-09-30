/**
 * 模块: features/consult/domain/parts
 * 职责: 消息 part 的视图侧契约——注册名与载荷类型（消息 content 的唯一形状来源）
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 5 节（citation 作为 data-* 自定义 part）
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 7 节（消息 part 形状表）
 *   - apps/web/src/app/assistantUi.smoke.test.tsx: MUST — 实测结论：注册名是 message part 类型去掉 `data-` 前缀后的名字
 * 边界:
 *   - 依赖: shared/types/sse（线格式载荷）
 *   - 被依赖: viewModel 的适配器与 history、view 的 part 渲染器
 * 禁止行为:
 *   - 禁止解析正文猜结构（卡片与提问只认事件/part 载荷）
 *   - 禁止在同一 part 名上挂两种载荷形状
 *
 * 两个视图侧命名决定（线格式的 part 类型仍在契约第 7 节，这里只定「送到渲染器的名字」）：
 * 1. `citations`（而非契约示意里的单条 `data-citation`）：契约的 `.citation-block` 是「依据 N 条」
 *    的单块折叠区（对话页设计契约修订 5），逐条渲染会得到 N 个折叠头。线格式里 citation 仍是
 *    逐条 part，聚合发生在适配器与 history 的映射里。
 * 2. `question-record`（而非 `question`）：历史水合的提问是静态已提交记录，与运行中待作答的
 *    提问卡行为不同（禁重复提交），而载荷本身不含「已提交」标记（通用基座第 7.2 节形状里没有
 *    这个字段，本包不得发明）。用两个注册名区分两种呈现，线格式 part 类型两处都是 `question`。
 */

import type { CitationRecord } from '../../../shared/types/sse';

/** 视图侧 part 注册名（`components.data.by_name` 的键）。 */
export const PART_NAME = {
  /** 依据区（聚合多条引用）。 */
  citations: 'citations',
  /** 工具调用指示行。 */
  toolCall: 'tool-call',
  /** 运行中待作答的提问卡。 */
  question: 'question',
  /** 历史水合的静态提问记录。 */
  questionRecord: 'question-record',
  /** 应急行动卡。 */
  actionCard: 'action-card',
} as const;

/** 依据区载荷。 */
export interface CitationsView {
  items: CitationRecord[];
}

/** 工具调用的视图形态（线格式没有状态位：started/finished 是两个事件）。 */
export interface ToolCallView {
  toolName: string;
  /** 运行内唯一调用标识；历史水合的 part 没有它（契约第 7 节只存 tool_name/ok/summary）。 */
  callId: string | null;
  state: 'running' | 'finished';
  /** 结束才有；null = 未结束或载荷未给。 */
  ok: boolean | null;
  summary: string | null;
}
