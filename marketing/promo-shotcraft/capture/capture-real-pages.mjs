// 真机对照:截**真实产品页面**,与影片里的手写复刻做像素级比对。
//
// ── 为什么需要这一步 ─────────────────────────────────────────────
// 影片有三个组件是**手写复刻**(EmergencyFormView / ChatScreen / ActionCardScreen),
// 不是真实页面。理由已经实测证明过:真实页面的 index/handled 是 useState,
// 不同帧渲染出**逐字节相同**的画面,无法作为帧驱动素材
// (证据见 .tmp/review-fixed.txt 与 ACCEPTANCE.md)。
//
// 复刻路线的固有风险是**漂移**。之前做的 `scripts/check-classnames.ts` 只验证了
// 「类名在产品 CSS 里存在」—— 但**类名对 ≠ 长得一样**:行内样式覆盖、遗漏的规则、
// 猜错的 token 值都不会被它抓到(已经抓到过一次:handled-note 的
// color/margin 两个值我都猜错了)。
//
// 这个脚本补上最后一环:同视口、同尺寸下截真实页面,供人工与复刻帧比对。
//
// 用法: node capture/capture-real-pages.mjs
import fs from 'fs';
import path from 'path';
import {fileURLToPath} from 'url';
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = 'http://localhost:5174';
const ACCOUNT = captureAccount();
const OUT = path.resolve(__dirname, '../out/parity');
fs.mkdirSync(OUT, {recursive: true});

/** 等字体与网络安定 —— 否则截到的是 fallback 字体,与影片里的字不是一套。 */
async function settle(page, ms = 1200) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

async function login(page) {
  await page.goto(`${BASE}/login`, {waitUntil: 'networkidle2', timeout: 60000});
  await settle(page, 600);
  // 产品登录页的两个输入框
  const inputs = await page.$$('input');
  if (inputs.length >= 2) {
    await inputs[0].type(ACCOUNT.name);
    await inputs[1].type(ACCOUNT.password);
    await page.keyboard.press('Enter');
    // quality-floor: ignore silent-catch 登录后的导航等待是尽力而为：下一行的固定等待兜底，失败不中断整批
    await page.waitForNavigation({waitUntil: 'networkidle2', timeout: 60000}).catch(() => {});
    await settle(page, 1000);
    return true;
  }
  return false;
}

const browser = await puppeteer.launch({
  headless: 'new',
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
  protocolTimeout: 300000,
});
const page = await browser.newPage();
// 与影片一致的视口:产品在 ≥560px 下渲染设备壳
await page.setViewport({width: 1280, height: 1000, deviceScaleFactor: 2});

console.log('登录…');
const ok = await login(page);
console.log(ok ? '  ✓ 已登录' : '  ✗ 未找到登录输入框(可能已有会话)');

// 与影片对应的三个复刻组件
const PAGES = [
  {name: 'real-emergency-form', url: `${BASE}/consult/emergency`},
  {name: 'real-chat', url: `${BASE}/consult`},
  {name: 'real-cases', url: `${BASE}/cases`},
  {name: 'real-profile', url: `${BASE}/profile`},
];

for (const p of PAGES) {
  try {
    await page.goto(p.url, {waitUntil: 'networkidle2', timeout: 60000});
    await settle(page);
    const file = path.join(OUT, `${p.name}.png`);
    await page.screenshot({path: file});

    // 同时把设备屏的几何记下来,便于对齐比对
    const geo = await page.evaluate(() => {
      const d = document.querySelector('.device');
      const s = document.querySelector('.device-screen');
      const r = (el) => (el === null ? null : el.getBoundingClientRect().toJSON());
      return {device: r(d), screen: r(s)};
    });
    console.log(`✓ ${p.name} → ${path.basename(file)}`);
    console.log(`    device=${JSON.stringify(geo.device && {x: Math.round(geo.device.x), y: Math.round(geo.device.y), w: Math.round(geo.device.width), h: Math.round(geo.device.height)})}`);
  } catch (e) {
    console.log(`✗ ${p.name}: ${String(e).slice(0, 140)}`);
  }
}

await browser.close();
console.log('done');
