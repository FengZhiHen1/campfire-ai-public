// 量出关键元素在页面内容坐标系里的位置,换算成「滚动进度比例」。
//
// ★ 为什么要量元素位置(而不是给一个比例常数):
//   镜头要「滚到虚构样例条目」「滚到待确认分组」这类**具体区块**。
//   给常数比例是猜;量出元素 offsetTop 再除以 maxScroll 才是可复核的。
//   内容变长时比例自动跟随,不会失效。
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = 'http://localhost:5174';
const ACCOUNT = {name: 'demo-parent', password: 'Demo#2026campfire'};
const OUT = path.resolve(__dirname, '../src/element-metrics.json');

async function settle(page, ms = 900) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

async function main() {
  const browser = await puppeteer.launch({headless: true, protocolTimeout: 300000});
  const page = await browser.newPage();
  await page.setViewport({width: 1280, height: 1000, deviceScaleFactor: 1});

  await page.goto(`${BASE}/login`, {waitUntil: 'networkidle0'});
  await settle(page, 700);
  const inputs = await page.$$('input');
  await inputs[0].type(ACCOUNT.name);
  await inputs[1].type(ACCOUNT.password);
  for (const b of await page.$$('button')) {
    if ((await b.evaluate((el) => el.textContent || '')).includes('登')) { await b.click(); break; }
  }
  await settle(page, 2500);

  const out = {};

  // ── 案例库:虚构样例条目 ──
  await page.goto(`${BASE}/cases`, {waitUntil: 'networkidle0'});
  await settle(page, 2000);
  out.cases = await page.evaluate(() => {
    const scroller = document.querySelector('.device-screen');
    const scrollerTop = scroller.getBoundingClientRect().top + window.scrollY;
    const maxScroll = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
    const res = {maxScroll, marks: {}};
    // 找所有状态标签,记录它们的 offsetTop(相对滚动容器内容)
    for (const el of document.querySelectorAll('.tag, .status, [class*="tag"]')) {
      const t = (el.textContent || '').trim();
      if (t === '虚构样例' || t === '内部') {
        const r = el.getBoundingClientRect();
        const offsetInScroller = r.top - scroller.getBoundingClientRect().top + scroller.scrollTop;
        if (res.marks[t] === undefined) {
          res.marks[t] = {offsetTop: Math.round(offsetInScroller), ratio: 0};
        }
      }
    }
    for (const k of Object.keys(res.marks)) {
      // 希望该元素滚到屏幕上方 1/4 处 → 滚动量 = offsetTop - 844*0.25
      const target = Math.max(0, res.marks[k].offsetTop - 844 * 0.25);
      res.marks[k].ratio = maxScroll === 0 ? 0 : Math.min(1, target / maxScroll);
      res.marks[k].scrollPx = Math.round(Math.min(maxScroll, target));
    }
    return res;
  });
  console.log('cases:', JSON.stringify(out.cases, null, 2));

  // ── 档案页:待确认分组 ──
  await page.goto(`${BASE}/profile`, {waitUntil: 'networkidle0'});
  await settle(page, 2500);
  out.profile = await page.evaluate(() => {
    const scroller = document.querySelector('.device-screen');
    const maxScroll = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
    const res = {maxScroll, marks: {}};
    for (const g of document.querySelectorAll('details.group-collapse')) {
      const summary = g.querySelector('summary');
      const t = (summary?.textContent || '').trim();
      if (t.includes('待确认')) {
        const r = g.getBoundingClientRect();
        const sc = scroller.getBoundingClientRect();
        const offsetInScroller = r.top - sc.top + scroller.scrollTop;
        const target = Math.max(0, offsetInScroller - 844 * 0.18);
        res.marks.pendingGroup = {
          offsetTop: Math.round(offsetInScroller),
          scrollPx: Math.round(Math.min(maxScroll, target)),
          ratio: maxScroll === 0 ? 0 : Math.min(1, target / maxScroll),
        };
      }
    }
    return res;
  });
  console.log('profile:', JSON.stringify(out.profile, null, 2));

  fs.writeFileSync(OUT, JSON.stringify(out, null, 2) + '\n');
  console.log(`\n→ ${OUT}`);
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
