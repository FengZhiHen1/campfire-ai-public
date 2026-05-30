/**
 * 模块: @campfire/ts-shared.common.types
 * 职责: 跨域共享的通用类型定义——泛型分页响应、API 错误结构等不特定于任何业务域的类型。
 *       这些类型被 cases 和 profiles 域共同使用，统一管理避免重复定义。
 * 数据来源:
 *   - py-schemas (common): SHOULD — 后端通用 Pydantic 模型
 *   - 项目结构.md §6.1: SHOULD — ts-shared 的类型范围
 * 边界:
 *   - 依赖: 无
 *   - 被依赖: cases、profiles、mini-program
 * 禁止行为:
 *   - 禁止在此文件中定义业务域特定的类型——业务类型放入对应的域目录
 *   - 禁止包含任何业务逻辑
 *   - 禁止使用 any——泛型参数必须有约束
 */

// === 泛型分页 ===

/** 泛型分页响应——对应后端 PaginatedResponse Pydantic 模型 */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// === API 错误结构 ===

/** 后端 API 错误响应结构 */
export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

// === 通用工具类型 ===

/** 将接口中所有字段变为可选且可 null */
export type DeepPartial<T> = {
  [P in keyof T]?: T[P] | null;
};

/** ISO 8601 日期时间字符串 */
export type ISODateTime = string;

/** YYYY-MM-DD 日期字符串 */
export type ISODate = string;
