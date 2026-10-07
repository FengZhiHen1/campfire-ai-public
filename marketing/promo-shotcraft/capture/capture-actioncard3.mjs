// 点开「生成行动卡」折叠区,滚动到可见位置,截行动卡
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, '../public/textures/live');
const BASE = 'http://localhost:5174';
const ACCOUNT = captureAccount();
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
  await settle(page, 1200);

  // 点开「生成行动卡」
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('*')];
    for (const el of all) {
      const t = el.textContent || '';
      if (t.includes('生成行动卡') && t.includes('已结束') && el.children.length < 5) {
        const btn = el.querySelector('button') || el.closest('div')?.querySelector('button');
        if (btn) { btn.click(); return; }
        el.click();
        return;
      }
    }
  });
  await settle(page, 2500);

  // 滚动到行动卡内容可见(找「医疗风险」或「01」附近的元素,scrollIntoView)
  const found = await page.evaluate(() => {
    const all = [...document.querySelectorAll('*')];
    for (const el of all) {
      const t = el.textContent || '';
      if (t.includes('医疗风险') && el.children.length < 10 && el.offsetHeight < 600 && el.offsetHeight > 80) {
        el.scrollIntoView({ block: 'start', behavior: 'instant' });
        return { y: el.getBoundingClientRect().y, h: el.offsetHeight };
      }
    }
    // 备用:找 01 编号
    for (const el of all) {
      const t = (el.textContent || '').trim();
      if (/^01/.test(t) && el.children.length < 10 && el.offsetHeight > 80) {
        el.scrollIntoView({ block: 'start', behavior: 'instant' });
        return { y: el.getBoundingClientRect().y, h: el.offsetHeight };
      }
    }
    return null;
  });
  console.log('滚动到:', JSON.stringify(found));
  await settle(page, 800);

  // 截 viewport(当前可见区域,即行动卡)
  await page.screenshot({ path: path.join(OUT, 'action-card-visible@2x.png') });

  // 截包含医疗风险的元素
  const riskEl = await page.evaluateHandle(() => {
    const all = [...document.querySelectorAll('*')];
    for (const el of all) {
      const t = el.textContent || '';
      if (t.includes('医疗风险') && el.children.length < 10 && el.offsetHeight < 600 && el.offsetHeight > 80) {
        return el;
      }
    }
    return null;
  });
  if (riskEl) {
    const box = await riskEl.boundingBox();
    if (box) {
      await riskEl.screenshot({ path: path.join(OUT, 'action-risk-block.png'), omitBackground: true });
      console.log('risk-block bbox:', JSON.stringify(box));
    }
  }

  console.log('完成');
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
