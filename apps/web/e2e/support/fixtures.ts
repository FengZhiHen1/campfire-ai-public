/**
 * 模块: e2e/support/fixtures
 * 职责: 逐页数据夹具与内容断言清单——免后端截图的唯一数据来源
 * 数据来源:
 *   - docs/证据/orchestrator-20261002-001/T01.md: MUST — 裁决 D（page.route 固定 JSON、fail-closed、真实感中文文案）
 *     与裁决 F（逐页内容断言的观察特征）
 *   - apps/web/src/shared/types/{consult,profile,library,memory}.ts: MUST — 夹具的线格式形状
 *   - apps/web/src/infrastructure/{http,consult}/*.ts: MUST — 各页实际发出的路径与方法
 *   - apps/web/src/features 下各特性的 viewModel: MUST — 各页挂载时真正发起的请求集合
 * 边界:
 *   - 依赖: @playwright/test、e2e/support/assertions
 *   - 被依赖: e2e/shots.spec.ts
 * 禁止行为:
 *   - 禁止用 `foo`/`lorem`/`测试1` 这类占位文案（截图用于人工目视判断版式）
 *   - 禁止改写设计文档的硬文案：需要展示硬文案处逐字取自设计文档
 *   - 禁止给未命中的请求一个「看起来正常」的空响应（那会把空态渲染成假绿）
 */

import { toolDisplayName } from '../../src/features/consult/view/MessageParts/toolLabels';
import type { ContentAssertion } from './assertions';

/**
 * 一条路由夹具。
 *
 * `path` 用精确 pathname 匹配（不含查询串）：查询串是调用方的意图表达，
 * 而本包关心的是「这一页会不会打到一个没人应答的端点」。忽略查询串也让夹具在
 * 端点新增查询参数时不会静默失配。
 */
export interface ApiFixture {
  /** 期望的 HTTP 方法。 */
  method: 'GET' | 'POST' | 'DELETE' | 'PATCH';
  /** 精确 pathname。 */
  path: string;
  /** 响应状态码；省略为 200。 */
  status?: number;
  /**
   * 响应载荷。
   *
   * 允许是函数：需要「相对当前时刻」的时间字段（如会话列表的相对时间）时用它，
   * 使渲染出的相对时间文案不随运行日期漂移。
   */
  body: unknown | (() => unknown);
}

/** 一个页面的截图配置。 */
export interface PageShot {
  /** 语义短名（文件名与 manifest 的键）。 */
  name: string;
  /** 路由路径；`:sessionId` 之类参数直接写成夹具 id 的字面值。 */
  path: string;
  /** 是否受登录守卫保护（决定「未跳转到 /login」这条断言怎么读）。 */
  guarded: boolean;
  /** 本页挂载时应该命中的夹具。 */
  fixtures: readonly ApiFixture[];
  /**
   * 必须未被请求的端点 pathname 前缀。
   *
   * 用途有二：把「本页不需要 SSE」这类判断固化成机器可检的断言（而不是报告里的一句话），
   * 以及拦住「页面偷偷多打了一个没人应答的端点」。
   */
  mustNotRequest?: readonly string[];
  /** 内容断言；至少一条，且必须能在内容缺失时失败。 */
  assertions: readonly ContentAssertion[];
  /** 夹具设计的说明（进 manifest，供审查者理解这些数字从哪来）。 */
  note: string;
}

/**
 * 时间夹具的两种构造方式，按页面怎么渲染这个字段来选，不是随手挑一个。
 *
 * 这两类曾经混用同一个 `Date.now()` 基座，结果是 20 张图里只有记忆页两张不稳定
 * （实测两次运行相差 626 字节）。原因是两类渲染对时间的敏感面不同：
 *
 *   - `agoIso` 给相对时间用（会话列表的 `formatRelativeTime`）。它算的是
 *     「渲染时刻 − 时间戳」，夹具与渲染用的是同一个 `Date.now()` 基座，差值恒定，
 *     因此文案稳定（「12 分钟前」永远不变）。这里必须用真实当前时刻：
 *     换成固定时刻的话，差值会随运行日期一起变，反而把「12 分钟前」渲染成别的档位。
 *   - `atIso` 给绝对时间用（记忆页的 `occurredAtLabel`「发生时间 MM-DD HH:MM」、
 *     档案页的 `formatMonthDay`「MM-DD 确认」）。它们直接呈现时间戳的日期与时分，
 *     与渲染时刻无关——所以夹具必须是固定常量，否则每过一分钟文案就变一次。
 */
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

