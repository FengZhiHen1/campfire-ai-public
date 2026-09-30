/**
 * 模块: shared/types/index
 * 职责: 线格式类型的唯一出口——四份 HTTP 契约与基座事件形状的汇总导出
 * 数据来源:
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md
 *   - docs/技术设计/面/profile/{档案面,记忆面,资料库面}HTTP契约.md
 * 边界:
 *   - 依赖: 同目录四个契约模块
 *   - 被依赖: features 与 infrastructure
 * 禁止行为:
 *   - 禁止在本文件定义新的线格式类型（定义归各契约文件，本文件只做出口）
 */

export * from './consult';
export * from './library';
export * from './memory';
export * from './profile';
export * from './sse';
