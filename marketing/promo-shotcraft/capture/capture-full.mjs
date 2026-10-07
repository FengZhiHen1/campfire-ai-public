// 补采:会话页全页截图(供 S5/S6 滚动用)+ 档案全页(验证)。
// 关键:滚动镜头必须用 fullPage 截图,视口截图滚动后会露出空白(已踩坑)。
import puppeteer from 'puppeteer';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, '../public/textures/full');
const BASE = 'http://localhost:5174';
const ACCOUNT = { name: 'demo-parent', password: 'Demo#2026campfire' };
const SESSION_ID = 'b897534e95b74aa99fdf23fe535248d7';

async function settle(page, ms = 900) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

async function main() {
  const fs = await import('fs');
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ headless: true, protocolTimeout: 180000 });
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });

  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle0' });
  await settle(page, 800);
  const inputs = await page.$$('input');
  await inputs[0].type(ACCOUNT.name);
  await inputs[1].type(ACCOUNT.password);
  for (const b of await page.$$('button')) {
    const t = await b.evaluate((el) => el.textContent || '');
    if (t.includes('登')) { await b.click(); break; }
  }
  await settle(page, 2500);
  console.log('登录后:', page.url());

  // ── 会话页:展开全部折叠区,采全页 ──
  await page.goto(`${BASE}/consult/sessions/${SESSION_ID}`, { waitUntil: 'networkidle0' });
  await settle(page, 3000);
  const n = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')].filter(
      (b) => (b.textContent || '').trim() === '展开',
    );
    btns.forEach((b) => b.click());
    return btns.length;
  });
  console.log('展开按钮:', n);
  await settle(page, 3000);

  const sessionH = await page.evaluate(() => document.body.scrollHeight);
  console.log('会话页全高(逻辑):', sessionH);
  await page.screenshot({ path: path.join(OUT, 'session-full.png'), fullPage: true });
  console.log('  → session-full.png');

  // ── 档案页全页 ──
  await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle0' });
  await settle(page, 2000);
  const profileH = await page.evaluate(() => document.body.scrollHeight);
  console.log('档案页全高(逻辑):', profileH);
  await page.screenshot({ path: path.join(OUT, 'profile-full.png'), fullPage: true });
  console.log('  → profile-full.png');

  // ── 案例页全页 ──
  await page.goto(`${BASE}/cases`, { waitUntil: 'networkidle0' });
  await settle(page, 2000);
  const casesH = await page.evaluate(() => document.body.scrollHeight);
  console.log('案例页全高(逻辑):', casesH);
  await page.screenshot({ path: path.join(OUT, 'cases-full.png'), fullPage: true });
  console.log('  → cases-full.png');

  // 记录全页高度供组件使用
  const meta = { session: sessionH, profile: profileH, cases: casesH };
  fs.writeFileSync(
    path.resolve(__dirname, '../src/page-heights.json'),
    JSON.stringify(meta, null, 2),
  );
  console.log('page-heights.json:', JSON.stringify(meta));

  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
