// capture-device-shots.mjs — 全核心页面「整机截图」采集(PPT 素材用)
//
// 需求(用户 2026-10-07):带手机设备框、规格一致、覆盖所有核心页面、
// 透明背景 PNG(@2x),数据必须是虚构演示数据。
//
// 关键几何:产品自己的 .device 外壳在视口 ≥560px 时由 global.css 渲染
// (390×844 屏 + 12px bezel = 414×868,56px 圆角,暖色 bezel)。
// 视口高必须 ≥916px(868 + 2×24 stage padding),否则 zoom 阶梯会把外壳缩小,
// 规格就不一致了。本脚本固定 1280×1000,恒命中 zoom=1 档。
//
// 输出:元素级截图(page.screenshot({clip}) 对 .device 的 bbox,omitBackground
// 出透明底),全部 828×1736px(@2x)。
//
// 用法:node capture-device-shots.mjs [--only name1,name2]
// 前置:后端 127.0.0.1:8000 + 前端 127.0.0.1:5173 均已就绪;
//       demo-parent 为虚构演示账号(数据安全已核对,可外发)。
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, '../out/device-shots');
const BASE = 'http://localhost:5173';  // vite 只绑 localhost(::1),用 127.0.0.1 会被拒
const ACCOUNT = captureAccount();

// 统一规格:宽视口 + 足够高(zoom 阶梯不命中),@2x 出图
const VIEWPORT = { width: 1280, height: 1000, deviceScaleFactor: 2 };

async function settle(page, ms = 800) {
  // ★ fonts.ready 用有界等待:无界 evaluate 在 renderer 假死时会永远挂起
  //   (实测踩过,Runtime.callFunctionOn timeout)。超时降级继续,不让整批报废。
  // quality-floor: ignore silent-catch 有意的降级：下一行的固定等待是兜底，见上一行实测记录
  await page.waitForFunction(() => document.fonts.status === 'loaded', { timeout: 15000 }).catch(() => {});
  await new Promise((r) => setTimeout(r, ms));
}