/** 相对时间的候选桶刻意落在桶中央，避免运行时刻擦到边界把文案换成另一种格式。 */
const RELATIVE_OFFSETS = {
  /** 12 分钟 → 渲染为「12 分钟前」。 */
  minutes12: 12 * MINUTE,
  /** 5 小时 → 「5 小时前」。 */
  hours5: 5 * HOUR,
  /** 30 小时 → 「昨天」（大于 24 且小于 48）。 */
  hours30: 30 * HOUR,
} as const;

/**
 * 生成一个「距当前时刻 offset」的 ISO 时间串。
 *
 * 只给渲染成相对时间的字段用（会话列表的 `updated_at`）；理由见上方两类说明。
 */
function agoIso(offsetMs: number): string {
  return new Date(Date.now() - offsetMs).toISOString();
}

/**
 * 固定的绝对时间点（带 +08:00 偏移，与 playwright.config.ts 的 timezoneId 一致）。
 *
 * 只给渲染成绝对时间的字段用（记忆页的发生时间、档案页的确认/记录日期）。
 * 取值刻意落在有代表性的日期上，让「按日期分组」与「MM-DD 确认」两处文案都能被目视复核。
 */
const FIXED_INSTANTS = {
  /** 较近的一条：日期分组头渲染为「10月2日」。 */
  recent: '2026-10-02T07:08:00+08:00',
  /** 较早的一条：日期分组头渲染为「10月1日」。 */
  earlier: '2026-10-01T06:08:00+08:00',
} as const;

/** 取一个固定绝对时间点的 ISO 串。 */
function atIso(key: keyof typeof FIXED_INSTANTS): string {
  return new Date(FIXED_INSTANTS[key]).toISOString();
}

/**
 * 内容断言消融开关（只给消融实验用）。
 *
 * 置为某页的语义短名时，该页夹具的承载列表被换成空数组——页面会渲染成合法的空态
 * （200 空数组不是失败），于是内容断言必须失败。若它仍然通过，说明那条断言是恒真的，
 * 截图就没有「必须有料」的保障。
 *
 * 读环境变量而不是命令行选项：`playwright test` 会拒绝未知选项（同一理由见 paths.ts）。
 */
const ABLATION_EMPTY_LIST_PAGE: string | undefined = process.env.SHOTS_ABLATION_EMPTY_LIST;

/**
 * 兜底 handler 消融开关（只给消融实验用）。
 *
 * 置为某个夹具的 pathname 时，该夹具被摘掉——于是这个请求落到兜底 handler，
 * 用例必须以非 0 退出并点名该 URL。若它仍然通过，说明兜底 handler 是摆设。
 */
const ABLATION_MISSING_FIXTURE: string | undefined = process.env.SHOTS_ABLATION_MISSING_FIXTURE;

/** 该页是否处于「承载内容改空数组」的消融态。 */
export function isAblationEmptyList(pageName: string): boolean {
  return ABLATION_EMPTY_LIST_PAGE === pageName;
}

/** 该夹具是否被消融摘掉。 */
export function isAblationMissingFixture(path: string): boolean {
  return ABLATION_MISSING_FIXTURE === path;
}

/**
 * 会话列表夹具（会话列表页）。
 *
 * 四个字段即契约第 3.2 节的返回形状（会话列表页设计第 36 行）；不编造第五个字段。
 */
const SESSION_LIST_FIXTURE = (): unknown => ({
  items: [
    {
      session_id: 'sess-1001',
      title: '超市里突然坐下不走，怎么带他离开',
      support_object_name: '小宇',
      updated_at: agoIso(RELATIVE_OFFSETS.minutes12),
      last_message_preview: '先把他带到人少的地方，再决定下一步',
    },
    {
      session_id: 'sess-1002',
      title: '晚上刷牙要磨很久，能不能换个办法',
      support_object_name: '小宇',
      updated_at: agoIso(RELATIVE_OFFSETS.hours5),
      last_message_preview: '把步骤拆成两张图卡贴在洗手台边上',
    },
    {
      session_id: 'sess-1003',
      title: '换了新班主任之后的午休安排',
      support_object_name: null,
      updated_at: agoIso(RELATIVE_OFFSETS.hours30),
      last_message_preview: '先跟老师确认午休位置有没有变',
    },
  ],
  next_cursor: null,
});

