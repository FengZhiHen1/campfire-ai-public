// 点开「生成行动卡」折叠区,截行动卡完整内容
import puppeteer from 'puppeteer';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, '../public/textures/live');
const BASE = 'http://localhost:5174';
const ACCOUNT = { name: 'demo-parent', password: 'Demo#2026campfire' };
const SESSION_ID = 'b897534e95b74aa99fdf23fe535248d7';

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

  await page.goto(`${BASE}/consult/sessions/${SESSION_ID}`, { waitUntil: 'networkidle0' });
  await settle(page, 2000);

  // 滚动到底部
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await settle(page, 1000);

  // 点开「生成行动卡」折叠区
  const clicked = await page.evaluate(() => {
    const all = [...document.querySelectorAll('*')];
    for (const el of all) {
      const t = el.textContent || '';
      if (t.includes('生成行动卡') && t.includes('已结束') && el.children.length < 5) {
        // 找它内部或旁边的「展开」按钮
        const btn = el.querySelector('button') || el.closest('div')?.querySelector('button');
        if (btn) { btn.click(); return 'btn'; }
        el.click();
        return 'el';
      }
    }
    return null;
  });
  console.log('点击展开:', clicked);
  await settle(page, 2000);

  // 截展开后的底部
  await page.screenshot({ path: path.join(OUT, 'action-card-expanded@2x.png') });
  console.log('完成');
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
