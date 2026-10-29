/**
 * @vitest-environment node
 *
 * 模块: tests/demo-manifest
 * 职责: 给「演示材料的五条判据」各配一个能失败的用例——判定逻辑不许只靠真跑验证
 * 数据来源:
 *   - docs/运维/演示材料生成.md 第 6 节: MUST — 五条判据（声明⊆产物、产物⊆声明、同批、
 *     哈希复算、帧唯一性）都必须**能变红**，不满足时 `manifest.json` 不写出
 *   - apps/web/demo/support/manifest.ts: 被测实现
 * 边界:
 *   - 依赖: vitest、node:fs/promises、node:os（临时目录）、node:path
 *   - 被依赖: 无（这是叶子测试）
 *   - 落点常量由 `vi.mock('../demo/support/paths')` 改道到临时目录：真实落点 `demo/`
 *     每轮被清理，测试不能碰它
 * 禁止行为:
 *   - 禁止只断言「有 problem」而不点名：五条判据必须能被区分，混成一条等于少四条
 *   - 禁止在测试里跳过「基线为绿」这一例：没有基线，红也说明不了谁坏了
 */

import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/** 临时落点（每个用例一份）；由 `vi.mock` 的工厂读它，故必须 hoisted。 */
const sandbox = vi.hoisted(() => ({ dir: '' }));

vi.mock('../demo/support/paths', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../demo/support/paths')>();
  return {
    ...actual,
    get DEMO_OUT_DIR() {
      return sandbox.dir;
    },
    get SIDECAR_DIR() {
      return join(sandbox.dir, '.run');
    },
    get RUN_ID_PATH() {
      return join(sandbox.dir, '.run', 'run-id.txt');
    },
    get MANIFEST_PATH() {
      return join(sandbox.dir, 'manifest.json');
    },
    sidecarPath: (slug: string, index: number, stepId: string): string =>
      join(sandbox.dir, '.run', slug, `${String(index + 1).padStart(2, '0')}-${stepId}.png.json`),
  };
});

const { buildDemoManifest } = await import('../demo/support/manifest');
const { VIEWPORT, DEVICE_SCALE_FACTOR, REPO_ROOT, toRepoRelative } = await import('../demo/support/paths');
const { REPO_ROOT: SHOTS_REPO_ROOT, toRepoRelative: shotsToRepoRelative } = await import('../e2e/support/paths');
type DemoScenario = import('../demo/support/scenario').DemoScenario;

const RUN_ID = '2026-10-27T00:00:00.000Z-abcdef12';

/**
 * 造一个「头部合法」的 PNG。
 *
 * 判据要的只是签名与 IHDR 里的宽高（`readPngSize` 只读这两处），因此不必真编码像素；
 * 填充字节由 `salt` 决定，好让「两张图内容不同」这件事可控。
 */
function fakePng(width: number, height: number, salt: string): Buffer {
  const buffer = Buffer.alloc(32);
  buffer.writeUInt32BE(0x89504e47, 0);
  buffer.writeUInt32BE(0x0d0a1a0a, 4);
  buffer.writeUInt32BE(width, 16);
  buffer.writeUInt32BE(height, 20);
  buffer.write(salt, 24, 'utf8');
  return buffer;
}

const WIDTH = VIEWPORT.width * DEVICE_SCALE_FACTOR;
const HEIGHT = VIEWPORT.height * DEVICE_SCALE_FACTOR;

const SCENARIO: DemoScenario = {
  slug: 'onboarding',
  title: '注册登录 → 首次咨询 → 引导建档',
  claim: '用一句话说明这条链路证明了什么。',
  steps: [
    { id: 'login-entry', caption: '登录页：一期不发自助注册。' },
    { id: 'home-after-register', caption: '注册成功直接进首页。' },
  ],
};

