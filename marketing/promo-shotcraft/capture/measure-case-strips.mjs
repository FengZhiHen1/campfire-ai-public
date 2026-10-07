// 实测案例库列表中「卡片标题 + 状态标签」的精确 bbox:
//   ① 虚构样例卡 ② 内部(真实)卡
// 用途:S8 用元素级特写只截「标题+标签」条,排除卡片下方的授权元数据。
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = 'http://localhost:5174';
const ACCOUNT = captureAccount();
const OUT = path.resolve(__dirname, '../src/layout-case-strips.json');

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

  await page.goto(`${BASE}/cases`, { waitUntil: 'networkidle0' });
  await settle(page, 2000);
  await page.evaluate(() => window.scrollTo(0, 0));
  await settle(page, 500);

  const res = await page.evaluate(() => {
    const found = {titles: [], badges: []};
    for (const el of document.querySelectorAll('*')) {
      const direct = [...el.childNodes].filter((n) => n.nodeType === 3)
        .map((n) => n.textContent.trim()).join('');
      if (!direct) continue;
      const r = el.getBoundingClientRect();
      const box = {
        text: direct.slice(0, 40),
        x: Math.round(r.left), y: Math.round(r.top + window.scrollY),
        w: Math.round(r.width), h: Math.round(r.height),
      };
      if (/^(虚构样例|内部)/.test(direct) && direct.length <= 8 && r.height < 40) {
        found.badges.push(box);
      }
      if (direct.startsWith('虚构样例：') || direct.startsWith('从强迫到尊重') ||
          direct.startsWith('从不定期炸弹') || direct.startsWith('成年才被看见')) {
        found.titles.push(box);
      }
    }
    return found;
  });

  console.log('卡片标题:');
  for (const t of res.titles) console.log(`  "${t.text}" x=${t.x} y=${t.y} w=${t.w} h=${t.h}`);
  console.log('状态标签:');
  for (const b of res.badges) console.log(`  "${b.text}" x=${b.x} y=${b.y} w=${b.w} h=${b.h}`);

  fs.writeFileSync(OUT, JSON.stringify(res, null, 2));
  console.log('\n→ src/layout-case-strips.json');
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
