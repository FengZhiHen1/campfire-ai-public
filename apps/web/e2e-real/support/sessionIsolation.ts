/**
 * 模块: e2e-real/support/sessionIsolation
 * 职责: 账号隔离探针的共享装置——真实注册/登录/登出，以及「上一个账号的内容有没有出现过」的观察口
 *
 * 观察边界（如实声明）：
 *   - 观察粒度是 **DOM 变更批次**：`MutationObserver` 在其回调（微任务）里直接扫
 *     `document.body.innerText`，不设定时器，因此任何**跨过一个批次**的可见文本都会被看到。
 *   - 看不到的只有两类：同一任务内插入又移除（从未跨批次存在过的 DOM），以及始终
 *     `display:none` 的内容（`innerText` 只含可见文本，这是刻意的口径）。
 *   - 命中写进 `sessionStorage`：同标签页同源的 `page.goto` 之后仍在，否则「最后一页没泄漏」
 *     会被误当成「整段没泄漏」。`clearForbiddenHits` 同时清内存与这份存储。
 *   - 只观察：不改 DOM、不发请求、不拦响应（与 README §7「无 mock」不冲突）。
 *
 * 凭据纪律：口令只经参数传入用于填表，不打印、不落盘、不进产物；本模块只读 cookie 的
 * 名称与 httpOnly 标志，不读值。
 */

import { expect, type BrowserContext, type Page, type Request } from '@playwright/test';

import { BASE_URL, waitMounted } from './real';

/** 一条「禁用字符串出现过」的记录。 */
export interface ForbiddenTextHit {
  readonly needle: string;
  readonly url: string;
  readonly at: string;
  /** 命中处前后各 40 字（不含表单值）。 */
  readonly text: string;
}

/**
 * 装上禁用字符串观察口。
 *
 * 必须在第一次 `goto` 之前调用（`addInitScript` 只对之后的文档加载生效）。SPA 路由切换
 * 不重载文档，因此「A 登出 → B 登录 → B 逛各页」整段由同一个观察口覆盖。
 *
 * @param needles 禁用字符串；建议同时给一条**不存在**的串作阴性对照
 */
export async function installForbiddenTextWatch(page: Page, needles: readonly string[]): Promise<void> {
  await page.addInitScript((list: string[]) => {
    interface Hit {
      needle: string;
      url: string;
      at: string;
      text: string;
    }

    interface WatchWindow extends Window {
      siaForbiddenWatch?: { needles: string[]; hits: Hit[] };
    }

    const STORAGE_KEY = 'sia.forbidden-hits';
    const loadHits = (): Hit[] => {
      try {
        const raw = sessionStorage.getItem(STORAGE_KEY);
        if (raw === null) return [];
        const parsed: unknown = JSON.parse(raw);
        return Array.isArray(parsed) ? (parsed as Hit[]) : [];
      } catch {
        return [];
      }
    };
    const saveHits = (hits: Hit[]): void => {
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(hits));
      } catch {
        // 存储不可用时只留本页内存记录：不阻断观察。
      }
    };

    const target = window as WatchWindow;
    target.siaForbiddenWatch = { needles: [...list], hits: loadHits() };

    const scan = (): void => {
      const watch = target.siaForbiddenWatch;
      if (watch === undefined) return;
      const text = document.body?.innerText ?? '';
      let changed = false;
      for (const needle of watch.needles) {
        const at = text.indexOf(needle);
        if (at < 0) continue;
        // 同一页同一串只记一条：流式输出会让同一段字反复变动。
        if (watch.hits.some((hit) => hit.needle === needle && hit.url === location.href)) continue;
        watch.hits.push({
          needle,
          url: location.href,
          at: new Date().toISOString(),
          text: text.slice(Math.max(0, at - 40), at + needle.length + 40).replaceAll(/\s+/g, ' '),
        });
        changed = true;
      }
      if (changed) saveHits(watch.hits);
    };

    const start = (): void => {
      const root = document.documentElement;
      if (root === null) return;
      // 每个批次扫一次（无节流）。class/style/hidden 的变动同样要扫：把已存在的节点「显示出来」
      // 也是闪现 A 内容的一种形态，只看新增节点会漏掉它。
      new MutationObserver(() => {
        scan();
      }).observe(root, {
        childList: true,
        characterData: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['class', 'style', 'hidden', 'aria-hidden'],
      });
      scan();
    };

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
      start();
    }
  }, [...needles]);
}

/** 读出观察口已记录的命中（含此前文档累积的）。 */
export async function readForbiddenHits(page: Page): Promise<ForbiddenTextHit[]> {
  return page.evaluate(() => {
    const watch = (window as unknown as { siaForbiddenWatch?: { hits: ForbiddenTextHit[] } }).siaForbiddenWatch;
    return watch?.hits ?? [];
  });
}

