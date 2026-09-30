/**
 * 模块: features/memory/domain/episodes.test
 * 职责: 记忆时间线呈现规则与失败分类的纯函数用例（含纠正两步中间态）
 * 数据来源:
 *   - docs/design/pages/记忆页.md: MUST — 第 24～28、50、59、62 行
 *   - docs/技术设计/面/profile/记忆面HTTP契约.md: MUST — 第 6 节（空与失败必须可区分）、第 5 节（两步语义）
 * 边界:
 *   - 依赖: features/memory/domain/*
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言 source_session_id 出现在界面上（它不该被渲染）
 *   - 禁止把 503 与空态断言成同一形态
 */

import { describe, expect, it } from 'vitest';

import type { MemoryEpisode } from '../../../shared/types/memory';
import {
  dateHeading,
  fromDatetimeLocalValue,
  groupByDate,
  localDateKey,
  occurredAtLabel,
  sourceLabel,
  toDatetimeLocalValue,
} from './episodes';
import {
  CORRECTION_INTERMEDIATE_COPY,
  classifyMemoryFailure,
  correctionOutcome,
  failureFromError,
  isRetryable,
  memoryFailureDescription,
  memoryFailureTitle,
} from './failures';
import { CorrectionValidationError, validateCorrectionDraft } from './formValidation';

/** 造一条记忆。 */
function episode(overrides: Partial<MemoryEpisode> = {}): MemoryEpisode {
  return {
    episode_key: 'e1',
    occurred_at: '2026-10-02T09:30:00+08:00',
    content: '今天在超市里人很多，我有点撑不住',
    source_session_id: 'session-abc',
    ...overrides,
  };
}

describe('记忆时间线分组', () => {
  it('按发生时间倒序、按日期分组，组内也倒序', () => {
    const groups = groupByDate([
      episode({ episode_key: 'a', occurred_at: '2026-10-01T09:00:00+08:00' }),
      episode({ episode_key: 'b', occurred_at: '2026-10-02T08:00:00+08:00' }),
      episode({ episode_key: 'c', occurred_at: '2026-10-02T20:00:00+08:00' }),
    ]);

    expect(groups.map((group) => group.key)).toEqual(['2026-10-02', '2026-10-01']);
    const [first] = groups;
    expect(first?.items.map((item) => item.episode_key)).toEqual(['c', 'b']);
  });

  it('日期键用本地日期而不是 UTC 日期', () => {
    // 本地时间 23:30 的东八区时刻，其 UTC 日期是前一天——按 UTC 分组会分错。
    expect(localDateKey('2026-10-02T23:30:00+08:00')).toBe('2026-10-02');
  });

  it('分组头是 M月D日；坏日期如实写「时间未知」', () => {
    expect(dateHeading('2026-10-02')).toBe('10月2日');
    expect(dateHeading('not-a-date')).toBe('时间未知');
  });

  it('时间无法解析的条目排在最后，且不被丢掉', () => {
    const groups = groupByDate([
      episode({ episode_key: 'bad', occurred_at: 'not-a-date' }),
      episode({ episode_key: 'good', occurred_at: '2026-10-02T09:00:00+08:00' }),
    ]);
    expect(groups.flatMap((group) => group.items).map((item) => item.episode_key)).toEqual(['good', 'bad']);
  });

  it('发生时间标注为「发生时间」，不是提交时间', () => {
    expect(occurredAtLabel('2026-10-02T09:30:00+08:00')).toContain('发生时间');
    expect(occurredAtLabel('not-a-date')).toBe('发生时间未知');
  });

  it('来源行只有一个固定文案，界面上读不到会话标识', () => {
    // 会话标识是排障定位，不是给使用者看的导航（记忆页第 26 行）。
    expect(sourceLabel()).toBe('来自一次咨询');
    expect(sourceLabel()).not.toContain('session');
  });

  it('datetime-local 值与时区串可互相转换；非法值不编造时间', () => {
    const local = toDatetimeLocalValue('2026-10-02T09:30:00+08:00');
    expect(local).toMatch(/^2026-10-02T\d{2}:\d{2}$/);
    expect(fromDatetimeLocalValue(local)).not.toBeNull();
    expect(fromDatetimeLocalValue('')).toBeNull();
    expect(fromDatetimeLocalValue('乱填')).toBeNull();
    expect(toDatetimeLocalValue('not-a-date')).toBe('');
  });
});

