/**
 * 模块: features/consult/view/consultRoutes
 * 职责: 咨询面的跳转协议——对话页路由参数与外部 deep-link 的唯一构造点
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 4.1 节（三条路由）
 *   - docs/design/pages/对话页.md: MUST — 契约修订 5（依据条目跳 /cases?item=）
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 5 节（应急提交后 navigate 到对话页）
 * 边界:
 *   - 依赖: 无（纯路径构造，字符串）
 *   - 被依赖: view 的对话页/应急表单页/依据区，以及 T12 的端到端跳转
 * 禁止行为:
 *   - 禁止在此做权限或存在性判断（跳转前提由服务端与数据决定）
 *   - 禁止把路径散落到各页面（改一处路由就要全仓改）
 */

/** 会话列表（一级页面）。 */
export const CONSULT_LIST_PATH = '/consult';

/** 应急表单页。 */
export const CONSULT_EMERGENCY_PATH = '/consult/emergency';

/** 对话页路径（对话 id 在 URL 中，刷新可回到同一条对话）。 */
export function consultChatPath(sessionId: string): string {
  return `/consult/sessions/${encodeURIComponent(sessionId)}`;
}

/** 案例库浏览页的条目 deep-link（按 library 分区由该页自行判定）。 */
export function caseItemPath(itemId: string): string {
  return `/cases?item=${encodeURIComponent(itemId)}`;
}
