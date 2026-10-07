// 端口适配层:把导出的真实数据包装成产品页面需要的 Port 接口。
//
// 为什么需要这一层:
//   真实页面组件(ProfilePage/LibraryPage/…)通过 Port 取数,Port 的实现走 HTTP + auth。
//   影片里不能登录、也不该有网络往返(不确定 + 慢)。所以用**内存实现**替换 Port,
//   数据来自 .tmp/export-fixtures.py 从本地数据库导出的真实记录(data.generated.ts)。
//
// 边界(重要):
//   - 本层只做「形状转换 + 内存返回」,不编造任何业务内容 —— 所有文本都来自 fixture。
//   - 不引入 fetch/supertokens;不修改产品源码。
import type {ProfileItem, ProfileSummaryResponse, SupportObject} from '../../../../apps/web/src/shared/types/profile';
import type {
  EvidenceLevel,
  LibraryItemStatus,
  LibraryKind,
  LibraryListItem,
  ReviewStatus,
} from '../../../../apps/web/src/shared/types/library';
// ★ 领域标签必须取产品真源,不得自造。
//   初版这里手写了一组 LABELS(sensory_processing:'感官处理' / communication:'沟通方式' /
//   risk_and_crisis:'风险与安全' / routines_and_change:'作息与变化'),与产品的
//   DOMAIN_LABELS 四个键**全部不一致** —— 而「渲染真实产品」正是本次转向的根本前提。
//   实现在 apps/web/src/features/profile/domain/domains.ts。
import {domainLabel} from '../../../../apps/web/src/features/profile/domain/domains';
import {FIXTURE_DATA} from '../fixtures/data.generated';
import {MEMORY_EPISODES} from '../fixtures/memory.generated';

const OBJECT: SupportObject = {
  id: FIXTURE_DATA.supportObject.id,
  display_name: FIXTURE_DATA.supportObject.display_name,
  archived_at: null,
};

/** 全部档案条目(真实导出,字段与 ProfileItem 对齐)。 */
export const PROFILE_ITEMS: readonly ProfileItem[] = FIXTURE_DATA.profileItems as unknown as readonly ProfileItem[];

/** 已确认条目。 */
export const CONFIRMED_ITEMS = PROFILE_ITEMS.filter((i) => i.confirmation === 'confirmed');

/** 候选(待确认)条目。 */
export const CANDIDATE_ITEMS = PROFILE_ITEMS.filter((i) => i.confirmation === 'unconfirmed');

/**
 * 档案端口的内存实现。
 *
 * 只实现影片用到的读路径;写路径(confirm/correct/reject)返回成功形状但不改数据 ——
 * 影片里的「确认」动作靠帧驱动的视觉状态表达,不依赖真实写入。
 */
export function makeProfilePort() {
  return {
    listObjects: async () => ({items: [OBJECT]}),
    getSummary: async (): Promise<ProfileSummaryResponse> => {
      // 摘要按 domain 分组,只取已确认条目(与产品「摘要只取稳定层」一致)
      const byDomain = new Map<string, typeof CONFIRMED_ITEMS>();
      for (const item of CONFIRMED_ITEMS) {
        const list = byDomain.get(item.domain) ?? [];
        byDomain.set(item.domain, [...list, item]);
      }
      return {
        has_profile: true,
        fields: [...byDomain.entries()].map(([domain, list]) => ({
          key: domain,
          // ★ 用产品真源的 domainLabel(),不自造文案。未知取值会落到「其他」(产品行为)。
          label: domainLabel(domain),
          items: list.map((i) => ({
            item_id: i.item_id,
            origin: i.origin,
            last_confirmed_at: i.last_confirmed_at,
            text: i.description,
          })),
        })),
      };
    },
    listItems: async () => ({items: [...CONFIRMED_ITEMS], candidates: [...CANDIDATE_ITEMS], next_cursor: null}),
    confirmItem: async (itemId: string) => ({item_id: itemId, confirmation: 'confirmed' as const}),
    correctItem: async (itemId: string) => ({item_id: itemId, supersedes: itemId}),
    rejectItem: async (itemId: string) => ({item_id: itemId, confirmation: 'rejected' as const}),
    deleteItem: async (itemId: string) => ({item_id: itemId, already: false}),
    /**
     * 手动新增条目。
     *
     * 影片不使用写路径(「确认/纠正」由帧驱动的视觉状态表达,不依赖真实写入),
     * 但 ProfilePort 契约要求该方法存在 —— 返回一个确定性 id。
     * 刻意**不用 Date.now()**:那会让同一帧两次渲染结果不同,违反确定性渲染。
     */
    addItem: async (_objectId: string, body: {description: string; topic?: string}) => ({
      item_id: 'fixture-added-item',
      topic: body.topic ?? '',
      description: body.description,
    }),
    createObject: async (displayName: string) => ({id: OBJECT.id, display_name: displayName, archived_at: null}),
    patchObject: async () => OBJECT,
  };
}

/** 知识/案例条目(真实导出)。 */
export const KNOWLEDGE_ITEMS = FIXTURE_DATA.knowledge;
export const CASE_ITEMS = FIXTURE_DATA.cases;

