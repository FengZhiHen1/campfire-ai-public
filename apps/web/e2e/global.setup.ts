/**
 * 模块: e2e/global.setup
 * 职责: 在本次运行的任何用例之前开一轮新批——清上一轮残留、生成本轮批号
 * 数据来源:
 *   - .tmp/dev-orchestrator/20261002-001/feedback/T01-review-rulings.md: MUST — P2-3
 *     （部分成功运行会留下旧 manifest + 新旧混合 PNG；要求能发现混批）
 * 边界:
 *   - 依赖: e2e/support/runid
 *   - 被依赖: playwright.config.ts 的 globalSetup
 * 禁止行为:
 *   - 禁止把清理写成「尽力而为、失败就跳过」（那正好会在混批场景失效并静默继续）
 */

import { beginRun } from './support/runid';

/**
 * Playwright 的 globalSetup 入口：开一轮新批。
 *
 * 为什么用 globalSetup 而不是各 spec 里的 beforeAll：清理必须在所有 project
 * （mobile / desktop / manifest）之前恰好发生一次。放在某个 spec 的 beforeAll 里，
 * 两个视口 project 会并发各清一次，先跑的那个把另一个已写的 sidecar 删掉。
 */
export default async function globalSetup(): Promise<void> {
  const runId = await beginRun();
  // 打进日志便于事后把「这一轮的图」与「这一轮的日志」对上。
  process.stdout.write(`[globalSetup] 本轮截图批号：${runId}\n`);
}