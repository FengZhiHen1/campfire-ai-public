/**
 * CASE-09 案例管理逻辑 — 表单 Store Hook。
 *
 * 直接导出 Zustand Store，是 views 层访问案例表单状态的唯一合法通道。
 *
 * 调用路径：views/ → hooks/useCaseFormStore → store/caseStore (Zustand)
 */

export { useCaseStore as useCaseFormStore } from '../store/caseStore';
export type { CaseFormFields, CaseFormState, FormErrors } from '../types';
