/**
 * 模块: features/memory/domain/formValidation
 * 职责: 纠正表单的领域校验——发生时间可解析、内容非空且与原内容不同
 * 数据来源:
 *   - docs/技术设计/面/profile/记忆面HTTP契约.md: MUST — 第 2 节 422（纠正无新内容）
 *   - docs/design/pages/记忆页.md: MUST — 第 61、62 行（提交失败保留已填内容）
 * 边界:
 *   - 依赖: features/memory/domain/episodes（时间解析）
 *   - 被依赖: features/memory 的用例
 * 禁止行为:
 *   - 禁止放过空内容或无法解析的时间（服务端会 422，前端应提前给出可读原因）
 */

import { fromDatetimeLocalValue } from './episodes';

/** 纠正表单的字段级错误。 */
export interface CorrectionFieldErrors {
  content?: string;
  occurredAt?: string;
}

/** 纠正草稿（表单值，时间是 datetime-local 的本地值）。 */
export interface CorrectionDraft {
  content: string;
  occurredAtLocal: string;
}

/**
 * 校验未通过。携带字段级错误，并携带已转换好的 ISO 时间（校验通过时）。
 */
export class CorrectionValidationError extends Error {
  constructor(readonly fieldErrors: CorrectionFieldErrors) {
    super('纠正表单校验未通过');
    this.name = 'CorrectionValidationError';
  }
}

/**
 * 校验纠正草稿。
 *
 * `unchanged` 由调用方比对原 `content` 后传入：内容逐字相同即「没有新内容」，
 * 与服务端的 422（纠正无新内容）一一对应。
 *
 * @returns 校验通过时返回可直接提交的 ISO 时间串。
 * @throws CorrectionValidationError 有字段级错误（未发起任何请求）
 */
export function validateCorrectionDraft(draft: CorrectionDraft, originalContent: string): string {
  const errors: CorrectionFieldErrors = {};
  const occurredAt = fromDatetimeLocalValue(draft.occurredAtLocal);
  if (occurredAt === null) errors.occurredAt = '请填写有效的发生时间';
  if (draft.content.trim() === '') errors.content = '内容不能为空';
  else if (draft.content === originalContent) errors.content = '内容和原来一样，没有需要更正的地方';
  if (Object.keys(errors).length > 0 || occurredAt === null) throw new CorrectionValidationError(errors);
  return occurredAt;
}