/** 对话夹具的会话 id；路由路径与夹具里的 session_id 必须一致。 */
const CHAT_SESSION_ID = 'sess-1001';

/**
 * 历史水合夹具（对话页）。
 *
 * 一条使用者消息 + 一条助手消息：助手消息的 parts 覆盖正文、工具调用、思考与引用
 * 四种渲染器（契约第 7 节的 part 表），使截图能反映对话面的真实形态。
 */
const CHAT_HISTORY_FIXTURE = (): unknown => ({
  session_id: CHAT_SESSION_ID,
  messages: [
    {
      id: 'msg-2001',
      role: 'user',
      parts: [{ type: 'text', text: '他在超市里突然坐下不走，我怎么劝都不动，周围人都在看。' }],
    },
    {
      id: 'msg-2002',
      role: 'assistant',
      parts: [
        { type: 'reasoning', delta: '先判断有没有医疗危险表现，再决定是就地处理还是撤离现场。' },
        { type: 'tool_call', tool_name: 'search_cases', ok: true, summary: '命中 2 条关于超市情境的案例' },
        {
          type: 'text',
          text: '先不劝。他坐下不走，多半是环境里的东西一下子太多，身体先替你踩了刹车。\n\n可以试的顺序是：你在他侧前方半步的地方蹲下来，说话只用短句；如果两分钟内没有变化，就把他连人带东西挪到人少的通道口或者门外，先离开货架和广播这两样。',
        },
        {
          type: 'citation',
          citation: {
            citation_id: 'cit-3001',
            run_id: 'run-4001',
            source: '公共案例库',
            reference: '超市情境下的就地停留：先降刺激再移动',
            // 引用记录的时间不进界面（CitationPart 只渲染 reference/source/summary），
            // 但仍用固定值：夹具里不留「每次求值都不同」的字段，便于逐字段比对。
            recorded_at: atIso('recent'),
            summary: '案例里的做法是先减少环境刺激，再决定是否撤离，不先做劝说。',
          },
        },
      ],
    },
  ],
});

/** 档案夹具的对象 id。 */
const PROFILE_OBJECT_ID = 'obj-5001';

/** 支持对象列表夹具（档案面契约第 2.1 节）。 */
const PROFILE_OBJECTS_FIXTURE = (): unknown => ({
  items: [
    { id: PROFILE_OBJECT_ID, display_name: '小宇', archived_at: null },
    { id: 'obj-5002', display_name: '小禾', archived_at: '2026-08-14T02:10:00.000Z' },
  ],
});

/** 一页摘要夹具（档案面契约第 3 节；只取稳定层）。 */
const PROFILE_SUMMARY_FIXTURE = (): unknown => ({
  has_profile: true,
  fields: [
    {
      key: 'communication',
      label: '沟通',
      items: [
        {
          item_id: 'item-6001',
          origin: 'user_statement',
          // 绝对时间：档案页用 formatMonthDay 渲染成「10-02 确认」，与渲染时刻无关。
          last_confirmed_at: atIso('recent'),
          text: '说得比听得快，需要给他留出五秒以上的空档再问下一句。',
        },
      ],
    },
    {
      key: 'sensory_processing',
      label: '感觉处理',
      items: [
        {
          item_id: 'item-6002',
          origin: 'guardian_observation',
          last_confirmed_at: null,
          text: '对超市的广播声和顶灯很敏感，进门十分钟左右开始明显不安。',
        },
      ],
    },
  ],
});

