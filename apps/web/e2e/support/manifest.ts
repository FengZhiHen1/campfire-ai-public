/**
 * 模块: e2e/support/manifest
 * 职责: 逐图 sidecar 与 manifest.json 的形状、读写与复算
 * 数据来源:
 *   - 原证物 orchestrator-20261002-001/T01.md: MUST — 目标 4（每张图的路径、sha256、字节数、
 *     像素尺寸与断言命中的内容特征串）与验收标准「manifest 记录值须与文件实际值一致」
 *   - 原证物 orchestrator-20261002-001/T01-rulings.md: MUST — 裁决 1（加 kind 字段、
 *     清点变 40 张）与其追加裁决（记 contentHeightPx 与 expandedScrollContainer）、
 *     裁决 2（记 fontLoaded；stubbedExternalHosts 语义改为「被阻断的清单外 host」）
 * 边界:
 *   - 依赖: node:fs、node:crypto（Node 内置，不引入第三方）
 *   - 被依赖: e2e/shots.spec.ts、e2e/manifest.spec.ts
 * 禁止行为:
 *   - 禁止把「文件读不到」当成空 manifest 放过（读不到就是失败，不是零张图）
 *   - 禁止记录未经复算的哈希（manifest 的值必须来自本次对磁盘文件的实读）
 */

import { createHash } from 'node:crypto';
import { readFile, readdir, writeFile } from 'node:fs/promises';

import { DEVICE_SCALE_FACTOR, PNG_HEIGHT_TOLERANCE_PX, type PageName, type ShotKind, type ViewportName } from './paths';

