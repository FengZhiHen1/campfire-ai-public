// 逐屏状态采集(支撑「设备框 + 元素级特写分级」方案)
// 产出:每个镜头需要的真实页面状态截图(viewport 390×844 @2x) + 元素切片
// 要点:viewport 截图是分级方案的基础——190 逻辑宽屏在设备框内 1.0-1.3 倍显示,纹理不被放大
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import fs from 'fs';
import path from 'path';
import { fileURLToPath} from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, '../public/textures/states');
const BASE = 'http://localhost:5174';
const ACCOUNT = captureAccount();
const SESSION_ID = 'b897534e95b74aa99fdf23fe535248d7';

async function settle(page, ms = 600) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
  console.log(`  [state] ${name}.png`);
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ headless: true, protocolTimeout: 120000 });
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });

  // 登录
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

  // ── 首页 ──
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle0' });
  await settle(page, 1200);
  await shot(page, 'home');

  // ── 应急表单:8 题逐屏 ──
  await page.goto(`${BASE}/consult/emergency`, { waitUntil: 'networkidle0' });
  await settle(page, 1500);
  for (let q = 1; q <= 8; q++) {
    await shot(page, `emergency-q${q}`);
    // 点「下一题」进入下一屏(最后一题不点)
    if (q < 8) {
      const clicked = await page.evaluate(() => {
        const btns = [...document.querySelectorAll('button')];
        const next = btns.find((b) => (b.textContent || '').trim() === '下一题');
        if (next) { next.click(); return true; }
        return false;
      });
      if (!clicked) { console.warn(`  [warn] q${q} 未找到「下一题」按钮`); break; }
      await settle(page, 900);
    }
  }

  // ── 行动卡会话:多个滚动位置 ──
  await page.goto(`${BASE}/consult/sessions/${SESSION_ID}`, { waitUntil: 'networkidle0' });
  await settle(page, 2500);
  // 展开「生成行动卡」
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
  await settle(page, 2000);

  // 滚到不同位置采 4 屏:医疗风险区 / 01建议 / 02沟通 / 03环境
  const anchors = ['医疗风险', '当前最大风险', '02 立即怎么沟通', '03 '];
  for (let i = 0; i < anchors.length; i++) {
    const ok = await page.evaluate((anchor) => {
      const all = [...document.querySelectorAll('*')];
      for (const el of all) {
        const t = el.textContent || '';
        if (t.includes(anchor) && el.children.length < 10 && el.offsetHeight < 600 && el.offsetHeight > 60) {
          el.scrollIntoView({ block: 'start', behavior: 'instant' });
          return true;
        }
      }
      return false;
    }, anchors[i]);
    if (!ok) { console.warn(`  [warn] 未找到锚点 ${anchors[i]}`); continue; }
    await settle(page, 900);
    await shot(page, `action-${i + 1}`);
  }

  // ── 档案页:待确认区 / 已确认区 ──
  await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle0' });
  await settle(page, 1500);
  await shot(page, 'profile-top');
  // 滚到「基本身份与档案信息」分组
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('*')];
    for (const el of all) {
      if ((el.textContent || '').includes('基本身份与档案信息') && el.children.length < 4) {
        el.scrollIntoView({ block: 'start', behavior: 'instant' });
        return;
      }
    }
  });
  await settle(page, 900);
  await shot(page, 'profile-groups');

  // ── 案例库:顶部 / 虚构样例 ──
  await page.goto(`${BASE}/cases`, { waitUntil: 'networkidle0' });
  await settle(page, 1500);
  await shot(page, 'cases-top');
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('*')];
    for (const el of all) {
      if ((el.textContent || '').trim() === '虚构样例' && el.children.length === 0) {
        el.scrollIntoView({ block: 'center', behavior: 'instant' });
        return;
      }
    }
  });
  await settle(page, 900);
  await shot(page, 'cases-fictional');

  console.log('完成');
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
