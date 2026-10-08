/**
 * 模块: t10-real-stack
 * 职责: T10 真实依赖端到端探针——真浏览器 + 真 Vite dev server + 真 FastAPI 后端 + 真 SuperTokens 登录
 *
 * ⚠ 需要真实栈（**不是** `pnpm shots` 的 mock 基建）：
 *   1. **后端必须经一个「进程内先规范化 `no_proxy` 再导入 httpx」的启动器起**
 *      （**不能**直接 `uv run uvicorn campfire.main:app …` ——理由见下方「为什么不能
 *      直接 uvicorn」；可跑的启动脚本与完整说明见 `apps/web/e2e-real/README.md`）。
 *   2. `pnpm --filter @campfire/web dev`（5173，vite 把 /api 代理到 8000）
 *   3. PostgreSQL / Redis(Memurai) / FalkorDB / SuperTokens 四个数据服务健康
 *   4. `.env` 里的 TOKENHUB_API_KEY 非占位符（第 3 条链路会**真调模型**）
 *   5. 一个真实邀请码：`uv run python -m campfire.cli invite issue`
 *      （**一次性**；本目录有**多处**真实注册 ⇒ 要现签**多枚**并用 `T10_INVITE_CODES`
 *      传码池，只签 1 枚会因复用产生**假红**；**具体枚数与下标见 `README.md` §4 的下标表**）
 *
 * ⚠ 为什么不能直接 `uv run uvicorn campfire.main:app …`（本机实测，2026-10-04）
 *
 * 本机环境的 `NO_PROXY` / `no_proxy` 里含**带方括号的 IPv6 字面量** `[::1]`
 * （典型取值 `127.0.0.1,localhost,::1,[::1]`）。`httpx` 的
 * `get_environment_proxies()` 会把它解析成 `all://*[::1]`，客户端**构造期**即抛
 * `httpx.InvalidURL: Invalid port: ':1]'`。而 `supertokens_python` 的 querier 用的是
 * httpx 的**默认客户端**（`trust_env=True`）⇒ **`POST /api/auth/signup` 必然 500**。
 *
 * **最坑的一点：此时 `/readyz` 仍然全绿**（探针自身 `trust_env=False`，见
 * `apps/api/src/campfire/core/auth/__init__.py`）⇒ 「健康检查绿而注册/登录全断」，
 * 排查者会去查 SuperTokens 与数据库，而根因是进程环境变量的词法问题。
 *
 * **从 shell 改是没用的**（实测两种写法都无效，原因不同）：
 *   - 环境块里 `NO_PROXY` 与 `no_proxy` **两个键并存**，Python 在 Windows 上折叠进
 *     `os.environ` 时**不区分大小写去重、后者覆盖前者**；
 *   - `SetEnvironmentVariableW` **不区分大小写地匹配块内首个条目并保留其原有大小写**
 *     ⇒ 你改的那条未必是 Python 折叠后胜出的那条。
 *
 * **唯一可靠的做法**：在**进程内、导入任何 httpx 消费者（`httpx` / `openai` /
 * supertokens）之前**，把**大小写两个键都写一遍**：
 *
 * ```python
 * import os
 *
 * os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"
 * os.environ["no_proxy"] = "127.0.0.1,localhost,::1"
 *
 * import uvicorn  # 必须在规范化之后导入
 *
 * uvicorn.run("campfire.main:app", host="127.0.0.1", port=8000, log_level="info")
 * ```
 *
 * **⚠ 该规范化只对【本进程】有效，不会传给子进程**（实测：子进程继承的是原始环境块，
 * 仍会抛 `InvalidURL`）——因此 uvicorn 必须由**这个**进程启动，不要用它去 `subprocess`
 * 拉起别的服务再指望它们继承豁免。
 *
 * 它**默认不被任何入口调用**：`pnpm --filter @campfire/web shots`（playwright.config.ts）
 * 的 testDir 是 `apps/web/e2e`，本目录是 `apps/web/e2e-real`，两者不重叠；
 * 本文件里也没有 `test.skip` 之类的静默降级——缺环境时它**失败**，不假装通过。
 *
 * 运行（显式 opt-in）：
 *   pnpm --filter @campfire/web exec playwright test \
 *     --config e2e-real/playwright.real.config.ts \
 *     --grep "@real" --reporter=list
 *
 * 环境变量：T10_BASE_URL（默认 http://localhost:5173）
 *          T10_INVITE_CODE（提供时用真实邀请码走注册；省略时用真实登录）
 *          T10_OUT（产物目录，默认 <repo>/tmp/T10）
 *          T10_ACCOUNT / T10_PASSWORD（可选，指定账号；省略则按时间戳生成）
 */