/** 档案条目夹具（档案面契约第 3 节：items 与 candidates 分开返回）。 */
const PROFILE_ITEMS_FIXTURE = (): unknown => ({
  items: [
    {
      item_id: 'item-6001',
      support_object_id: PROFILE_OBJECT_ID,
      domain: 'communication',
      topic: '需要留出回应的空档',
      description: '问完一句话之后要停住等他，五秒以上他才开始组织回答。',
      contexts: ['家里吃饭时', '学校晨检'],
      manifestations: ['被连问两次就不再回答', '会先看向别处再开口'],
      person_report: '他说过「你一次问太多我不知道先答哪个」。',
      probable_need: '需要把问题一次只留一个。',
      helpful_support: ['问完就停下', '给两个选项而不是开放问题'],
      unhelpful_support: ['重复追问', '替他把话说完'],
      origin: 'user_statement',
      source: { session_id: CHAT_SESSION_ID, message_ref: 'msg-2001', recorded_at: atIso('recent') },
      confirmation: 'confirmed',
      freshness: 'current',
      first_recorded_at: atIso('earlier'),
      last_confirmed_at: atIso('recent'),
      superseded_by: null,
    },
    {
      item_id: 'item-6003',
      support_object_id: PROFILE_OBJECT_ID,
      domain: 'emotional_regulation',
      topic: '音量先于情绪升高',
      description: '情绪上来之前说话音量会先变大，这是比表情更早的信号。',
      contexts: ['写作业时'],
      manifestations: ['音量突然变大', '开始重复同一句话'],
      person_report: null,
      probable_need: '需要在音量变大时就先把任务停下来。',
      helpful_support: ['立刻暂停当前任务', '换个房间再谈'],
      unhelpful_support: ['当场讲道理'],
      origin: 'guardian_observation',
      source: { relayed_by: '妈妈', recorded_at: atIso('earlier') },
      confirmation: 'confirmed',
      freshness: 'historical',
      first_recorded_at: atIso('earlier'),
      last_confirmed_at: null,
      superseded_by: 'item-6004',
    },
  ],
  candidates: [
    {
      item_id: 'item-6005',
      support_object_id: PROFILE_OBJECT_ID,
      domain: 'sensory_processing',
      topic: '对洗手液的气味敏感',
      description: '洗手时会皱鼻子并尽量把手举远，可能是不喜欢洗手液的气味。',
      contexts: ['饭前洗手'],
      manifestations: ['皱鼻子', '把手举远'],
      person_report: null,
      probable_need: null,
      helpful_support: [],
      unhelpful_support: [],
      origin: 'ai_inference',
      source: { session_id: CHAT_SESSION_ID, tool_name: 'propose_profile_item', recorded_at: atIso('recent') },
      confirmation: 'unconfirmed',
      freshness: 'current',
      first_recorded_at: atIso('recent'),
      last_confirmed_at: null,
      superseded_by: null,
    },
  ],
  next_cursor: null,
});

/**
 * 案例库夹具（资料库面契约第 3、3.1 节）。
 *
 * 案例侧的六项必带字段全部给全——缺任一个页面就无法如实回答「谁说的、多可信、什么时候」，
 * 而这正是本页存在的理由。`review_status` 取 owner：它必须显示成「项目所有者核准」。
 */
