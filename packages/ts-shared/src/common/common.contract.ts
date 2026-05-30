// @contract
/**
 * 模块: @campfire/ts-shared.common.contract
 * 职责: 跨域共享的通用契约——泛型校验工具、ISO 格式检测、分页参数校验。
 *       这些守卫函数不绑定任何业务域，可在整个 mini-program 中复用。
 * 数据来源:
 *   - common.types.ts: MUST — 本域的类型定义
 * 边界:
 *   - 依赖: common.types.ts
 *   - 被依赖: cases、profiles、mini-program
 * 禁止行为:
 *   - 禁止包含业务域的特定校验逻辑
 *   - 禁止副作用
 */

// === ISO 格式校验 ===

/**
 * 校验 ISO 8601 日期时间字符串格式。
 * 前置: str 为非空字符串。
 * 后置: 返回 true 表示格式为 ISO 8601 datetime。
 * 输入约束: 非空字符串。
 * 输出约束: 布尔值。
 * 异常: 无。
 * Side Effects: 无。
 */
export function isISODateTime(str: string): boolean {
  // 格式: YYYY-MM-DDTHH:mm:ss + 可选(.sss Z/±HH:mm)
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?(Z|[+-]\d{2}:\d{2})?$/.test(str);
}

/**
 * 校验 YYYY-MM-DD 日期字符串格式。
 */
export function isISODate(str: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(str);
}

// === 分页校验 ===

/**
 * 校验分页响应结构。
 * 前置: data 为 API 返回的可能分页数据。
 * 后置: 返回 true 表示包含 items 数组和分页元数据。
 */
export function isValidPaginatedResponse<T>(
  data: unknown,
  itemGuard?: (item: unknown) => item is T,
): data is { items: T[]; total: number; page: number; page_size: number; total_pages: number } {
  if (!data || typeof data !== 'object') return false;
  const d = data as Record<string, unknown>;
  if (!Array.isArray(d['items'])) return false;
  if (typeof d['total'] !== 'number') return false;
  if (typeof d['page'] !== 'number') return false;
  if (typeof d['page_size'] !== 'number') return false;
  if (typeof d['total_pages'] !== 'number') return false;
  if (itemGuard) {
    return d['items'].every(itemGuard);
  }
  return true;
}

// === 语义类型（品牌类型） ===

declare const UrlBrand: unique symbol;
/** URL 字符串——已校验的合法 URL，禁止与普通 string 混用 */
export type SafeUrl = string & { [UrlBrand]: 'SafeUrl' };

declare const EmailBrand: unique symbol;
/** 邮箱地址——已校验的合法邮箱，禁止与普通 string 混用 */
export type SafeEmail = string & { [EmailBrand]: 'SafeEmail' };
