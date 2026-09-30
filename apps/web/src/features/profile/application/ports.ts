/**
 * 模块: features/profile/application/ports
 * 职责: 档案用例依赖的端口声明（HTTP 实现归 infrastructure）
 * 数据来源:
 *   - docs/技术设计/面/profile/档案面HTTP契约.md: MUST — 第 2～5 节（端点与载荷形状）
 *   - docs/项目结构设计.md: MUST — 第 9 节（application 不导入框架与 HTTP 库）
 * 边界:
 *   - 依赖: shared/types/profile
 *   - 被依赖: features/profile 的用例
 * 禁止行为:
 *   - 禁止在此 import fetch、react 或任何框架模块
 *   - 禁止让端口暴露 status code 或 HTTP 细节（失败分类归 domain/errors）
 */

import type {
  ConfirmProfileItemResponse,
  CorrectProfileItemRequest,
  CorrectProfileItemResponse,
  CreateProfileItemRequest,
  CreateProfileItemResponse,
  DeleteProfileItemResponse,
  ListProfileItemsResponse,
  ListSupportObjectsResponse,
  PatchSupportObjectRequest,
  ProfileSummaryResponse,
  RejectProfileItemResponse,
  SupportObject,
} from '../../../shared/types/profile';

/**
 * 档案端口：档案面契约第 2～5 节的全部端点。
 *
 * 为什么一个端口装下全部端点而不是按资源拆：这些端点共用同一条「越权即 404、
 * 归档即 409」的失败语义，拆开会把同一份错误分类复制到每个端口；
 * 而它们的消费者只有一个页面。
 */
export interface ProfilePort {
  /** 列出当前账号的支持对象，含已归档对象（契约第 2.1 节）。 */
  listObjects(): Promise<ListSupportObjectsResponse>;
  /** 创建支持对象（契约第 2.1 节）；空名由服务端拒为 422。 */
  createObject(displayName: string): Promise<SupportObject>;
  /** 改名 / 归档 / 恢复（契约第 2.2 节）；同一端点的三个状态位赋值。 */
  patchObject(objectId: string, patch: PatchSupportObjectRequest): Promise<SupportObject>;
  /** 一页摘要，只取稳定层（契约第 3 节）。 */
  getSummary(objectId: string): Promise<ProfileSummaryResponse>;
  /** 读取条目；候选层单独成组返回（契约第 3 节）。 */
  listItems(objectId: string, options?: { includeCandidates?: boolean; cursor?: string }): Promise<ListProfileItemsResponse>;
  /** 确认一条候选（契约第 4 节）；只能作用于未确认条目。 */
  confirmItem(itemId: string): Promise<ConfirmProfileItemResponse>;
  /** 纠正 = 新增取代条目（契约第 4 节）。 */
  correctItem(itemId: string, body: CorrectProfileItemRequest): Promise<CorrectProfileItemResponse>;
  /**
   * 否定一条候选（契约第 4.1 节）；不物理删除，此后不再作候选。
   *
   * 本包**未在界面暴露**这一动作：档案页设计给候选行的操作只有「确认」「删除」
   * 两个（第 24 行），而否定是语义不同的第三条路径。端口保留它是因为端口是
   * 「本面对外形状」的声明，不是「当前页面用到的子集」；不自行发明第三个按钮
   * 也如实登记在交付报告的未决问题节。
   */
  rejectItem(itemId: string): Promise<RejectProfileItemResponse>;
  /** 删除一条条目（契约第 4 节）。 */
  deleteItem(itemId: string): Promise<DeleteProfileItemResponse>;
  /** 手动补充一条（契约第 5 节）；origin 由服务端定为 user_statement。 */
  addItem(objectId: string, body: CreateProfileItemRequest): Promise<CreateProfileItemResponse>;
}