/** 一张图的 sidecar（由截图用例写、由 manifest project 汇总）。 */
export interface ShotSidecar {
  page: PageName;
  viewport: ViewportName;
  /**
   * 图种（裁决 1）：`viewport` = 视口尺寸截图，`full` = fullPage 整页截图。
   *
   * 两者回答不同的问题，尺寸断言也不同（见 shots.spec.ts 的 capture）：
   * 视口图证首屏几何（设备外壳判定依据），fullPage 图供逐页版式审计。
   */
  kind: ShotKind;
  /** 相对仓库根的 POSIX 路径（进 manifest）。 */
  file: string;
  /** 绝对路径（供汇总时回读复算；不进 manifest，理由见 ShotsManifestShot）。 */
  absolutePath: string;
  /**
   * 本张图所属的运行批号（来自 `global.setup.ts` 写入的批号文件）。
   *
   * 汇总时校验 40 条 sidecar 的批号一致：若某个落点目录里混了两次运行的产物
   * （部分成功的一轮留下的），不一致就会在汇总时被点名，而不是拼出一份
   * 「sha256 与实际 PNG 不对应」的清单（P2-3）。
   */
  runId: string;
  sha256: string;
  bytes: number;
  width: number;
  height: number;
  /** 断言意图 → 本次命中的内容特征串。 */
  assertedContent: { intent: string; evidence: string }[];
  /** 夹具说明：这些数字从哪来。 */
  fixtureNote: string;
  /**
   * 截图的滚动指标（在中和之前实测，记录的是真实渲染形态）。
   *
   * `truncatedByPx` 是文档级溢出；`hiddenOverflowPx` 才是「整页图必须覆盖多少」的判据
   * （= max(文档级, 内层滚动容器级)）。本轮 P1-1 的教训：设备外壳落地后溢出发生在内层容器，
   * 只看 `truncatedByPx` 会让守卫看到 0 或一个小值，于是 1184px 被藏住而毫无反应。
   * 两个值都记，让审查者能直接看出「藏住的到底在哪里」。
   */
  scroll: {
    documentHeight: number;
    viewportHeight: number;
    truncatedByPx: number;
    documentWidth: number;
    viewportWidth: number;
    horizontalOverflowPx: number;
    /** 内层滚动容器的最大溢出（CSS px）；当前结构下为 0。 */
    innerOverflowPx: number;
    /** 隐藏溢出 = max(truncatedByPx, innerOverflowPx)；判断「有没有藏住内容」。 */
    hiddenOverflowPx: number;
    /** 「整页图至少要有多高」的内容高：逐滚动来源取最大，不跨来源相加。 */
    requiredContentHeightPx: number;
    /** 仍在纵向溢出的滚动容器清单（元素描述 + 各自溢出量）。 */
    hiddenOverflowContainers: { selector: string; overflowPx: number; scrollHeightPx: number; clientHeightPx: number }[];
  };
  /**
   * 本次真实出网的外部主机（字体 CDN 白名单内）。
   *
   * 语义（裁决 2）：从「被本地替身接管」改为「被放行真实出网」。清单外主机会被阻断并
   * 让用例失败，那些记录在运行日志的 `blockedExternal` 里（不进 manifest，因为出现即失败）。
   */
  allowedExternalHosts: string[];
  /**
   * 标题字体是否真的加载（裁决 2 的判据）。
   *
   * 注意：这里的 `true` 不来自裁决字面指定的 `document.fonts.check()`——实测它对任意
   * 族名（含必然不存在的那个）都返回 true，恒真即不可能失败，不构成守卫。
   * 承重的是 `fontLoadedFaceCount`（`fonts.load()` 命中的 face 数）与
   * `fontLoadedFacesForFamily`。`fontCheckResult` 仍记录 `check()` 的值以保持字面连续。
   * 详见 `e2e/support/fonts.ts` 的说明与报告 §4.3 的证据对。
   */
  fontLoaded: boolean;
  /** 裁决字面指定的判据字符串（`document.fonts.check` 的入参）。 */
  fontProbe: string;
  /** `document.fonts.check(probe)` 的返回值。不承重（对不存在的族也返回 true）。 */
  fontCheckResult: boolean;
  /** `document.fonts.load(probe)` 命中的 FontFace 数。承重判据，0 即字体缺失。 */
  fontLoadedFaceCount: number;
  /** 该族中 `status === 'loaded'` 的 face 数。承重判据之二。 */
  fontLoadedFacesForFamily: number;
  /** 负对照（必然不存在的族）在 `fonts.load()` 下的命中数，必须为 0（否则判据恒真）。 */
  fontNegativeControlFaceCount: number;
  /** `document.fonts.status`，应为 `loaded`。 */
  fontStatus: string;
  /** 页面上被 `@font-face` 声明过的族名（确认思源宋体确实被声明，而不只是 check 返回 true）。 */
  fontDeclaredFamilies: string[];
  /** 是否注入了 fixed 中和样式（fullPage 图的取舍登记；视口图为 false）。 */
  fixedNeutralised: boolean;
  /** 被中和的 fixed 元素选择器（本次实际命中的；视口图为空数组）。 */
  neutralisedSelectors: string[];
  /** 被展开的主滚动容器：元素描述，或 `documentElement`。视口图为 null（未展开）。 */
  expandedScrollContainer: string | null;
  /** 被展开的祖先链（不含滚动容器自身）；非空表示展开穿透了外层固定高度。 */
  expandedAncestors: string[];
  /** 展开后测得的内容高（CSS px）。视口图为 null。 */
  contentHeightPx: number | null;
  /**
   * 本次实际发生的请求清单（`动作 路径`），按发生顺序。
   *
   * 为什么记进产物：审查者据图判断「这一页确实呈现了夹具数据」时，光有断言命中串
   * 与图还不够——它无法回答「这页到底打了哪些端点、有没有打到本机预览服务器之外」。
   * 记下实际请求让「零真实后端」这件事在产物内自证，而不必去翻运行日志。
   */
  requests: string[];
}

/** manifest 里的一条记录。 */
export interface ShotsManifestShot {
  page: string;
  viewport: string;
  kind: ShotKind;
  file: string;
  sha256: string;
  bytes: number;
  width: number;
  height: number;
  assertedContent: { intent: string; evidence: string }[];
  fixtureNote: string;
  scroll: ShotSidecar['scroll'];
  allowedExternalHosts: string[];
  fontLoaded: boolean;
  fontProbe: string;
  fontCheckResult: boolean;
  fontLoadedFaceCount: number;
  fontLoadedFacesForFamily: number;
  fontNegativeControlFaceCount: number;
  fontStatus: string;
  fontDeclaredFamilies: string[];
  fixedNeutralised: boolean;
  neutralisedSelectors: string[];
  expandedScrollContainer: string | null;
  expandedAncestors: string[];
  contentHeightPx: number | null;
  requests: string[];
}

