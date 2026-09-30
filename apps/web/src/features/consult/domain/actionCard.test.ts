/**
 * 模块: features/consult/domain/actionCard.test
 * 职责: 行动卡转换内核的回归守卫——七节分派、状态词表、越界拒渲染、标注定位与 unknown 语义
 * 数据来源:
 *   - docs/技术设计/面/consult/tools/emit_emergency_action_card.md: MUST — 第 4 节（词表与 unknown 语义）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 6.2 节（越界拒渲染、旧卡失效）
 *   - 编排器裁决 A6/A9: MUST — kind 解码为 source:confidence；指不到行的标注不渲染
 * 边界:
 *   - 依赖: domain/actionCard、test/fixtures
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止只测「合法卡渲染」而漏掉越界与定位失败（这两条是契约的机械边界）
 */

import { describe, expect, it } from 'vitest';

import { buildActionCard } from './actionCard';
import { actionCardEvent } from '../test/fixtures';

describe('buildActionCard — 七节与状态', () => {
  it('按规范顺序分派，序号从 01 起，「立即做」标为优先级节', () => {
    const build = buildActionCard(actionCardEvent(), { expired: false });
    expect(build.status).toBe('rendered');
    if (build.status !== 'rendered') return;

    expect(build.view.sections.map((section) => section.key)).toEqual([
      'status',
      'communicate',
      'do_now',
      'avoid',
      'medical_checks',
      'safety',
      'when_to_escalate',
    ]);
    expect(build.view.sections.map((section) => section.ordinal)).toEqual([
      '01',
      '02',
      '03',
      '04',
      '05',
      '06',
      '07',
    ]);
    expect(build.view.sections.find((section) => section.key === 'do_now')?.isPriority).toBe(true);
  });

  it('医疗风险三值走徽章，其余状态字段读成中文档位', () => {
    const build = buildActionCard(actionCardEvent(), { expired: false });
    if (build.status !== 'rendered') throw new Error('应渲染');

    expect(build.view.medicalRisk).toEqual({ tone: 'unruled', text: '医疗风险 · 未排除' });
    expect(build.view.stateLines).toEqual(['与平时相比：明显', '当前沟通：下降', '当前感觉负荷：未排除']);
  });

  it('medical_risk 越界 → 拒渲染（不得静默替换成合法值）', () => {
    const build = buildActionCard(
      actionCardEvent({ states: [{ key: 'medical_risk', value: 'critical' }] }),
      { expired: false },
    );
    expect(build.status).toBe('rejected');
    if (build.status !== 'rejected') return;
    expect(build.reason).toContain('medical_risk');
    expect(build.reason).toContain('critical');
  });

  it('deviation=unknown 不读成「无变化」，而是「未排除」', () => {
    const build = buildActionCard(actionCardEvent({ states: [{ key: 'deviation', value: 'unknown' }] }), {
      expired: false,
    });
    if (build.status !== 'rendered') throw new Error('应渲染');
    expect(build.view.stateLines).toEqual(['与平时相比：未排除']);
  });

  it('医疗风险缺失时按「未排除」呈现（不是稳定）', () => {
    const build = buildActionCard(actionCardEvent({ states: [] }), { expired: false });
    if (build.status !== 'rendered') throw new Error('应渲染');
    expect(build.view.medicalRisk).toEqual({ tone: 'unruled', text: '医疗风险 · 未排除' });
  });

  it('没有任何分节 → 拒渲染', () => {
    const build = buildActionCard(actionCardEvent({ sections: [] }), { expired: false });
    expect(build.status).toBe('rejected');
  });
});

describe('buildActionCard — 标注定位', () => {
  it('target 是按七节摊平的 1 起序号，kind 解码为来源与置信', () => {
    // 摊平后的行：1=status[0] 2=communicate[0] 3=do_now[0] ... 9=safety[0]
    const build = buildActionCard(actionCardEvent(), { expired: false });
    if (build.status !== 'rendered') throw new Error('应渲染');

    const doNow = build.view.sections.find((section) => section.key === 'do_now');
    expect(doNow?.lines[0]?.annotation).toEqual({
      source: 'family_report',
      sourceLabel: '家属报告',
      confidence: 'likely',
      confidenceLabel: '较可能',
    });
    const safety = build.view.sections.find((section) => section.key === 'safety');
    expect(safety?.lines[0]?.annotation?.sourceLabel).toBe('AI 推断');
    expect(build.view.droppedAnnotations).toBe(0);
  });

  it('指不到行或词表越界的标注被丢弃，不指到别的行', () => {
    const build = buildActionCard(
      actionCardEvent({
        annotations: [
          { target: '99', kind: 'family_report:likely' },
          { target: '3', kind: '不存在的来源:likely' },
          { target: '不是数字', kind: 'family_report:likely' },
          { target: '3', kind: 'family_report:也许' },
        ],
      }),
      { expired: false },
    );
    if (build.status !== 'rendered') throw new Error('应渲染');

    const doNow = build.view.sections.find((section) => section.key === 'do_now');
    expect(doNow?.lines[0]?.annotation).toBeNull();
    expect(build.view.droppedAnnotations).toBe(4);
  });

  it('同一行重复标注只保留第一条', () => {
    const build = buildActionCard(
      actionCardEvent({
        annotations: [
          { target: '3', kind: 'family_report:likely' },
          { target: '3', kind: 'ai_inference:possible' },
        ],
      }),
      { expired: false },
    );
    if (build.status !== 'rendered') throw new Error('应渲染');
    const doNow = build.view.sections.find((section) => section.key === 'do_now');
    expect(doNow?.lines[0]?.annotation?.source).toBe('family_report');
  });
});

describe('buildActionCard — 失效态与契约外分节', () => {
  it('失效卡带 expired 标记（旧卡保留可回看）', () => {
    const build = buildActionCard(actionCardEvent(), { expired: true });
    if (build.status !== 'rendered') throw new Error('应渲染');
    expect(build.view.expired).toBe(true);
  });

  it('契约外的分节追加在末尾而不是被丢弃', () => {
    const base = actionCardEvent();
    const build = buildActionCard(
      actionCardEvent({ sections: [...base.sections, { key: 'future_section', heading: '将来的一节', lines: ['内容'] }] }),
      { expired: false },
    );
    if (build.status !== 'rendered') throw new Error('应渲染');
    expect(build.view.sections.at(-1)?.key).toBe('future_section');
    expect(build.view.sections.at(-1)?.ordinal).toBe('08');
  });

  it('契约外的状态键被忽略而不影响渲染', () => {
    const build = buildActionCard(
      actionCardEvent({ states: [{ key: 'medical_risk', value: 'stable' }, { key: '将来字段', value: 'x' }] }),
      { expired: false },
    );
    if (build.status !== 'rendered') throw new Error('应渲染');
    expect(build.view.medicalRisk).toEqual({ tone: 'stable', text: '医疗风险 · 稳定' });
    expect(build.view.stateLines).toEqual([]);
  });
});
