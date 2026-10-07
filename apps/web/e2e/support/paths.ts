/**
 * 模块: e2e/support/paths
 * 职责: 截图基建的固定常量——落点解析、页面 × 视口 × 图种矩阵与两处时间上界
 * 数据来源:
 *   - docs/证据/orchestrator-20261002-001/T01.md: MUST — 裁决 E（两视口、命名、--out 支持、落点 tmp/screenshots）
 *   - docs/证据/orchestrator-20261002-001/T01-rulings.md: MUST — 裁决 1 与其追加裁决
 *     （每条页面 × 视口 出两张图：视口图与 fullPage 图，命名 `<page>-<viewport>-full.png`）
 *   - docs/项目结构设计.md: MUST — 第 9 节（e2e 属工程设施，不被 src 引用）
 * 边界:
 *   - 依赖: node:path、node:url（Node 内置，不引入第三方）
 *   - 被依赖: playwright.config.ts、e2e 的 spec 与 global setup/teardown
 * 禁止行为:
 *   - 禁止把落点写成字面量散落在各文件（默认值只在本文件算一次）
 *   - 禁止从 src 下任何模块 import 本文件（分层纪律：工程设施不进产品代码）
 */

import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

/** 本文件所在目录（apps/web/e2e/support）。 */
const SUPPORT_DIR = fileURLToPath(new URL('.', import.meta.url));
/** e2e 目录（apps/web/e2e）。 */
export const E2E_DIR = resolve(SUPPORT_DIR, '..');
/** 前端包根（apps/web）。webServer 的 command 默认就在这个目录里执行。 */
export const WEB_ROOT = resolve(E2E_DIR, '..');
/** 仓库根。落点默认值的参照系。 */
export const REPO_ROOT = resolve(WEB_ROOT, '..', '..');

/**
 * 落点根目录。
 *
 * 默认 `.tmp/screenshots`（相对仓库根；`.tmp/` 随根 `.gitignore` 被忽略，
 * 且已被 `pyproject.toml` 的 ruff exclude 与 `.dockerignore` 排除）。
 * 可用环境变量 `SHOTS_OUT` 改写；相对路径按仓库根解析，绝对路径原样使用。
 * 为什么不提供 `--out` 命令行开关：`playwright test` 会拒绝未知选项，而它自己的同名选项
 * （`--output`）指的是测试产物目录、语义不同；环境变量是任务包允许的等价通道，且不会被
 * 与 Playwright 自带选项混用。
 *
 * 2026-10-06：原落点 `tmp/screenshots`（与 `.tmp/` 并列的**第二个**临时目录）。
 * 该目录已按「只保留一个临时目录」的裁决整体清空，落点统一到 `.tmp/`——
 * 不改这里会在下次跑 e2e 时**把 `tmp/` 重新建出来**，两目录的问题就回来了。
 */
export const SHOTS_OUT_DIR: string = ((): string => {
  const configured = process.env.SHOTS_OUT;
  if (configured === undefined || configured.trim() === '') return resolve(REPO_ROOT, '.tmp', 'screenshots');
  return resolve(REPO_ROOT, configured.trim());
})();

/**
 * Playwright 自身的测试产物目录（trace、失败截图等）。
 *
 * 必须是落点的子目录而不是落点本身：Playwright 每次运行会清空 outputDir，
 * 指向落点本身会把上一轮的基线 PNG 一起删掉。
 */
export const PLAYWRIGHT_OUTPUT_DIR: string = resolve(SHOTS_OUT_DIR, '.playwright');

/** 每张图一条 sidecar JSON 的目录；由 global teardown 合并成 manifest.json。 */
export const SIDECAR_DIR: string = resolve(SHOTS_OUT_DIR, '.run');

/** manifest 落点。 */
export const MANIFEST_PATH: string = resolve(SHOTS_OUT_DIR, 'manifest.json');

/**
 * 本轮运行批号的落点。
 *
 * 由 `e2e/global.setup.ts` 写入、由截图用例记进每条 sidecar、由汇总时校验一致——
 * 三者用同一个批号，「同一落点混了两次运行的产物」就会在汇总时被点名（P2-3）。
 */
export const RUN_ID_PATH: string = resolve(SIDECAR_DIR, 'run-id.txt');

