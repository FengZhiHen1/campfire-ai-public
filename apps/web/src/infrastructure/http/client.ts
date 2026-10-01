/**
 * 模块: infrastructure/http/client
 * 职责: 带凭据的 fetch 包装器——统一 401 语义的产品无关部分（清状态与跳转由 app 注入）
 * 数据来源:
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 2 节错误码（401 清本地状态跳登录页）
 *   - docs/项目结构设计.md: MUST — 第 9 节（view 不得直接调 HTTP）
 * 边界:
 *   - 依赖: 无框架模块（只用浏览器 fetch）
 *   - 被依赖: 各特性的 infrastructure 端口实现
 * 禁止行为:
 *   - 禁止把 401 处理写死成路由跳转（跳转归 app 层；本模块只发通知）
 *   - 禁止在此日志或错误消息里复述凭据与 Cookie
 */

/** 401 处置回调；由 app 层在装配时注入（清本地状态 + 跳登录页）。 */
export type UnauthorizedHandler = () => void;

/** 业务 HTTP 失败；status 保留原始状态码供调用方按契约分支。 */
export class HttpError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`HTTP ${status}: ${detail}`);
    this.name = 'HttpError';
  }
}

let unauthorizedHandler: UnauthorizedHandler | null = null;

/**
 * 业务接口的统一前缀。
 *
 * 为什么要有它（2026-10-01 修正，实测缺陷）：后端四个面的接口此前直接挂在根
 * （`/consult/*`、`/profile/*`），而前端**页面路由**用了同样的前缀。Nginx 把
 * `^/(consult|profile|...)` 转给 API，且正则 location 优先于 SPA 的 `location /`，
 * 于是 `/consult`、`/profile` 这些页面被转发给 API，用户直接访问或刷新会拿到
 * JSON 404/405 而不是应用界面。
 *
 * 现在接口在 `/api/*`、页面在 `/consult`，两类路径不可能再相撞。
 *
 * 前缀只在这一处拼（而不是各端口各写一遍）：端口里的路径继续表达**业务资源**
 * （`/consult/sessions`），与后端各 router 自己的 prefix 一致；「对外暴露在哪个
 * 前缀下」是部署决策，属于这一层。后端同样如此（`include_router(prefix=...)`）。
 */
const API_PREFIX = '/api';

/**
 * 把业务路径拼成实际请求路径。
 *
 * 导出供 SSE 传输层复用（`infrastructure/sse.ts` 的 fetch 不经 `request()`，因为它要读
 * 响应体流而不是 JSON）。前缀规则只有这一份——两处各写一遍必然漂移。
 *
 * @param path 业务路径，形如 `/consult/sessions`；已是绝对 URL 时原样返回。
 * @returns 带 `/api` 前缀的请求路径。
 */
export function withApiPrefix(path: string): string {
  // 绝对 URL 与协议相对地址不拼前缀：调用方显式给了完整地址，说明它知道要去哪。
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(path) || path.startsWith('//')) return path;
  return `${API_PREFIX}${path.startsWith('/') ? path : `/${path}`}`;
}

/**
 * 装配 401 处置回调。
 *
 * @param handler 收到 401 时要执行的动作；传入新值即替换旧值。
 */
export function setUnauthorizedHandler(handler: UnauthorizedHandler): void {
  unauthorizedHandler = handler;
}

/**
 * 清掉已装配的回调。
 *
 * 供测试与热更新使用：模块级单例不清理会让上一个用例装好的 spy 被下一个用例触发。
 */
export function clearUnauthorizedHandler(): void {
  unauthorizedHandler = null;
}

/**
 * 从错误响应正文里取出排障说明。
 *
 * 读不到结构化 detail 时返回 null（由调用方退回状态文本），不抛异常：
 * 错误响应是网关页、空体或非 JSON 都属正常情形，为它们中断错误处理反而会掩盖原始状态码。
 */
function readDetailField(raw: string): string | null {
  if (raw === '') return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    // 正文不是 JSON：这是预期分支而不是被吞掉的故障，明确转成 null 交给调用方回退。
    return null;
  }

  if (typeof parsed === 'object' && parsed !== null && 'detail' in parsed) {
    const detail = (parsed as { detail: unknown }).detail;
    if (typeof detail === 'string') return detail;
  }
  return null;
}

/**
 * 发起一次带凭据的业务请求。
 *
 * @param path 业务路径，形如 `/consult/sessions`（后端路由各自声明面前缀，本函数补 `/api`）。
 * @param init 额外请求配置；未提供 body 时不发送 Content-Type。
 * @returns 2xx 响应的 JSON 载荷。
 * @throws HttpError 非 2xx；401 会先触发已装配的处置回调再抛。
 * @throws SyntaxError 2xx 响应不是合法 JSON（服务端违约，不能当作空数据继续）。
 */
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(withApiPrefix(path), {
    ...init,
    // 会话凭据经 httpOnly cookie 自动携带（认证与账号第 5 节）；
    // anti-CSRF 头由 supertokens-web-js 包装过的 fetch 注入，此处不重复实现。
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(init.body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...init.headers,
    },
  });

  if (response.status === 401) {
    // 先通知 app 层清状态并跳登录页，再抛错让调用方停止后续处理——
    // 只清状态不抛错会让调用方拿到空体继续渲染，把「会话过期」显示成「没有数据」。
    unauthorizedHandler?.();
    throw new HttpError(401, '会话已失效');
  }

  if (!response.ok) {
    throw new HttpError(response.status, readDetailField(await response.text()) ?? response.statusText);
  }

  return (await response.json()) as T;
}
