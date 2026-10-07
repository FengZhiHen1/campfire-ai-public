/**
 * 模块: e2e/support/runid
 * 职责: 本次运行的批号（run id）——让「同一落点里混了两次运行的产物」变成可检测的
 * 数据来源:
 *   - docs/证据/orchestrator-20261002-001/T01-review-rulings.md: MUST — P2-3
 *     「部分成功运行会在复用的落点留下旧 manifest + 新旧混合 PNG……要能发现混批」
 * 边界:
 *   - 依赖: node:fs、node:crypto（Node 内置）
 *   - 被依赖: e2e/global.setup.ts（写入者）、e2e/shots.spec.ts（写进 sidecar）、
 *     e2e/manifest.spec.ts（汇总时校验一致）
 * 禁止行为:
 *   - 禁止用「时间戳碰巧不同」来代替显式批号（时间戳无法回答「这两张图是不是同一轮」）
 *   - 禁止在批号缺失时静默放过（缺失即失败：那份 sidecar 不该被混进 manifest）
 */

import { randomUUID } from 'node:crypto';
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';

import { MANIFEST_PATH, RUN_ID_PATH, SIDECAR_DIR } from './paths';

/**
 * 开始一次运行：生成本轮批号、清掉上一轮的残留。
 *
 * 前置: 无（由 Playwright 的 globalSetup 调用，早于任何用例）
 * 后置: 批号已落盘；`manifest.json` 与 `.run/` 里的上一轮残留已删除
 * 异常: 清理或写盘失败时向上抛（不吞：那会让「混批」在下一轮才暴露）
 *
 * 为什么要清残留（P2-3）
 *
 * 上一轮的行为是：截图用例边跑边覆盖 PNG，而 `manifest.json` 只在两个截图 project
 * 全绿时才重写。于是「部分成功」的一轮会留下旧 manifest + 新旧混合 PNG：
 * 清单里的 sha256 与它声称的那些 PNG 不再对应，而外观上目录是"满"的。
 * 清掉旧清单与旧 sidecar 后，「清单存在」就等价于「本轮跑完了」。
 */
export async function beginRun(): Promise<string> {
  await rm(SIDECAR_DIR, { recursive: true, force: true });
  await rm(MANIFEST_PATH, { force: true });
  // 目录要重建：上面刚把 .run/ 整个删掉，批号文件就写在它里面。
  await mkdir(SIDECAR_DIR, { recursive: true });

  // 批号 = 时间戳 + 随机段：前者便于人工按时间排序，后者保证同一毫秒内两次运行也不撞。
  const runId = `${new Date().toISOString()}-${randomUUID().slice(0, 8)}`;
  await writeFile(RUN_ID_PATH, runId, 'utf8');
  return runId;
}

/**
 * 读取本轮批号。
 *
 * 前置: 已调用 beginRun（即已在同一次运行的 globalSetup 覆盖下）
 * 后置: 返回本轮批号
 *
 * @throws Error 批号文件不存在或为空（说明没走 globalSetup，或落点被别的运行清了）
 *
 * 为什么缺失时抛错而不是降级用一个默认值：一个「默认批号」会让所有混批都通过校验，
 * 那正是这条机制要防的事——它就成了永远不失败的检查。
 */
export async function readRunId(): Promise<string> {
  const raw = await readFile(RUN_ID_PATH, 'utf8').catch(() => null);
  if (raw === null || raw.trim() === '') {
    throw new Error(
      `本次运行的批号文件不存在或为空（${RUN_ID_PATH}）：说明 globalSetup 未运行，` +
        '或落点被另一次运行清过。无法判定产物是否同批，故失败而不是放行。',
    );
  }
  return raw.trim();
}