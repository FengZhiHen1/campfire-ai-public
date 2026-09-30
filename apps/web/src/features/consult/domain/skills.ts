/**
 * 模块: features/consult/domain/skills
 * 职责: 技能选择器可选项的目录（技能标识 ↔ 中文显示名）
 * 数据来源:
 *   - docs/技术设计/面/consult/skills/{daily-consulting,emergency-consulting,profile-curation}.md: MUST — 三个技能标识
 *   - docs/design/components.html: MUST — 对话工作面预览的技能 chip 文案（自动/日常咨询/应急咨询/档案整理）
 * 边界:
 *   - 依赖: features/consult/domain/types（SkillSummary）
 *   - 被依赖: viewModel 与端口实现
 * 禁止行为:
 *   - 禁止把 onboarding 放进可选项（它只由服务端程序注入，技能设计第 4 节）
 *   - 禁止在此发明第四个技能（技能清单的权威在服务端 skill 目录，未知标识不猜测）
 *
 * 为什么目录在本层而不是从端点取：HTTP/SSE 契约第 3～6 节定义了会话、发消息、订阅、
 * 应急与引导跳过五组端点，没有技能目录端点；而技能选择器（RQ-CON-08）必须能列出
 * 可选项。这里按已确认的三个技能标识与页面设计的中文名构成目录，作为目录端点的替身点，
 * 已在交付报告「未决问题」节登记（端点落地后此处改为远端读取，选择器无需改动）。
 */

import type { SkillSummary } from './types';

/** 应急技能标识；用于「首字超 10 秒」的降级提示判定与技术设计第 6 节的入口语义。 */
export const EMERGENCY_SKILL_ID = 'emergency-consulting';

/** 日常技能标识；"自动"之外最常用的选择，列表页「开始新的日常咨询」不预选（缺省即自动）。 */
export const DAILY_SKILL_ID = 'daily-consulting';

/** 可选技能目录（顺序即 chip 顺序）。 */
export const SKILL_CATALOG: readonly SkillSummary[] = [
  { id: DAILY_SKILL_ID, label: '日常咨询' },
  { id: EMERGENCY_SKILL_ID, label: '应急咨询' },
  { id: 'profile-curation', label: '档案整理' },
];

/** 按标识取显示名；未知标识返回标识本身（不猜测、不隐藏）。 */
export function skillLabel(catalog: readonly SkillSummary[], id: string | null): string | null {
  if (id === null) return null;
  const found = catalog.find((skill) => skill.id === id);
  return found === undefined ? id : found.label;
}