/**
 * manifest 顶层结构。
 *
 * 不落 `absolutePath`：manifest 要能跨机与跨轮次比对（同一份产物在两台机器上的
 * 盘符不同，绝对路径会让比对必然失败）。
 */
export interface ShotsManifest {
  /**
   * 产物格式版本。
   *
   * v2（本版）：每页每视口两张图（`kind`），新增字体与中和取证字段。
   * 形状变化时递增，供后续包判断能否直接消费——消费方应按版本分支，而不是猜字段缺失的含义。
   */
  formatVersion: 2;
  /** 本轮运行的批号（与每条 sidecar 的 `runId` 一致；混批在汇总时即失败）。 */
  runId: string;
  /** 生成时刻（ISO）。 */
  generatedAt: string;
  /** 落点（相对仓库根）。 */
  outputDir: string;
  deviceScaleFactor: number;
  viewports: Record<string, { width: number; height: number }>;
  shots: ShotsManifestShot[];
}

/** 计算一段字节的 sha256（十六进制小写）。 */
export function sha256Of(bytes: Buffer): string {
  return createHash('sha256').update(bytes).digest('hex');
}

/** PNG 的像素尺寸。用具名类型而不是就地对象字面量：后者会让静态检查把返回类型误当函数体。 */
export interface PngSize {
  width: number;
  height: number;
}

/**
 * 读 PNG 的 IHDR 宽高。
 *
 * 前置: bytes 是完整读入的 PNG 文件内容
 * 后置: 返回 IHDR 里的大端宽高
 *
 * PNG 布局：0..7 为签名，8..15 为 IHDR 的长度与类型，16..19 为宽，20..23 为高
 * （均为大端无符号）。只读这 24 字节，不解码像素。
 *
 * @throws Error 签名不符或长度不足——不做「看起来像 PNG 就算」的宽松判断
 */