import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, type BrowserContext, type ConsoleMessage, type Page } from '@playwright/test';

/**
 * 仓库根。
 *
 * 本文件在 `apps/web/e2e-real/support/`，因此从 `support/` 起要上溯 **4** 级
 * （support → e2e-real → web → apps → 仓库根）。上溯级数少一级会把产物写进
 * `apps/tmp/`——一个看起来「也像 tmp」却不在仓库根 tmp/ 下的位置。
 */
const REPO_ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '..', '..', '..', '..');

/** 产物目录：只写仓库根的 `.tmp/T10`（不碰 apps/web/dist）。
 *
 * 2026-10-06：原落点 `tmp/T10`，该目录已按「只保留一个临时目录」的裁决整体清空，
 * 落点统一到 `.tmp/`——不改这里会在下次跑真栈 e2e 时把 `tmp/` 重新建出来。
 */
export const OUT_DIR = process.env.T10_OUT?.trim() === undefined || process.env.T10_OUT?.trim() === ''
  ? resolve(REPO_ROOT, '.tmp', 'T10')
  : resolve(process.env.T10_OUT.trim());

/** 被测站点根地址（Vite dev server，/api 被代理到真后端）。 */
export const BASE_URL = process.env.T10_BASE_URL?.trim() ?? 'http://localhost:5173';

/** 一轮探针里累积的观察值，最后整份落盘成 JSON 证据。 */
export interface ProbeLog {
  readonly entries: Record<string, unknown>;
}

/** 建一个记录器；`record` 的值会被 JSON 序列化落盘。 */
export function createLog(): ProbeLog & { record(key: string, value: unknown): void } {
  const entries: Record<string, unknown> = {};
  return {
    entries,
    record(key: string, value: unknown): void {
      entries[key] = value;
    },
  };
}

/** 把记录器落盘到 OUT_DIR/<name>.json。 */
export async function saveLog(log: ProbeLog, name: string): Promise<string> {
  await mkdir(OUT_DIR, { recursive: true });
  const path = resolve(OUT_DIR, `${name}.json`);
  await writeFile(path, `${JSON.stringify(log.entries, null, 2)}\n`, 'utf8');
  return path;
}

/** 一条控制台/页面错误记录。 */
export interface ConsoleRecord {
  /**
   * 记录种类。
   *
   * `console-error` 与 `console-network-error` 是**两类不同的东西**，刻意分开：
   *   - `console-error`：页面 JS 自己调 `console.error(...)`（应用缺陷或库报错）；
   *   - `console-network-error`：**浏览器**为一个失败响应自动记的
   *     「Failed to load resource: the server responded with a status of N」。
   *     它不是应用代码的异常，但它确实出现在控制台里（type 仍为 error），
   *     因此不能默默过滤掉——过滤掉就成了「永远不会失败的检查」。分开记录让
   *     「应用异常」与「浏览器网络日志」各自可判定。
   * 判别方式：浏览器自动记的那条，其 text 以 `Failed to load resource:` 开头。
   */
  readonly kind: 'console-error' | 'console-network-error' | 'pageerror' | 'requestfailed' | 'response-4xx-5xx';
  readonly text: string;
  readonly url: string;
  readonly at: string;
  /** 控制台消息的来源位置（应用侧脚本才有的绝对 URL；浏览器网络日志也会带资源 URL）。 */
  readonly source?: string;
}

/** 浏览器为失败响应自动记的控制台前缀。 */
const BROWSER_RESOURCE_ERROR_PREFIX = 'Failed to load resource:';

/**
 * 挂上控制台错误采集器，记录**直接写进调用方给的 sink**。
 *
 * 为什么写 sink 而不是返回一个自己的数组：一轮真实栈探针会开多个 page，而链路 7
 * 要的是「全程」的汇总。各 page 各持一个数组时，调用方只能拿到创建那一刻的引用，
 * 事后的 push 不会流进汇总数组——那会让链路 7 永远看到空数组（一条永远通过的检查）。
 * 显式传 sink 让「记录落到哪里」在调用点可见。
 *
 * 只收**真错误**：`console.error`、未捕获异常、失败请求与非 2xx/3xx 响应。
 * 404 也算——本产品不该有 404 资源请求（favicon 缺失会被显式记下来而不是放行，
 * 放行需要理由，而理由要写进报告）。
 */
