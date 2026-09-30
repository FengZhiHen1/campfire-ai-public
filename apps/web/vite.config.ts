import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/** 后端 dev 服务地址；与 apps/api 的 uvicorn 默认端口一致。 */
const BACKEND_ORIGIN = 'http://localhost:8000';

/**
 * 后端路由不带 `/api` 前缀（契约路径是 `/consult/sessions`、`/auth/*` 等直接路径），
 * 因此这里逐段列出业务前缀，而不是笼统代理 `/api`。
 * 开发态前端与 API 同为 localhost，属 same-site，cookie 与 anti-CSRF 头均成立
 * （认证与账号第 5 节本地开发条）。
 */
const PROXIED_PREFIXES = ['/auth', '/consult', '/profile', '/memory', '/library', '/health'];

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