/** 写一张图与它的 sidecar；`overrides` 用于制造被判据抓住的各种坏情况。 */
async function writeShot(
  options: {
    index?: number;
    bytes?: Buffer;
    runId?: string;
    skipSidecar?: boolean;
    skipPng?: boolean;
    sha256?: string;
  } = {},
): Promise<void> {
  const index = options.index ?? 0;
  const step = SCENARIO.steps[index];
  if (step === undefined) throw new Error('用例写错了：没有这一步');
  const name = `${String(index + 1).padStart(2, '0')}-${step.id}`;
  const bytes = options.bytes ?? fakePng(WIDTH, HEIGHT, `step-${String(index)}`);
  const pngPath = join(sandbox.dir, SCENARIO.slug, `${name}.png`);
  const sidecarPath = join(sandbox.dir, '.run', SCENARIO.slug, `${name}.png.json`);
  await mkdir(join(sandbox.dir, SCENARIO.slug), { recursive: true });
  await mkdir(join(sandbox.dir, '.run', SCENARIO.slug), { recursive: true });
  if (options.skipPng !== true) await writeFile(pngPath, bytes);
  if (options.skipSidecar === true) return;
  await writeFile(
    sidecarPath,
    JSON.stringify({
      slug: SCENARIO.slug,
      index,
      stepId: step.id,
      caption: step.caption,
      file: `demo/${SCENARIO.slug}/${name}.png`,
      runId: options.runId ?? RUN_ID,
      capturedAt: '2026-10-27T00:00:00.000Z',
      sha256: options.sha256 ?? createHash('sha256').update(bytes).digest('hex'),
      bytes: bytes.length,
      width: WIDTH,
      height: HEIGHT,
    }),
    'utf8',
  );
}

beforeEach(async () => {
  sandbox.dir = await mkdtemp(join(tmpdir(), 'campfire-demo-'));
  await mkdir(join(sandbox.dir, '.run'), { recursive: true });
  await writeFile(join(sandbox.dir, '.run', 'run-id.txt'), RUN_ID, 'utf8');
});

afterEach(async () => {
  await rm(sandbox.dir, { recursive: true, force: true });
});

describe('材料路径在 worktree 与临时落点中的身份', () => {
  it.each([
    ['demo', REPO_ROOT, toRepoRelative],
    ['shots', SHOTS_REPO_ROOT, shotsToRepoRelative],
  ] as const)('%s：仓库外的两张图仍有不同且可还原的路径', (_name, root, convert) => {
    const first = join(sandbox.dir, '01-declared.png');
    const second = join(sandbox.dir, '99-orphan.png');
    expect(convert(first)).not.toBe(convert(second));
    expect(resolve(root, convert(first))).toBe(first);
    expect(resolve(root, convert(second))).toBe(second);
    expect(convert(join(root, 'demo', 'shot.png'))).toBe('demo/shot.png');
  });
});

describe('演示材料清单的五条判据', () => {
  it('基线：图、sidecar、批号三者对齐时没有问题', async () => {
    await writeShot({ index: 0 });
    await writeShot({ index: 1 });
    const { manifest, problems } = await buildDemoManifest([SCENARIO]);
    expect(problems).toEqual([]);
    expect(manifest.totals.shots).toBe(2);
    expect(manifest.origin).toBeTruthy();
  });

  it('判据一：声明了却没有图 ⇒ 点名那一张', async () => {
    await writeShot({ index: 0 });
    // 第 2 步只写 sidecar 不写图：模拟「截图那一步挂了」。
    await writeShot({ index: 1, skipPng: true });
    const { problems } = await buildDemoManifest([SCENARIO]);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain('home-after-register');
    expect(problems[0]).toContain('磁盘上没有');
  });

  it('判据二：落点里多出一张没声明的图 ⇒ 点名孤儿图', async () => {
    await writeShot({ index: 0 });
    await writeShot({ index: 1 });
    await writeFile(join(sandbox.dir, SCENARIO.slug, '99-orphan.png'), fakePng(WIDTH, HEIGHT, 'orphan'));
    const { problems } = await buildDemoManifest([SCENARIO]);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain('99-orphan.png');
    expect(problems[0]).toContain('多余图');
  });

  it('判据三：sidecar 的批号与本轮不同 ⇒ 判混批', async () => {
    await writeShot({ index: 0 });
    await writeShot({ index: 1, runId: '2026-10-26T00:00:00.000Z-deadbeef' });
    const { problems } = await buildDemoManifest([SCENARIO]);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain('混批');
  });

  it('判据四：图被换过（哈希对不上）⇒ 失败', async () => {
    await writeShot({ index: 0 });
    await writeShot({ index: 1, sha256: 'f'.repeat(64) });
    const { problems } = await buildDemoManifest([SCENARIO]);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain('sha256');
  });

  it('判据五：同一场景两帧逐字节相同 ⇒ 第二帧不是新画面', async () => {
    const same = fakePng(WIDTH, HEIGHT, 'same');
    await writeShot({ index: 0, bytes: same });
    await writeShot({ index: 1, bytes: same });
    const { problems } = await buildDemoManifest([SCENARIO]);
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain('逐字节相同');
  });

  it('缺批号文件时直接抛错（不降级成默认值）', async () => {
    await writeShot({ index: 0 });
    await rm(join(sandbox.dir, '.run', 'run-id.txt'));
    await expect(buildDemoManifest([SCENARIO])).rejects.toThrow(/批号文件不存在或为空/);
  });
});
