/**
 * 模块: tmp/design-render/render.mjs
 * 职责: 把当前视觉契约（docs/design/components.html + tokens.css）渲染成 PNG 参照图
 * 数据来源:
 *   - docs/design/components.html: MUST — 组件契约与交互预览（唯一渲染输入，本脚本只读）
 *   - docs/design/tokens.css: MUST — token 层，由 components.html 以 <link> 引入
 * 边界:
 *   - 依赖: 本机 Chrome（CDP）+ Node 内置 WebSocket / fetch / spawn；无第三方依赖
 *   - 被依赖: 人工对照前端实现；不参与任何质量门禁或 CI
 * 禁止行为:
 *   - 禁止改写真源文件（只读渲染）
 *   - 禁止自造样式或伪造状态：状态图必须由契约页自身的控件触发
 *   - 禁止把本目录产物当作设计权威（权威是 docs/design/）
 *
 * 产物落点: tmp/design-render/{sections,states}/*.png、page-annotated.png、inventory.json
 * 用法: node tmp/design-render/render.mjs [--scale=1|2] [--only=<子串>]
 */

import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// ── 配置 ─────────────────────────────────────────────────────────────────────

const HERE = dirname(fileURLToPath(import.meta.url));
// 2026-10-06：本文件由 `tmp/design-render/` 迁入 `docs/证据/design-render/`，
// 比原位置深一级，故上溯层数由 2 改为 3——不改会让 REPO 指向 `docs/` 而非仓库根，
// 静默渲染错误的输入或写入错误的落点。
const REPO = resolve(HERE, '..', '..', '..');
const CONTRACT = resolve(REPO, 'docs', 'design', 'components.html');

/** 手机单列定调：宽 390 = iPhone 14/15 逻辑宽度；dpr 2 让图片在 Retina 上不糊。 */
const VIEWPORT = { width: 390, height: 844 };
const ARGS = new Map(process.argv.slice(2).map((a) => {
  const [k, v = 'true'] = a.replace(/^--/, '').split('=');
  return [k, v];
}));
const SCALE = Number(ARGS.get('scale') ?? 2);
const ONLY = ARGS.get('only') ?? null;

const CHROME_CANDIDATES = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  join(process.env.LOCALAPPDATA ?? '', 'Google', 'Chrome', 'Application', 'chrome.exe'),
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
];

/**
 * 截图模式。
 * - flow:  元素按文档流排版，`.emergency-controls` 的 sticky 被中和为 static——
 *          与契约自带 `@media print { .emergency-controls { position: static } }` 同语义。
 *          单张静态图无法表达「吸附」，按流序呈现才不含歧义。
 * - sticky: 保留契约原样（sticky 生效），滚动到元素吸附位置后截取一屏 390×844。
 *          用于表达「手机上按钮始终可达」的真实运行形态。
 */
const MODES = new Set(['flow', 'sticky']);

/** 中和 sticky 的注入样式：只关掉吸附，不改任何视觉参数。 */
const FLOW_CSS = '.emergency-controls { position: static !important; }';

/**
 * 分区图：与 components.html 的 9 个 `.component-section` 一一对应（id 由真源派生）。
 * 每个分区恰好一张，便于回答「我这个组件在契约里长什么样」。
 */
const SECTION_CAPTIONS = {
  'situation-entry': '首页入口：应急优先面板 + 日常入口整卡可点',
  safety: '应急表单采集、可跳过追问、提问卡（含表单状态与选项密度）',
  provenance: '行动卡七节结构、来源标签、依据折叠、三值风险徽章、过期卡',
  plan: '档案摘要与「待确认」候选分层、list-row、空态',
  forms: '输入与校验反馈、服务失败就地重试、日常对话输入',
  actions: '操作层级：主 / 次 / 静默（跳过）/ 危险',
  // 该分区自带状态切换器，默认落在「失败」；其余形态见 states/state-*.png，不在一张图里伪造并置。
  states: '状态切换器 + 默认选中的「失败」形态；populated/loading/delayed/empty/no-results/partial 见 states/state-*.png',
  conversation: '完整对话工作面：消息、追问、依据、运行反馈、技能选择',
  foundation: '基础输入、卡片三层语言、页头与 tab 栏、消息骨架',
};

