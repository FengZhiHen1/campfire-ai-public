// 探测案例库页面:是否有折叠态(收起/展开),以及折叠态下「虚构样例」标签的位置。
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = 'http://localhost:5174';
const ACCOUNT = captureAccount();
const OUT = path.resolve(__dirname, '../out/probe');

async function settle(page, ms = 900) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

async function main() {
  const fs = await import('fs');
  fs.mkdirSync(OUT, { recursive: true });
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

  await page.goto(`${BASE}/cases`, { waitUntil: 'networkidle0' });
  await settle(page, 2000);

  // 1. 页面上的所有按钮文案
  const btns = await page.evaluate(() =>
    [...document.querySelectorAll('button')].map((b) => (b.textContent || '').trim()).filter(Boolean),
  );
  console.log('按钮文案:', JSON.stringify([...new Set(btns)]));

  // 2. 是否有「展开」「收起」
  const hasExpand = btns.some((t) => t.includes('展开'));
  const hasCollapse = btns.some((t) => t.includes('收起'));
  console.log(`含「展开」按钮: ${hasExpand} | 含「收起」按钮: ${hasCollapse}`);

  // 3. 默认状态下「虚构样例」标签的位置
  const tagInfo = await page.evaluate(() => {
    const out = [];
    for (const el of document.querySelectorAll('*')) {
      const t = (el.textContent || '').trim();
      if (t === '虚构样例' && el.children.length === 0) {
        const r = el.getBoundingClientRect();
        out.push({y: Math.round(r.top + window.scrollY), x: Math.round(r.left), w: Math.round(r.width)});
      }
    }
    return out;
  });
  console.log('默认态「虚构样例」标签位置:', JSON.stringify(tagInfo));

  // 4. 全页高度
  const h = await page.evaluate(() => document.body.scrollHeight);
  console.log('全页高度:', h);

  // 5. 截默认态顶部
  await page.screenshot({ path: path.join(OUT, 'cases-default-top.png') });

  // 6. 如果有「展开」,试点击再截(看是否元数据是折叠内容)
  if (hasExpand) {
    await page.evaluate(() => {
      [...document.querySelectorAll('button')]
        .filter((b) => (b.textContent || '').trim().includes('展开'))
        .forEach((b) => b.click());
    });
    await settle(page, 1800);
    const h2 = await page.evaluate(() => document.body.scrollHeight);
    console.log('展开后全页高度:', h2);
    await page.screenshot({ path: path.join(OUT, 'cases-expanded-top.png') });
    await page.screenshot({ path: path.join(OUT, 'cases-expanded-full.png'), fullPage: true });
  }

  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
