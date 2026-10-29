/**
 * 模块: app/App
 * 职责: 应用外壳装配——身份 SDK 初始化、会话查证、401 处置接线与路由表挂载
 * 数据来源:
 *   - docs/项目结构设计.md: MUST — 第 9 节（app 负责路由、Provider 与装配）
 * 边界:
 *   - 依赖: app/routes、infrastructure/auth/session、features/accounts/viewModel
 *   - 被依赖: src/main
 * 禁止行为:
 *   - 禁止在 view 层直接调 HTTP（数据获取归 infrastructure 端口 + application 用例）
 *   - 禁止把 401 处置写成权限判定（它只清本地状态并跳登录页）
 */

import { useEffect } from 'react';
import { RouterProvider, createBrowserRouter } from 'react-router';

import { buildRouteObjects } from './routes';
import { initSession, supertokensSessionPort } from '../infrastructure/auth/session';
import { setUnauthorizedHandler } from '../infrastructure/http/client';
import { useSessionStore } from '../features/accounts/viewModel/sessionStore';
import { installSessionCacheReset } from './sessionCacheReset';

/**
 * 路由实例只建一次（模块级）。写在 render 体里时，App 的任何一次重渲染都会
 * 换掉 history 与全部路由订阅（路由状态丢失、监听器泄漏）。
 */
const router = createBrowserRouter(buildRouteObjects());

/**
 * 装配全局副作用：SDK 初始化、启动时查证会话、401 处置。
 *
 * 前置: 无
 * 后置: SDK 已 init；会话状态被查证一次；此后任何 401 都会把会话标为匿名
 *
 * 两条失败路径的处置刻意不同：
 * 会话查证失败由 ResolveSessionUseCase 返回 unknown（显式状态，守卫显示等待态）；
 * SDK 装配失败则不捕获——它意味着整个凭据传输通道不可用，让异常冒泡成可见错误
 * 比吞掉它、让使用者对着永不结束的等待态更好。init 本身不发网络请求，后端未起时不会走这条路。
 *
 * 为什么不把 401 处置做成路由跳转：跳转需要 router 上下文，而 handler 由
 * infrastructure 的 fetch 包装器调用。这里只改 store，跳转由 RequireSession 的
 * Navigate 完成——单一跳转路径，避免两处各写一份导航逻辑。
 */
function useAppBootstrap(): void {
  const refresh = useSessionStore((state) => state.refresh);
  const markAnonymous = useSessionStore((state) => state.markAnonymous);

  useEffect(() => {
    initSession();
    // 先订阅再查证：查证落定（unknown → authenticated / anonymous）也是一次身份变化。
    const uninstall = installSessionCacheReset();
    void refresh(supertokensSessionPort);
    setUnauthorizedHandler(markAnonymous);
    return uninstall;
  }, [refresh, markAnonymous]);
}

/**
 * 应用外壳：路由表 + 启动装配。
 *
 * 前置: 无
 * 后置: 挂载路由树；启动副作用已接线
 * 异常: 无
 */
export function App() {
  useAppBootstrap();
  return <RouterProvider router={router} />;
}