export function watchConsole(page: Page, sink: ConsoleRecord[]): void {
  const records = sink;
  const at = (): string => new Date().toISOString();

  page.on('console', (message: ConsoleMessage) => {
    if (message.type() !== 'error') return;
    const text = message.text();
    const location = message.location();
    records.push({
      // 浏览器的「资源加载失败」自动日志与页面 JS 主动的 console.error 分开归类。
      kind: text.startsWith(BROWSER_RESOURCE_ERROR_PREFIX) ? 'console-network-error' : 'console-error',
      text,
      url: page.url(),
      at: at(),
      ...(location.url === '' ? {} : { source: location.url }),
    });
  });
  page.on('pageerror', (error: Error) => {
    records.push({ kind: 'pageerror', text: `${error.name}: ${error.message}`, url: page.url(), at: at() });
  });
  page.on('requestfailed', (request) => {
    records.push({
      kind: 'requestfailed',
      text: `${request.method()} ${request.url()} → ${request.failure()?.errorText ?? 'unknown'}`,
      url: page.url(),
      at: at(),
    });
  });
  page.on('response', (response) => {
    const status = response.status();
    if (status < 400) return;
    records.push({
      kind: 'response-4xx-5xx',
      text: `${String(status)} ${response.request().method()} ${response.url()}`,
      url: page.url(),
      at: at(),
    });
  });
}

/**
 * 确认单打开时，「背景能否被程序化聚焦」这组判据的**全部读数**。
 *
 * 为什么把它抽成共享函数（T11 第 1 条的核心）
 *
 * 原实现把这段逻辑**内联在链路 4 的用例里**，于是它有两个问题：
 *
 * 1. **有恒真路径**：候选写法是 `outside.find(e => !e.closest('[inert]')) ?? outside[0] ?? null`。
 *    若 `outside`（单外匹配选择器的元素）**为空**，则 `candidate === null`
 *    ⇒ `focusEscaped === false` ⇒「背景不可聚焦」这条断言**无条件通过**——
 *    结论在该情形下从未被检验。`outsideSelectorMatchCount` 就是为堵这条路而采集的。
 * 2. **无法被证明能红**：判据内联时，任何控制臂只能另写一份等价逻辑，
 *    证明的就不是生产量（T06 的 P1-1 正是这个坑：生产喂文档级、证明喂内层级）。
 *    抽成导出函数后，控制臂与生产调用点**共用同一段代码**。
 *
 * `outsideSelectorMatchCount` 的口径刻意与生产候选选择**逐字对齐**：
 * 同样的选择器、同样的「不在单内」过滤、**不过滤 `disabled`、不排除 inert 祖先**。
 * 为什么不过滤 disabled：生产代码的候选也可能落到一个 `disabled` 元素上
 * （`outside[0]` 兜底那一支），若这里把它滤掉，两处的空洞边界就不一致了。
 * 已知残余（如实登记，见报告第 4 节）：候选是 disabled 元素时 focus 失败也会让
 * `focusEscaped === false`，那条路径的结论强度弱于 inert 真正生效的情形——
 * 控制臂的「正对照」臂（撤掉 inert 后必须 escaped=true）覆盖了这一整类。
 */
export interface SheetFocusFacts {
  /** 单是否存在。不存在时其余字段无意义。 */
  readonly sheetPresent: boolean;
  /** `aria-labelledby` 指向的 id。 */
  readonly sheetLabelledBy: string | null;
  /** `role`（判据要求 `dialog`）。 */
  readonly sheetRole: string | null;
  /** `aria-modal`（判据要求 `true`）。 */
  readonly sheetAriaModal: string | null;
  /** 采集那一刻焦点是否已在单内（判据要求 true —— 即焦点被移进了单）。 */
  readonly activeElementInsideSheet: boolean;
  /** 采集那一刻焦点的标签（`button#id` 形式，诊断用）。 */
  readonly activeElementTag: string | null;
  /** 背景被标记 `inert` 的元素数（判据要求 > 0）。 */
  readonly inertCount: number;
  /** 背景被标记 `inert` 的元素标签摘要（前 10 个）。 */
  readonly inertTags: string[];
  /**
   * 单外**匹配生产选择器**的元素数——即生产候选数组 `outside` 的长度。
   * 这就是「非空洞性前置」读的量：它为 0 时 `backgroundFocusEscaped` 恒为 false。
   */
  readonly outsideSelectorMatchCount: number;
  /** 单外匹配元素里 `disabled === true` 的个数（登记项：见残余说明）。 */
  readonly outsideDisabledCount: number;
  /** 单外匹配元素里**不在** `[inert]` 子树内的个数（生产候选的首选那一支）。 */
  readonly outsideNonInertCount: number;
  /** 单外匹配元素里**真的被渲染**（`getClientRects().length > 0`）的个数——诊断用。 */
  readonly outsideVisibleCount: number;
  /** 实际被选为候选的元素标签（无候选时为 null）。 */
  readonly candidateTag: string | null;
  /**
   * 候选是否**真的被渲染**（`getClientRects().length > 0`）。
   *
   * 为什么必须单独有这一条（T11-r2 的 P2-1）：`outsideSelectorMatchCount > 0` 只证明
   * 「选择器匹配到了元素」，**不证明那个元素能被聚焦**。`display:none` /
   * `visibility:hidden` 的元素照样被 `querySelectorAll` 匹配到、`candidateTag` 也非 null，
   * 但 `focus()` 对它们是**静默失败**的 ⇒ `backgroundFocusEscaped` 仍为 false
   * ⇒ 「inert 挡住了背景聚焦」这条结论在那处**从未被检验**（与「无候选」是同一个空洞，
   * 只是入口更隐蔽：计数 > 0 让前一条前置断言放行）。
   * 因此这一条是那条前置的**补漏**：候选存在**且可见**，结论才算测过。
   */
  readonly candidateVisible: boolean;
  /** 程序化聚焦后焦点是否真的落到了候选上（true = 背景可聚焦 = inert 未生效）。 */
  readonly backgroundFocusEscaped: boolean;
  /** 聚焦尝试后 `document.activeElement` 的标签（诊断用）。 */
  readonly backgroundFocusResult: string | null;
}