/** 对 .device 元素截透明底整机图;校验尺寸恒定,不一致即报错(规格一致性是硬需求)。 */
async function shotDevice(page, name, dir = OUT) {
  const el = await page.$('.device');
  if (!el) throw new Error(`[${name}] .device 未找到 —— 视口或页面结构不对`);
  const box = await el.boundingBox();
  const expectW = (390 + 12 * 2) * 2;   // 828
  const expectH = (844 + 12 * 2) * 2;   // 1736
  if (!box || Math.round(box.width * 2) !== expectW || Math.round(box.height * 2) !== expectH) {
    throw new Error(`[${name}] .device 尺寸 ${box?.width}×${box?.height} ≠ 414×868(zoom 档命中了?)`);
  }
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${name}.png`);
  await page.screenshot({
    path: file,
    omitBackground: true,
    clip: { x: box.x, y: box.y, width: box.width, height: box.height },
  });
  console.log(`shot ${name}.png  ${Math.round(box.width * 2)}x${Math.round(box.height * 2)}`);
  return box;
}

async function login(page) {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle0' });
  await settle(page, 700);
  const inputs = await page.$$('input');
  await inputs[0].type(ACCOUNT.name);
  await inputs[1].type(ACCOUNT.password);
  for (const b of await page.$$('button')) {
    if ((await b.evaluate((el) => el.textContent || '')).includes('登')) { await b.click(); break; }
  }
  await settle(page, 2500);
  if (!page.url().endsWith('/login')) console.log('已登录 →', page.url());
}

/** 应急表单逐题推进到第 q 题(q: 1..8),不提交。
 *  ★ 必须用真实选项文案点击(与 run-real-consult.mjs 的 answerPlan 同源),
 *    泛点「第一个像选项的元素」会点到页头「← 返回」直接离开表单(踩过)。 */
const EMERGENCY_PLAN = [
  { q: 1, picks: ['明显疼痛'] },
  { q: 2, picks: ['明显'] },
  { q: 3, picks: ['下降'] },
  { q: 4, picks: ['强烈'] },
  { q: 5, picks: ['噪音', '人群'] },
  { q: 6, text: '在超市突然蹲下捂住耳朵,周围人多' },
  { q: 7, picks: ['走失'] },
  { q: 8, picks: ['是'] },
];

async function emergencyToQuestion(page, q) {
  await page.goto(`${BASE}/consult/emergency`, { waitUntil: 'networkidle0' });
  await settle(page, 1200);
  for (let i = 1; i < q; i++) {
    const step = EMERGENCY_PLAN[i - 1];
    // 勾选该题真实选项
    await page.evaluate((picks) => {
      const cands = [...document.querySelectorAll('label, button, [role="button"], [class*="check"], [class*="choice"], [class*="option"]')];
      for (const p of picks) {
        const el = cands.find((x) => {
          const t = (x.textContent || '').trim();
          return t === p || (t.length < 24 && t.includes(p));
        });
        if (el) el.click();
      }
    }, step.picks ?? []);
    await settle(page, 350);
    // q6 填自由文本
    if (step.text) {
      await page.evaluate((txt) => {
        const ta = document.querySelector('textarea');
        if (!ta) return;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
        setter.call(ta, txt);
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      }, step.text);
      await settle(page, 300);
    }
    // 下一题
    await page.evaluate(() => {
      const next = [...document.querySelectorAll('button')]
        .find((x) => (x.textContent || '').trim() === '下一题');
      if (next) next.click();
    });
    await settle(page, 700);
  }
}

async function main() {
  const only = process.argv.includes('--only')
    ? new Set(process.argv[process.argv.indexOf('--only') + 1].split(','))
    : null;
  const want = (n) => !only || only.has(n);

  const browser = await puppeteer.launch({ headless: true, protocolTimeout: 600000 });
  const page = await browser.newPage();
  await page.setViewport(VIEWPORT);

  fs.mkdirSync(OUT, { recursive: true });
  const sessionUrlFile = path.join(OUT, '_session-url.txt');
  let sessionId = null;
  if (fs.existsSync(sessionUrlFile)) {
    const prev = fs.readFileSync(sessionUrlFile, 'utf8').trim();
    const m = prev.match(/sessions\/([0-9a-f]+)/);
    if (m) sessionId = m[1];
  }

  // ── 静态路由 ──
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle0' });
  await settle(page, 900);
  if (want('login')) await shotDevice(page, '01-login');

  await login(page);

  for (const [name, p, wait] of [
    ['02-home', '/', 1200],
    ['11-consult-list', '/consult', 1500],
    ['14-profile', '/profile', 1800],
    ['15-cases', '/cases', 1800],
    ['16-settings', '/settings', 1200],
    ['17-memory', '/settings/memory', 1500],
    ['18-guide', '/guide', 1200],
  ]) {
    if (!want(name)) continue;
    await page.goto(`${BASE}${p}`, { waitUntil: 'networkidle0' });
    await settle(page, wait);
    // 案例库附加版:搜索「虚构」只留演示数据条目(内部台账条目不可外发)
    if (name === '15-cases') {
      await page.evaluate(() => {
        const inp = document.querySelector('input[type="search"], input[placeholder*="搜"]');
        if (!inp) return;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(inp, '虚构');
        inp.dispatchEvent(new Event('input', { bubbles: true }));
      });
      await settle(page, 1200);
      await shotDevice(page, '15b-cases-fictional');
      // 清空搜索,恢复默认态供 15-cases 截图
      await page.evaluate(() => {
        const inp = document.querySelector('input[type="search"], input[placeholder*="搜"]');
        if (!inp) return;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(inp, '');
        inp.dispatchEvent(new Event('input', { bubbles: true }));
      });
      await settle(page, 1200);
    }
    await shotDevice(page, name);
  }

  // ── 应急表单 q1..q8(编号 03–10)──
  const Q_NAMES = ['03-emergency-q1', '04-emergency-q2', '05-emergency-q3', '06-emergency-q4',
    '07-emergency-q5', '08-emergency-q6', '09-emergency-q7', '10-emergency-q8'];
  for (const q of [1, 2, 3, 4, 5, 6, 7, 8]) {
    const name = Q_NAMES[q - 1];
    if (!want(name)) continue;
    await emergencyToQuestion(page, q);
    await shotDevice(page, name);
  }

  // ── 会话流:流式输出中(12)+ 行动卡完整态(13)──
  // 一次真实应急咨询:提交后在流式输出窗口抓 12,分析完成后抓 13。
  if (want('12-chat-streaming') || want('13-action-card')) {
    console.log('跑一次真实应急咨询(与宣传片 run-real-consult 同方案)…');
    await emergencyToQuestion(page, 8);
    // 第 8 题作答与提交
    const picks8 = ['是'];
    await page.evaluate((pp) => {
      const cands = [...document.querySelectorAll('label, button, [role="button"], [class*="check"], [class*="choice"], [class*="option"]')];
      for (const p of pp) {
        const el = cands.find((x) => {
          const t = (x.textContent || '').trim();
          return t === p || (t.length < 24 && t.includes(p));
        });
        if (el) el.click();
      }
    }, picks8);
    await settle(page, 350);
    await page.evaluate(() => {
      const btns = [...document.querySelectorAll('button')];
      const t = btns.find((x) => (x.textContent || '').trim().startsWith('提交'));
      if (t) t.click();
    });
    console.log('已提交,等待状态变化…');
    fs.writeFileSync(path.join(OUT, '_session-url.txt'), page.url());
    console.log('会话 URL:', page.url());

    // 阶段 1:等流式输出出现(回答开始生成),抓 12
    // ★ 判据用结构而非文案:助手消息节点出现、且会话仍处于 SSE 流中
    //   (「正在分析」是分析阶段文案,用户消息后的回答流没有固定提示词)
    let shot12 = false;
    for (let i = 0; i < 60 && !shot12; i++) {
      await settle(page, 2000);
      const st = await page.evaluate(() => {
        const t = document.body.innerText || '';
        const bubbles = document.querySelectorAll('[class*="bubble"], [class*="message"], [class*="msg"]');
        return {
          streaming: t.includes('正在分析') || t.includes('分析中') || t.includes('正在整理') || t.includes('正在回答'),
          bubbleCount: bubbles.length,
          hasCard: t.includes('行动建议') || t.includes('医疗风险'),
        };
      });
      if (st.hasCard) break;                    // 已经出卡,12 错过了
      if (st.streaming) {
        await shotDevice(page, '12-chat-streaming');
        shot12 = true;
      }
    }
    if (!shot12 && want('12-chat-streaming')) {
      console.log('⚠ 未在轮询窗口内捕捉到流式态(12 跳过;可重跑一次)');
    }

    // 阶段 2:等分析完成(最多 8 分钟),展开全部折叠区,抓 13
    if (want('13-action-card')) {
      for (let i = 0; i < 96; i++) {
        await settle(page, 5000);
        const st = await page.evaluate(() => {
          const t = document.body.innerText || '';
          return {
            hasCard: t.includes('行动建议') || t.includes('医疗风险'),
            analyzing: t.includes('正在分析') || t.includes('分析中'),
          };
        });
        if (st.hasCard && !st.analyzing) break;
      }
      await page.evaluate(() => {
        [...document.querySelectorAll('button')]
          .filter((b) => (b.textContent || '').trim() === '展开')
          .forEach((b) => b.click());
      });
      await settle(page, 2500);
      await shotDevice(page, '13-action-card');
    }
  }

  await browser.close();
  console.log('DONE');
}

main().catch((e) => { console.error(e); process.exit(1); });
