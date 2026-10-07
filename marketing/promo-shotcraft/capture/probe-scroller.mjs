// 探测会话页/档案页的滚动容器结构(内部 scroll 容器 vs body 滚动)。
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = 'http://localhost:5174';
const ACCOUNT = captureAccount();
const SESSION_ID = 'b897534e95b74aa99fdf23fe535248d7';

async function settle(page, ms = 900) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

async function main() {
  const browser = await puppeteer.launch({ headless: true, protocolTimeout: 180000 });
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

  await page.goto(`${BASE}/consult/sessions/${SESSION_ID}`, { waitUntil: 'networkidle0' });
  await settle(page, 3000);

  const info = await page.evaluate(() => {
    const out = [];
    const walk = (el) => {
      const cs = getComputedStyle(el);
      const scrollable = el.scrollHeight > el.clientHeight + 20;
      if (scrollable && (cs.overflowY === 'auto' || cs.overflowY === 'scroll')) {
        const r = el.getBoundingClientRect();
        out.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.className || '').toString().slice(0, 60),
          scrollH: el.scrollHeight,
          clientH: el.clientHeight,
          y: Math.round(r.y),
          x: Math.round(r.x),
          w: Math.round(r.width),
        });
      }
      for (const c of el.children) walk(c);
    };
    walk(document.body);
    return { containers: out, bodyScrollH: document.body.scrollHeight, docScrollH: document.documentElement.scrollHeight };
  });
  console.log('body scrollH:', info.bodyScrollH, '| doc:', info.docScrollH);
  console.log('可滚动容器:');
  for (const c of info.containers) console.log('  ', JSON.stringify(c));
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
