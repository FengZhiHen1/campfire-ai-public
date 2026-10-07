/**
 * 模块: features/profile/test/fixtures
 * 职责: 档案面的测试夹具——支持对象、条目与端口替身，形状由端口与线格式类型同源约束
 * 数据来源:
 *   - features/profile/application/ports: MUST — ProfilePort（替身必须过同一类型）
 *   - shared/types/profile: MUST — ProfileItem 与 SupportObject 的字段全集
 * 边界:
 *   - 依赖: shared/types/profile、features/profile/application/ports
 *   - 被依赖: features/profile 的测试（只用于测试，不进生产 bundle）
 * 禁止行为:
 *   - 禁止在夹具里发明契约未定义的字段
 *   - 禁止让夹具绕过类型检查（不用 any 断言；字段缺失必须由类型报错暴露）
 */

import { vi } from 'vitest';

import type { ProfileItem, SupportObject } from '../../../shared/types/profile';
import type { ProfilePort } from '../application/ports';

/** 造一条档案条目；缺省是一条已确认的稳定条目。 */
export function profileItem(overrides: Partial<ProfileItem> = {}): ProfileItem {
  return {
    item_id: 'i1',
    support_object_id: 'o1',
    domain: 'communication',
    topic: '表达方式',
    description: '用图片卡表达需求',
    contexts: [],
    manifestations: [],
    person_report: null,
    probable_need: null,
    helpful_support: [],
    unhelpful_support: [],
    origin: 'user_statement',
    source: {},
    confirmation: 'confirmed',
    freshness: 'current',
    first_recorded_at: '2026-10-02T09:00:00Z',
    last_confirmed_at: '2026-10-02T09:00:00Z',
    superseded_by: null,
    ...overrides,
  };
}

/** 造一个支持对象。 */
export function supportObject(id: string, name: string, archivedAt: string | null = null): SupportObject {
  return { id, display_name: name, archived_at: archivedAt };
}

/**
 * 端口替身；缺省「一个对象 + 一条稳定条目 + 一条候选」，与档案页首屏一致。
 *
 * 每个方法都是 `vi.fn`，用例可以按需覆盖其中一个来制造时序（例如挂起不决的 Promise）。
 */
export function profilePort(overrides: Partial<ProfilePort> = {}): ProfilePort {
  return {
    listObjects: vi.fn(async () => ({ items: [supportObject('o1', '小宝')] })),
    createObject: vi.fn(async (name: string) => supportObject('o2', name)),
    patchObject: vi.fn(async (id: string) => supportObject(id, '小宝')),
    getSummary: vi.fn(async () => ({
      fields: [
        {
          key: 'communication',
          label: '沟通',
          items: [
            {
              item_id: 'i1',
              origin: 'user_statement' as const,
              last_confirmed_at: '2026-10-02T09:00:00Z',
              text: '用图片卡表达需求',
            },
          ],
        },
      ],
      has_profile: true,
    })),
    listItems: vi.fn(async () => ({
      items: [profileItem()],
      candidates: [
        profileItem({
          item_id: 'c1',
          topic: '提前知道结束时间',
          origin: 'ai_inference',
          confirmation: 'unconfirmed',
          freshness: 'current',
        }),
      ],
      next_cursor: null,
    })),
    confirmItem: vi.fn(async (itemId: string) => ({ item_id: itemId, confirmation: 'confirmed' as const })),
    correctItem: vi.fn(async (itemId: string) => ({ item_id: 'new1', supersedes: itemId })),
    rejectItem: vi.fn(async (itemId: string) => ({ item_id: itemId, confirmation: 'rejected' as const })),
    deleteItem: vi.fn(async (itemId: string) => ({ item_id: itemId, already: false })),
    addItem: vi.fn(async () => ({ item_id: 'new2' })),
    ...overrides,
  };
}
