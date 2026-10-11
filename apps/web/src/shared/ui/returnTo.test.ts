/**
 * 模块: shared/ui/returnTo.test
 * 职责: 返回地址收敛的纯函数用例——只放行应用内绝对路径
 * 数据来源:
 *   - apps/web/src/shared/ui/returnTo.ts: MUST — 三个拒绝条件
 * 边界:
 *   - 依赖: shared/ui/returnTo
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止只测 `//host` 而漏掉反斜杠变体：那是真实的开放重定向绕过（浏览器把 `\` 当 `/`）
 */

import { describe, expect, it } from 'vitest';

import { safeReturnTo } from './returnTo';

describe('返回地址收敛', () => {
  it('放行应用内绝对路径（含查询串）', () => {
    expect(safeReturnTo({ returnTo: '/' })).toBe('/');
    expect(safeReturnTo({ returnTo: '/cases?section=knowledge' })).toBe('/cases?section=knowledge');
  });

  it('拒绝协议相对与反斜杠变体——两者都会被浏览器解析成站外地址', () => {
    expect(safeReturnTo({ returnTo: '//outside.example' })).toBeNull();
    expect(safeReturnTo({ returnTo: '/\\outside.example' })).toBeNull();
    expect(safeReturnTo({ returnTo: '\\\\outside.example' })).toBeNull();
    expect(safeReturnTo({ returnTo: 'https://outside.example/' })).toBeNull();
  });

  it('相对路径不放行：落在哪一页取决于调用点，不可预测', () => {
    expect(safeReturnTo({ returnTo: 'cases' })).toBeNull();
  });

  it('缺字段、类型不符与非对象 state 都返回 null（不编造默认值）', () => {
    expect(safeReturnTo({})).toBeNull();
    expect(safeReturnTo({ returnTo: 42 })).toBeNull();
    expect(safeReturnTo(null)).toBeNull();
    expect(safeReturnTo(undefined)).toBeNull();
    expect(safeReturnTo('/cases')).toBeNull();
  });
});
