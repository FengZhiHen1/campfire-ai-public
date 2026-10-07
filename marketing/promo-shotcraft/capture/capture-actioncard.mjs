// 行动卡区域截图:滚动到底部展开全部内容,截关键区域
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import fs from 'fs';
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

  // 登录
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

  // 滚动到底部,等思考过程/行动卡渲染
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await settle(page, 1500);

  // 截全页(滚动后的完整内容)
  await page.screenshot({ path: path.join(OUT, 'action-card-full@2x.png'), fullPage: true });

  // 找「医疗风险」相关区域并截元素
  const riskArea = await page.evaluateHandle(() => {
    const all = [...document.querySelectorAll('*')];
    for (const el of all) {
      const t = el.textContent || '';
      if (t.includes('医疗风险') && el.children.length < 8 && el.offsetHeight < 400 && el.offsetHeight > 40) {
        return el;
      }
    }
    return null;
  });
  if (riskArea) {
    const box = await riskArea.boundingBox();
    if (box) {
      await riskArea.screenshot({ path: path.join(OUT, 'action-risk-area.png'), omitBackground: true });
      console.log('risk-area:', JSON.stringify(box));
    }
  }

  // 找「01」编号块
  const blocks = await page.$$eval('*', (els) => {
    const found = [];
    for (const el of els) {
      const t = (el.textContent || '').trim();
      if (/^0[123]/.test(t) && el.children.length < 10 && el.offsetHeight < 500 && el.offsetHeight > 60) {
        const r = el.getBoundingClientRect();
        found.push({ tag: el.tagName, cls: el.className?.toString()?.slice(0, 50), y: r.y, h: r.height });
      }
    }
    return found.slice(0, 5);
  });
  console.log('编号块:', JSON.stringify(blocks, null, 2));

  // 截底部 viewport(行动卡可见部分)
  await page.screenshot({ path: path.join(OUT, 'action-card-bottom@2x.png') });

  console.log('完成');
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
