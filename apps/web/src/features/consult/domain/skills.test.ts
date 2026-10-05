/**
 * 模块: features/consult/domain/skills.test
 * 职责: 技能显示名解析的用例——程序注入技能有中文名，且它们【没有被放进可手选目录】
 * 数据来源:
 *   - docs/design/components.html: MUST — `chatSkillNames`（`emergency: '应急咨询'`）是
 *     「当前生效技能」文案的视觉契约正本
 *   - docs/技术设计/technical-details/技能设计.md: MUST — 第 1 节总表（onboarding =
 *     「一次性引导」）、第 3.5 节（`skill` 参数合法值域 = 模型可见目录集）
 *   - docs/design/pages/对话页.md: MUST — 页头展示「当前生效技能」，未知名显示原文名
 * 边界:
 *   - 依赖: domain/skills
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言守卫等于授权（这里只断言「可选项里没有它们」，授权由服务端 422 承担）
 *   - 禁止只测顺利路径：未知名回退与「目录不得被污染」必须都有用例
 *
 * 为什么本文件是防回归的关键：OBS-01 的 `onboarding` 来自**页头技能 chip**
 * （不是工具行），而修复它最省事、也最错误的做法就是往 `SKILL_CATALOG` 里加两行——
 * 那会经 `listSkills()`（`infrastructure/consult/consultPort.ts`）把这两个技能
 * 变成 `SkillPicker` 里**可手选**的 chip，而技能设计第 3.5 节明确它们传入即 422。
 * 因此下面既测「显示名对」，也测「可选项没被污染」。
 */

import { describe, expect, it } from 'vitest';

import { INJECTED_SKILL_LABELS, SKILL_CATALOG, skillLabel } from './skills';

describe('技能显示名解析', () => {
  it('程序注入的两个技能在页头显示为中文名，不是标识符', () => {
    // 这两个是 OBS-01 在界面上暴露的原始名称（onboarding 尤其直接可见）。
    expect(skillLabel(SKILL_CATALOG, 'onboarding')).toBe('一次性引导');
    expect(skillLabel(SKILL_CATALOG, 'emergency-consulting')).toBe('应急咨询');
  });

  it('可手选的两个技能仍取目录里的显示名', () => {
    expect(skillLabel(SKILL_CATALOG, 'daily-consulting')).toBe('日常咨询');
    expect(skillLabel(SKILL_CATALOG, 'profile-curation')).toBe('档案整理');
  });

  it('未知标识符仍返回原文名（保持「不猜测、不隐藏」，不是一律兜底）', () => {
    // 这条防的是「把 fail-open 改成 fail-silent」：一律返回中性词会让
    // 「服务端新增了技能而前端没跟上」这件事在界面上彻底不可见。
    expect(skillLabel(SKILL_CATALOG, 'some-future-skill')).toBe('some-future-skill');
    // 已知标识符不得被兜底吞掉（与上一条互为反向）。
    expect(skillLabel(SKILL_CATALOG, 'onboarding')).not.toBe('onboarding');
  });

  it('null 表示「自动匹配」，不产出标签', () => {
    expect(skillLabel(SKILL_CATALOG, null)).toBeNull();
  });

  it('★ 可手选目录【仍然没有】程序注入的两个技能（防可手选漏洞回归）', () => {
    const catalogIds = SKILL_CATALOG.map((skill) => skill.id);
    expect(catalogIds).toEqual(['daily-consulting', 'profile-curation']);
    expect(catalogIds).not.toContain('onboarding');
    expect(catalogIds).not.toContain('emergency-consulting');
  });

  it('★ 显示名表与可手选目录是两张分离的表（键集合不相交）', () => {
    // 为什么断言「不相交」而不是「无交集即可」：若有人把映射合并进 SKILL_CATALOG，
    // 这里会出现交集——那是可手选漏洞的前一步。
    const injectedIds = Object.keys(INJECTED_SKILL_LABELS);
    expect(injectedIds).toEqual(['emergency-consulting', 'onboarding']);
    for (const id of injectedIds) {
      expect(SKILL_CATALOG.map((skill) => skill.id)).not.toContain(id);
    }
  });
});
