import { Outlet } from 'react-router-dom';

/**
 * 应用外壳 — 路由出口容器。
 * Phase 0 占位，后续将集成 TabBar、PageContent、安全区适配。
 */
export default function AppShell() {
  return <Outlet />;
}