/** 清空命中（内存 + `sessionStorage`），用于「阳性对照之后、切换账号之前」重新起算。 */
export async function clearForbiddenHits(page: Page): Promise<void> {
  await page.evaluate(() => {
    const watch = (window as unknown as { siaForbiddenWatch?: { hits: ForbiddenTextHit[] } }).siaForbiddenWatch;
    if (watch !== undefined) watch.hits.length = 0;
    try {
      sessionStorage.removeItem('sia.forbidden-hits');
    } catch {
      // 清内存已足够。
    }
  });
}

/**
 * 经真实邀请码注册，并断言注册**真的成功**。
 *
 * 只看 HTTP 200 不够：复用失效邀请码时身份服务返回 `200 + {status:'GENERAL_ERROR'}`，
 * 于是「只看 200」的断言恒真（README §4 的实测）。`invite` 必须非空——调用方负责断言，
 * 缺凭证要失败，不要跳过。
 */
export async function registerWithInvite(
  page: Page,
  account: string,
  password: string,
  invite: string,
): Promise<void> {
  await page.goto(`${BASE_URL}/login`);
  await waitMounted(page);
  await page.getByRole('button', { name: '已有邀请码？注册账号' }).click();
  await expect(page.locator('#auth-invite')).toBeVisible({ timeout: 20_000 });
  await page.fill('#auth-account', account);
  await page.fill('#auth-password', password);
  await page.fill('#auth-invite', invite);
  const answered = page.waitForResponse((response) => response.url().endsWith('/api/auth/signup'));
  await page.locator('button[type="submit"]').click();
  const signup = await answered;
  expect(signup.status(), '注册的 HTTP 状态（失效码同样是 200，见下一条）').toBe(200);
  expect((await signup.json() as { status: string }).status, '注册响应体 status 必须是 OK').toBe('OK');
  await expect(page).toHaveURL(`${BASE_URL}/`, { timeout: 45_000 });
}

/** 用已注册账号登录（不消耗邀请码）。 */
export async function signIn(page: Page, account: string, password: string): Promise<void> {
  await page.goto(`${BASE_URL}/login`);
  await waitMounted(page);
  await page.fill('#auth-account', account);
  await page.fill('#auth-password', password);
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(`${BASE_URL}/`, { timeout: 45_000 });
}

/** 走设置页的真实登出（确认单 → 退出 → 回登录页）。 */
export async function logoutViaSettings(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/settings`);
  await waitMounted(page);
  await page.getByRole('button', { name: '退出登录' }).click();
  const dialog = page.getByRole('dialog', { name: '退出登录？' });
  await expect(dialog).toBeVisible({ timeout: 20_000 });
  await dialog.getByRole('button', { name: '退出', exact: true }).click();
  await expect(page).toHaveURL(`${BASE_URL}/login`, { timeout: 30_000 });
}

/** 会话 cookie 读数（只有名称与 httpOnly 标志，**不含值**）。 */
export interface SessionCookieFacts {
  /** SDK 认证凭据；sFrontToken 是 JS 可见的会话元数据，不属于此集合。 */
  readonly tokenCookies: { name: string; httpOnly: boolean; path: string }[];
  /** `document.cookie` 能读到的 cookie 名——凭据不得出现在这里。 */
  readonly jsVisibleCookieNames: string[];
}

/** 读会话 cookie 事实：判据（httpOnly、前端不可读）由调用方给。 */
export async function readSessionCookieFacts(context: BrowserContext, page: Page): Promise<SessionCookieFacts> {
  const cookies = await context.cookies();
  const tokenCookies = cookies
    .filter((cookie) => cookie.name === 'sAccessToken' || cookie.name === 'sRefreshToken')
    .map((cookie) => ({ name: cookie.name, httpOnly: cookie.httpOnly, path: cookie.path }));
  const jsVisibleCookieNames = await page.evaluate(() =>
    document.cookie
      .split(';')
      .map((pair) => pair.split('=')[0]?.trim() ?? '')
      .filter((name) => name !== ''),
  );
  return { tokenCookies, jsVisibleCookieNames };
}

/** 记录匹配的请求地址（只用于等事件，不做断言）。 */
export function collectRequests(
  page: Page,
  predicate: (url: string) => boolean,
): { readonly urls: string[]; stop(): void } {
  const urls: string[] = [];
  const listener = (request: Request): void => {
    if (predicate(request.url())) urls.push(request.url());
  };
  page.on('request', listener);
  return {
    urls,
    stop(): void {
      page.off('request', listener);
    },
  };
}