const LIBRARY_CASE_FIXTURE = (): unknown => ({
  library: 'case',
  items: [
    {
      item_id: 'case-7001',
      library: 'case',
      title: '超市里坐下不走：先降刺激，再移动',
      snippet: '孩子在货架间突然停住不走，家长没有劝说，而是先离开广播与顶灯两个刺激源。',
      source: '家长访谈记录',
      applicable_scope: '学龄前至学龄期，能在提示下跟随移动',
      status: 'published',
      locator: '访谈 2026-08 第 3 段',
      ranking: { rank: 1, channels: ['vector', 'trigram'] },
      authorization: '已获家长书面授权',
      source_type: '家长经验',
      evidence_level: 'OBSERVATIONAL',
      review_status: 'owner',
      interview_at: '2026-08-09',
      makes_claims_high_risk: false,
      inferred_fields: [],
      narrative: {
        sections: [
          { key: 'context', heading: '当时的情境', text: '工作日下午的连锁超市，广播在循环播放促销，顶灯是冷白色。' },
          { key: 'attempt', heading: '试过什么', text: '先蹲下来劝说两分钟，没有变化；随后把人带到通道口，半分钟后起身跟随。' },
        ],
      },
      cards: [
        {
          card_id: 'card-8001',
          scenario: '在货架间突然坐下不走，周围有陌生人和持续广播声',
          immediate_action: '蹲到侧前方半步远的位置，只用短句说话；两分钟内没有变化就先离开刺激源。',
          inferred_fields: [],
          risk_class: 'low',
          comforting_phrase: '我在这儿，我们不着急。',
          observation_metrics: '是否愿意抬头看你',
          parent_category: '公共场合的情境支持',
        },
      ],
    },
    {
      item_id: 'case-7002',
      library: 'case',
      title: '刷牙磨很久：把步骤拆成图卡',
      snippet: '把刷牙拆成三张图卡贴在洗手台边上，孩子按图卡顺序完成，不需要口头催促。',
      source: '家长访谈记录',
      applicable_scope: '能理解两步以上连续指令',
      status: 'fictional',
      locator: '虚构样例，用于演示版式',
      ranking: { rank: 2, channels: ['vector'] },
      authorization: '虚构样例，不含真实个人信息',
      source_type: '虚构样例',
      evidence_level: 'OBSERVATIONAL',
      review_status: 'pending',
      interview_at: '2026-08-21',
      makes_claims_high_risk: false,
      inferred_fields: ['applicable_scope'],
      narrative: { sections: [{ key: 'context', heading: '当时的情境', text: '晚间洗漱时间，家长反复催促导致双方都很累。' }] },
      cards: [],
    },
  ],
  next_cursor: null,
});

/**
 * 记忆时间线夹具（记忆面契约第 3 节）。
 *
 * `occurred_at` 用固定绝对时间（atIso）而不是相对时间：记忆页把它渲染成
 * 「发生时间 10-02 07:08」这样的绝对文案，用相对时间构造会让文案每分钟漂一次
 * （实测：这是 20 张图里唯一不稳定的一组）。
 */
const MEMORY_EPISODES_FIXTURE = (): unknown => ({
  items: [
    {
      episode_key: 'ep-9001',
      occurred_at: atIso('recent'),
      content: '在超市里人多的时候会突然停下不走，需要先离开广播和顶灯。',
      source_session_id: CHAT_SESSION_ID,
    },
    {
      episode_key: 'ep-9002',
      occurred_at: atIso('earlier'),
      content: '换班主任之后午休位置变了，他连着三天没睡着。',
      source_session_id: 'sess-1003',
    },
  ],
  next_cursor: null,
});

/**
 * 十页的截图配置。
 *
 * 顺序即逐页执行顺序，也是 manifest 内的呈现顺序。
 */