/**
 * 采集「确认单打开时背景可聚焦性」的全部读数。
 *
 * 只在单存在时有意义；单不存在时 `sheetPresent: false`、计数为 0。
 * 副作用：会尝试把焦点移给一个单外元素（这是判据本身，不是采集的副作用）。
 *
 * ⚠ 顺序敏感：必须先读 `document.activeElement`（这是「焦点有没有进入单」的判据），
 * 再执行候选聚焦（那是「背景能不能被聚焦」的判据）。反过来会让第一条判据读到
 * 被本函数自己移动过的焦点。
 */
export function sheetFocusFacts(): SheetFocusFacts {
  const sheet = document.querySelector('.confirm-sheet');
  if (sheet === null) {
    return {
      sheetPresent: false,
      sheetLabelledBy: null,
      sheetRole: null,
      sheetAriaModal: null,
      activeElementInsideSheet: false,
      activeElementTag: null,
      inertCount: 0,
      inertTags: [],
      outsideSelectorMatchCount: 0,
      outsideDisabledCount: 0,
      outsideNonInertCount: 0,
      outsideVisibleCount: 0,
      candidateTag: null,
      candidateVisible: false,
      backgroundFocusEscaped: false,
      backgroundFocusResult: null,
    };
  }

  // 先读焦点落点（判据：焦点是否已被移进单内）。
  const active = document.activeElement;
  const inertElements = Array.from(document.querySelectorAll('[inert]'));
  // 与生产候选选择逐字对齐：同一组选择器、同一「不在单内」过滤（见接口说明）。
  const outside = Array.from(document.querySelectorAll('button, a[href], input, textarea, select')).filter(
    (element) => !sheet.contains(element),
  ) as HTMLElement[];

  // 再执行候选聚焦（判据：背景能否被程序化聚焦）。
  const candidate = outside.find((element) => !element.closest('[inert]')) ?? outside[0] ?? null;
  // 在 focus() **之前**取可见性：`getClientRects()` 为空即「未被渲染」（display:none、
  // 或在 display:none 子树内）。visibility:hidden 仍会产出 rect，但那种元素 focus() 同样
  // 静默失败——因此本读数只覆盖「未渲染」这一类，残余另记（见接口说明与报告）。
  const candidateVisible = candidate !== null && candidate.getClientRects().length > 0;
  candidate?.focus();
  const focusEscaped = candidate !== null && document.activeElement === candidate;

  return {
    sheetPresent: true,
    sheetLabelledBy: sheet.getAttribute('aria-labelledby'),
    sheetRole: sheet.getAttribute('role'),
    sheetAriaModal: sheet.getAttribute('aria-modal'),
    activeElementInsideSheet: active !== null && sheet.contains(active),
    activeElementTag: active === null ? null : `${active.tagName.toLowerCase()}${active.id === '' ? '' : `#${active.id}`}`,
    inertCount: inertElements.length,
    inertTags: inertElements.slice(0, 10).map((element) => `${element.tagName.toLowerCase()}.${element.className || '(no-class)'}`),
    outsideSelectorMatchCount: outside.length,
    outsideDisabledCount: outside.filter((element) => element.matches(':disabled')).length,
    outsideNonInertCount: outside.filter((element) => element.closest('[inert]') === null).length,
    outsideVisibleCount: outside.filter((element) => element.getClientRects().length > 0).length,
    candidateTag: candidate === null ? null : candidate.tagName.toLowerCase(),
    candidateVisible,
    backgroundFocusEscaped: focusEscaped,
    backgroundFocusResult: document.activeElement === null ? null : document.activeElement.tagName.toLowerCase(),
  };
}

