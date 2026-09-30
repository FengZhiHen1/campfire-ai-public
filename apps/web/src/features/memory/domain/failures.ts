/**
 * 模块: features/memory/domain/failures
 * 职责: 记忆面失败的分类与文案，以及纠正两步的中间态判定
 * 数据来源:
 *   - docs/技术设计/面/profile/记忆面HTTP契约.md: MUST — 第 2 节错误码、第 5 节两步语义、第 6 节空与失败必须可区分
 *   - docs/design/pages/记忆页.md: MUST — 第 59、62 行（图库不可用的文案、中间态文案）
 * 边界:
 *   - 依赖: shared/types/memory（只取响应的判别字段，不 import 传输实现）
 *   - 被依赖: features/memory 的 viewModel 与 view
 * 禁止行为:
 *   - 禁止把 503（图库不可用）呈现成「还没有记录」——空与失败必须可区分
 *   - 禁止把中间态文案写进后端响应（它是前端文案；后端只给结构化标记）
 */

import type { CorrectMemoryEpisodeResponse } from '../../../shared/types/memory';

/** 记忆面失败的分类。 */
export type MemoryFailure =
  | { kind: 'unauthorized' }
  | { kind: 'not-found' }
  | { kind: 'invalid-payload' }
  | { kind: 'graph-unavailable' }
  | { kind: 'unknown' };

/** 从任意异常对象里取 HTTP 状态码；取不到返回 null。 */
function statusOf(error: unknown): number | null {
  if (typeof error !== 'object' || error === null) return null;
  const status = (error as { status?: unknown }).status;
  return typeof status === 'number' ? status : null;
}

/**
 * 按 HTTP 状态码分类。
 *
 * 503 单独成型是本面最要紧的一条：图库不可用与「没有记忆」在界面上必须是两件事
 * （契约第 6 节、记忆页第 59 行）。
 */
export function classifyMemoryFailure(status: number): MemoryFailure {
  switch (status) {
    case 401:
      return { kind: 'unauthorized' };
    case 404:
      return { kind: 'not-found' };
    case 422:
      return { kind: 'invalid-payload' };
    // 后端在配置缺失时也可能用 500 表达「图库不可用」（`_unavailable` 的默认码），
    // 因此 5xx 一并归入「暂时读不到」这一类，而不是含糊的 unknown。
    case 500:
    case 502:
    case 503:
    case 504:
      return { kind: 'graph-unavailable' };
    default:
      return { kind: 'unknown' };
  }
}

/** 把任意异常分类成记忆面失败。 */
export function failureFromError(error: unknown): MemoryFailure {
  return classifyMemoryFailure(statusOf(error) ?? 0);
}

/** 失败对应的界面标题。 */
export function memoryFailureTitle(failure: MemoryFailure): string {
  switch (failure.kind) {
    case 'unauthorized':
      return '登录状态已失效';
    case 'not-found':
      return '这条记录不存在';
    case 'invalid-payload':
      return '这次提交没有通过校验';
    case 'graph-unavailable':
      // 明确不写「你还没有记录」（记忆页第 59 行）。
      return '暂时无法读取记录';
    case 'unknown':
      return '暂时无法读取记录';
  }
}

/** 失败对应的说明与下一步。 */
export function memoryFailureDescription(failure: MemoryFailure): string {
  switch (failure.kind) {
    case 'unauthorized':
      return '请重新登录后再试。';
    case 'not-found':
      return '它可能已被删除或不属于当前账号，请刷新后重试。';
    case 'invalid-payload':
      return '请检查填写的内容后重新提交。';
    case 'graph-unavailable':
      // 删除与纠正的「撤下」仍可用（账本在本库），但读取不行——如实说明重试即可。
      return '记录暂时读不出来，这不等于没有记录；请稍后重试。';
    case 'unknown':
      return '记录暂时读不出来，这不等于没有记录；请稍后重试。';
  }
}

/** 是否给「重试」按钮：不存在与越权重试无用。 */
export function isRetryable(failure: MemoryFailure): boolean {
  return failure.kind === 'graph-unavailable' || failure.kind === 'unknown';
}

/**
 * 纠正提交结果的判别联合。
 *
 * 两步的语义不同（契约第 5 节），因此结果也必须分成两个可区分的形态：
 * 写成了，还是只撤下了旧的而新的没写成。
 */
export type CorrectionOutcome = { kind: 'written'; episodeKey: string } | { kind: 'superseded-only' };

/**
 * 从响应判定纠正处在哪一步。
 *
 * 判据是 `new_episode_written` 这个结构化标记，不是状态码，也不是文案——
 * 后端把中间态以 200 返回（成功是 201），而共享客户端只透出载荷；
 * 文案则是前端的事，后端不该为了界面措辞而改响应。
 *
 * 前置: 响应形状已通过线格式类型校验（类型层保证）
 * 后置: `new_episode_written` 为真且带标识时返回 `written`；否则返回 `superseded-only`
 * 异常: 无
 */
export function correctionOutcome(response: CorrectMemoryEpisodeResponse): CorrectionOutcome {
  if (response.new_episode_written && response.episode_key !== null) {
    return { kind: 'written', episodeKey: response.episode_key };
  }
  return { kind: 'superseded-only' };
}

/**
 * 中间态的界面文案（前端文案，不进后端响应）。
 *
 * 逐字取自记忆页设计第 62 行：不得笼统报成功或失败——旧记录已经不再作为依据了，
 * 使用者需要知道「现在的状态」与「下一步做什么」。
 */
export const CORRECTION_INTERMEDIATE_COPY = '原记录已不再作为依据，但新记录没写成，请重试';

/** 纠正成功的提示。 */
export const CORRECTION_WRITTEN_COPY = '已新增一条更正，原记录不再作为依据';