export function readPngSize(bytes: Buffer): PngSize {
  const pngSignature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  if (bytes.length < 24 || !bytes.subarray(0, 8).equals(pngSignature)) {
    throw new Error('产物不是合法 PNG（签名不符或长度不足 24 字节），无法读取像素尺寸');
  }
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

/** 写一条 sidecar。 */
export async function writeSidecar(path: string, sidecar: ShotSidecar): Promise<void> {
  await writeFile(path, `${JSON.stringify(sidecar, null, 2)}\n`, 'utf8');
}

/** 读回 sidecar 目录里的全部条目；目录不存在返回空数组（由调用方判空并失败）。 */
export async function readSidecars(dir: string): Promise<ShotSidecar[]> {
  const names = await readdir(dir).catch(() => [] as string[]);
  // 豁免 no-array-sort 的理由：排的是 filter 返回的副本，调用方的数组不受影响；
  // 规则建议的 `toSorted` 不在本项目的 TS lib 目标里（ES2023 起才提供）。
  // oxlint-disable-next-line unicorn/no-array-sort
  const ordered = names.filter((entry) => entry.endsWith('.json')).sort();
  const sidecars: ShotSidecar[] = [];
  for (const name of ordered) {
    const raw = await readFile(`${dir}/${name}`, 'utf8');
    sidecars.push(JSON.parse(raw) as ShotSidecar);
  }
  return sidecars;
}

/**
 * 从 sidecar 组装 manifest，并回读磁盘复算 sha256、字节数与像素尺寸。
 *
 * 前置: 每条 sidecar 的 absolutePath 指向一张已落盘的 PNG
 * 后置: 返回的每条记录里的 sha256/bytes 都来自本次对文件的实读；尺寸与图种相符
 *
 * @throws Error PNG 读不到、签名不合法，或实际尺寸与期望不符（宁可失败也不记一条假值）
 *
 * 为什么在这里复算而不是信 sidecar 里的值：sidecar 与 PNG 之间可能隔着一次失败的写盘。
 * 复算让 manifest 记录「磁盘现状」，而不是「我以为写成了什么」。
 *
 * 尺寸判据按 `kind` 分两条（裁决 1）：
 *   - `viewport`：宽高都 = 视口 × 倍率（严格相等）；
 *   - `full`：宽 = 视口宽 × 倍率；高 = contentHeightPx × 倍率（容差见 shots.spec.ts 的说明）。
 */
export async function buildManifest(
  sidecars: readonly ShotSidecar[],
  meta: { outputDir: string; viewports: Record<string, { width: number; height: number }>; runId: string },
): Promise<ShotsManifest> {
  const shots: ShotsManifestShot[] = [];
  for (const sidecar of sidecars) {
    const bytes = await readFile(sidecar.absolutePath);
    const size = readPngSize(bytes);
    const expected = meta.viewports[sidecar.viewport];
    if (expected === undefined) throw new Error(`sidecar 里的视口 ${sidecar.viewport} 不在配置内`);
    const expectedWidth = expected.width * DEVICE_SCALE_FACTOR;

    if (sidecar.kind === 'viewport') {
      const expectedHeight = expected.height * DEVICE_SCALE_FACTOR;
      if (size.width !== expectedWidth || size.height !== expectedHeight) {
        throw new Error(
          `${sidecar.file}（视口图）的像素尺寸是 ${String(size.width)}×${String(size.height)}，` +
            `期望 ${String(expectedWidth)}×${String(expectedHeight)}` +
            `（视口 ${String(expected.width)}×${String(expected.height)} × ${String(DEVICE_SCALE_FACTOR)}）`,
        );
      }
    } else {
      if (sidecar.contentHeightPx === null) {
        throw new Error(`${sidecar.file}（fullPage 图）缺少 contentHeightPx，无法复算高度`);
      }
      if (size.width !== expectedWidth) {
        throw new Error(
          `${sidecar.file}（fullPage 图）的宽是 ${String(size.width)}，期望视口宽 × 倍率 = ${String(expectedWidth)}`,
        );
      }
      const expectedHeight = sidecar.contentHeightPx * DEVICE_SCALE_FACTOR;
      const delta = Math.abs(size.height - expectedHeight);
      // 容差与 screenshots 用例内保持同一值（2 CSS px × 倍率）：两处若不一致，
      // 会出现「用例通过但汇总失败」的错位，那种失败最难诊断。
      if (delta > PNG_HEIGHT_TOLERANCE_PX * DEVICE_SCALE_FACTOR) {
        throw new Error(
          `${sidecar.file}（fullPage 图）的高是 ${String(size.height)}，` +
            `期望「展开后内容高 × ${String(DEVICE_SCALE_FACTOR)}」= ${String(expectedHeight)}，相差 ${String(delta)}px`,
        );
      }
    }

    shots.push({
      page: sidecar.page,
      viewport: sidecar.viewport,
      kind: sidecar.kind,
      file: sidecar.file,
      sha256: sha256Of(bytes),
      bytes: bytes.byteLength,
      width: size.width,
      height: size.height,
      assertedContent: sidecar.assertedContent,
      fixtureNote: sidecar.fixtureNote,
      scroll: sidecar.scroll,
      allowedExternalHosts: sidecar.allowedExternalHosts,
      fontLoaded: sidecar.fontLoaded,
      fontProbe: sidecar.fontProbe,
      fontCheckResult: sidecar.fontCheckResult,
      fontLoadedFaceCount: sidecar.fontLoadedFaceCount,
      fontLoadedFacesForFamily: sidecar.fontLoadedFacesForFamily,
      fontNegativeControlFaceCount: sidecar.fontNegativeControlFaceCount,
      fontStatus: sidecar.fontStatus,
      fontDeclaredFamilies: sidecar.fontDeclaredFamilies,
      fixedNeutralised: sidecar.fixedNeutralised,
      neutralisedSelectors: sidecar.neutralisedSelectors,
      expandedScrollContainer: sidecar.expandedScrollContainer,
      expandedAncestors: sidecar.expandedAncestors,
      contentHeightPx: sidecar.contentHeightPx,
      requests: sidecar.requests,
    });
  }

  shots.sort((left, right) => (left.file < right.file ? -1 : left.file > right.file ? 1 : 0));

  return {
    formatVersion: 2,
    runId: meta.runId,
    generatedAt: new Date().toISOString(),
    outputDir: meta.outputDir,
    deviceScaleFactor: DEVICE_SCALE_FACTOR,
    viewports: meta.viewports,
    shots,
  };
}