/**
 * 右边界越出视口的元素清单——「无横向溢出」的**元素级**信号。
 *
 * 为什么文档级 `scrollWidth` 不够（T11 第 2 条，对应 facts `(z17)`：
 * 「这个读数会不会被我自己的布局裁掉/吸收？」）
 *
 * 宽视口下 `.device { overflow: hidden }`（`global.css`）把外壳内的溢出**裁掉**，
 * 于是它不会传递到 `documentElement.scrollWidth`——判据被自己的布局吸收了。
 * T10 两次实测该数组均为 `[]`，而文档级读数同样是 0：两者在「真有内部溢出」时
 * 才会分道扬镳。因此元素级信号才是那道能红的判据。
 *
 * 抽成导出函数是为了让负面控制臂用**同一个**取量函数（原见 `e2e-real/control.spec.ts`；
 * 该控制臂已于 2026-10-08 按用户裁决删除），否则控制臂证明的只是「另一个量会红」。
 */
export function elementsPastViewportRight(): string[] {
  return Array.from(document.querySelectorAll('*'))
    .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
    .slice(0, 10)
    .map((element) => `${element.tagName.toLowerCase()}.${element.className || '(no-class)'}`);
}

/**
 * 未登录首载时**预期**的 `session/refresh` 401（口径，不是过滤）。
 *
 * `supertokens-web-js` 在没有 `sRefreshToken` 时的第一次启动会尝试刷新并拿到 401；
 * T10 已实测它在未登录的 `/`、`/login` 与未知路由上都发生，且登录后 reload 不再发生。
 * 它是**既有探测行为**，不是缺陷——因此链路 7 不对 4xx 做全局断言。
 *
 * 关键纪律：它是**排除出 5xx 判据的口径说明**，绝不能变成过滤。
 * 采集到的 401 必须原样留在产物 JSON 里（`tallyResponses` 只做分类计数，不删记录）。
 */
export const EXPECTED_ANONYMOUS_REFRESH = {
  method: 'POST',
  pathSuffix: '/api/auth/session/refresh',
  status: 401,
} as const;

/** 一条带状态码的响应记录（从 `ConsoleRecord.text` 解析出来的读数）。 */
export interface ResponseReading {
  readonly status: number;
  readonly method: string;
  readonly url: string;
}

/**
 * 把 `response-4xx-5xx` 记录解析回 `(状态码, 方法, URL)`。
 *
 * 解析失败返回 `null` 而不是抛错：本函数用于**汇总**，一条畸形记录不该让整轮
 * 探针崩掉——但它也绝不能被静默吞掉，因此调用方把解析失败数一并落盘（见 `tallyResponses`）。
 */
export function parseResponseRecord(record: ConsoleRecord): ResponseReading | null {
  // 写入格式见 watchConsole：`${status} ${method} ${url}`。
  const match = /^(\d{3}) ([A-Z]+) (\S+)$/.exec(record.text);
  if (match?.[1] === undefined || match[2] === undefined || match[3] === undefined) return null;
  return { status: Number(match[1]), method: match[2], url: match[3] };
}

/** 一轮探针里非 2xx/3xx 响应的分类计数（链路 7 的判据原料）。 */
export interface NetworkTally {
  /** 全部 4xx（**保留**，不做全局断言）。 */
  readonly clientErrors: ResponseReading[];
  /** 全部 5xx——真正的缺陷信号，判据要求为空。 */
  readonly serverErrors: ResponseReading[];
  /** 其中属于「未登录 `session/refresh` 401」这一**预期**口径的条数。 */
  readonly expectedAnonymousRefreshCount: number;
  /** 4xx 里扣掉预期 401 之后剩下的条数（登记用；本包不对它做断言，理由见链路 7 说明）。 */
  readonly unexpectedClientErrorCount: number;
  /** 无法解析的记录数（应为 0；非 0 说明采集格式漂移，必须可见）。 */
  readonly unparsedCount: number;
}

/**
 * 汇总非 2xx/3xx 响应。**只分类、不删除**——产物 JSON 里仍保留全部原始记录。
 */
