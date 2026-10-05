/**
 * 模块: features/consult/view/MessageParts/toolLabels.test
 * 职责: 工具行文案词表的用例——覆盖兜底与「绝不显示标识符」这条不变量
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 契约修订 7（工具行用面向使用者的名称）
 *   - apps/api/tests/test_tool_labels_coverage.py: MUST — 同一份词表的服务端侧完整性核对
 * 边界:
 *   - 依赖: MessageParts/toolLabels
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止只测「命中词表」这一条顺利路径（兜底与「不回退成标识符」才是 OBS-01 的形态）
 */

import { describe, expect, it } from 'vitest';

import { FALLBACK_TOOL_LABEL, MAPPED_TOOL_NAMES, TOOL_LABELS, toolDisplayName } from './toolLabels';

describe('工具行文案词表', () => {
  it('十个产品工具标识符都有中文友好名', () => {
    // 与 apps/api 的 `registry.build_product_tools` 逐项对应（服务端侧按真源机械核对）。
    for (const toolName of [
      'create_support_object',
      'emit_emergency_action_card',
      'finish_onboarding',
      'propose_profile_item',
      'read_memory',
      'read_profile_items',
      'read_profile_summary',
      'search_cases',
      'search_knowledge',
      'write_memory',
    ]) {
      expect(TOOL_LABELS[toolName]).toBeDefined();
    }
  });

  it('三个基座保留名工具也有中文友好名（它们同样会开出工具行）', () => {
    for (const toolName of ['ask_user', 'read_skill_resource', 'skill']) {
      expect(TOOL_LABELS[toolName]).toBeDefined();
    }
  });

  it('友好名本身不含标识符形状的拉丁词（不是把标识符换个位置显示）', () => {
    for (const [name, label] of Object.entries(TOOL_LABELS)) {
      // 兜底比标识符好，但「别名 = 标识符」等于没修（OBS-01 的形态之一）。
      expect(label, `工具 ${name} 的显示名不能与标识符相同`).not.toBe(name);
      expect(label).not.toMatch(/[A-Za-z_]/);
    }
  });

  it('未命中的工具标识符回退到中性文案，而不是标识符本身', () => {
    expect(toolDisplayName('some_new_tool_v2')).toBe(FALLBACK_TOOL_LABEL);
    // 这条是 OBS-01 的不变量：界面上永远不出现标识符。
    expect(toolDisplayName('some_new_tool_v2')).not.toContain('some_new_tool_v2');
  });

  it('兜底文案不是空串（空串会让「没渲染」与「没起名」无法区分）', () => {
    expect(FALLBACK_TOOL_LABEL).not.toBe('');
  });

  it('MAPPED_TOOL_NAMES 与词表键集合一致', () => {
    // 用集合比较而不是排序后比较：`lib` 是 ES2022，`toSorted` 不在其内，而 oxlint 禁止
    // 会就地改写的 `sort()`。集合相等与顺序无关，正是这里要的语义。
    expect(new Set(MAPPED_TOOL_NAMES)).toEqual(new Set(Object.keys(TOOL_LABELS)));
  });
});
