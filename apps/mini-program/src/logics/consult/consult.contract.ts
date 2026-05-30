// @contract
/**
 * 模块: mini-program.consult.contract
 * 职责: 咨询编排域的品牌类型（编译期语义安全）+ 类型守卫（运行时校验）。
 *       品牌类型防止 SessionId / RequestId 与普通 string 混用；
 *       类型守卫在数据入口点（提交时、API 响应）执行校验。
 *       与 Python 侧 ABC 模板方法不同，React 业务逻辑层契约表现为
 *       品牌类型 + 类型守卫 + Hook Contract——无运行时继承链，仅类型安全 + 数据校验。
 * 数据来源:
 *   - CSLT-01 (BehaviorTypeCategory): MUST — 行为类型七分类
 *   - CSLT-04 (SSE 事件载荷): MUST — 流式事件结构
 *   - CSLT-05 (置信度校验): MUST — 校验输出结构
 *   - CSLT-06 (咨询历史): MUST — 归档写入模型
 *   - shared/httpClient: MUST — 统一 HTTP 客户端
 * 边界:
 *   - 依赖: types/index.ts, @campfire/ts-shared
 *   - 被依赖: hooks/useConsult.ts, store/useConsultStore.ts, services/consultApi.ts
 * 禁止行为:
 *   - 禁止在此文件中包含 API 调用、状态管理或业务逻辑
 *   - 禁止品牌类型降级为裸 string——所有接口签名必须使用品牌类型
 *   - 禁止校验函数产生副作用（日志、网络请求等）
 */

import type { BehaviorTypeCategory } from './types';

// ============================================================================
// 品牌类型（Branded Types）——等价于 Python NewType
// ============================================================================

declare const SessionBrand: unique symbol;
/** 咨询会话 ID——UUID v4，禁止与普通 string 混用 */
export type SessionId = string & { [SessionBrand]: 'SessionId' };

declare const RequestBrand: unique symbol;
/** 幂等请求 ID——UUID v4，禁止与普通 string 混用 */
export type RequestId = string & { [RequestBrand]: 'RequestId' };

// ============================================================================
// 类型守卫
// ============================================================================

/**
 * 校验咨询提交请求必填字段非空。
 * 前置: data 为 Store 层传入的表单数据。
 * 后置: 返回 true 表示 behavior_description 非空且 behavior_type_selection 至少 1 项。
 * 输入约束: data 不为 null/undefined。
 * 输出约束: 布尔值，不修改输入。
 * 异常: 无——仅返回 false，由调用方决定如何处理。
 * Side Effects: 无。
 */
export function isValidConsultSubmitRequest(data: unknown): boolean {
  if (!data || typeof data !== 'object') return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d['behavior_description'] === 'string' &&
    (d['behavior_description'] as string).trim().length > 0 &&
    Array.isArray(d['behavior_type_selection']) &&
    (d['behavior_type_selection'] as unknown[]).length >= 1
  );
}

// TODO: 待 Hook 层复用后启用
// /**
//  * 校验行为描述文本有效性。
//  */
// export function isValidBehaviorDescription(desc: unknown): desc is string {
//   return typeof desc === 'string' && desc.trim().length > 0;
// }

// TODO: 待外部消费启用
// /**
//  * 校验行为类型列表有效性。
//  */
// export function isValidBehaviorTypes(types: unknown): types is BehaviorTypeCategory[] {
//   if (!Array.isArray(types) || types.length === 0) return false;
//   const validCategories: BehaviorTypeCategory[] = [
//     'SELF_INJURY', 'AGGRESSION', 'ELOPEMENT', 'MEDICATION',
//     'EMOTIONAL_MELTDOWN', 'STEREOTYPY', 'OTHER',
//   ];
//   return types.every((t: unknown) => validCategories.includes(t as BehaviorTypeCategory));
// }