export function tallyResponses(records: readonly ConsoleRecord[]): NetworkTally {
  const bad = records.filter((record) => record.kind === 'response-4xx-5xx');
  const clientErrors: ResponseReading[] = [];
  const serverErrors: ResponseReading[] = [];
  let expected = 0;
  let unparsed = 0;
  for (const record of bad) {
    const reading = parseResponseRecord(record);
    if (reading === null) {
      unparsed += 1;
      continue;
    }
    if (reading.status >= 500) {
      serverErrors.push(reading);
      continue;
    }
    clientErrors.push(reading);
    if (
      reading.status === EXPECTED_ANONYMOUS_REFRESH.status &&
      reading.method === EXPECTED_ANONYMOUS_REFRESH.method &&
      reading.url.endsWith(EXPECTED_ANONYMOUS_REFRESH.pathSuffix)
    ) {
      expected += 1;
    }
  }
  return {
    clientErrors,
    serverErrors,
    expectedAnonymousRefreshCount: expected,
    unexpectedClientErrorCount: clientErrors.length - expected,
    unparsedCount: unparsed,
  };
}

/** 一条 API 请求的实测记录（真实性判据的原料）。 */
export interface ApiTrace {
  readonly method: string;
  readonly url: string;
  readonly status: number;
  readonly viaProxy: boolean;
  readonly bodyKeyIds: string[];
  readonly fetchedBy: 'browser';
}

/**
 * 采集浏览器侧**真实发出**的 `/api/**` 请求。
 *
 * 关键：本函数只 `page.on('response')` **观察**，不注册任何 `page.route`。
 * 只要有请求从浏览器发到站点源、拿到 2xx 且响应体里带真实 id，就说明它来自真后端
 * （mock 需要 route.fulfill，而本探针里没有任何 route 调用）。
 */
export function watchApi(page: Page, trace: ApiTrace[]): void {
  page.on('response', (response) => {
    const url = response.url();
    if (!url.includes('/api/')) return;
    const request = response.request();
    const method = request.method();
    // 只记业务写读，静态资源不记。
    void (async (): Promise<void> => {
      const bodyKeyIds: string[] = [];
      try {
        const text = await response.text();
        for (const key of ['session_id', 'run_id', 'message_id', 'id', 'status']) {
          const match = new RegExp(`"${key}"\\s*:\\s*"([^"]{4,})"`).exec(text);
          if (match?.[1] !== undefined) bodyKeyIds.push(`${key}=${match[1]}`);
        }
      } catch {
        // 无正文（202/204）是合法情形；不记 id 即可，不伪造。
      }
      trace.push({
        method,
        url,
        status: response.status(),
        viaProxy: url.startsWith(BASE_URL),
        bodyKeyIds,
        fetchedBy: 'browser',
      });
    })();
  });
}

/** 采集浏览器 cookie（证明拿到了真实会话）。 */
export async function sessionCookies(context: BrowserContext): Promise<{ name: string; domain: string; path: string; httpOnly: boolean; sameSite: string; valueLength: number; valuePrefix: string }[]> {
  const cookies = await context.cookies();
  return cookies.map((cookie) => ({
    name: cookie.name,
    domain: cookie.domain,
    path: cookie.path,
    httpOnly: cookie.httpOnly,
    sameSite: cookie.sameSite,
    valueLength: cookie.value.length,
    valuePrefix: cookie.value.slice(0, 6),
  }));
}

/** 时间戳账号名（账号名实际强制邮箱格式，见 docs/TODO.md PROD-01）。 */
export function freshAccount(stamp: number): string {
  return process.env.T10_ACCOUNT?.trim() ?? `e2e-${String(stamp)}@example.test`;
}

/** 口令：≥8 字符、含小写字母与数字（docs/TODO.md 记载的策略）。 */
export function freshPassword(stamp: number): string {
  return process.env.T10_PASSWORD?.trim() ?? `e2e${String(stamp % 100000)}pw`;
}

/**
 * 取一枚真实邀请码。
 *
 * 邀请码是**一次性**的，而本轮有多处真实注册（验收链路 1 一次、两个消融各一次）。
 * 只给一枚时，先跑的用例会把码用掉，后跑的就以「邀请码无效或已被使用」失败——
 * 那条失败看起来像产品缺陷，实际是夹具不够。因此支持一个码池：
 * `T10_INVITE_CODES`（逗号分隔）按下标分配；只给 `T10_INVITE_CODE` 时一律用它。
 *
 * @param index 码池下标（0 归验收链路 1，消融从 1 起）
 * @returns 该下标对应的邀请码；池为空时返回空串（调用方须显式断言非空）
 */
export function inviteCodeFor(index: number): string {
  const pool = (process.env.T10_INVITE_CODES ?? '')
    .split(',')
    .map((code) => code.trim())
    .filter((code) => code !== '');
  if (pool.length > 0) return pool[index % pool.length] ?? pool[0] ?? '';
  return process.env.T10_INVITE_CODE?.trim() ?? '';
}

/** 等待 React 根节点挂上内容。 */
export async function waitMounted(page: Page): Promise<void> {
  await expect(page.locator('#root > *').first()).toBeAttached({ timeout: 20_000 });
}

