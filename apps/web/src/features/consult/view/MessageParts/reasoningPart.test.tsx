/**
 * 模块: features/consult/view/MessageParts/reasoningPart.test
 * 职责: 思考行呈现开关的来源守卫——取自对话工作面下发的上下文，不自行订阅 runStore
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 6.3 节（呈现纪律）
 *   - docs/design/pages/对话页.md: MUST — 契约修订 6（.reasoning-row 的行内文案）
 * 边界:
 *   - 依赖: view/MessageParts/parts（被测注册表）
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止把思考文本渲染成正文段落（必须留在折叠区内）
 *
 * 判别性：修复前 ReasoningPart 自己订阅 runStore 取两个开关，本文件里 store 是初始态
 * （connection = idle、无激活技能），于是「应急 + 流式中」的用例拿到的是「思考过程」而变红。
 * 现在开关经上下文下发，用例提供什么就渲染什么——这也正是渲染器可用 fixture 驱动的前提。
 */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { CONSULT_MESSAGE_COMPONENTS, ConsultThreadProvider, type ConsultThreadContextValue } from './parts';

/** 造一份对话消息流上下文；缺省非流式、非应急。 */
function contextValue(overrides: Partial<ConsultThreadContextValue> = {}): ConsultThreadContextValue {
  return {
    // 这份上下文只为渲染思考行：提交回答的回调不被调用，恒真返回「已受理」即可。
    submitAnswers: () => true,
    newestActionCardId: null,
    reasoningStreaming: false,
    reasoningEmergency: false,
    ...overrides,
  };
}

/** 渲染一个思考段。 */
function renderReasoning(text: string, value: ConsultThreadContextValue) {
  return render(
    <ConsultThreadProvider value={value}>
      <CONSULT_MESSAGE_COMPONENTS.Reasoning text={text} />
    </ConsultThreadProvider>,
  );
}

describe('思考行 · 呈现开关来自上下文', () => {
  it('P1 应急且在流式中 → 收为一行「正在分析…」', () => {
    renderReasoning('先确认安全，再给步骤。', contextValue({ reasoningStreaming: true, reasoningEmergency: true }));

    expect(screen.getByText('正在分析…')).toBeDefined();
  });

  it('P1 应急且已结束 → 「分析说明 · 已结束」', () => {
    renderReasoning('先确认安全，再给步骤。', contextValue({ reasoningStreaming: false, reasoningEmergency: true }));

    expect(screen.getByText('分析说明 · 已结束')).toBeDefined();
  });

  it('P1 非应急 → 常规「思考过程」', () => {
    renderReasoning('先确认安全，再给步骤。', contextValue({ reasoningStreaming: true, reasoningEmergency: false }));

    expect(screen.getByText('思考过程')).toBeDefined();
    // 思考不参与引用：折叠区里带「中间状态」说明，且不出现 citation 语义。
    expect(screen.getByText(/不作为结论或依据/)).toBeDefined();
  });

  it('P1 空思考段不生成折叠行', () => {
    const { container } = renderReasoning('   ', contextValue({ reasoningStreaming: true }));

    expect(container.querySelector('.reasoning-row')).toBeNull();
  });
});
