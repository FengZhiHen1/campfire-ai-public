/**
 * 模块: e2e/support/session
 * 职责: 免后端的登录态注入——用两个 cookie 让 supertokens 前端 SDK 判出「已登录」且零网络
 * 数据来源:
 *   - 原证物 orchestrator-20261002-001/facts.md: MUST — §5（端到端已证 doesSessionExist=true 且 fetchCount=0）
 *   - 原证物 orchestrator-20261002-001/T01.md: MUST — 裁决 C（两个 cookie、载荷形状与编码）
 * 边界:
 *   - 依赖: @playwright/test 的 Page/expect
 *   - 被依赖: e2e/shots.spec.ts
 * 禁止行为:
 *   - 禁止在产品源码里加「测试登录态」开关（合规路径是本文件的 addInitScript）——
 *     注入发生在浏览器侧，产品代码零改动
 *   - 禁止把注入失败当成可忽略的降级（它会让截图落成登录页冒充目标页）
 */

import { expect, type Page } from '@playwright/test';

import { SESSION_READY_TIMEOUT_MS } from './paths';

/** 守卫等待态出现的文案（app/RequireSession.tsx 的 unknown 分支）。注入生效即不应出现它。 */
const SESSION_UNKNOWN_COPY = '正在确认登录状态';

/**
 * 注入用的用户标识。
 *
 * 不是真实账号：它只出现在 frontToken 载荷里，供 SDK 判出 EXISTS；任何服务端都不参与。
 */
const PROBE_UID = 'shot-probe-user';

/**
 * frontToken cookie 名（supertokens-web-js 的 FrontToken key）。
 *
 * 与 `LAST_ACCESS_COOKIE` 一起被 `installSession` 用来拼 cookie 名——不能在写入处
 * 重复写字面量：本轮 P2-4 发现这两个常量当时无人使用、而写入处用的是同值字面量，
 * 于是「改常量」不会生效也不会有人发现（`export` 让 lint 的未使用检查失效）。
 */
const FRONT_TOKEN_COOKIE = 'sFrontToken';

/** 最近访问时间 cookie 名（supertokens-web-js 的前缀 `st-` 上）。 */
const LAST_ACCESS_COOKIE = 'st-last-access-token-update';

/**
 * 组装 frontToken 载荷。
 *
 * `ate` 是过期时刻（毫秒）；SDK 只在它晚于当前时刻时判 EXISTS，因此取「当前 + 1 小时」。
 * `up: {}` 是空 claim 集（本注入不伪造任何权限声明）。
 *
 * @param uid 载荷里的用户标识
 * @param nowMs 参照时刻（毫秒）；由调用方注入以便测试可控
 * @param ttlMs 有效期（毫秒）
 */
export function frontTokenPayload(uid: string, nowMs: number, ttlMs: number): { uid: string; ate: number; up: Record<string, never> } {
  return { uid, ate: nowMs + ttlMs, up: {} };
}

/**
 * 把 frontToken 载荷编成 cookie 值。
 *
 * 与 SDK 的 `parseFrontToken`（`JSON.parse(decodeURIComponent(escape(atob(value))))`）互逆：
 * 先 encodeURIComponent 保住非 ASCII，再过 escape 转成 Latin-1，最后 btoa。
 * 缺了中间一步，uid 含非 ASCII 时 atob 会抛 InvalidCharacterError。
 *
 * @param payload frontTokenPayload 的产物
 */
export function encodeFrontToken(payload: { uid: string; ate: number; up: Record<string, never> }): string {
  return btoa(unescape(encodeURIComponent(JSON.stringify(payload))));
}

/** 一小时；注入效期的上界（本包只求「截图期间不过期」）。 */
export const INJECTED_TTL_MS = 60 * 60 * 1000;

/** 注入选项。 */
export interface SessionInjectionOptions {
  /**
   * 是否真的注入 cookie。
   *
   * 只给消融实验用（临时置 false 以证明「去掉注入会失败」）。默认注入。
   */
  enabled?: boolean;
}

