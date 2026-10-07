// diag-cases-deeplink.mjs — 诊断 deep-link 页面实际渲染状态
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = 'http://localhost:5173';
const ACCOUNT = captureAccount();
const ITEM_ID = 'c06b0969-daed-4831-a5ce-d1468c37cf46';

async function settle(page, ms = 800) {
  // quality-floor: ignore silent-catch 字体就绪是尽力而为的等待，失败降级为下一行的固定等待，不让整批截图报废
  await page.waitForFunction(() => document.fonts.status === 'loaded', { timeout: 15000 }).catch(() => {});
  await new Promise((r) => setTimeout(r, ms));
}

const browser = await puppeteer.launch({ headless: true, protocolTimeout: 120000 });
const page = await browser.newPage();
page.on('response', (r) => { if (r.status() >= 400) console.log('HTTP', r.status(), r.url().slice(0, 120)); });
await page.setViewport({ width: 1280, height: 1000, deviceScaleFactor: 2 });

await page.goto(`${BASE}/login`, { waitUntil: 'networkidle0', timeout: 30000 });
await settle(page, 700);
const inputs = await page.$$('input');
await inputs[0].type(ACCOUNT.name);
await inputs[1].type(ACCOUNT.password);
for (const b of await page.$$('button')) {
  if ((await b.evaluate((el) => el.textContent || '')).includes('登')) { await b.click(); break; }
}
await settle(page, 2500);
console.log('logged in:', page.url());

await page.goto(`${BASE}/cases?item=${ITEM_ID}`, { waitUntil: 'networkidle0', timeout: 30000 });
for (let i = 0; i < 8; i++) {
  await settle(page, 1500);
  const st = await page.evaluate(() => ({
    url: location.href.slice(0, 100),
    hasDevice: !!document.querySelector('.device'),
    textHead: (document.body.innerText || '').slice(0, 300).replace(/\n+/g, ' | '),
  }));
  console.log(`--- t=${i} hasDevice=${st.hasDevice} url=${st.url}`);
  console.log('   ', st.textHead.slice(0, 220));
  if (st.hasDevice) break;
}
await page.screenshot({ path: path.join(__dirname, '../out/device-shots/_diag.png') });
console.log('diag saved');
await browser.close();
