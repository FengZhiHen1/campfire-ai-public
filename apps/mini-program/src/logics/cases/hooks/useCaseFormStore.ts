/**
 * CASE-09 案例管理逻辑 — 表单 Store Hook。
 *
 * 直接导出 Zustand Store 的 selector/action 绑定，是表单编辑的入口。
 * 这是 views 层访问案例表单状态的唯一合法通道。
 *
 * 调用路径：
 *   views/ → hooks/useCaseFormStore → store/caseStore (Zustand)
 *
 * 设计依据：
 * - 设计文档 §1.1 Hooks 桥接层
 * - 项目结构 §6.1 views/logics 三层隔离架构
 */

export { useCaseStore as useCaseFormStore } from '../store/caseStore';
export type { CaseFormFields, CaseFormState, FormErrors } from '../types';
