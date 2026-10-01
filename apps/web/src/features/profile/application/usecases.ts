/**
 * 模块: features/profile/application/usecases
 * 职责: 档案页的用例编排——加载（对象+摘要+条目）、确认/否定/纠正/删除、补充、对象管理
 * 数据来源:
 *   - docs/技术设计/面/profile/档案面HTTP契约.md: MUST — 第 2～5 节（端点语义）
 *   - docs/design/pages/档案页.md: MUST — 状态覆盖表（提交失败保留已填内容）
 * 边界:
 *   - 依赖: features/profile/domain、features/profile/application/ports
 *   - 被依赖: features/profile 的 viewModel
 * 禁止行为:
 *   - 禁止在此持有 UI 状态（busy/error 归 viewModel）
 *   - 禁止把校验放在 viewModel（同一份规则必须被纠正与补充两条路径复用）
 *   - 禁止按角色名或界面隐藏做授权判断（越权由服务端 404 表达）
 */

import type { ProfileItem, ProfileSummaryField, SupportObject } from '../../../shared/types/profile';
import { hasFieldErrors, type ItemDraft, ProfileValidationError, validateItemDraft, validateObjectName } from '../domain/formValidation';
import type { ProfilePort } from './ports';

/** 一页档案的完整快照。 */
export interface ProfileSnapshot {
  objects: SupportObject[];
  selectedObjectId: string | null;
  summary: ProfileSummaryField[];
  hasProfile: boolean;
  /**
   * 完整条目区的条目：稳定层，外加曾属稳定层的历史（已被取代）条目。
   * 历史条目在 `include_superseded` 打开时返回；归组由服务端判（`AC-18` 的服务端侧保证，
   * 前端不重做）：历史且未确认的系统推断归 `candidates`，不落在这里。
   */
  items: ProfileItem[];
  /** 候选层条目；由服务端单独成组返回（`AC-18` 的服务端侧保证）。 */
  candidates: ProfileItem[];
}

/** 对象操作：三个状态位赋值的判别联合（契约第 2.2 节合在一个端点的原因）。 */
export type ObjectAction = { kind: 'rename'; displayName: string } | { kind: 'archive' } | { kind: 'restore' };

/**
 * 加载当前账号的档案页数据。
 *
 * 为什么「选中的对象」由用例决定而不是 viewModel：选择规则（没选就取第一个、
 * 选中的已不在列表里就回退到第一个）是业务规则；viewModel 只负责把结果放进状态。
 */
export class LoadProfileUseCase {
  constructor(private readonly port: ProfilePort) {}

  /**
   * 执行加载。
   *
   * 前置: 无
   * 后置: 返回对象列表与选中对象的摘要/条目；无对象时 selectedObjectId 为 null、
   *      摘要与条目为空数组
   * @throws 端口异常原样抛出——对象列表失败由调用方整页报错，单对象详情失败由调用方
   *      只报内容区错误（对象切换器保持可用，档案页状态覆盖表）
   */
  async execute(preferredObjectId: string | null): Promise<ProfileSnapshot> {
    const { items: objects } = await this.port.listObjects();
    const selectedObjectId = pickObjectId(objects, preferredObjectId);
    if (selectedObjectId === null) {
      return { objects, selectedObjectId: null, summary: [], hasProfile: false, items: [], candidates: [] };
    }
    return { ...(await this.loadObject(selectedObjectId)), objects, selectedObjectId };
  }

  /**
   * 只加载一个对象的内容区（切换对象与刷新内容共用这一条）。
   *
   * 后置: 返回摘要与两组条目；候选层只取第一页（它是「待确认」小分组，不是可分页的流）
   * 请求形状: 两个开关都打开——候选层是页面的一等分组，历史（已被取代）条目按档案页第 62 行
   *      必须在列表里可见（行首「已更正」标）；只开前者会让纠正后的旧条目凭空消失。
   * @throws 端口异常原样抛出
   */
  async loadObject(objectId: string): Promise<Omit<ProfileSnapshot, 'objects' | 'selectedObjectId'>> {
    const [summary, listed] = await Promise.all([
      this.port.getSummary(objectId),
      this.port.listItems(objectId, { includeCandidates: true, includeSuperseded: true }),
    ]);
    return {
      summary: summary.fields,
      hasProfile: summary.has_profile ?? summary.fields.length > 0,
      items: listed.items,
      candidates: listed.candidates,
    };
  }
}

/**
 * 选中的对象标识：优先沿用调用方的选择，否则取列表第一个。
 *
 * 已归档对象也在列表里（契约第 2.1 节），因此这里不做「跳过归档」的过滤——
 * 归档对象仍可查看与纠正，把它的内容藏起来会让使用者以为记录丢了。
 */
export function pickObjectId(objects: readonly SupportObject[], preferred: string | null): string | null {
  if (preferred !== null && objects.some((object) => object.id === preferred)) return preferred;
  const first = objects[0];
  return first === undefined ? null : first.id;
}

