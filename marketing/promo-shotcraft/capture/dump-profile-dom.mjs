// 从真实渲染的档案页里 dump 出「待确认」分组的 DOM 结构,
// 目的是找到**稳定的 CSS 选择器**用于影片高亮(不能靠猜坐标,也不能改产品源码)。
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = 'http://localhost:5174';
const ACCOUNT = {name: 'demo-parent', password: 'Demo#2026campfire'};

async function settle(page, ms = 900) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

async function main() {
  const browser = await puppeteer.launch({headless: true, protocolTimeout: 300000});
  const page = await browser.newPage();
  await page.setViewport({width: 390, height: 844, deviceScaleFactor: 2});

  await page.goto(`${BASE}/login`, {waitUntil: 'networkidle0'});
  await settle(page, 700);
  const inputs = await page.$$('input');
  await inputs[0].type(ACCOUNT.name);
  await inputs[1].type(ACCOUNT.password);
  for (const b of await page.$$('button')) {
    if ((await b.evaluate((el) => el.textContent || '')).includes('登')) { await b.click(); break; }
  }
  await settle(page, 2500);

  await page.goto(`${BASE}/profile`, {waitUntil: 'networkidle0'});
  await settle(page, 2200);

  const info = await page.evaluate(() => {
    // 找「待确认」分组的 details.tile.group-collapse
    const groups = [...document.querySelectorAll('details.group-collapse, .group-collapse')];
    const out = [];
    for (const g of groups) {
      const summaryText = (g.querySelector('summary')?.textContent || '').trim();
      const isPending = summaryText.includes('待确认');
      out.push({
        summaryText: summaryText.slice(0, 60),
        isPending,
        className: g.className,
        // 组内所有带 class 的元素(去重)
        innerClasses: [...new Set([...g.querySelectorAll('[class]')].map((e) => e.className))].slice(0, 30),
        // 组内所有按钮文案
        buttons: [...g.querySelectorAll('button')].map((b) => (b.textContent || '').trim()),
      });
    }
    return out;
  });

  console.log(JSON.stringify(info, null, 2));
  fs.writeFileSync(
    path.resolve(__dirname, '../out/probe/profile-dom.json'),
    JSON.stringify(info, null, 2),
  );
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
