// capture-cases-fictional.mjs — 案例库搜索「虚构」后的整机截图(单独跑,带日志)
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

log('goto login');
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle0', timeout: 30000 });
await settle(page, 700);
const inputs = await page.$$('input');
await inputs[0].type(ACCOUNT.name);
await inputs[1].type(ACCOUNT.password);
for (const b of await page.$$('button')) {
  if ((await b.evaluate((el) => el.textContent || '')).includes('登')) { await b.click(); break; }
}
await settle(page, 2500);
log('logged in →', page.url());

log('goto /cases');
await page.goto(`${BASE}/cases`, { waitUntil: 'networkidle0', timeout: 30000 });
await settle(page, 1500);

log('type 虚构 into search');
const typed = await page.evaluate(() => {
  const inp = [...document.querySelectorAll('input')]
    .find((i) => (i.placeholder || '').includes('搜') || i.type === 'search');
  if (!inp) return false;
  inp.focus();
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(inp, '虚构');
  inp.dispatchEvent(new Event('input', { bubbles: true }));
  return true;
});
log('typed:', typed);
await settle(page, 1800);

const counts = await page.evaluate(() => document.body.innerText.length);
log('body text len:', counts);

const el = await page.$('.device');
if (!el) throw new Error('.device 未找到');
const box = await el.boundingBox();
log('device box:', box.width, box.height);
await page.screenshot({
  path: path.join(OUT, '15b-cases-fictional.png'),
  omitBackground: true,
  clip: { x: box.x, y: box.y, width: box.width, height: box.height },
});
log('shot 15b-cases-fictional.png');
await browser.close();