export const PAGE_SHOTS: readonly PageShot[] = [
  {
    name: 'login',
    path: '/login',
    guarded: false,
    fixtures: [],
    note: '登录页静态渲染、零取数；会话查证走本地 cookie 解析，不发请求。',
    assertions: [
      { kind: 'text', intent: '品牌区标题与标语可见', minHits: 2, candidates: ['篝火智答', '每一次咨询，都有据可依'] },
      {
        kind: 'visible',
        intent: '品牌区与表单区同屏可见',
        // 只挑稳定标识：`#auth-title` 是页面里的真实 id，`.field` 是契约全局类名。
        // 不用 CSS Modules 的短名（`.brand`）——它在产物里被哈希改名，选择器会静默失配。
        selector: '#auth-title, .field input, .field label',
        minCount: 3,
      },
      { kind: 'text', intent: '表单已渲染为登录态（账号名与密码两个字段）', minHits: 2, candidates: ['账号名', '密码'] },
    ],
  },
  {
    name: 'home',
    path: '/',
    guarded: true,
    fixtures: [],
    note: '首页初始渲染零取数；输入草稿后显式进入对话才创建会话。',
    assertions: [
      {
        kind: 'text',
        intent: '应急入口与日常入口同屏可见',
        minHits: 5,
        candidates: ['现在需要帮助', '日常咨询', '开始应急咨询', '今天，想聊些什么？', '案例库'],
      },
      { kind: 'count', intent: '底部 tab 栏四项导航可见', selector: 'nav.tab-bar a.tab-item', minCount: 4 },
      { kind: 'count', intent: '应急入口的呼吸点已渲染（它是首页唯一循环动效）', selector: '.flame-dot.breathing', minCount: 1 },
    ],
  },
  {
    name: 'consult-list',
    path: '/consult',
    guarded: true,
    fixtures: [{ method: 'GET', path: '/api/consult/sessions', body: SESSION_LIST_FIXTURE }],
    note: '会话列表取 GET /api/consult/sessions 一页（limit 缺省 20，夹具回三条、无下一页）。',
    assertions: [
      { kind: 'count', intent: '至少一条会话行', selector: 'button.list-row', minCount: 3 },
      {
        kind: 'text',
        intent: '会话行含标题与相对时间',
        scope: 'button.list-row',
        minHits: 3,
        candidates: ['超市里突然坐下不走，怎么带他离开', '12 分钟前', '5 小时前', '昨天'],
      },
    ],
  },
  {
    name: 'chat',
    path: `/consult/sessions/${CHAT_SESSION_ID}`,
    guarded: true,
    fixtures: [
      { method: 'GET', path: `/api/consult/sessions/${CHAT_SESSION_ID}/messages`, body: CHAT_HISTORY_FIXTURE },
    ],
    mustNotRequest: ['/api/consult/runs/'],
    note:
      '对话页只做历史水合（技能目录是 domain 常量、不发请求）。SSE 运行流本页不需要：' +
      '订阅只在发送消息之后才发起，而本页的目标形态是「刷新后恢复的历史对话」；' +
      '因此 /api/consult/runs/ 列入必须为空清单，由机器断言未被请求。',
    assertions: [
      { kind: 'count', intent: '至少一条使用者气泡', selector: '.bubble-user', minCount: 1 },
      { kind: 'count', intent: '至少一条助手消息', selector: '.msg-doc', minCount: 1 },
      {
        kind: 'text',
        intent: '助手正文、工具行与依据区可见',
        // 候选串刻意只取默认可见的部分：引用条目在 `.citation-block` 这个 `<details>` 里
        // 默认收起（对话页设计契约修订 5），它的正文不在 innerText 中。用「依据 1 条」这个
        // 折叠头来断言依据区存在——它才是首屏真实呈现的形态。
        //
        // 工具行那一条**派生自词表**，不写字面量：2026-10-07 实测本项曾长期失败，原因是
        // 这里写的是线上标识符 `search_cases · 已结束`，而产品按设计真源（对话页设计契约
        // 修订 7）渲染的是中文友好名「查阅案例 · 已结束」——本断言只命中 2/3 条。
        // 映射是否正确不归本夹具证明（它由 src 侧的 toolLabels.test.ts 与后端的
        // test_tool_labels_coverage.py 各自把关）；这里要的只是「这一行确实渲染出来了」。
        minHits: 3,
        candidates: ['先不劝。他坐下不走', '依据 1 条', `${toolDisplayName('search_cases')} · 已结束`],
      },
    ],
  },
  {
    name: 'emergency',
    path: '/consult/emergency',
    guarded: true,
    fixtures: [],
    note: '应急表单页零取数：八项是本地结构，只在提交时打 POST /api/consult/emergency。',
    assertions: [
      {
        kind: 'text',
        intent: '首个采集字段（题面与选项）可见',
        minHits: 4,
        candidates: ['现在有没有以下医疗危险表现？', '意识改变', '呼吸异常', '跳过 = 未排除，不会当作正常'],
      },
      { kind: 'count', intent: '进度条可见', selector: '.progress-track', minCount: 1 },
    ],
  },
  {
    name: 'profile',
    path: '/profile',
    guarded: true,
    fixtures: [
      { method: 'GET', path: '/api/profile/objects', body: PROFILE_OBJECTS_FIXTURE },
      { method: 'GET', path: `/api/profile/objects/${PROFILE_OBJECT_ID}/summary`, body: PROFILE_SUMMARY_FIXTURE },
      { method: 'GET', path: `/api/profile/objects/${PROFILE_OBJECT_ID}/items`, body: PROFILE_ITEMS_FIXTURE },
    ],
    note: '档案页挂载时打三个端点：对象列表 → 选中对象的摘要与条目（两个并发）。',
    assertions: [
      { kind: 'count', intent: '至少一条档案条目', selector: 'article.list-row', minCount: 3 },
      {
        kind: 'text',
        intent: '摘要、条目与待确认分组可见',
        minHits: 4,
        candidates: ['关于 TA 的当前认识', '需要留出回应的空档', '待确认', '小宇'],
      },
    ],
  },
  {
    name: 'cases',
    path: '/cases',
    guarded: true,
    fixtures: [{ method: 'GET', path: '/api/library/items', body: LIBRARY_CASE_FIXTURE }],
    note: '案例库浏览页挂载时取 GET /api/library/items（library 缺省 case）；不起 deep-link 查询。',
    assertions: [
      { kind: 'count', intent: '至少一条案例', selector: 'article.list-row', minCount: 2 },
      {
        kind: 'text',
        intent: '案例标题与来源可信度信息可见',
        minHits: 4,
        candidates: [
          '超市里坐下不走：先降刺激，再移动',
          '项目所有者核准',
          '观察性经验',
          '虚构样例',
        ],
      },
    ],
  },
  {
    name: 'settings',
    path: '/settings',
    guarded: true,
    fixtures: [],
    note:
      '设置页零取数。账号名显示降级文案是既定行为（冷启动读不到账号名，凭据在 httpOnly cookie、' +
      '一期无账号信息查询端点），不是夹具缺项。',
    assertions: [
      {
        kind: 'text',
        intent: '账号卡、数据卡与操作区可见',
        minHits: 6,
        candidates: [
          '我的',
          '个人账号 · 邀请码注册',
          '关于你的数据',
          '我提过的事',
          '本应用尚未经专业审阅，不能替代专业服务；遇到紧急医疗情况请直接就医或拨打急救电话',
          '退出登录',
        ],
      },
      { kind: 'visible', intent: '操作区的退出登录按钮可见', selector: '.btn.btn-secondary', minCount: 1 },
    ],
  },
  {
    name: 'memory',
    path: '/settings/memory',
    guarded: true,
    fixtures: [{ method: 'GET', path: '/api/memory/episodes', body: MEMORY_EPISODES_FIXTURE }],
    note: '记忆页取 GET /api/memory/episodes 一页；夹具回两条、无下一页。',
    assertions: [
      { kind: 'count', intent: '至少一条记忆条目', selector: 'article.list-row', minCount: 2 },
      {
        kind: 'text',
        intent: '记忆原文与归属说明可见',
        minHits: 3,
        candidates: ['在超市里人多的时候会突然停下不走', '这些是你自己在咨询中说过或经历过的事', '来自一次咨询'],
      },
      {
        kind: 'pattern',
        intent: '日期分组头按设计格式渲染（M月D日）',
        selector: 'details.group-collapse summary',
        pattern: '\\d{1,2}月\\d{1,2}日',
      },
    ],
  },
  {
    name: 'guide',
    path: '/guide',
    guarded: true,
    fixtures: [],
    note: '使用说明页是全静态内容（四小节文案为设计成稿），零取数。',
    assertions: [
      {
        kind: 'text',
        intent: '四节标题可见',
        minHits: 4,
        candidates: ['应急咨询', '日常咨询', '档案与记忆', '数据与隐私'],
      },
      {
        kind: 'text',
        intent: '尾部边界说明可见',
        minHits: 1,
        candidates: ['本应用尚未经专业审阅，不能替代专业服务'],
      },
    ],
  },
];