/**
 * 状态图。`control` 指向契约页里的原生 <select> id，`value` 为其取值——
 * 状态全部由页面自身脚本产生，本脚本只负责选值与截图。
 */
const STATE_SHOTS = [
  { file: 'state-populated', ref: '[data-state="populated"]', mode: 'flow', state: 'populated',
    caption: '列表正常态：可点行 + 时间戳 + 下一步' },
  { file: 'state-loading', ref: '[data-state="loading"]', mode: 'flow', state: 'loading',
    caption: '加载态：同形骨架 + 运行状态文案' },
  { file: 'state-delayed', ref: '[data-state="delayed"]', mode: 'flow', state: 'delayed',
    caption: '等待较久：给出重试与取消两条出口' },
  { file: 'state-empty', ref: '[data-state="empty"]', mode: 'flow', state: 'empty',
    caption: '首次使用空态：说明 + 唯一主动作' },
  { file: 'state-no-results', ref: '[data-state="no-results"]', mode: 'flow', state: 'no-results',
    caption: '搜索无结果：回显检索词 + 清除筛选' },
  { file: 'state-error', ref: '[data-state="error"]', mode: 'flow', state: 'error',
    caption: '失败态：错误卡 + 重试 / 返回入口' },
  { file: 'state-partial', ref: '[data-state="partial"]', mode: 'flow', state: 'partial',
    caption: '回答中断：保留已收到文字，不当作完整建议' },

  { file: 'chat-daily', selector: '#chat-shell', mode: 'flow',
    control: ['chat-scenario', 'daily'], caption: '对话工作面 · 日常：追问卡 + 依据折叠' },
  { file: 'chat-emergency', selector: '#chat-shell', mode: 'flow',
    control: ['chat-scenario', 'emergency'], caption: '对话工作面 · 应急：行动卡 + 多题追问' },
  { file: 'chat-history', selector: '#chat-shell', mode: 'flow',
    control: ['chat-scenario', 'history'], waitMs: 1200,
    caption: '对话工作面 · 历史：载入完成后恢复为静态记录' },
  { file: 'chat-history-error', selector: '#chat-shell', mode: 'flow',
    control: ['chat-scenario', 'history-error'], waitMs: 1200,
    caption: '对话工作面 · 历史载入失败：重试出口 + 草稿保留' },
  { file: 'chat-retrieval-error', selector: '#chat-shell', mode: 'flow',
    control: ['chat-scenario', 'retrieval-error'], waitMs: 400,
    caption: '对话工作面 · 检索不可用：中断标注 + 重试' },
  { file: 'chat-reconnecting', selector: '#chat-shell', mode: 'flow',
    control: ['chat-scenario', 'reconnecting'], waitMs: 400,
    caption: '对话工作面 · 连接中断重连（1/3）：已收到文字保持可见' },
  { file: 'chat-delayed', selector: '#chat-shell', mode: 'flow',
    control: ['chat-scenario', 'delayed'], waitMs: 11000,
    caption: '对话工作面 · 首字超过 10 秒：等待提示 + 可停止' },

  { file: 'question-daily', selector: '#question-preview', mode: 'flow',
    control: ['question-scenario', 'daily'], caption: '提问卡 · 多题日常情境' },
  { file: 'question-single', selector: '#question-preview', mode: 'flow',
    control: ['question-scenario', 'single'], caption: '提问卡 · 单题咨询方向' },
  { file: 'question-emergency', selector: '#question-preview', mode: 'flow',
    control: ['question-scenario', 'emergency'], caption: '提问卡 · 多题现场核对' },

  { file: 'warning-sticky', selector: '.emergency-preview', mode: 'sticky', scrollOffset: 320,
    caption: '应急表单吸附态：滚动时「跳过 / 下一题 / 提交」始终可达（sticky 真实生效）' },
  { file: 'form-save-error', selector: '#record-form', mode: 'flow', drive: 'saveError',
    caption: '保存失败：服务错误卡 + 输入保留 + 主按钮改文案' },
];