/**
 * 在页面里装一个**只读**的 SSE 字节观察口。
 *
 * 为什么需要它：本应用的 SSE 不用 `EventSource`，而是用 `fetch` + 流式 `ReadableStream`
 * 读取（契约第 2 节明文禁止 `EventSource`，因为它无法携带 anti-CSRF 自定义头）。
 * 因此 CDP 的 `Network.eventSourceMessageReceived` **一条都不会触发**（实测 0 帧）。
 * 而 Playwright 的 `response.text()` 拿不到正文——流已被页面自己消费掉了（实测空串，
 * 而页面正文明明有 385 字）。
 *
 * 做法：在**页面脚本之前**包一层 `window.fetch`，只对该请求的响应做 `clone()`，
 * 把 clone 的流 tee 进 `window.t10SseTap`。
 *
 * 为什么这**不是 mock**：原请求照发（真 fetch、真 cookie、真 anti-CSRF 头），
 * 原响应原样返回给应用（一个字节都不改，应用读的是 original body）。
 * 我们读的是 `clone()` 出来的**第二份**流——这是对真实传输的旁路观察，
 * 不是伪造响应。`route.fulfill` 那种替换响应的做法在这里完全不存在。
 */
export async function installSseTap(page: Page): Promise<void> {
  await page.addInitScript(() => {
    interface TapWindow extends Window {
      t10SseTap?: { url: string; contentType: string | null; status: number; events: { event: string; data: string }[]; raw: string[] };
    }
    const target = window as TapWindow;
    const original = window.fetch.bind(window);

    target.t10SseTap = { url: '', contentType: null, status: 0, events: [], raw: [] };

    window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const response = await original(input, init);
      const contentType = response.headers.get('content-type');
      if (contentType === null || !contentType.includes('text/event-stream')) return response;

      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      target.t10SseTap = { url, contentType, status: response.status, events: [], raw: [] };

      // clone() 让应用与我们各读一份；异常一律吞掉——观察口绝不能让被测链路失败。
      try {
        const clone = response.clone();
        const reader = clone.body?.getReader();
        const decoder = new TextDecoder();
        void (async () => {
          if (reader === undefined) return;
          let buffer = '';
          try {
            for (;;) {
              const { done, value } = await reader.read();
              if (done) break;
              buffer += decoder.decode(value, { stream: true });
              // 按空行切帧（SSE 规范）；半帧留在 buffer 里等下一个 chunk。
              let boundary = buffer.indexOf('\n\n');
              while (boundary !== -1) {
                const frame = buffer.slice(0, boundary);
                buffer = buffer.slice(boundary + 2);
                target.t10SseTap?.raw.push(frame);
                const eventName = /^event:\s*(.+)$/m.exec(frame)?.[1]?.trim() ?? '';
                const dataLines = frame
                  .split('\n')
                  .filter((line) => line.startsWith('data:'))
                  .map((line) => line.replace(/^data:\s?/, ''));
                if (dataLines.length > 0) target.t10SseTap?.events.push({ event: eventName, data: dataLines.join('\n') });
                boundary = buffer.indexOf('\n\n');
              }
            }
          } catch {
            // 观察口失败不影响被测链路。
          }
        })();
      } catch {
        // 同上。
      }
      return response;
    };
  });
}

/** 读出 SSE 观察口已采集到的帧。 */
export async function readSseTap(page: Page): Promise<{ url: string; contentType: string | null; status: number; events: { event: string; data: string }[]; raw: string[] }> {
  return page.evaluate(() => {
    const tap = (window as unknown as { t10SseTap?: unknown }).t10SseTap;
    return (tap ?? { url: '', contentType: null, status: 0, events: [], raw: [] }) as {
      url: string;
      contentType: string | null;
      status: number;
      events: { event: string; data: string }[];
      raw: string[];
    };
  });
}