describe('记忆面失败分类', () => {
  it('图库不可用与「没有记忆」是两件事（契约第 6 节）', () => {
    const failure = classifyMemoryFailure(503);
    expect(failure.kind).toBe('graph-unavailable');
    expect(memoryFailureTitle(failure)).toBe('暂时无法读取记录');
    expect(memoryFailureTitle(failure)).not.toContain('还没有记录');
    expect(memoryFailureDescription(failure)).toContain('不等于没有记录');
  });

  it('5xx 一律归「暂时读不到」而不是含糊的未知', () => {
    expect(classifyMemoryFailure(500).kind).toBe('graph-unavailable');
    expect(classifyMemoryFailure(502).kind).toBe('graph-unavailable');
  });

  it('只有可恢复的失败给重试', () => {
    expect(isRetryable({ kind: 'graph-unavailable' })).toBe(true);
    expect(isRetryable({ kind: 'not-found' })).toBe(false);
  });

  it('从异常取状态码用结构化检查', () => {
    expect(failureFromError({ status: 404 }).kind).toBe('not-found');
    expect(failureFromError(new Error('断网')).kind).toBe('unknown');
  });
});

describe('纠正两步语义', () => {
  it('新记忆已写入 → written，带新标识', () => {
    expect(
      correctionOutcome({ superseded: true, new_episode_written: true, episode_key: 'new1', supersedes: 'e1' }),
    ).toEqual({ kind: 'written', episodeKey: 'new1' });
  });

  it('旧已撤下、新没写成 → 中间态（不得笼统报成功或失败）', () => {
    expect(
      correctionOutcome({ superseded: true, new_episode_written: false, episode_key: null, supersedes: 'e1' }),
    ).toEqual({ kind: 'superseded-only' });
  });

  it('声称写了但没给标识 → 按中间态处理（不编造一个不存在的标识）', () => {
    expect(
      correctionOutcome({ superseded: true, new_episode_written: true, episode_key: null, supersedes: 'e1' }),
    ).toEqual({ kind: 'superseded-only' });
  });

  it('中间态文案逐字取自记忆页设计第 62 行（前端文案，不进后端响应）', () => {
    expect(CORRECTION_INTERMEDIATE_COPY).toBe('原记录已不再作为依据，但新记录没写成，请重试');
  });
});

describe('纠正表单校验', () => {
  const draft = { content: '改过之后的内容', occurredAtLocal: '2026-10-02T09:30' };

  it('合法草稿返回可解析的带时区 ISO 串', () => {
    const iso = validateCorrectionDraft(draft, '原内容');
    expect(iso).toContain('T');
    // 判据是「可被 Date 解析」而不是匹配某个正则：后端要的是「带时区的合法时刻」，
    // 而 `toISOString` 的形状（UTC + Z）只是它的一种。
    expect(Number.isNaN(new Date(iso).getTime())).toBe(false);
  });

  it('空内容与无法解析的时间都被拒', () => {
    expect(() => validateCorrectionDraft({ ...draft, content: '  ' }, '原内容')).toThrow(CorrectionValidationError);
    expect(() => validateCorrectionDraft({ ...draft, occurredAtLocal: '' }, '原内容')).toThrow(CorrectionValidationError);
  });

  it('内容与原内容逐字相同 → 拒（服务端也会 422：纠正无新内容）', () => {
    expect(() => validateCorrectionDraft({ ...draft, content: '原内容' }, '原内容')).toThrow(CorrectionValidationError);
  });
});
