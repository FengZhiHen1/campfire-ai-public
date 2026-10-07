// capture-cases-fictional.mjs — 案例库精准搜索虚构样例(折叠态,不触发展开 bug)
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, '../out/device-shots');
const BASE = 'http://localhost:5173';
const ACCOUNT = captureAccount();

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

async function settle(page, ms = 800) {
  // quality-floor: ignore silent-catch 字体就绪是尽力而为的等待，失败降级为下一行的固定等待，不让整批截图报废
  await page.waitForFunction(() => document.fonts.status === 'loaded', { timeout: 15000 }).catch(() => {});
  await new Promise((r) => setTimeout(r, ms));
}

const browser = await puppeteer.launch({ headless: true, protocolTimeout: 120000 });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 1000, deviceScaleFactor: 2 });

log('login');
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle0', timeout: 30000 });
await settle(page, 700);
const inputs = await page.$$('input');
await inputs[0].type(ACCOUNT.name);
await inputs[1].type(ACCOUNT.password);
for (const b of await page.$$('button')) {
  if ((await b.evaluate((el) => el.textContent || '')).includes('登')) { await b.click(); break; }
}
await settle(page, 2500);

log('goto /cases');
await page.goto(`${BASE}/cases`, { waitUntil: 'networkidle0', timeout: 30000 });
await settle(page, 1500);

log('search 超市感官过载');
await page.evaluate(() => {
  const inp = [...document.querySelectorAll('input')]
    .find((i) => (i.placeholder || '').includes('搜') || i.type === 'search');
  if (!inp) return;
  inp.focus();
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(inp, '超市感官过载');
  inp.dispatchEvent(new Event('input', { bubbles: true }));
});
await settle(page, 2000);

const listing = await page.evaluate(() =>
  [...document.querySelectorAll('.list-row, article')]
    .map((r) => (r.textContent || '').trim().slice(0, 60)).filter(Boolean).slice(0, 5));
log('rows:', JSON.stringify(listing, null, 1));

// 只保留第一屏:把视口内第二行以下的内容藏掉,避免「内部」条目入镜
await page.evaluate(() => {
  const screen = document.querySelector('.device-screen');
  if (!screen) return;
  const rows = [...screen.querySelectorAll('.list-row, article')];
  // 找到虚构样例行,把它之后的所有行藏掉
  const idx = rows.findIndex((r) => (r.textContent || '').includes('虚构样例'));
  if (idx >= 0) rows.slice(idx + 1).forEach((r) => { r.style.visibility = 'hidden'; });
});

const el = await page.$('.device');
if (!el) throw new Error('.device 未找到');
const box = await el.boundingBox();
await page.screenshot({
  path: path.join(OUT, '15b-cases-fictional.png'),
  omitBackground: true,
  clip: { x: box.x, y: box.y, width: box.width, height: box.height },
});
log('shot 15b-cases-fictional.png');
await browser.close();
