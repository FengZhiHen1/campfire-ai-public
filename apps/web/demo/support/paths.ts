/**
 * 模块: demo/support/paths
 * 职责: 演示材料装置的全部路径与几何常量——本装置里唯一写下这些字面量的地方
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 落点 `demo/`（仓库根、整目录不入库、每轮覆盖）、
 *     单视口 mobile 390×844@2x、目录布局 `<slug>/<NN>-<id>.png`
 * 边界:
 *   - 依赖: node:path、node:url（Node 内置，不引入第三方）
 *   - 被依赖: demo/support/*、demo/global.setup.ts、demo/playwright.demo.config.ts
 * 禁止行为:
 *   - 禁止在别处写字面量路径（改落点只改本文件）
 *   - 禁止提供环境变量改道落点：2026-10-27 用户裁决「固定一个位置」，
 *     而 `SHOTS_OUT` 这条等价通道在历史上正好被用来把产物散到第二个临时目录
 *   - 禁止从 apps/web/src 下 import 本文件（工程设施不进产品代码）
 */

import { relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

/** 本文件所在目录（apps/web/demo/support）。 */
const SUPPORT_DIR = fileURLToPath(new URL('.', import.meta.url));
/** 演示装置目录（apps/web/demo）。 */
export const DEMO_DIR = resolve(SUPPORT_DIR, '..');
/** 前端包根（apps/web）。 */
export const WEB_ROOT = resolve(DEMO_DIR, '..');
/** 仓库根：落点与 manifest 里相对路径的参照系。 */
export const REPO_ROOT = resolve(WEB_ROOT, '..', '..');

/**
 * 演示材料落点（仓库根 `demo/`）。
 *
 * 该目录整体在 `.gitignore` 与 `.dockerignore` 里（见两文件中的条目），
 * 因此**不入库、不进镜像**，但在磁盘上位置固定、不被 `.tmp/` 的清理带走。
 * 保留策略是「只留当前基线，每轮覆盖」：`global.setup.ts` 开新批时清空本目录内容。
 */
export const DEMO_OUT_DIR: string = resolve(REPO_ROOT, 'demo');

/** 一张图一个 sidecar 的目录；由截图用例写、由 manifest project 汇总并核对。 */
export const SIDECAR_DIR: string = resolve(DEMO_OUT_DIR, '.run');

/** 本轮批号落点：写入者 global.setup，读取者截图用例与汇总核对。 */
export const RUN_ID_PATH: string = resolve(SIDECAR_DIR, 'run-id.txt');

/** manifest 落点（相对仓库根的路径会写进 manifest 自身）。 */
export const MANIFEST_PATH: string = resolve(DEMO_OUT_DIR, 'manifest.json');

/**
 * Playwright 自身的 outputDir（失败 trace 等）。
 *
 * 必须是落点的子目录而不是落点本身：Playwright 每次运行会清空 outputDir，
 * 指到落点本身会把上一轮的 PNG 一起删掉。
 */
export const PLAYWRIGHT_OUTPUT_DIR: string = resolve(DEMO_OUT_DIR, '.playwright');

/** 预览/开发服务器地址：真实栈由使用者先起（本装置不声明 webServer）。 */
export const BASE_URL: string = process.env.DEMO_BASE_URL?.trim() || 'http://127.0.0.1:5173';

/**
 * 单视口：演示材料只出手机端。
 *
 * 理由：一期只交付手机端 H5（docs/需求/功能需求与验收.md），对外展示要的是产品真实形态；
 * 双视口会让材料量翻倍且 40 张矩阵已由 `pnpm shots` 覆盖，两者不重复。
 */
export const VIEWPORT = { width: 390, height: 844 } as const;

/** 设备像素比：与截图基建一致用 2 倍，投影/缩放时字不糊。 */
export const DEVICE_SCALE_FACTOR = 2;

/** 单个场景的整条走查上界：真实模型调用 + 页面水合，留足余量。 */
export const SCENARIO_TIMEOUT_MS = 300_000;

/** 单张截图前等待页面静定的上界（字体、动画、流式收尾都在这条之内）。 */
export const SETTLE_TIMEOUT_MS = 20_000;

/**
 * 场景短名（顺序即 manifest 与磁盘目录的呈现顺序）。
 *
 * 这张表是「已实现」清单，不是愿望清单：每加入一个场景必须同时补齐三处
 * （① 本表登记；② `scenarios/<slug>.schema.ts` 声明步骤与讲解词；
 * ③ `scenarios/<slug>.spec.ts` 真跑），三者不一致由
 * `apps/web/tests/demo-coverage.test.ts` 机械判失败。
 * 目标场景共 6 个，尚未实现的部分登记在 docs/TODO.md，不写进本表——
 * 否则 manifest 会宣布一批根本不存在的材料。
 */
export const SCENARIO_SLUGS = [
  'onboarding',
  'consult-citation',
  'emergency',
  'library',
  'profile',
  'memory',
] as const;

/** 场景短名联合类型。 */
export type ScenarioSlug = (typeof SCENARIO_SLUGS)[number];

/** 一张图的绝对路径：`<落点>/<slug>/<NN>-<stepId>.png`。 */
export function shotFilePath(slug: ScenarioSlug, index: number, stepId: string): string {
  return resolve(DEMO_OUT_DIR, slug, `${String(index + 1).padStart(2, '0')}-${stepId}.png`);
}

/** 一张图的 sidecar 绝对路径：`<落点>/.run/<slug>/<NN>-<stepId>.png.json`。 */
export function sidecarPath(slug: ScenarioSlug, index: number, stepId: string): string {
  return resolve(SIDECAR_DIR, slug, `${String(index + 1).padStart(2, '0')}-${stepId}.png.json`);
}

/** 把绝对路径转成相对仓库根的 POSIX 路径（manifest 里一律用它，便于跨机器阅读）。 */
export function toRepoRelative(absolutePath: string): string {
  return relative(REPO_ROOT, resolve(absolutePath)).split('\\').join('/');
}
