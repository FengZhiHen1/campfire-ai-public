// 精确实测:待确认卡片内「待确认」徽标的位置(供 S7 的状态翻转覆盖层定位)。
import puppeteer from 'puppeteer';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = 'http://localhost:5174';
const ACCOUNT = { name: 'demo-parent', password: 'Demo#2026campfire' };

async function settle(page, ms = 900) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

async function main() {
  const browser = await puppeteer.launch({ headless: true, protocolTimeout: 300000 });
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });

  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle0' });
  await settle(page, 700);
  const inputs = await page.$$('input');
  await inputs[0].type(ACCOUNT.name);
  await inputs[1].type(ACCOUNT.password);
  for (const b of await page.$$('button')) {
    if ((await b.evaluate((el) => el.textContent || '')).includes('登')) { await b.click(); break; }
  }
  await settle(page, 2500);

  await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle0' });
  await settle(page, 2200);

  const res = await page.evaluate(() => {
    const hits = [];
    for (const el of document.querySelectorAll('*')) {
      const direct = [...el.childNodes].filter((n) => n.nodeType === 3)
        .map((n) => n.textContent.trim()).join('');
      if (direct === '待确认' || direct === 'AI 归纳' || direct === '待确认 · AI 归纳') {
        const r = el.getBoundingClientRect();
        hits.push({
          text: direct,
          x: Math.round(r.left), y: Math.round(r.top),
          w: Math.round(r.width), h: Math.round(r.height),
          cls: (el.className || '').toString().slice(0, 50),
        });
      }
    }
    return hits;
  });

  console.log('「待确认」相关元素:');
  for (const h of res) {
    console.log(`  "${h.text}" x=${h.x} y=${h.y} w=${h.w} h=${h.h} cls=${h.cls}`);
  }
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
