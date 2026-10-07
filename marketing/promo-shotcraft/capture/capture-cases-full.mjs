// 补采:案例库全页长图(供 S8 滚动)。
// 案例库是 body 滚动页面,可直接 fullPage 截。
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, '../public/textures/full');
const BASE = 'http://localhost:5174';
const ACCOUNT = { name: 'demo-parent', password: 'Demo#2026campfire' };

async function settle(page, ms = 900) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

async function main() {
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

  // 案例库
  await page.goto(`${BASE}/cases`, { waitUntil: 'networkidle0' });
  await settle(page, 1800);
  const h = await page.evaluate(() => document.body.scrollHeight);
  console.log('案例页全高(逻辑):', h);
  await page.screenshot({ path: path.join(OUT, 'cases-full.png'), fullPage: true });
  console.log('  → cases-full.png');

  // 也采首页全页(供后续可能的滚动)
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle0' });
  await settle(page, 1200);
  const h2 = await page.evaluate(() => document.body.scrollHeight);
  console.log('首页全高(逻辑):', h2);

  const metaPath = path.resolve(__dirname, '../src/page-heights.json');
  const meta = JSON.parse(fs.readFileSync(metaPath, 'utf-8'));
  meta.cases = { w: 390, h };
  meta.home = { w: 390, h: h2 };
  fs.writeFileSync(metaPath, JSON.stringify(meta, null, 2));
  console.log('page-heights.json 已更新:', JSON.stringify(meta));

  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