/**
 * 取一页本次运行实际生效的夹具。
 *
 * 正常运行时就是配置原样；消融期按两个开关做两处窄变换：
 * 摘掉指定夹具（验兜底 handler）、把承载列表清空（验内容断言）。
 * 变换只在本函数发生，别处读到的都是「最终夹具」——避免消融逻辑散落在 spec 里。
 *
 * 前置: shot 来自 PAGE_SHOTS
 * 后置: 返回夹具数组；消融开关未设时与 shot.fixtures 逐项等价
 *
 * @throws Error 内容断言消融没有清到任何数组——立即失败并点名。
 *   本轮 P1-2：上一版只清 `items`/`candidates`，而 chat 页的载荷字段是 `messages`，
 *   于是 `SHOTS_ABLATION_EMPTY_LIST=chat` 什么都没做却报了一轮全绿。
 *   那是「把『没做消融』报成『消融通过』」的通道——它污染的是验证手段本身的可信度，
 *   比断言有缺陷更危险（AGENTS.md：禁止留下永远不会失败的检查）。
 *   因此这里不再依赖「注释已披露边界」，而是让「没清到」这件事直接抛错。
 */
export function effectiveFixtures(shot: PageShot): readonly ApiFixture[] {
  const withoutMissing = shot.fixtures.filter((fixture) => !isAblationMissingFixture(fixture.path));
  if (!isAblationEmptyList(shot.name)) return withoutMissing;

  // 先逐个试清一次，确认这一页的载荷里确实有可清的顶层数组。
  // 为什么在这里就查而不是等请求进来再查：本函数在用例体开头调用，此时失败能立刻
  // 指出「这个消融目标选错了」，而不是等一轮跑完才以「断言没红」的形式暴露。
  const probe = withoutMissing.map((fixture) => emptyTopLevelArrays(fixture.body));
  const clearedKeys = [...new Set(probe.flatMap((entry) => entry.clearedKeys))];
  if (clearedKeys.length === 0) {
    const observedKeys = [...new Set(probe.flatMap((entry) => entry.topLevelKeys))];
    throw new Error(
      `内容断言消融对页面「${shot.name}」无效：其夹具载荷里没有任何顶层数组被清空，` +
        `因此这个消融开关什么都不做，「用例仍然通过」不能证明断言有效。` +
        `载荷的顶层键：${observedKeys.length > 0 ? observedKeys.join('、') : '（无夹具或载荷非对象）'}。` +
        '请把该页的承载字段纳入 emptyTopLevelArrays，或把该页从消融目标里去掉。',
    );
  }

  return withoutMissing.map((fixture) => ({
    ...fixture,
    body: (): unknown => emptyTopLevelArrays(fixture.body).body,
  }));
}

