// 案例库页面采集(修正路由:/cases 不是 /library/cases)
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, '../public/textures/live');
const BASE = 'http://localhost:5174';
const ACCOUNT = captureAccount();

async function settle(page, ms) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

async function main() {
  const browser = await puppeteer.launch({ headless: true, protocolTimeout: 120000 });
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });

  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle0' });
  await settle(page, 600);
  const inputs = await page.$$('input');
  await inputs[0].type(ACCOUNT.name);
  await inputs[1].type(ACCOUNT.password);
  for (const b of await page.$$('button')) {
    const t = await b.evaluate((el) => el.textContent || '');
    if (t.includes('登')) { await b.click(); break; }
  }
  await settle(page, 2500);

  await page.goto(`${BASE}/cases`, { waitUntil: 'networkidle0' });
  await settle(page, 1500);

  // 全页截图
  await page.screenshot({ path: path.join(OUT, 'case-library@2x.png'), fullPage: true });

  // 案例行 cutout(找案例列表项)
  const rows = await page.$$('article.list-row, [class*="case"], [class*="list-row"]');
  console.log('案例行数:', rows.length);
  for (let i = 0; i < Math.min(rows.length, 4); i++) {
    try {
      await rows[i].screenshot({
        path: path.join(OUT, `case-row${i + 1}.png`),
        omitBackground: true,
      });
      const box = await rows[i].boundingBox();
      if (box) console.log(`  case-row${i + 1}:`, JSON.stringify(box));
    } catch (e) {
      console.warn(`  case-row${i + 1} 失败:`, e.message.slice(0, 60));
    }
  }

  // 「虚构样例」标签
  const tags = await page.$$eval('*', (els) => {
    const found = [];
    for (const el of els) {
      const t = (el.textContent || '').trim();
      if (t === '虚构样例' && el.children.length === 0) {
        const r = el.getBoundingClientRect();
        found.push({ x: r.x, y: r.y, w: r.width, h: r.height });
      }
    }
    return found;
  });
  console.log('虚构样例标签:', JSON.stringify(tags));

  console.log('完成');
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