/**
 * 记忆端口的内存实现(账号级时间线)。
 *
 * 数据来自 `memory.generated.ts` —— 由 `verify/memory-episodes.py export` 走
 * **产品读路径**(`modules.memory.store.read_timeline`,内部做删除账本过滤)导出,
 * 与 `data.generated.ts` 的区别只是数据源(记忆在图库、档案在关系库)。
 *
 * 与 `makeProfilePort` 同一条边界:只实现读路径;写路径(删除/纠正)返回成功形状
 * 但**不改数据** —— 影片里的动作用帧驱动的视觉状态表达,不依赖真实写入
 * (真实写入会改变账号数据,而影片只是演示)。
 */
export function makeMemoryPort() {
  return {
    listEpisodes: async () => ({items: [...MEMORY_EPISODES], next_cursor: null}),
    deleteEpisode: async (episodeKey: string) => ({
      episode_key: episodeKey,
      newly_deleted: true,
      reason: 'user_request' as const,
    }),
    correctEpisode: async (episodeKey: string, body: {occurred_at: string; content: string}) => ({
      superseded: true,
      // 影片不演「纠正已写入」的中间态,因此如实给 true;正文不回写(见上方边界)。
      new_episode_written: true,
      episode_key: `fixture-corrected:${body.occurred_at}`,
      supersedes: episodeKey,
    }),
  };
}

/**
 * 案例库端口的内存实现。
 *
 * 两个库分开返回。条目形状按产品真源 shared/types/library.ts 的
 * LibraryListItem 构造:除 LibraryItem 的必填字段外,还带 narrative 与 cards
 * (列表页展开某一条时会渲染它们)。
 *
 * ★ 2026-10-07 跟随产品改动:该类型原名 ExpandedLibraryItem,产品的 3e33346 把它
 *   改名为 LibraryListItem 并把 narrative/cards 改为**可空** —— 普通列表请求里两者
 *   恒为 null,旧名与必填写法让守卫判 undefined,生产上点开任一条即被错误边界接管。
 *   影片这里仍然填非空值(它是「展开后」的静态画面),但类型必须跟随产品,否则 tsc
 *   直接报 no exported member(实测踩到:用户提交后影片源码一度编译不过)。
 *
 * narrative / cards 的内容也来自数据库导出的真实字段(narrative 用 title+snippet,
 * cards 为空数组 —— 影片不展开正文,只展示列表与状态标签)。
 */
export function makeLibraryPort() {
  const toItem = (
    raw: {
      id: string;
      title: string;
      source: string;
      applicable_scope: string;
      status: string;
      source_type?: string;
      authorization?: string;
      evidence_level?: string;
      // ★ 这两个字段**必须**透传:产品的 itemMetaParts()
      //   (apps/web/src/features/library/domain/labels.ts)把案例卡「来源」行
      //   拼成 6 段 —— 来源 + 来源类型 + 证据等级 + **审阅状态** + 授权 + **访谈时间**。
      //   原先这里没接,导致影片的来源行比真实页面少两段
      //   (真机对照实测:真实页面有「项目所有者核准」与「访谈 2026-05-31T00:50:00Z」)。
      //   产品注释写明「缺字段不补默认值」,所以这不是装饰,而是案例功能的一部分。
      review_status?: string;
      interview_at?: string | null;
      // ★ 首个内容节点文本。真实页面的 `.lr-sub` 显示的就是它
      //   (后端 `_first_node_summary()` 按 node_id 排序取该条目第一个节点)。
      //   原先这里硬写 `snippet: raw.title` ⇒ 摘要行只是**重复标题**,
      //   而真实页面显示「title：… scenario：…」(独立复核 P4-b 指出,已真机对照证实)。
      snippet?: string | null;
    },
    library: 'case' | 'knowledge',
  ): LibraryListItem =>
    ({
      item_id: raw.id,
      library,
      title: raw.title,
      // 取不到节点时回退到 title —— 但导出器会报出有多少条取不到,以便发现规则漂移。
      snippet: raw.snippet ?? raw.title,
      source: raw.source,
      applicable_scope: raw.applicable_scope,
      status: raw.status as LibraryItemStatus,
      locator: raw.id,
      ranking: {rank: 1, matched_by: ['browse']},
      source_type: raw.source_type,
      authorization: raw.authorization,
      evidence_level: raw.evidence_level as EvidenceLevel | undefined,
      review_status: raw.review_status as ReviewStatus | undefined,
      // interview_at 为 null 时不要传空串:itemMetaParts 用 `!== ''` 判断,
      // 传空串会拼出一段空的「访谈 」。
      interview_at: raw.interview_at ?? undefined,
      // 展开字段:影片不展开正文,但类型要求存在
      narrative: {sections: []},
      cards: [],
    }) as unknown as LibraryListItem;

  return {
    listItems: async ({library}: {library: LibraryKind}) => ({
      library,
      items:
        library === 'case'
          ? CASE_ITEMS.map((c) => toItem(c, 'case'))
          : KNOWLEDGE_ITEMS.map((k) => toItem(k, 'knowledge')),
      next_cursor: null,
    }),
    getItem: async (itemId: string) => {
      const c = CASE_ITEMS.find((x) => x.id === itemId);
      if (c) return {item: toItem(c, 'case')};
      const k = KNOWLEDGE_ITEMS.find((x) => x.id === itemId);
      if (k) return {item: toItem(k, 'knowledge')};
      return {item: null};
    },
  };
}