/** 页面语义短名（裁决 E 的表；顺序即 manifest 与基线的呈现顺序）。 */
export const PAGE_NAMES = [
  'login',
  'home',
  'consult-list',
  'chat',
  'emergency',
  'profile',
  'cases',
  'settings',
  'memory',
  'guide',
] as const;

/** 页面语义短名的联合类型。 */
export type PageName = (typeof PAGE_NAMES)[number];

/**
 * 两种视口的 CSS 像素尺寸（裁决 E）。
 *
 * mobile 取 390×844 与设计渲染视图一致；desktop 用于后续验证 PC 端设备外壳。
 */
export const VIEWPORTS = {
  mobile: { width: 390, height: 844 },
  desktop: { width: 1280, height: 1000 },
} as const;

/** 视口名联合类型，也是 Playwright 的 project 名。 */
export type ViewportName = keyof typeof VIEWPORTS;

/** 视口名清单（顺序即 manifest 内的呈现顺序）。 */
export const VIEWPORT_NAMES = ['mobile', 'desktop'] as const satisfies readonly ViewportName[];

/** 设备像素比；两种视口共用（裁决 E：均 2 倍）。 */
export const DEVICE_SCALE_FACTOR = 2;

/** 预览服务器端口（裁决 B）。 */
export const PREVIEW_PORT = 4173;

/**
 * 预览服务器绑定地址。
 *
 * 用回环字面量而不是 `localhost`：本机 `localhost` 会先解析到 `::1`，而预览服务器若只绑
 * IPv4，每次连接都要先撞一次注定失败的地址（code-craft 的 testing 切片 T-02 实测该项
 * 在本机单次成本 2.07 秒）。`127.0.0.1` 是回环字面量，仍然零外网。
 */
export const LOOPBACK_HOST = '127.0.0.1';

/** 预览服务器根地址。 */
export const BASE_URL = `http://${LOOPBACK_HOST}:${String(PREVIEW_PORT)}`;

/**
 * 图种（裁决 1：每条页面 × 视口 出两张图）。
 *
 * - `viewport`：视口尺寸截图，回答「首屏长什么样」。设备外壳（T02）的判定依据就是首屏几何。
 * - `full`：整页截图，回答「整页长什么样」，供 T03 的逐页视觉审计使用。
 *
 * 为什么两种都要：视口图能证外壳几何，但裁掉 1184px（profile-mobile）就没法判断版式；
 * fullPage 图能看整页，却不能用来判断首屏。两者回答的问题不同，不可互相替代。
 */
export const SHOT_KINDS = ['viewport', 'full'] as const;

/** 图种联合类型。 */
export type ShotKind = (typeof SHOT_KINDS)[number];

/** 判断一个字符串是否是已知图种；供 manifest 汇总时收窄类型，不裸用 as。 */
export function isShotKind(value: string): value is ShotKind {
  return (SHOT_KINDS as readonly string[]).includes(value);
}

/** 一张图的文件名：`<page>-<viewport>.png`；fullPage 图带 `-full` 后缀。 */
export function shotFileName(page: PageName, viewport: ViewportName, kind: ShotKind): string {
  return kind === 'full' ? `${page}-${viewport}-full.png` : `${page}-${viewport}.png`;
}

/** 一张图的绝对路径。 */
export function shotFilePath(page: PageName, viewport: ViewportName, kind: ShotKind): string {
  return resolve(SHOTS_OUT_DIR, shotFileName(page, viewport, kind));
}

/** 一条 sidecar 的绝对路径。 */
export function sidecarPath(page: PageName, viewport: ViewportName, kind: ShotKind): string {
  return resolve(SIDECAR_DIR, `${shotFileName(page, viewport, kind)}.json`);
}

/** 把绝对路径转成相对仓库根的 POSIX 形式，供落盘记录跨机可读。 */
export function toRepoRelative(absolutePath: string): string {
  return resolve(absolutePath).slice(REPO_ROOT.length + 1).split('\\').join('/');
}

/** 判断一个字符串是否是已知视口名；供 spec 从 project 名收窄类型，不裸用 as。 */
export function isViewportName(value: string): value is ViewportName {
  return (VIEWPORT_NAMES as readonly string[]).includes(value);
}

