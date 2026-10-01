/**
 * 模块: infrastructure/auth/session
 * 职责: 身份服务前端 SDK 的装配——init 与 Session recipe，实现 accounts 的 SessionPort
 * 数据来源:
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 5 节（supertokens-web-js 职责）
 *   - docs/项目结构设计.md: MUST — 第 9 节（凭据纪律）
 * 边界:
 *   - 依赖: supertokens-web-js（唯一被允许接触身份服务的模块）
 *   - 被依赖: app 的装配
 * 禁止行为:
 *   - 禁止读取或存储 access/refresh 令牌（httpOnly cookie，前端不可读）
 *   - 禁止在此做业务授权判定（前端守卫只负责体验，不是权限证明）
 */

import SuperTokens from 'supertokens-web-js';
import Session from 'supertokens-web-js/recipe/session';

import type { SessionPort } from '../../features/accounts/application/ports';

/**
 * 后端 API 源。
 *
 * 开发态走 Vite dev 代理时同源，用相对路径反而更稳；但身份服务要求显式 apiDomain
 * （授权与 anti-CSRF 判定基于它），因此这里保留环境变量入口，默认开发态指向本地 API
 * （认证与账号第 5 节本地开发条：端口不同但同为 localhost，属 same-site）。
 */
const API_DOMAIN: string = import.meta.env.VITE_API_DOMAIN ?? 'http://localhost:8000';

/**
 * 身份服务挂载路径；后端 FastAPI 按固定的 apiBasePath 挂载 `/api/auth/*`。
 *
 * 与 `core/config.py` 的 `supertokens_api_base_path` 必须一致：一处是后端的挂载点，
 * 一处是前端 SDK 拼 URL 的依据，不一致会让登录/刷新请求打到 404。
 * 2026-10-01 起两者一起从 `/auth` 改为 `/api/auth`（统一收进 /api 前缀）。
 */
const API_BASE_PATH = '/api/auth';

let initialized = false;

/**
 * 装配身份服务前端 SDK（幂等）。
 *
 * 前置: 无
 * 后置: 首次调用完成 init；重复调用不重复初始化（SDK 的 init 会重装全局 fetch 拦截器）
 * 异常: SuperTokensConfig 不合法时由 SDK 抛出——不在此捕获，装配失败必须可见
 *
 * 为什么 init 只做一次：SDK 的 init 会把全局 fetch 换成带刷新重试与 anti-CSRF 注入的
 * 版本；重复 init 在页面上堆叠拦截器，会让一次 401 触发多轮刷新。
 * init 不发网络请求，因此后端未启动不会使本调用失败。
 */
export function initSession(): void {
  if (initialized) return;
  SuperTokens.init({
    appInfo: {
      appName: 'campfire-web',
      apiDomain: API_DOMAIN,
      apiBasePath: API_BASE_PATH,
    },
    recipeList: [Session.init()],
  });
  initialized = true;
}

/**
 * 会话端口的 SDK 实现。
 *
 * 为什么这里不实现刷新重试循环：supertokens-web-js 已在全局 fetch 拦截器里承担
 * 「令牌过期时的刷新重试」与 anti-CSRF 头注入（认证与账号第 5 节，并注明并发请求遇
 * 401 的单飞刷新是自写 HTTP 层的常见缺陷来源）。自写一层等于把该缺陷重新引入。
 */
export const supertokensSessionPort: SessionPort = {
  doesSessionExist: () => Session.doesSessionExist(),
  signOut: () => Session.signOut(),
};

/** 测试用：重置初始化标记（vitest 用例间隔离，避免二次 init 被幂等分支吞掉）。 */
export function resetSessionInitForTests(): void {
  initialized = false;
}

/** 当前装配使用的 apiDomain；供排障与断言读取，不含任何凭据。 */
export function sessionApiDomain(): string {
  return API_DOMAIN;
}
