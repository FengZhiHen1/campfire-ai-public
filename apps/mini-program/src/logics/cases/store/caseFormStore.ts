/**
 * 重导出别名 —— 保留旧文件名兼容。
 *
 * 本文件为过渡期兼容层，所有实现已迁移至 ./caseStore.ts。
 * 待确认所有引用已迁移后删除本文件。
 *
 * @deprecated 请直接使用 './caseStore' 中的导出。
 */

export { useCaseStore as useCaseFormStore } from './caseStore';
