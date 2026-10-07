// DOM 结构导出:登录后 dump 各页面真实 DOM 树(标签+类名+文本+bbox),作为坐标实测依据。
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, '../public/textures/states');
const BASE = 'http://localhost:5174';
const ACCOUNT = captureAccount();
const SESSION_ID = 'b897534e95b74aa99fdf23fe535248d7';

async function settle(page, ms = 900) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

// dump 可视区内的元素树(只取有文本或有意义的容器)
async function dump(page, label) {
  const tree = await page.evaluate(() => {
    const out = [];
    const walk = (el, depth) => {
      if (depth > 7) return;
      const r = el.getBoundingClientRect();
      const txt = (el.textContent || '').trim().slice(0, 40);
      const cls = (el.className || '').toString().slice(0, 60);
      // 只记可见且有一定尺寸的元素
      if (r.width > 30 && r.height > 12 && r.bottom > 0 && r.top < 844 && r.right > 0 && r.left < 390) {
        out.push({
          d: depth,
          tag: el.tagName.toLowerCase(),
          cls,
          y: Math.round(r.y),
          x: Math.round(r.x),
          w: Math.round(r.width),
          h: Math.round(r.height),
          txt,
        });
      }
      for (const c of el.children) walk(c, depth + 1);
    };
    walk(document.body, 0);
    return out;
  });
  console.log(`\n===== ${label} (${tree.length} 元素) =====`);
  for (const e of tree) {
    if (!e.txt && !e.cls) continue;
    console.log(`${'  '.repeat(e.d)}${e.tag}.${e.cls.slice(0, 34)} [${e.x},${e.y} ${e.w}x${e.h}] ${e.txt}`);
  }
  return tree;
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ headless: true, protocolTimeout: 120000 });
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });

  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle0' });
  await settle(page, 800);
  const inputs = await page.$$('input');
  await inputs[0].type(ACCOUNT.name);
  await inputs[1].type(ACCOUNT.password);
  for (const b of await page.$$('button')) {
    const t = await b.evaluate((el) => el.textContent || '');
    if (t.includes('登')) { await b.click(); break; }
  }
  await settle(page, 2500);

  await page.goto(`${BASE}/`, { waitUntil: 'networkidle0' });
  await settle(page, 1200);
  await dump(page, 'HOME');

  await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle0' });
  await settle(page, 1500);
  await dump(page, 'PROFILE');
  await page.screenshot({ path: path.join(OUT, 'profile-top.png') });
}
main().catch((e) => { console.error(e); process.exit(1); });
main().then(() => process.exit(0));
