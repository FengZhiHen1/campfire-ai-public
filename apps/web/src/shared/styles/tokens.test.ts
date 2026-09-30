/**
 * 模块: src/shared/styles/tokens.test
 * 职责: token 同步的逐字一致断言——shared/styles/tokens.css 是 docs/design/tokens.css 的生成物
 * 数据来源:
 *   - docs/design/tokens.css: MUST — 视觉契约唯一权威（项目结构第 9 节）
 *   - docs/项目结构设计.md: MUST — 第 9 节（生成物、不手改，并有检查断言两份逐字一致）
 * 边界:
 *   - 依赖: node:fs（只读两个文件并比较字符串，不解析 CSS）
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止在实现侧定义色值与间距（本用例就是这条约束的机械守卫）
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

/** apps/web 根目录；vitest 的工作目录即包根。 */
const WEB_ROOT = resolve(process.cwd());
const SOURCE = resolve(WEB_ROOT, '..', '..', 'docs', 'design', 'tokens.css');
const GENERATED = resolve(WEB_ROOT, 'src', 'shared', 'styles', 'tokens.css');

describe('token 同步', () => {
  it('生成物与真源逐字一致', () => {
    const source = readFileSync(SOURCE, 'utf8');
    const generated = readFileSync(GENERATED, 'utf8');

    // 逐字符比较：任何一处颜色、间距或注释差异都必须失败——
    // 只比较「变量个数」或「解析后的键值」会放过值被改而键不变的情形。
    expect(generated).toBe(source);
  });

  it('逐字符比较能发现单字符改动（canary）', () => {
    const source = readFileSync(SOURCE, 'utf8');
    // 在副本上改一个字符，断言比较逻辑确实会失败——防止「两边都读同一个文件」
    // 这类恒真断言把守卫变成永远通过的空检查。
    const mutated = `${source.slice(0, 10)}X${source.slice(11)}`;

    expect(mutated).not.toBe(source);
    expect(() => {
      expect(mutated).toBe(source);
    }).toThrow();
  });

  it('生成物落点与真源都已就位，脚本路径不漂移', () => {
    // 同步脚本负责写入；这里断言脚本仍指向 docs/design，避免脚本路径漂移后
    // 出现「两边都读同一个文件」的恒真断言（那会让守卫永远通过）。
    const scriptPath = resolve(WEB_ROOT, 'scripts', 'sync-tokens.mjs');
    const script = readFileSync(scriptPath, 'utf8');

    expect(script).toContain("'docs'");
    expect(script).toContain('tokens.css');
    expect(SOURCE).not.toBe(GENERATED);
    expect(readFileSync(SOURCE, 'utf8')).toContain(':root');
  });
});
