// 内部滚动容器拼接全页图:
// 会话页内容在 .thread 内部滚动容器里(scrollHeight 7820 / clientHeight 608),
// 无法用 fullPage 一次截出。做法:按步长滚动容器,逐屏截取,再纵向拼接成一张长图。
// 拼接后坐标 = 容器内容坐标系,组件按此坐标定位/滚动,不会再露空白。
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { PNG } from 'pngjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, '../public/textures/full');
const TMP = path.resolve(__dirname, '../out/stitch');
const BASE = 'http://localhost:5174';
const ACCOUNT = captureAccount();
const SESSION_ID = 'df1eb792aa3b47998f4dc0460077c6ef';

async function settle(page, ms = 900) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

/** 滚动内部容器并逐屏截取,再拼接为一张长图 */
async function stitchScrollable(page, selector, outName, step = 500) {
  const meta = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {
      scrollH: el.scrollHeight,
      clientH: el.clientHeight,
      x: Math.round(r.x), y: Math.round(r.y),
      w: Math.round(r.width), h: Math.round(r.height),
    };
  }, selector);
  if (!meta) throw new Error(`找不到滚动容器 ${selector}`);
  console.log(`  ${selector}: scrollH=${meta.scrollH} clientH=${meta.clientH}`);

  const shots = [];
  for (let top = 0; top < meta.scrollH; top += step) {
    await page.evaluate(({ sel, t }) => {
      const el = document.querySelector(sel);
      el.scrollTop = t;
    }, { sel: selector, t: top });
    await settle(page, 260);
    const actualTop = await page.evaluate((sel) => document.querySelector(sel).scrollTop, selector);
    const f = path.join(TMP, `${outName}-${String(top).padStart(5, '0')}.png`);
    // 只截容器区域(@2x)
    await page.screenshot({
      path: f,
      clip: { x: meta.x, y: meta.y, width: meta.w, height: meta.h },
    });
    shots.push({ file: f, top: actualTop });
    if (actualTop + meta.clientH >= meta.scrollH) break;
  }

  // 纵向拼接:每屏按实际 scrollTop 偏移贴入(@2x → 坐标和像素都 ×2)
  const SCALE = 2;
  const dstW = meta.w * SCALE;
  const dstH = meta.scrollH * SCALE;
  const dst = new PNG({ width: dstW, height: dstH, fill: true });
  // 初始化底色为暖米纸
  for (let i = 0; i < dst.data.length; i += 4) {
    dst.data[i] = 0xfb; dst.data[i + 1] = 0xf6; dst.data[i + 2] = 0xee; dst.data[i + 3] = 255;
  }

  for (const s of shots) {
    const src = PNG.sync.read(fs.readFileSync(s.file));
    const dy = s.top * SCALE;
    const copyH = Math.min(src.height, dstH - dy);
    for (let y = 0; y < copyH; y++) {
      for (let x = 0; x < Math.min(src.width, dstW); x++) {
        const si = (src.width * y + x) << 2;
        const di = (dstW * (dy + y) + x) << 2;
        dst.data[di] = src.data[si];
        dst.data[di + 1] = src.data[si + 1];
        dst.data[di + 2] = src.data[si + 2];
        dst.data[di + 3] = 255;
      }
    }
  }

  fs.writeFileSync(path.join(OUT, `${outName}.png`), PNG.sync.write(dst));
  console.log(`  → ${outName}.png (${dstW}x${dstH}, 逻辑 ${meta.w}x${meta.scrollH})`);
  return { w: meta.w, h: meta.scrollH };
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  fs.mkdirSync(TMP, { recursive: true });
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

  const heights = {};

  // 会话页
  await page.goto(`${BASE}/consult/sessions/${SESSION_ID}`, { waitUntil: 'networkidle0' });
  await settle(page, 3000);
  // 展开全部折叠
  await page.evaluate(() => {
    [...document.querySelectorAll('button')]
      .filter((b) => (b.textContent || '').trim() === '展开')
      .forEach((b) => b.click());
  });
  await settle(page, 2500);
  heights.sessionArchive = await stitchScrollable(page, 'div[class*="_thread"]', 'session-archive-full');

  // 档案页
  await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle0' });
  await settle(page, 2000);
  const profileScroller = await page.evaluate(() => {
    const out = [];
    const walk = (el) => {
      const cs = getComputedStyle(el);
      if (el.scrollHeight > el.clientHeight + 20 && (cs.overflowY === 'auto' || cs.overflowY === 'scroll')) {
        out.push((el.className || '').toString());
      }
      for (const c of el.children) walk(c);
    };
    walk(document.body);
    return out;
  });
  console.log('档案页可滚动容器:', JSON.stringify(profileScroller));
  if (profileScroller.length) {
    heights.profile = await stitchScrollable(page, `div[class*="${profileScroller[0].split(' ')[0].replace(/_/g, '_')}"]`, 'profile-full');
  } else {
    await page.screenshot({ path: path.join(OUT, 'profile-full.png'), fullPage: true });
    heights.profile = { w: 390, h: await page.evaluate(() => document.body.scrollHeight) };
    console.log('  → profile-full.png (fullPage)');
  }

  fs.writeFileSync(
    path.resolve(__dirname, '../src/page-heights.json'),
    JSON.stringify(heights, null, 2),
  );
  console.log('page-heights.json:', JSON.stringify(heights));
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
