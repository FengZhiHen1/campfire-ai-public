/**
 * 模块: e2e/global.setup
 * 职责: 在本次运行的任何用例之前开一轮新批——生成本轮批号，并在截图入口上清上一轮残留
 * 数据来源:
 *   - docs/证据/orchestrator-20261002-001/T01-review-rulings.md: MUST — P2-3
 *     （部分成功运行会留下旧 manifest + 新旧混合 PNG；要求能发现混批）
 * 边界:
 *   - 依赖: e2e/support/runid
 *   - 被依赖: playwright.config.ts 的 globalSetup
 * 禁止行为:
 *   - 禁止把清理写成「尽力而为、失败就跳过」（那正好会在混批场景失效并静默继续）
 *   - 禁止在断言入口（`pnpm e2e`）上清掉上一轮 `shots` 的产物——那是评审要看的证据
 */

import { beginRun } from './support/runid';

/**
 * 本次运行是否包含截图入口的 project。
 *
 * 判据取**精确的 `--project=` 参数**而不是 spec 文件名，理由是 2026-10-07 实测到的连带行为：
 * manifest project 声明了 `dependencies: ['mobile', 'desktop']`，只要它被选中就会把两个视口
 * project 一起带跑。入口因此由 project 划定（见 playwright.config.ts 的 testMatch），
 * 这里就必须按同一组 project 名判断。
 *
 * 用精确相等而不是子串匹配：`content-desktop` 含 `desktop`，按子串判会把断言入口误判成
 * 截图入口，于是跑一次断言就删掉了上一次截图的 manifest.json。
 *
 * 为什么从 `process.argv` 判而不是用环境变量：npm script 里 `SHOTS_RESET=1` 在 Windows 的
 * cmd 下不生效，`set X=1&&` 在 POSIX sh 下不生效，而引入 `cross-env` 属于为一行配置新增
 * 依赖（项目禁令）。globalSetup 与 runner 同进程，argv 就是命令行本身，两个平台一致。
 */
const SCREENSHOT_PROJECTS = new Set(['--project=mobile', '--project=desktop', '--project=manifest']);

/**
 * Playwright 的 globalSetup 入口：开一轮新批。
 *
 * 为什么用 globalSetup 而不是各 spec 里的 beforeAll：清理必须在所有 project
 * （mobile / desktop / manifest）之前恰好发生一次。放在某个 spec 的 beforeAll 里，
 * 两个视口 project 会并发各清一次，先跑的那个把另一个已写的 sidecar 删掉。
 *
 * 为什么清理由「本次是否跑截图」决定：截图与内容断言是两条入口（`pnpm shots` / `pnpm e2e`）
 * 但共用这一份配置。无条件清理会让「跑一次断言」删掉「上一次截图的 manifest.json」——
 * 那是评审要看的产物，删它属于静默销毁证据。见 `support/runid.ts` 的 `beginRun`。
 */
export default async function globalSetup(): Promise<void> {
  const reset = process.argv.some((argument) => SCREENSHOT_PROJECTS.has(argument));
  const runId = await beginRun(reset);
  // 打进日志便于事后把「这一轮的图」与「这一轮的日志」对上。
  process.stdout.write(`[globalSetup] 本轮批号：${runId}（清理上一轮产物：${reset ? '是' : '否'}）\n`);
}