/**
 * 在 `page.goto()` 之前装配登录态。
 *
 * 前置: 无（可在任意时刻调用，但必须在 goto 之前，否则 SDK 已在冷启动查过一次会话）
 * 后置: `enabled` 为真时 document.cookie 已带两个 cookie；为假时一个也不写
 * 异常: 浏览器拒绝写 cookie 时由 addInitScript 在页面侧抛出，不在本函数吞掉
 *
 * 为什么用 addInitScript 而不是继续用 document.cookie 直接写：
 * `page.addInitScript` 保证脚本在文档的任何页面脚本之前执行，因此 SDK 冷启动时
 * 两个 cookie 一定已在；而 context.addCookies 需要域与路径完全匹配（端口无关但路径有
 * 隐式要求），用 document.cookie 在源内写入没有这类匹配问题。
 */
export async function installSession(page: Page, options: SessionInjectionOptions = {}): Promise<void> {
  if (options.enabled === false) return;

  const token = encodeFrontToken(frontTokenPayload(PROBE_UID, Date.now(), INJECTED_TTL_MS));
  const lastAccess = new Date().toISOString();

  await page.addInitScript(
    (cookies: { frontTokenName: string; frontToken: string; lastAccessName: string; lastAccess: string }) => {
      // path=/ 让 cookie 对整个源可见；SameSite 缺省 Lax 与本项目同源部署一致。
      // 名字来自上面的常量（经参数传入）：页面侧拿不到模块作用域，故随参数一起带过去，
      // 避免在这里重复写一份同值字面量（否则改常量不会生效）。
      document.cookie = `${cookies.frontTokenName}=${cookies.frontToken}; path=/`;
      document.cookie = `${cookies.lastAccessName}=${cookies.lastAccess}; path=/`;
    },
    {
      frontTokenName: FRONT_TOKEN_COOKIE,
      frontToken: token,
      lastAccessName: LAST_ACCESS_COOKIE,
      lastAccess,
    },
  );
}

/**
 * 断言登录态注入真的生效。
 *
 * 前置: 页面已 goto 且尚未进入目标形态（即本函数在等待目标内容之前调用）
 * 后置: 通过——URL 不是 /login，且页面上没有「正在确认登录状态」的等待态
 * 异常: `expect` 失败即抛（用例失败，不产生一张假的目标页截图）
 *
 * 为什么要这一条：cookie 注入失败时应用会走 RequireSession 的 anonymous 分支转 /login，
 * 而登录页同样能截出一张「看起来正常」的图——那是最坏的假绿：截图成功、内容却是错的页。
 * 因此「没被重定向」与「没停在等待态」都必须显式断言，而不是靠后续内容断言间接担保
 * （部分页的内容断言与登录页并不互斥）。
 *
 * 两段式而不是一条「等目标选择器」：
 *   1. 先等 React 根节点挂上内容——「已挂载」的正向凭据，避免在空白页上抢跑判定；
 *   2. 再等「不再是等待态」——等待态是守卫的 unknown 分支，它消失即表示查证已落定
 *      （落成 authenticated 或 anonymous，后者被 /login 断言拦下）。
 * 不用 `.phone-shell` 之类外观选择器做凭据：对话页的工作面不走 AppShell（没有该元素），
 * 而登录页反倒有它——同一选择器既是假阴性也是假阳性的来源。
 */
export async function expectSessionInjected(page: Page): Promise<void> {
  await expect(
    page.locator('#root > *').first(),
    'React 根节点没有挂载任何内容：页面脚本未执行或挂载失败',
  ).toBeAttached({ timeout: SESSION_READY_TIMEOUT_MS });

  await expect(
    page.getByText(SESSION_UNKNOWN_COPY, { exact: false }),
    `页面始终停在「${SESSION_UNKNOWN_COPY}」等待态：会话查证未落定（注入未生效、已过期或 SDK 未就绪）`,
  ).toHaveCount(0, { timeout: SESSION_READY_TIMEOUT_MS });

  expect(
    new URL(page.url()).pathname,
    '页面被重定向到 /login：登录态注入未生效（cookie 未写入或已过期）',
  ).not.toBe('/login');
}