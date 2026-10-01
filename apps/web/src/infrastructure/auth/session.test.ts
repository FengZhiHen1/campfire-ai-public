/**
 * 模块: infrastructure/auth/session 的 apiDomain 解析
 * 职责: 守住「协议跟随页面」这条性质——它决定了部署切到 HTTPS 时前端会不会因
 *       mixed content 而整体失效
 * 数据来源:
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 5 节（SDK 装配）
 * 边界:
 *   - 依赖: vitest
 *   - 被依赖: 无（纯测试）
 * 禁止行为:
 *   - 禁止只断言「读到了环境变量」而不测协议跟随——那正是本文件存在的理由
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

/**
 * 为什么必须测「协议跟随」：
 *
 * `VITE_API_DOMAIN` 是构建期常量。若原样写成 apiDomain，产物就固定了一个协议。
 * 用 `http://` 构建的产物拿到 `https://` 上服务时，页面会请求 `http://` 接口，
 * 被浏览器以 **mixed content** 拦掉——请求根本发不出去，界面上是一堆没有网络
 * 记录的失败（本次就是这样两个 P0 的邻居）。
 *
 * 由于部署形态是 nginx 同源托管 + 反代 `/api`，同源永远正确且天然跟随协议。
 */

/** 重置模块缓存后以指定 location 与构建期变量重新求值。 */
async function loadWith(opts: { origin: string; configured?: string }) {
  vi.resetModules();
  vi.stubGlobal('location', { origin: opts.origin, host: new URL(opts.origin).host });
  vi.stubEnv('VITE_API_DOMAIN', opts.configured ?? '');
  const mod = await import('./session');
  return mod.sessionApiDomain();
}

describe('sessionApiDomain — 协议跟随页面', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it('配置与页面同 host 时用页面 origin（HTTP 构建产物在 HTTP 下 → http）', async () => {
    const domain = await loadWith({
      origin: 'http://campfire.example',
      configured: 'http://campfire.example',
    });
    expect(domain).toBe('http://campfire.example');
  });

  it('**同一份 HTTP 构建的产物**在 HTTPS 页面下解析为 https（mixed content 防线）', async () => {
    const domain = await loadWith({
      origin: 'https://campfire.example',
      configured: 'http://campfire.example',
    });
    expect(domain).toBe('https://campfire.example');
  });

  it('反过来：HTTPS 构建的产物在 HTTP 页面下解析为 http', async () => {
    const domain = await loadWith({
      origin: 'http://campfire.example',
      configured: 'https://campfire.example',
    });
    expect(domain).toBe('http://campfire.example');
  });

  it('配置指向别的 host 时尊重配置原值（本地开发：页面 :5173、接口 :8000）', async () => {
    const domain = await loadWith({
      origin: 'http://localhost:5173',
      configured: 'http://localhost:8000',
    });
    expect(domain).toBe('http://localhost:8000');
  });

  it('未配置时用页面 origin（而不是写死 localhost）', async () => {
    const domain = await loadWith({ origin: 'https://campfire.example' });
    expect(domain).toBe('https://campfire.example');
  });

  it('配置不是合法 URL 时按同源处理，不抛异常', async () => {
    const domain = await loadWith({ origin: 'https://campfire.example', configured: '/api' });
    expect(domain).toBe('https://campfire.example');
  });
});
