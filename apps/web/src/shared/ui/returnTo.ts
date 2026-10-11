/**
 * 模块: shared/ui/returnTo
 * 职责: 把路由 state 里的 `returnTo` 收敛成「应用内绝对路径」或 null
 * 数据来源:
 *   - docs/技术设计/面/consult/… 与各页设计文档：次级页面返回实际来源
 *   - apps/web/src/shared/ui/BackLink.tsx: MUST — 本函数的展示形态（返回链接与实际来源一致）
 * 边界:
 *   - 依赖: 无（纯函数）
 *   - 被依赖: shared/ui/BackLink（返回链接）、features/consult/view/EmergencyFormPage（退出应急）
 * 禁止行为:
 *   - 禁止接受协议相对地址与反斜杠变体（`//host`、`/\host`、`\\host`）——那是开放重定向
 *   - 禁止对缺字段/类型不符编造返回值：判不出来就返回 null，由调用方给明确的默认入口
 *
 * 为什么单独一个模块而不是在每处各写一遍判断：同一段判断此前在 BackLink 与应急页各有一份，
 * 两处都会随「什么算合法返回地址」的变化而漂移，而这种漂移的代价是安全边界而非样式差异。
 */

/**
 * 取出 state 里的 `returnTo`，只放行应用内绝对路径。
 *
 * 前置: 无
 * 后置: 返回以单个 `/` 开头的应用内路径；缺失、类型不符或疑似外部地址时返回 null
 * 异常: 无
 *
 * 三个拒绝条件各自的理由：
 *   - 不以 `/` 开头：相对路径会相对当前 URL 解析，落在哪一页取决于调用点，不可预测；
 *   - 以 `//` 开头：协议相对地址，会被当作 `//host` 解析成站外；
 *   - 含 `\`：URL 规范对 http(s) 把 `\` 视同 `/`，于是 `/\evil.example` 等价于 `//evil.example`，
 *     只判 `//` 会漏掉它。应用内的合法路径不会带反斜杠，整串拒绝没有代价。
 */
export function safeReturnTo(state: unknown): string | null {
  if (typeof state !== 'object' || state === null || !('returnTo' in state)) return null;
  const candidate: unknown = (state as { returnTo?: unknown }).returnTo;
  if (typeof candidate !== 'string') return null;
  if (!candidate.startsWith('/') || candidate.startsWith('//') || candidate.includes('\\')) return null;
  return candidate;
}
