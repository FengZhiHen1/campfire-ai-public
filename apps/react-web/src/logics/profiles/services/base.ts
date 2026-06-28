/**
 * PROF-07 档案数据逻辑 — API 服务层共享工具
 *
 * 数据来源:
 *   - AUTH-06 httpClient: MUST — IRequestResponse<T> 类型
 * 边界:
 *   - 依赖: ../../shared/services/httpClient
 *   - 被依赖: profileApi.ts, eventApi.ts
 */

import type { IRequestResponse } from '../../shared/services/httpClient';

/** 从 httpClient 响应中提取 data 字段 */
export function pickData<T>(res: IRequestResponse<T>): T {
  return res.data;
}
