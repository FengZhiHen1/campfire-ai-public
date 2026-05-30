/**
 * @campfire/ts-shared/common — 跨域共享的通用类型与校验工具。
 *
 * 提供 N 大能力：
 * 1. 泛型分页：PaginatedResponse<T>
 * 2. API 错误结构：ApiError
 * 3. 工具类型：DeepPartial<T>、ISODateTime、ISODate
 * 4. 通用校验：isISODateTime、isValidPaginatedResponse
 * 5. 语义类型：SafeUrl、SafeEmail
 *
 * Usage:
 *     import { PaginatedResponse, isISODateTime } from '@campfire/ts-shared/common';
 *     import type { ISODateTime } from '@campfire/ts-shared/common';
 */

export * from './common.types';
export * from './common.contract';
