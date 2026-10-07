// 实测档案页「待确认」卡片内「纠正」按钮的真实坐标。
// 之前手猜 top = 卡片顶 + 108,结果压在正文上(S7 flip 帧可见)。
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = 'http://localhost:5174';
const ACCOUNT = { name: 'demo-parent', password: 'Demo#2026campfire' };

async function settle(page, ms = 900) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

async function main() {
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

  await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle0' });
  await settle(page, 2200);

  const info = await page.evaluate(() => {
    const out = { groups: [], buttons: [], texts: [], tags: [] };
    // 所有「待确认」「已确认」等分组标题
    for (const el of document.querySelectorAll('*')) {
      const direct = [...el.childNodes].filter((n) => n.nodeType === 3)
        .map((n) => n.textContent.trim()).join('');
      if (/^(待确认|已确认|基本身份与档案信息)\s*[（(]\d+[）)]?$/.test(direct)) {
        const r = el.getBoundingClientRect();
        out.groups.push({text: direct, y: Math.round(r.top), x: Math.round(r.left), h: Math.round(r.height)});
      }
      if (direct === '纠正' || direct === '确认' || direct === '删除') {
        const r = el.getBoundingClientRect();
        out.texts.push({text: direct, x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height)});
      }
      if (direct === '待确认' || direct.startsWith('待确认')) {
        const r = el.getBoundingClientRect();
        out.tags = out.tags || []; out.tags.push({t: direct, y: Math.round(r.top), x: Math.round(r.left), w: Math.round(r.width), h: Math.round(r.height)});
      }
    }
    return out;
  });

  console.log('分组标题:', JSON.stringify(info.groups, null, 1));
  console.log('卡片标题:', JSON.stringify(info.topic));
  console.log('按钮/文字:', JSON.stringify(info.texts, null, 1));

  fs.writeFileSync(
    path.resolve(__dirname, '../src/layout-profile-actions.json'),
    JSON.stringify(info, null, 2),
  );
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