/**
 * 「某一页已呈现目标形态」的等待上界（毫秒）。
 *
 * 上界理由（CORE-11 有界性）：全部数据由 `page.route` 在本机内存里即时 fulfill，
 * 页面自身只有一个渲染轮次与一次 React effect，实测正常值在百毫秒级；取 15 秒是
 * 一个「本机不可能达到、真挂住时又不会把失败拖成分钟级」的余量。
 */
export const RENDER_SETTLE_TIMEOUT_MS = 15_000;

/**
 * 会话就绪（守卫放行）的等待上界（毫秒）。
 *
 * 比 RENDER_SETTLE_TIMEOUT_MS 短，因为这一步在页面加载前就应完成：`doesSessionExist()`
 * 是纯 cookie 解析、零网络（facts.md §5 的 fetchCount=0 已证）。5 秒足够，同时让
 * 「注入没生效」以「超时等待登录态」的形式快速失败，而不是拖满 15 秒。
 */
export const SESSION_READY_TIMEOUT_MS = 5_000;

/**
 * 「PNG 像素高 vs CSS 内容高 × 倍率」的容差（CSS px；比对时再乘 DEVICE_SCALE_FACTOR）。
 *
 * 这是同一个量上的三条判据，因此共用同一个常量（P2-E 的教训）：
 *   1. `capture()`：出图后校验 `|图高 − 展开后内容高 × 倍率| ≤ 容差`；
 *   2. `assertFullPageExpanded()`：校验 `图高 ≥ 最高滚动来源的内容高 × 倍率 − 容差`；
 *   3. `buildManifest()`：汇总时对落盘 PNG 复算同一条判据。
 * 三处若各写一个容差，就会出现「用例通过但汇总失败」这类错位——实测 20 张 full 图里
 * 12 张余量恰好为 0，任何口径差异都会立刻变成假红或漏报。
 *
 * 取值 2 的依据：沿用 `docs/证据/design-render/README.md` 第 19、40–44 行登记的同一现象与同一处置
 * ——该仓渲染器实测「宽度 30/30 精确，高度 26/30 短 1–2px，成因未确定」，用 2px 容差吸收，
 * 并把「谁查清成因就把容差收紧到 1px」写进了 README。此处取同一值，不另立标准。
 */
export const PNG_HEIGHT_TOLERANCE_PX = 2;

/**
 * 纯 CSS 空间布局比较的容差（CSS px）。
 *
 * 与 `PNG_HEIGHT_TOLERANCE_PX` 是两个不同的量：本常量用于「CSS 高 vs CSS 高」，
 * 不涉及 PNG 像素、不乘倍率。两个用途：
 *   1. `findClippedElements`：判断 `scrollHeight − clientHeight` 是否超过取整噪声；
 *   2. `assertExpanded` 的辅助判据：比较展开后内容高与展开前的内容高。
 *
 * 取值依据（实测，不凭感觉）
 *
 * 用真实页面的探针实测（`T01-assets/probe-clip-mobile.txt`，10 页，mobile 视口）：
 * 扫描 `overflow-y ∈ {auto,scroll,hidden,clip}` 且 `scrollHeight > clientHeight` 的元素，
 * 排除三类设计内的刻意截断后（ellipsis / line-clamp / clip-path），
 * 非刻意截断的条目数为 0 —— 真实页面在 1px 阈值下也没有「该展开而没展开」的元素。
 *
 * 排除项里实际出现的像素差是 2px（`span.sp-title`：`clientHeight=36 / scrollHeight=38`）
 * 与 27px（`.sr-only`：1×1px 的 a11y 视觉隐藏，`clip-path: inset(50%)`）。
 * 后者说明不能靠调大容差来区分「设计内截断」与「真被裁」——两者的像素量级可以重叠，
 * 27px 的刻意隐藏比 2px 的省略还大。所以刻意截断必须按 CSS 属性排除
 * （`findClippedElements` 的做法），容差只承担它该承担的事：吸收
 * `clientHeight`/`scrollHeight` 这对整数在亚像素布局下的取整差异（实测同类差异为 2px）。
 *
 * 既然按属性排除后实测为 0，本容差不承重；目标场景里真被裁的量级是 156px 起
 * （外壳矩阵逐页实测），因此 2px 不会掩盖任何真裁切。
 */
export const CSS_LAYOUT_TOLERANCE_PX = 2;