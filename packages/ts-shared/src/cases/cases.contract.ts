// @contract
/**
 * 模块: @campfire/ts-shared.cases.contract
 * 职责: 案例管理域的行为契约——品牌类型（编译期语义安全）+ 类型守卫（运行时校验）。
 *       品牌类型防止 CaseId 与普通 string 混用；类型守卫在数据入口点（API 响应）执行校验。
 *       与 *_contract.ts 在 Python 侧的 ABC 模板方法不同，ts-shared 作为纯类型包，
 *       契约表现为品牌类型 + 类型守卫——无运行时业务逻辑，仅类型安全 + 数据校验。
 * 数据来源:
 *   - py-schemas (cases): MUST — 后端 CaseId 格式、字段约束
 *   - cases.types.ts: MUST — 本域的类型定义
 * 边界:
 *   - 依赖: cases.types.ts, cases.enums.ts
 *   - 被依赖: mini-program（运行时类型校验入口）
 * 禁止行为:
 *   - 禁止在此文件中包含 API 调用、状态管理或业务逻辑
 *   - 禁止品牌类型降级为裸 string——所有接口签名必须使用品牌类型
 *   - 禁止校验函数产生副作用（日志、网络请求等）
 */

import type { CaseCreateRequest, CaseUpdate, AttachmentRef } from './cases.types';

// === 品牌类型（Branded Types）——等价于 Python NewType ===

declare const CaseBrand: unique symbol;
/** 案例 ID——格式 CASE-YYYY-NNNN，禁止与普通 string 混用 */
export type CaseId = string & { [CaseBrand]: 'CaseId' };

declare const NarrativeBrand: unique symbol;
/** 叙事 ID——格式 NRT-YYYY-NNNN，禁止与普通 string 混用 */
export type NarrativeId = string & { [NarrativeBrand]: 'NarrativeId' };

declare const CardBrand: unique symbol;
/** 卡片 ID——格式 CRD-YYYY-NNNN，禁止与普通 string 混用 */
export type CardId = string & { [CardBrand]: 'CardId' };

declare const ReviewerBrand: unique symbol;
/** 审核人 ID——UUID v4，禁止与普通 string 混用 */
export type ReviewerId = string & { [ReviewerBrand]: 'ReviewerId' };

declare const AuthorBrand: unique symbol;
/** 作者 ID——UUID v4，禁止与普通 string 混用 */
export type AuthorId = string & { [AuthorBrand]: 'AuthorId' };

// === 类型守卫 ===

/**
 * 校验 CaseCreateRequest 必填字段非空。
 * 前置: data 为 API 层传入的表单数据。
 * 后置: 返回 true 表示 MVP 九个核心字段均非空字符串。
 * 输入约束: data 不为 null/undefined。
 * 输出约束: 布尔值，不修改输入。
 * 异常: 无——仅返回 false，由调用方决定如何处理。
 * Side Effects: 无。
 */
export function isValidCaseCreateRequest(data: unknown): data is CaseCreateRequest {
  if (!data || typeof data !== 'object') return false;
  const d = data as Record<string, unknown>;
  const required = [
    'title', 'behavior_type', 'severity', 'scene',
    'immediate_action', 'comforting_phrase', 'observation_metrics',
    'medical_criteria', 'evidence_level',
  ];
  return required.every(f => typeof d[f] === 'string' && (d[f] as string).trim().length > 0);
}

/**
 * 校验 CaseUpdate 乐观锁字段存在。
 * 前置: data 为 API 层传入的更新数据。
 * 后置: 返回 true 表示 updated_at 字段为非空字符串。
 * 输入约束: data 不为 null/undefined。
 * 输出约束: 布尔值。
 */
export function isValidCaseUpdate(data: unknown): data is CaseUpdate {
  if (!data || typeof data !== 'object') return false;
  const d = data as Record<string, unknown>;
  return typeof d['updated_at'] === 'string' && d['updated_at'].trim().length > 0;
}

/**
 * 校验附件引用结构。
 * 前置: ref 为可能的附件对象。
 * 后置: 返回 true 表示包含必填的 file_name 和 minio_path 字段。
 */
export function isValidAttachmentRef(ref: unknown): ref is AttachmentRef {
  if (!ref || typeof ref !== 'object') return false;
  const r = ref as Record<string, unknown>;
  return typeof r['file_name'] === 'string' && typeof r['minio_path'] === 'string';
}