/** 确认一条候选（契约第 4 节）。 */
export class ConfirmItemUseCase {
  constructor(private readonly port: ProfilePort) {}

  /**
 * 后置: 成功后该条目进稳定层
 * @throws 端口异常原样抛出（重复确认会被服务端拒为 422）
 */
  async execute(itemId: string): Promise<void> {
    await this.port.confirmItem(itemId);
  }
}

/** 删除一条条目（契约第 4 节）；二次确认由视图承担，服务端不做「猜你不是故意的」。 */
export class DeleteItemUseCase {
  constructor(private readonly port: ProfilePort) {}

  /** 后置: 成功后该条目在检索与衍生中不再被使用（`AC-08`）。 */
  async execute(itemId: string): Promise<void> {
    await this.port.deleteItem(itemId);
  }
}

/**
 * 纠正一条条目（契约第 4 节）：新增取代条目，旧条目转历史，不物理覆盖。
 *
 * @throws ProfileValidationError 草稿未通过校验（未发起任何请求）
 * @throws 端口异常原样抛出（401/404/409/422 由 domain/failures 分类）
 */
export class CorrectItemUseCase {
  constructor(private readonly port: ProfilePort) {}

  /**
   * 执行纠正。
   *
   * 前置: draft 是新条目的完整形状而不是补丁；`originalDescription` 用于拦下
   *      「内容没变」的提交（服务端也会拒为 422，这里提前给出可读的原因）
   * 后置: 返回新条目标识与它取代的旧条目标识
   * @throws ProfileValidationError（未发起请求）；端口异常原样抛出
   */
  async execute(itemId: string, draft: ItemDraft, originalDescription: string): Promise<{ itemId: string; supersedes: string }> {
    const errors = validateItemDraft(draft, draft.description === originalDescription);
    if (hasFieldErrors(errors)) throw new ProfileValidationError(errors);
    const result = await this.port.correctItem(itemId, {
      description: draft.description,
      topic: draft.topic,
    });
    return { itemId: result.item_id, supersedes: result.supersedes };
  }
}

/**
 * 手动补充一条（契约第 5 节）；origin 由服务端定为 user_statement。
 *
 * @throws ProfileValidationError 草稿未通过校验（未发起任何请求）
 * @throws 端口异常原样抛出（归档对象为 409，由 domain/failures 分类）
 */
export class AddItemUseCase {
  constructor(private readonly port: ProfilePort) {}

  /**
   * 前置: draft.domain 必须是闭集内取值（未知取值由校验拦下，不交给服务端 422）
   * 后置: 返回新条目标识
   * @throws ProfileValidationError（未发起请求）；端口异常原样抛出（归档对象为 409）
   */
  async execute(objectId: string, draft: ItemDraft): Promise<string> {
    const errors = validateItemDraft(draft);
    if (hasFieldErrors(errors)) throw new ProfileValidationError(errors);
    const result = await this.port.addItem(objectId, {
      domain: draft.domain,
      topic: draft.topic,
      description: draft.description,
      contexts: [],
      manifestations: [],
    });
    return result.item_id;
  }
}

/**
 * 新建支持对象（契约第 2.1 节）。对话式创建是一等入口，这是补充路径。
 *
 * @throws ProfileValidationError 名字去空白后为空（未发起任何请求）
 * @throws 端口异常原样抛出
 */
export class CreateObjectUseCase {
  constructor(private readonly port: ProfilePort) {}

  /**
   * 前置: displayName 去空白后非空（空名由校验拦下，不弹错——单一字段不需要错误态）
   * 后置: 返回新对象
   * @throws ProfileValidationError（未发起请求）；端口异常原样抛出
   */
  async execute(displayName: string): Promise<SupportObject> {
    const errors = validateObjectName(displayName);
    if (hasFieldErrors(errors)) throw new ProfileValidationError(errors);
    return this.port.createObject(displayName.trim());
  }
}

/**
 * 对象操作（改名 / 归档 / 恢复，契约第 2.2 节）。
 *
 * @throws ProfileValidationError 改名时名字去空白后为空（未发起任何请求）
 * @throws 端口异常原样抛出
 */
export class UpdateObjectUseCase {
  constructor(private readonly port: ProfilePort) {}

  /**
   * 前置: `rename` 动作的 displayName 去空白后非空
   * 后置: 返回更新后的对象；归档与恢复幂等（服务端保证）
   * @throws ProfileValidationError（未发起请求）；端口异常原样抛出
   */
  async execute(objectId: string, action: ObjectAction): Promise<SupportObject> {
    if (action.kind === 'archive') return this.port.patchObject(objectId, { archived: true });
    if (action.kind === 'restore') return this.port.patchObject(objectId, { archived: false });
    const errors = validateObjectName(action.displayName);
    if (hasFieldErrors(errors)) throw new ProfileValidationError(errors);
    return this.port.patchObject(objectId, { display_name: action.displayName.trim() });
  }
}