// ── CDP 客户端（原生 WebSocket，无第三方依赖） ───────────────────────────────

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.seq = 0;
    this.pending = new Map();
    this.handlers = new Set();
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id !== undefined) {
        const slot = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) slot.reject(new Error(`${msg.error.message ?? JSON.stringify(msg.error)}`));
        else slot.resolve(msg.result);
      } else {
        for (const handler of this.handlers) handler(msg);
      }
    });
  }

  static async connect(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => {
      ws.addEventListener('open', res, { once: true });
      ws.addEventListener('error', () => rej(new Error('CDP WebSocket 连接失败')), { once: true });
    });
    return new Cdp(ws);
  }

  send(method, params = {}, sessionId) {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }

  on(handler) {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function launchChrome() {
  const exe = CHROME_CANDIDATES.find((c) => c && existsSync(c));
  if (!exe) throw new Error('未找到 Chrome/Edge 可执行文件');
  const profileDir = join(tmpdir(), `cf-design-render-${process.pid}`);
  const port = 9400 + (process.pid % 200);
  const child = spawn(exe, [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--disable-lcd-text',
    '--disable-features=CalculateNativeWinOcclusion',
    '--force-color-profile=srgb',
    '--font-render-hinting=none',
    `--window-size=${VIEWPORT.width},${VIEWPORT.height}`,
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profileDir}`,
    'about:blank',
  ], { stdio: 'ignore' });

  for (let i = 0; i < 200; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (res.ok) return { child, profileDir, info: await res.json() };
    } catch { /* 端口未就绪，继续等 */ }
    await sleep(100);
  }
  child.kill();
  throw new Error('Chrome DevTools 端口未就绪');
}

function existsSync(p) {
  try { readFileSync(p); return true; } catch { return false; }
}

// ── 页面会话 ─────────────────────────────────────────────────────────────────

class Page {
  constructor(browser, sessionId) {
    this.browser = browser;
    this.sessionId = sessionId;
  }

  send(method, params) { return this.browser.send(method, params, this.sessionId); }

  async eval(expression) {
    const res = await this.send('Runtime.evaluate', {
      expression, awaitPromise: true, returnByValue: true,
    });
    if (res.exceptionDetails) {
      throw new Error(`页面求值失败: ${res.exceptionDetails.exception?.description ?? res.exceptionDetails.text}`);
    }
    return res.result.value;
  }

  /** 重新载入并等待「契约页脚本 + webfont」都就位，保证每张图起点一致。 */
  async reload() {
    const { url } = await this.send('Page.getNavigationHistory').then((h) => h.entries[h.currentIndex]);
    const loaded = new Promise((res) => {
      const off = this.browser.on((msg) => {
        if (msg.sessionId === this.sessionId && msg.method === 'Page.loadEventFired') { off(); res(); }
      });
    });
    await this.send('Page.navigate', { url });
    await loaded;
    // 等字体：若在 webfont 到位前截图，标题会静默回退成系统宋体，对照意义就没了。
    await this.eval('document.fonts.ready.then(() => document.fonts.status)');
    await this.eval('new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))');
  }

  async injectFlowCss(on) {
    await this.eval(`(() => {
      let style = document.getElementById('__render_flow__');
      if (!${on}) { style?.remove(); return null; }
      if (!style) {
        style = document.createElement('style');
        style.id = '__render_flow__';
        style.textContent = ${JSON.stringify(FLOW_CSS)};
        document.head.append(style);
      }
      return style.textContent;
    })()`);
  }

  /** 用页面自身的控件切换状态；原生 select 的 change 事件即契约脚本的入口。 */
  async setControl(id, value) {
    const ok = await this.eval(`(() => {
      const select = document.getElementById(${JSON.stringify(id)});
      if (!select) return 'missing';
      if (![...select.options].some((o) => o.value === ${JSON.stringify(value)})) return 'no-option';
      select.value = ${JSON.stringify(value)};
      if (document.getElementById(select.id + '-value')) {
        document.getElementById(select.id + '-value').textContent = select.selectedOptions[0].textContent;
      }
      select.dispatchEvent(new Event('change', { bubbles: true }));
      return 'ok';
    })()`);
    if (ok !== 'ok') throw new Error(`控件 ${id} 取值 ${value} 无法设置（${ok}）`);
  }

  /** 驱动表单到「保存失败」形态：填入内容后提交，等预览层的 650ms 定时器落地。 */
  async driveSaveError() {
    await this.eval(`(() => {
      const field = document.getElementById('record-content');
      field.value = '他喜欢提前知道什么时候结束。';
      field.dispatchEvent(new Event('input', { bubbles: true }));
      document.getElementById('record-form').requestSubmit();
      return true;
    })()`);
    await sleep(1000);
  }

  async scrollTo(y) {
    await this.eval(`(() => { scrollTo(0, ${Math.round(y)}); return scrollY; })()`);
    await this.eval('new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))');
  }

  async rectOf(selector, mode) {
    return this.eval(`(() => {
      const node = document.querySelector(${JSON.stringify(selector)});
      if (!node) return null;
      const r = node.getBoundingClientRect();
      if (node.scrollHeight > node.clientHeight + 1 && node.clientHeight > 0) node.scrollTop = 0;
      return { x: r.left + scrollX, y: r.top + scrollY, width: r.width, height: r.height };
    })()`);
  }

  async screenshot({ clip, beyondViewport, clipScale = 1 }) {
    const shot = await this.send('Page.captureScreenshot', {
      format: 'png',
      fromSurface: true,
      captureBeyondViewport: beyondViewport,
      ...(clip ? { clip: { ...clip, scale: clipScale } } : {}),
    });
    return Buffer.from(shot.data, 'base64');
  }}

// ── 主流程 ───────────────────────────────────────────────────────────────────

const written = [];
const problems = [];

/**
 * 从 PNG 字节读实际尺寸（IHDR 前两个大端 uint32）。
 *
 * 为什么必须读文件而不是用请求值：`captureBeyondViewport` 在超长内容上可能静默截断，
 * 只记录「我请求了多高」会让截断以「尺寸正确」的假象通过检查。判据必须来自产物本身。
 */
function pngSize(buffer) {
  const signature = buffer.subarray(0, 8).toString('hex');
  if (signature !== '89504e470d0a1a0a') throw new Error('产物不是 PNG');
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

function want(file) { return !ONLY || file.includes(ONLY); }

function save(dir, file, buffer, meta) {
  const rel = `${dir}/${file}.png`;
  const path = join(HERE, rel);
  const actual = pngSize(buffer);
  // 期望尺寸 = CSS 尺寸 × dpr。`Emulation.setDeviceMetricsOverride` 的 dsf 会乘到 clip 上，
  // 因此实际像素必然带这个倍率；把它算进期望，才能让「亚像素舍入」与「真截断」区分开。
  const expected = { width: Math.round(meta.cssWidth * meta.dpr), height: Math.round(meta.cssHeight * meta.dpr) };
  // 容差 2px：元素矩形常带 .5 小数，Chrome 取整方式与 Math.round 可能差 1px。
  // 真正的截断会差几十到上千像素，不会被这个容差放过。
  const TOLERANCE = 2;
  if (Math.abs(actual.width - expected.width) > TOLERANCE || Math.abs(actual.height - expected.height) > TOLERANCE) {
    problems.push(`${rel}: 实际 ${actual.width}×${actual.height} ≠ 期望 ${expected.width}×${expected.height}（超出 ${TOLERANCE}px 容差，疑似截断）`);
  }
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, buffer);
  written.push({
    file: rel,
    caption: meta.caption,
    mode: meta.mode,
    source: meta.source,
    deviceScaleFactor: meta.dpr,
    cssSize: { width: Math.round(meta.cssWidth * 10) / 10, height: Math.round(meta.cssHeight * 10) / 10 },
    expectedPixels: expected,
    actualPixels: actual,
    bytes: buffer.length,
    sha256: createHash('sha256').update(buffer).digest('hex'),
  });
  console.log(`  ✓ ${rel}  ${actual.width}×${actual.height}  ${(buffer.length / 1024).toFixed(0)} KB`);
}

const { child, profileDir, info } = await launchChrome();
let browser;
try {
  browser = await Cdp.connect(info.webSocketDebuggerUrl);
  const { targetId } = await browser.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await browser.send('Target.attachToTarget', { targetId, flatten: true });
  await browser.send('Page.enable', {}, sessionId);
  await browser.send('Runtime.enable', {}, sessionId);

  // 视口用 CDP 显式设定，而不是依赖窗口尺寸（headless 窗口高度不等视口高度）。
  await browser.send('Emulation.setDeviceMetricsOverride', {
    width: VIEWPORT.width, height: VIEWPORT.height, deviceScaleFactor: SCALE, mobile: true,
  }, sessionId);
  await browser.send('Page.navigate', { url: pathToFileURL(CONTRACT).href }, sessionId);
  await new Promise((res) => {
    const off = browser.on((m) => {
      if (m.sessionId === sessionId && m.method === 'Page.loadEventFired') { off(); res(); }
    });
  });

  const page = new Page(browser, sessionId);
  await page.eval('document.fonts.ready.then(() => document.fonts.status)');

  const audit = await page.eval(`(() => {
    const h1 = getComputedStyle(document.querySelector('h1'));
    return {
      fontsStatus: document.fonts.status,
      notoSerif: document.fonts.check('500 28px "Noto Serif SC"'),
      h1Font: h1.fontFamily.split(',')[0].trim(),
      bodyBg: getComputedStyle(document.body).backgroundColor,
      dpr: devicePixelRatio,
      inner: [innerWidth, innerHeight],
      maskWidth: Math.round(document.querySelector('.phone-shell').getBoundingClientRect().width),
      sections: [...document.querySelectorAll('.component-section')].map((s) => s.id),
    };
  })()`);
  console.log('渲染前置检查:', JSON.stringify(audit));
  if (!audit.notoSerif) problems.push('Noto Serif SC 未加载：标题字体已回退，图片不能作为字形参照');
  if (audit.inner[0] !== VIEWPORT.width) problems.push(`视口宽度 ${audit.inner[0]} ≠ ${VIEWPORT.width}`);

  // —— 分区图 ——
  console.log('\n[1/4] 分区图');
  for (const id of audit.sections) {
    if (!want(id)) continue;
    await page.reload();
    await page.injectFlowCss(true);
    const rect = await page.rectOf(`#${id}`);
    const buffer = await page.screenshot({
      clip: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      beyondViewport: true,
    });
    save('sections', id, buffer, {
      caption: SECTION_CAPTIONS[id] ?? '（未登记说明）',
      mode: 'flow',
      source: `docs/design/components.html#${id}`,
      cssWidth: rect.width, cssHeight: rect.height, dpr: SCALE,
    });
    if (!SECTION_CAPTIONS[id]) problems.push(`分区 ${id} 缺少文字说明`);
  }

  // —— 状态图 ——
  console.log('\n[2/4] 状态图');
  for (const spec of STATE_SHOTS) {
    if (!want(spec.file)) continue;
    await page.reload();
    // 状态切换器需要先落到目标态；它是隐藏的原生 select，矩形无意义，只能靠它换出可见的 .state-view。
    if (spec.state) await page.setControl('state-picker', spec.state);
    if (spec.control) await page.setControl(spec.control[0], spec.control[1]);
    if (spec.drive === 'saveError') await page.driveSaveError();
    if (spec.waitMs) await sleep(spec.waitMs);
    if (spec.mode === 'sticky') {
      await page.injectFlowCss(false);
      const base = await page.rectOf(spec.selector, 'flow');
      await page.scrollTo(Math.max(0, base.y + (spec.scrollOffset ?? 0)));
      const buffer = await page.screenshot({
        clip: { x: 0, y: await page.eval('scrollY'), width: VIEWPORT.width, height: VIEWPORT.height },
        beyondViewport: false,
      });
      save('states', spec.file, buffer, {
        caption: spec.caption, mode: 'sticky', source: `docs/design/components.html (${spec.control?.[0] ?? spec.selector})`,
        cssWidth: VIEWPORT.width, cssHeight: VIEWPORT.height, dpr: SCALE,
      });
    } else {
      await page.injectFlowCss(true);
      const selector = spec.selector ?? spec.ref;
      const rect = await page.rectOf(selector, spec.mode);
      if (!rect) { problems.push(`${spec.file}: 选择器 ${selector} 无命中`); continue; }
      // 0 尺寸几乎总是「元素仍被 hidden」的信号；直接截会得到空图，必须当失败处理。
      if (rect.width < 1 || rect.height < 1) {
        problems.push(`${spec.file}: ${selector} 矩形为 ${Math.round(rect.width)}×${Math.round(rect.height)}，疑似未切到目标状态`);
        continue;
      }
      const buffer = await page.screenshot({
        clip: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        beyondViewport: true,
      });
      save('states', spec.file, buffer, {
        caption: spec.caption, mode: 'flow',
        source: `docs/design/components.html (${spec.control ? spec.control.join('=') : spec.state ? `state=${spec.state}` : selector})`,
        cssWidth: rect.width, cssHeight: rect.height, dpr: SCALE,
      });
    }
  }

  // —— 全页带标注 ——
  console.log('\n[3/4] 全页带标注');
  if (want('page-annotated')) {
    await page.reload();
    await page.injectFlowCss(true);
    const marks = await page.eval(`(() => {
      const nav = document.querySelector('.catalog-nav');
      const navH = nav.getBoundingClientRect().height;
      const pins = [];
      document.querySelectorAll('.component-section').forEach((section, index) => {
        const r = section.getBoundingClientRect();
        const y = r.top + scrollY;
        const heading = section.querySelector('.section-kicker')?.textContent?.trim() ?? '';
        const title = section.querySelector('h2')?.textContent?.trim() ?? '';
        const pin = document.createElement('div');
        pin.setAttribute('data-render-pin', '');
        pin.style.cssText = [
          'position:absolute', 'z-index:9999', 'left:0', 'right:0',
          'top:' + y + 'px', 'display:flex', 'gap:8px', 'align-items:center',
          'padding:4px 8px', 'background:rgba(32,25,20,.86)', 'color:#fffdf8',
          'font:600 11px/1.4 system-ui,sans-serif', 'letter-spacing:.02em',
        ].join(';');
        pin.textContent = String(index + 1).padStart(2, '0') + '  ' + heading + ' · ' + title;
        document.body.append(pin);
        pins.push({ index: index + 1, id: section.id, y: Math.round(y) });
      });
      document.querySelector('.catalog-nav').style.position = 'static';
      document.documentElement.style.scrollBehavior = 'auto';
      return { pins, navH };
    })()`);
    const height = await page.eval('document.documentElement.scrollHeight');
    // 全页图按 1x 输出：两万像素高的图在很多查看器里打不开，作为「索引」1x 足够。
    const buffer = await page.screenshot({
      clip: { x: 0, y: 0, width: VIEWPORT.width, height }, beyondViewport: true, clipScale: 1 / SCALE,
    });
    save('.', 'page-annotated', buffer, {
      caption: `全页目录：${marks.pins.length} 个分区位置（标注条为对照用叠加层，不属于契约内容）`,
      mode: 'flow-annotated',
      source: 'docs/design/components.html',
      cssWidth: VIEWPORT.width, cssHeight: height, dpr: 1,
    });
    // 顶部裁切：让叠加层样式与首屏可直接判读，不必打开两万像素高的全页图。
    const top = await page.screenshot({
      clip: { x: 0, y: 0, width: VIEWPORT.width, height: VIEWPORT.height }, beyondViewport: true,
    });
    save('.', 'page-annotated-top', top, {
      caption: '全页目录顶部：分区标注条样式与首屏（标注条为对照用叠加层）',
      mode: 'flow-annotated',
      source: 'docs/design/components.html',
      cssWidth: VIEWPORT.width, cssHeight: VIEWPORT.height, dpr: SCALE,
    });
    writeFileSync(join(HERE, 'page-annotated.pins.json'), `${JSON.stringify(marks.pins, null, 2)}\n`);
  }

  // —— 清单 ——
  console.log('\n[4/4] 清单');
  const hash = (p) => createHash('sha256').update(readFileSync(resolve(REPO, p))).digest('hex');
  const inventory = {
    generatedAt: new Date().toISOString(),
    renderer: 'tmp/design-render/render.mjs',
    chrome: info.Browser,
    viewport: { ...VIEWPORT, deviceScaleFactor: SCALE },
    sources: [
      { path: 'docs/design/components.html', sha256: hash('docs/design/components.html') },
      { path: 'docs/design/tokens.css', sha256: hash('docs/design/tokens.css') },
    ],
    preshoot: audit,
    notes: [
      '分区图与 flow 状态图按文档流排版：`.emergency-controls` 的 sticky 被中和为 static，语义等同契约自带 @media print 规则。单张静态图无法表达吸附。',
      'warning-sticky 保留契约原样，滚动到吸附位置后截取一屏，用于表达真实运行时的吸附形态。',
      '状态图全部由契约页自身脚本产生（原生 select 的 change 事件），未注入任何自造样式或伪造内容。',
      '固定定位元素（.tab-bar / .confirm-sheet）在分区图中按文档流呈现，不代表运行时的覆盖层级。',
    ],
    shots: written,
    problems,
  };
  writeFileSync(join(HERE, 'inventory.json'), `${JSON.stringify(inventory, null, 2)}\n`);
  console.log(`inventory.json: ${written.length} 张图，问题 ${problems.length} 条`);
  for (const p of problems) console.log('  ! ' + p);

  // 闸门：提取到 0 张图应失败，而不是静默通过（AGENTS.md 禁止留下永不失败的检查）。
  // 判据是「实际写出的文件数」，且每个来源分区都必须有对应产物。
  if (written.length === 0) throw new Error('未产出任何图片——渲染未真正执行');
  const missing = ONLY ? [] : audit.sections.filter((id) => !written.some((w) => w.file === `sections/${id}.png`));
  if (missing.length) throw new Error(`以下分区未产出图片：${missing.join(', ')}`);
  if (ONLY && written.length === 0) throw new Error(`--only=${ONLY} 未匹配任何产物——过滤条件写错了，且这类运行必须失败`);
  if (problems.length) throw new Error(`渲染存在 ${problems.length} 条问题，见上方与 inventory.json`);
  console.log('渲染完成：全部预期产物已写出且无问题。');
} finally {
  try { browser?.ws.close(); } catch { /* 已断开 */ }
  child.kill();
  await sleep(300);
  rmSync(profileDir, { recursive: true, force: true });
}
