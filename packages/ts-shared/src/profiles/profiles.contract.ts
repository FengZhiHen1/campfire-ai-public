// @contract
/**
 * 模块: @campfire/ts-shared.profiles.contract
 * 职责: 档案管理域的行为契约——品牌类型 + 类型守卫。
 *       品牌类型防止 ProfileId/EventId 与普通 string 混用。
 *       类型守卫在 mini-program 的数据入口点（API 响应/表单提交）执行校验。
 * 数据来源:
 *   - py-schemas (profiles): MUST — 后端 ProfileId/EventId 格式
 *   - profiles.types.ts: MUST — 本域的类型定义
 * 边界:
 *   - 依赖: profiles.types.ts, profiles.enums.ts
 *   - 被依赖: mini-program（运行时校验入口）
 * 禁止行为:
 *   - 禁止包含 API 调用或状态管理逻辑
 *   - 禁止品牌类型降级为裸 string
 *   - 禁止校验函数产生副作用
 */

import type { ProfileCreate, EventCreate } from './profiles.types';

// === 品牌类型 ===

declare const ProfileBrand: unique symbol;
/** 档案 ID——UUID v4，禁止与普通 string 混用 */
export type ProfileId = string & { [ProfileBrand]: 'ProfileId' };

declare const EventBrand: unique symbol;
/** 事件 ID——UUID v4，禁止与普通 string 混用 */
export type EventId = string & { [EventBrand]: 'EventId' };

declare const CaregiverBrand: unique symbol;
/** 家属 ID——UUID v4，禁止与普通 string 混用 */
export type CaregiverId = string & { [CaregiverBrand]: 'CaregiverId' };

// === 类型守卫 ===

/**
 * 校验 ProfileCreate 必填字段。
 * 前置: data 为表单提交的档案数据。
 * 后置: 返回 true 表示必填字段存在且非空。
 * 输入约束: data 不为 null/undefined。
 * 输出约束: 布尔值，不修改输入。
 * 异常: 无。
 * Side Effects: 无。
 */
export function isValidProfileCreate(data: unknown): data is ProfileCreate {
  if (!data || typeof data !== 'object') return false;
  const d = data as Record<string, unknown>;
  if (typeof d['birth_date'] !== 'string' || d['birth_date'].trim().length === 0) return false;
  if (typeof d['diagnosis_type'] !== 'string') return false;
  if (typeof d['primary_behavior'] !== 'string') return false;
  return true;
}

/**
 * 校验 birth_date 格式为 YYYY-MM-DD。
 * 前置: dateStr 为字符串。
 * 后置: 返回 true 表示格式合法。
 * 输入约束: 非空字符串。
 * 输出约束: 布尔值。
 */
export function isValidBirthDate(dateStr: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(dateStr);
}

/**
 * 校验 EventCreate 必填字段。
 * 前置: data 为事件提交数据。
 * 后置: 返回 true 表示必填字段存在且非空。
 */
export function isValidEventCreate(data: unknown): data is EventCreate {
  if (!data || typeof data !== 'object') return false;
  const d = data as Record<string, unknown>;
  const required = [
    'event_time', 'behavior_type', 'severity_level',
    'trigger_description', 'manifestation',
    'intervention_tried', 'intervention_result',
  ];
  return required.every(f => typeof d[f] === 'string' && (d[f] as string).trim().length > 0);
}
