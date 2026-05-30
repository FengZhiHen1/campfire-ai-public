/**
 * @campfire/ts-shared/cases — 案例管理域共享类型、枚举与契约。
 *
 * 提供 N 大能力：
 * 1. 枚举定义：CaseStatus、BehaviorType、SeverityLevel 等 7 个前端枚举
 * 2. 接口类型：CaseCreateRequest、CaseResponse、CaseListItem 等 CRUD + 审核 DTO
 * 3. 品牌类型：CaseId、NarrativeId 等编译期安全类型
 * 4. 类型守卫：isValidCaseCreateRequest 等运行时校验函数
 *
 * Usage:
 *     import { CaseStatus, CaseCreateRequest, isValidCaseCreateRequest } from '@campfire/ts-shared/cases';
 */

export * from './cases.enums';
export * from './cases.types';
export * from './cases.contract';
