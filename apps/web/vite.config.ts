import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/** 后端 dev 服务地址；与 apps/api 的 uvicorn 默认端口一致。 */
const BACKEND_ORIGIN = 'http://localhost:8000';

/**
 * 后端业务接口统一在 `/api` 前缀下（2026-10-01 起，见 `apps/api/src/campfire/main.py`
 * 的 `_API_PREFIX`）：`/api/consult/sessions`、`/api/auth/*` 等。
 *
 * 因此开发态只代理这一个前缀就够了。此前是逐段列业务前缀
 * （`/auth`、`/consult`、…）——那种写法在接口前缀变动时会**静默失效**：
 * 代理不匹配时 Vite 直接返回 index.html，页面拿到 HTML 当 JSON 解析而报出
 * 与真实原因无关的错误。一个前缀没有这个问题。
 *
 * 探针（`/livez`、`/readyz`、`/health`）不在 `/api` 下，单独代理，便于开发时
 * 直接访问健康检查。
 *
 * 开发态前端与 API 同为 localhost，属 same-site，cookie 与 anti-CSRF 头均成立
 * （认证与账号第 5 节本地开发条）。
 */
const PROXIED_PREFIXES = ['/api', '/livez', '/readyz', '/health'];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      PROXIED_PREFIXES.map((prefix) => [prefix, { target: BACKEND_ORIGIN, changeOrigin: false }]),
    ),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
    restoreMocks: true,
  },
});
