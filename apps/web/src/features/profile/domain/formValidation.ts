/**
 * 模块: features/profile/domain/formValidation
 * 职责: 档案页两个表单的领域校验——新建对象的名字、补充/纠正条目的字段
 * 数据来源:
 *   - docs/design/pages/档案页.md: MUST — 第 72 行（去空白后非空的单一字段校验）
 *   - docs/技术设计/面/profile/档案面HTTP契约.md: MUST — 第 1 节 422（空描述、未知领域名、纠正无变更）
 * 边界:
 *   - 依赖: features/profile/domain/domains
 *   - 被依赖: features/profile 的 viewModel
 * 禁止行为:
 *   - 禁止把服务端会拒的载荷放行（空描述、未知领域、纠正无变更都必须在提交前拦下）
 *   - 禁止在此做呈现决策（什么时候展示错误归 viewModel）
 */

import { DOMAIN_FALLBACK, type ProfileDomain, toProfileDomain } from './domains';

/** 字段级错误集合；没有错误的字段不出现。 */
export interface ProfileFieldErrors {
  displayName?: string;
  topic?: string;
  description?: string;
  domain?: string;
}

/**
 * 校验未通过；携带字段级错误。
 *
 * 为什么抛错而不是返回错误对象：返回 `{ok, errors}` 时「忘了看 ok 就提交」
 * 是一条静默失效路径；抛错让漏检不可能通过（与 accounts 的 ValidationError 同一形状）。
 */
export class ProfileValidationError extends Error {
  constructor(readonly fieldErrors: ProfileFieldErrors) {
    super('表单校验未通过');
    this.name = 'ProfileValidationError';
  }
}

/** 新建/改名对象的名字：去空白后非空即可（契约第 2.1 节；同名不拒）。 */
export function validateObjectName(raw: string): ProfileFieldErrors {
  return raw.trim() === '' ? { displayName: '名字不能为空' } : {};
}

/** 补充或纠正条目的草稿。 */
export interface ItemDraft {
  domain: string;
  topic: string;
  description: string;
}

/**
 * 空草稿：领域默认落在兜底项，使用者可以改。
 *
 * 「什么算空」与「什么算已编辑」必须是同一份判据（`emptyItemDraft` 与 `itemDraftChanged`），
 * 否则两处会各自漂移：只比较主题与描述时，「先选好领域、还没写内容」的草稿会被判成没编辑
 * 过，切换对象或转入另一个表单时就静默丢掉了这次选择。
 */
export function emptyItemDraft(): ItemDraft {
  return { domain: DOMAIN_FALLBACK, topic: '', description: '' };
}

/**
 * 草稿相对空草稿是否有改动——领域从默认值改开也算改动。
 *
 * 为什么领域也要算：它是使用者的一次显式选择，丢掉它和丢掉已输入的正文是同一类问题
 * （档案页第 98 行「保护未保存草稿」不区分字段）。
 */
export function itemDraftChanged(draft: ItemDraft): boolean {
  const blank = emptyItemDraft();
  return draft.domain !== blank.domain || draft.topic.trim() !== '' || draft.description.trim() !== '';
}

/**
 * 校验补充/纠正条目的草稿。
 *
 * 三条判据与服务端的 422 一一对应：空描述、未知领域名、以及（纠正时）
 * 描述与原条目的描述相同——最后一条在调用方比对后传入 `unchanged`，
 * 因为「有没有变更」需要原条目，而原条目不属于草稿。
 *
 * @param unchanged 纠正场景下，新描述与原描述是否逐字相同。新增场景传 false。
 */
export function validateItemDraft(draft: ItemDraft, unchanged = false): ProfileFieldErrors {
  const errors: ProfileFieldErrors = {};
  if (draft.topic.trim() === '') errors.topic = '主题不能为空';
  if (draft.description.trim() === '') errors.description = '描述不能为空';
  else if (unchanged) errors.description = '内容和原来一样，没有需要更正的地方';
  if (!isKnownDomain(draft.domain)) errors.domain = '请选择一个领域';
  return errors;
}

/** 是否含任何字段错误。 */
export function hasFieldErrors(errors: ProfileFieldErrors): boolean {
  return Object.keys(errors).length > 0;
}

/**
 * 领域取值是否合法（而非「会被归到其他」）。
 *
 * 与 `toProfileDomain` 的区别：那个是读路径的容错（未知取值归「其他」不丢条目），
 * 这个是写路径的严格校验（未知取值必须拦下，否则会被服务端 422 挡回）。
 */
export function isKnownDomain(raw: string): raw is ProfileDomain {
  return raw !== '' && toProfileDomain(raw) === raw;
}