/** 清空顶层数组的结果。 */
interface EmptiedBody {
  /** 清空后的载荷。 */
  body: unknown;
  /** 本次实际被清空的顶层键（用于让「没清到」变成可失败的判据）。 */
  clearedKeys: string[];
  /** 载荷的全部顶层键（失败时用于点名，便于发现字段名写错）。 */
  topLevelKeys: string[];
}

/**
 * 把夹具载荷里所有顶层数组改成空数组。
 *
 * 为什么不写死 `items`/`candidates` 两个名字：本项目各面列表端点用的承载字段名不止一个
 * （会话、记忆、资料库用 `items`；档案的候选层用 `candidates`；对话用 `messages`）。
 * 写死名单会让「字段名不在名单里」的页面静默空转——本轮 P1-2 正是如此。
 * 改成「清所有顶层数组」后，新页面新增列表字段会自动被覆盖。
 *
 * 只动顶层、不递归：条目内部的 `contexts`、`helpful_support` 这类同形数组不应被清
 * （它们是条目的属性，不是承载列表）。保持顶层这一层边界，语义仍然明确。
 *
 * 为什么这是正确的消融方式：空数组是合法响应（契约明确「查询为空返回 200 空数组」），
 * 页面会渲染成合法空态而不是错误态。于是「断言失败」只能归因于断言本身，
 * 不会被 500/501 之类的错误态混进来。
 */
function emptyTopLevelArrays(body: ApiFixture['body']): EmptiedBody {
  const materialized = typeof body === 'function' ? (body as () => unknown)() : body;
  if (typeof materialized !== 'object' || materialized === null) {
    return { body: materialized, clearedKeys: [], topLevelKeys: [] };
  }

  const source = materialized as Record<string, unknown>;
  const emptied: Record<string, unknown> = { ...source };
  const clearedKeys: string[] = [];
  for (const [key, value] of Object.entries(source)) {
    if (Array.isArray(value) && value.length > 0) {
      emptied[key] = [];
      clearedKeys.push(key);
    }
  }
  return { body: emptied, clearedKeys, topLevelKeys: Object.keys(source) };
}
