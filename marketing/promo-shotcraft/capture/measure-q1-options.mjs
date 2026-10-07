// 实测应急第 1 题各选项行的真实坐标(供 S4 勾选 overlay 对齐)。
// 输出写到 src/layout-emergency-q1.json,组件按它定位,不再手猜。
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = 'http://localhost:5174';
const ACCOUNT = captureAccount();
const OUT = path.resolve(__dirname, '../src/layout-emergency-q1.json');

async function settle(page, ms = 900) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

const OPTIONS = [
  '意识改变', '呼吸异常', '严重出血', '明显外伤',
  '癫痫持续或异常发作', '中毒或误服', '严重过敏', '明显疼痛',
];

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

  await page.goto(`${BASE}/consult/emergency`, { waitUntil: 'networkidle0' });
  await settle(page, 1800);

  // 找每个选项文本所在的行容器,记录其 bbox 与左侧圆圈(第一个 svg/圆形元素)位置
  const rows = await page.evaluate((opts) => {
    const out = [];
    for (const label of opts) {
      // 找到文本节点精确匹配的元素
      const all = [...document.querySelectorAll('*')];
      let target = null;
      for (const el of all) {
        const direct = [...el.childNodes]
          .filter((n) => n.nodeType === 3)
          .map((n) => n.textContent.trim())
          .join('');
        if (direct === label) { target = el; break; }
      }
      if (!target) { out.push({label, found: false}); continue; }
      const tr = target.getBoundingClientRect();

      // 向上找全宽行容器(宽度 > 300 的祖先)
      let row = target;
      for (let i = 0; i < 8 && row.parentElement; i++) {
        row = row.parentElement;
        if (row.getBoundingClientRect().width > 300) break;
      }
      const rr = row.getBoundingClientRect();

      // 行内最左的圆形元素(单选圈):宽高接近且 <= 34,位于文本左侧
      let circle = null;
      for (const c of [...row.querySelectorAll('*')]) {
        const cr = c.getBoundingClientRect();
        if (cr.width >= 14 && cr.width <= 34 && Math.abs(cr.width - cr.height) <= 5 && cr.left < tr.left) {
          if (!circle || cr.left < circle.x) {
            circle = {x: cr.left, y: cr.top, w: cr.width, h: cr.height};
          }
        }
      }
      out.push({
        label, found: true,
        text: {x: Math.round(tr.left), y: Math.round(tr.top), w: Math.round(tr.width), h: Math.round(tr.height)},
        row: {x: Math.round(rr.left), y: Math.round(rr.top), w: Math.round(rr.width), h: Math.round(rr.height)},
        circle: circle ? {x: Math.round(circle.x), y: Math.round(circle.y), w: Math.round(circle.w)} : null,
      });
    }
    return out;
  }, OPTIONS);

  console.log('第 1 题选项实测坐标(逻辑 px, 视口 390×844):');
  for (const r of rows) {
    if (!r.found) { console.log(`  ${r.label}: 未找到`); continue; }
    const c = r.circle ? `circle=(${r.circle.x},${r.circle.y},${r.circle.w})` : 'circle=未知';
    console.log(`  ${r.label.padEnd(12)} row=(${r.row.x},${r.row.y},${r.row.w}x${r.row.h}) ${c}`);
  }

  fs.writeFileSync(OUT, JSON.stringify(rows, null, 2));
  console.log('\n→ src/layout-emergency-q1.json');
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