/**
 * 在真实记忆图库里种一条 episode，让**记忆页删除确认单**可达。
 *
 * 为什么必须种、且为什么从存储层种（证据边界，如实声明）
 *
 * 1. 记忆面（`modules/memory/routes.py`）只有读 / 删 / 纠正三个端点，**没有创建端点**：
 *    episode 的产生路径是 `write_memory` 工具 → `pending_write` 队列 → Worker 消费。
 *    探针里起一个 Worker 不现实。
 * 2. **那条路径在本机当前是坏的**（T11 实测，独立于本包四条加固）：Graphiti 的
 *    `OpenAIEmbedder.create_batch` 不传 `encoding_format`，而 TokenHub 只接受 `float`
 *    ⇒ `400001`，`add_episode` 必失败 ⇒ `write_episode` 抛 `MemoryUnavailableError`。
 *    因此即便走产品写路径也种不进去。该缺陷已登记进 `docs/TODO.md` 第四节。
 * 3. 于是本函数**只写读路径要求的最小字段集**（与 `modules/memory/store._read_timeline`
 *    的判据逐项对齐：`group_id` / `write_state='done'` / `content` / `valid_at`）。
 *
 * **它是什么、不是什么**：它是**夹具**——把被测对象（记忆页 + 真 HTTP API + 真图库）
 * 置于「有一条记忆」的前置条件下。它**不是响应伪造**：整个确认单链路里没有任何
 * `page.route`，页面经 `GET /api/memory/episodes` 真读到这条、经 `DELETE` 真删掉。
 *
 * **它不能证明什么**（必须随报告一起读）：本探针因此**不**构成对「记忆写入路径可用」
 * 的证据——那条路径当前因上述嵌入缺陷而不可用。种进去的 episode 的**来源**不是产品写路径。
 *
 * 直连协议为什么用 `node:net` 手写 RESP：FalkorDB 是 Redis 协议；探针侧不引入
 * 任何新依赖（AGENTS.md：没有消费者的依赖不预先声明）。只需要 `GRAPH.QUERY` 一条命令。
 *
 * @param accountId 分区键（= 图名 = SuperTokens 的 user id）
 * @param content 片段原文
 * @param port FalkorDB 端口（`core/config.py` 默认 6380）
 * @returns 写入的 episode 标识（页面会读到的就是它）
 */
export async function seedMemoryEpisode(accountId: string, content: string, port = 6380): Promise<string> {
  const { randomUUID } = await import('node:crypto');
  const net = await import('node:net');
  const episodeUuid = randomUUID();
  const stamp = new Date().toISOString();
  // 值走 Cypher 字符串字面量：本夹具的三个值都由本函数生成（uuid / ISO 时间），
  // 只有 content 来自调用方；转义单引号与反斜杠即可，不做拼接之外的推断。
  const quote = (value: string): string => `'${value.replaceAll('\\', '\\\\').replaceAll("'", "\\'")}'`;
  const cypher =
    `MERGE (e:Episodic {uuid: ${quote(episodeUuid)}}) ` +
    `SET e = {uuid: ${quote(episodeUuid)}, name: ${quote(`memory:${episodeUuid}`)}, ` +
    `group_id: ${quote(accountId)}, source: 'message', source_description: 'session=seed-t11 message=0', ` +
    `content: ${quote(content)}, entity_edges: [], created_at: ${quote(stamp)}, valid_at: ${quote(stamp)}, ` +
    `write_state: 'done'}`;

  const payload = (() => {
    const args = ['GRAPH.QUERY', accountId, cypher];
    let out = `*${String(args.length)}\r\n`;
    for (const arg of args) {
      out += `$${String(Buffer.byteLength(arg, 'utf8'))}\r\n${arg}\r\n`;
    }
    return out;
  })();

  await new Promise<void>((done, fail) => {
    const socket = net.createConnection({ host: '127.0.0.1', port });
    let reply = '';
    let settled = false;
    /**
     * FalkorDB **不会**在一次 `GRAPH.QUERY` 之后关闭连接（它是 Redis 协议的长连接），
     * 因此不能用 `close` 事件判定回复结束——那样每次都要等超时。运行时实测：回复末尾
     * 固定带 `Query internal execution time: …`，据此判定本次查询已完整到达。
     * `close` 只作为兜底（服务端主动断开时也该收结果）。
     *
     * 形参命名避开模块顶部 import 的 `resolve`（`node:path`），否则 oxlint 报
     * `no-shadow`——本条注释存在就是为了让下一个人不要把它改回去。
     */
    const settle = (error?: Error): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      if (error !== undefined) {
        fail(error);
        return;
      }
      if (reply.includes('ERR') || reply === '') {
        fail(new Error(`种记忆片段被图库拒绝：${reply.slice(0, 300)}`));
        return;
      }
      done();
    };
    const timer = setTimeout(() => {
      settle(new Error(`种记忆片段超时（FalkorDB ${String(port)}），已收到：${reply.slice(0, 200)}`));
    }, 10_000);
    socket.on('connect', () => socket.write(payload));
    socket.on('data', (chunk: Buffer) => {
      reply += chunk.toString('utf8');
      if (reply.includes('Query internal execution time')) settle();
    });
    socket.on('error', (error: Error) => {
      settle(new Error(`连接 FalkorDB ${String(port)} 失败：${error.message}`));
    });
    socket.on('close', () => {
      settle();
    });
  });

  return episodeUuid;
}
