// 量出影片用到的各页面在 390×844 视口下的真实内容高度,生成 src/page-metrics.json。
//
// ★ 为什么必须量(而不是写死滚动量):
//   截图路线的缺陷之一就是「按固定像素滚动 → 滑出内容底部露空白」。
//   组件路线里内容高度是真实的,但**不能就此猜一个量**:不同页面高度差很多,
//   猜大了就滚过头(S8 实测滚到授权台账与空白处)。
//   正确做法:量出 maxScroll,滚动量 = 比例 × maxScroll,比例 1 恰好到内容底部。
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = 'http://localhost:5174';
const ACCOUNT = {name: 'demo-parent', password: 'Demo#2026campfire'};
const OUT = path.resolve(__dirname, '../src/page-metrics.json');

async function settle(page, ms = 900) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

/** 找到页面里真正的滚动容器(产品在 ≥560px 下是 .device-screen)。 */
async function measure(page) {
  return page.evaluate(() => {
    const candidates = ['.device-screen', '.phone-shell', 'body'];
    for (const sel of candidates) {
      const el = document.querySelector(sel);
      if (el === null) continue;
      const sh = el.scrollHeight;
      const ch = el.clientHeight;
      if (sh > ch + 8) {
        return {selector: sel, scrollHeight: sh, clientHeight: ch, maxScroll: sh - ch};
      }
    }
    // 没有溢出时也回一个结果,便于确认「这页不需要滚动」
    const el = document.querySelector('.device-screen') ?? document.body;
    return {
      selector: '.device-screen(fallback)',
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      maxScroll: Math.max(0, el.scrollHeight - el.clientHeight),
    };
  });
}

async function main() {
  const browser = await puppeteer.launch({headless: true, protocolTimeout: 300000});
  const page = await browser.newPage();
  // 视口宽度必须 ≥560,否则产品外壳媒体查询不命中(与影片一致)
  await page.setViewport({width: 1280, height: 1000, deviceScaleFactor: 1});

  await page.goto(`${BASE}/login`, {waitUntil: 'networkidle0'});
  await settle(page, 700);
  const inputs = await page.$$('input');
  await inputs[0].type(ACCOUNT.name);
  await inputs[1].type(ACCOUNT.password);
  for (const b of await page.$$('button')) {
    if ((await b.evaluate((el) => el.textContent || '')).includes('登')) { await b.click(); break; }
  }
  await settle(page, 2500);

  const pages = {
    home: '/',
    emergencyQ1: '/consult/emergency',
    profile: '/profile',
    cases: '/cases',
  };

  const out = {};
  for (const [key, url] of Object.entries(pages)) {
    await page.goto(`${BASE}${url}`, {waitUntil: 'networkidle0'});
    await settle(page, 1800);
    // 档案页需要等取数完成
    if (key === 'profile') await settle(page, 1500);
    const m = await measure(page);
    out[key] = m;
    console.log(
      `${key.padEnd(12)} ${m.selector.padEnd(24)} scrollH=${m.scrollHeight} clientH=${m.clientHeight} maxScroll=${m.maxScroll}`,
    );
  }

  fs.writeFileSync(OUT, JSON.stringify(out, null, 2) + '\n');
  console.log(`\n→ ${OUT}`);
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
