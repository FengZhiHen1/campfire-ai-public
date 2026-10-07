// Campfire-AI 宣传片素材采集(video-shotcraft 阶段 4 三件套)
// 产出:全页 2x 截图 / per-element cutout / layout.json
// 硬前提:demo-parent 可登录,种子数据(小满档案+4案例)已在库——已确认
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const CONFIG = {
  BASE: 'http://localhost:5174',
  OUT_DIR: path.resolve(__dirname, '../public/textures/live'),
  LAYOUT_JSON: path.resolve(__dirname, '../src/live-layout.json'),
  VIEWPORT: { width: 390, height: 844, deviceScaleFactor: 2 },
  SETTLE_MS: 600,
  ACCOUNT: captureAccount(),
  PAGES: [
    {
      name: 'home',
      path: '/',
      cutouts: [
        { name: 'emergency-card', selector: 'article.emergency-entry' },
        { name: 'daily-card', selector: 'a.daily-entry' },
      ],
      boxes: [{ key: 'tab-bar', selector: 'nav.tab-bar' }],
    },
    {
      name: 'emergency-form',
      path: '/consult/emergency',
      cutouts: [
        { name: 'question-tile', selector: 'section.tile' },
        { name: 'progress', selector: '.progress-track' },
      ],
    },
    {
      name: 'profile',
      path: '/profile',
      cutouts: [
        { name: 'pending-item', selector: 'article.candidate-record' },
        { name: 'confirmed-item', selector: 'article.list-row:not(.candidate-record)' },
      ],
    },
    {
      name: 'case-library',
      path: '/library/cases',
      cutouts: [
        { name: 'case-row', selector: 'article.list-row, .case-row, [class*="case"]', all: true, max: 4 },
      ],
    },
  ],
};

async function settle(page, ms) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

async function login(page, account) {
  await page.goto(`${CONFIG.BASE}/login`, { waitUntil: 'networkidle0' });
  await settle(page, 800);
  const inputs = await page.$$('input');
  await inputs[0].type(account.name);
  await inputs[1].type(account.password);
  const btns = await page.$$('button');
  for (const b of btns) {
    const txt = await b.evaluate((el) => el.textContent || '');
    if (txt.includes('登')) {
      await b.click();
      break;
    }
  }
  await page.waitForNavigation({ waitUntil: 'networkidle0', timeout: 15000 }).catch(() => {});
  await settle(page, 2000);
}

async function main() {
  fs.mkdirSync(CONFIG.OUT_DIR, { recursive: true });
  fs.mkdirSync(path.dirname(CONFIG.LAYOUT_JSON), { recursive: true });

  const browser = await puppeteer.launch({ headless: true, protocolTimeout: 120000 });
  const page = await browser.newPage();
  await page.setViewport(CONFIG.VIEWPORT);

  console.log('[capture] 登录…');
  await login(page, CONFIG.ACCOUNT);
  console.log('[capture] 已登录,落地:', page.url());

  // 行动卡:从咨询列表点击应急会话行,从导航后的 URL 拿路径
  await page.goto(`${CONFIG.BASE}/consult`, { waitUntil: 'networkidle0' });
  await settle(page, 1200);
  const actionHref = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('button.list-row, a.list-row')];
    for (const r of rows) {
      const t = r.textContent || '';
      if (t.includes('应急') || t.includes('现场')) {
        // button.list-row 的点击导航由 React Router 处理,记录其文本供后续点击
        return t.slice(0, 20);
      }
    }
    return null;
  });
  let actionPath = null;
  if (actionHref) {
    // 点击该行,等导航,读 URL
    const rows = await page.$$('button.list-row, a.list-row');
    for (const r of rows) {
      const t = await r.evaluate((el) => el.textContent || '');
      if (t.includes('应急') || t.includes('现场')) {
        await r.click();
        await settle(page, 2000);
        actionPath = new URL(page.url()).pathname;
        break;
      }
    }
  }
  console.log('[capture] 行动卡会话:', actionHref || '(未找到,跳过)');

  const layout = {};

  for (const p of CONFIG.PAGES) {
    console.log(`[capture] ${p.name}: ${p.path}`);
    await page.goto(`${CONFIG.BASE}${p.path}`, { waitUntil: 'networkidle0' });
    await settle(page, CONFIG.SETTLE_MS + (p.waitMs || 0));

    await page.screenshot({
      path: path.join(CONFIG.OUT_DIR, `${p.name}@2x.png`),
      fullPage: true,
    });

    const pageLayout = {
      pageH: await page.evaluate(() => document.body.scrollHeight),
      boxes: {},
      cutouts: {},
    };

    for (const b of p.boxes || []) {
      const els = await page.$$(b.selector);
      const bboxes = [];
      for (const el of els) {
        const box = await el.boundingBox();
        if (box) bboxes.push({ x: box.x, y: box.y, w: box.width, h: box.height });
      }
      pageLayout.boxes[b.key] = b.all ? bboxes : bboxes[0] || null;
    }

    for (const c of p.cutouts || []) {
      const els = await page.$$(c.selector);
      const list = c.all ? els.slice(0, c.max || 10) : els.slice(0, 1);
      const infos = [];
      for (let i = 0; i < list.length; i++) {
        const name = c.all ? `${c.name}${i + 1}` : c.name;
        try {
          await list[i].screenshot({
            path: path.join(CONFIG.OUT_DIR, `${name}.png`),
            omitBackground: true,
          });
          const box = await list[i].boundingBox();
          if (box) infos.push({ name, x: box.x, y: box.y, w: box.width, h: box.height });
        } catch (e) {
          console.warn(`  [warn] cutout ${name}: ${e.message.slice(0, 80)}`);
        }
      }
      pageLayout.cutouts[c.name] = c.all ? infos : infos[0] || null;
    }

    layout[p.name] = pageLayout;
  }

  // 行动卡单独处理(动态路径,从点击导航后的 URL 获得)
  if (actionPath) {
    console.log(`[capture] action-card: ${actionPath}`);
    await page.goto(`${CONFIG.BASE}${actionPath}`, { waitUntil: 'networkidle0' });
    await settle(page, 2500);
    await page.screenshot({
      path: path.join(CONFIG.OUT_DIR, 'action-card@2x.png'),
      fullPage: true,
    });
    layout['action-card'] = {
      pageH: await page.evaluate(() => document.body.scrollHeight),
      boxes: {},
      cutouts: {},
    };
    // 三档标注/来源行/编号块——按实际类名尝试
    for (const [name, sel] of [
      ['risk-triple', '[class*="risk"], [class*="badge"]'],
      ['source-line', '[class*="source"], [class*="citation"]'],
      ['action-block', '[class*="block"], [class*="section"]'],
    ]) {
      const els = await page.$$(sel);
      if (els.length) {
        try {
          await els[0].screenshot({
            path: path.join(CONFIG.OUT_DIR, `${name}.png`),
            omitBackground: true,
          });
          const box = await els[0].boundingBox();
          if (box) layout['action-card'].cutouts[name] = { name, x: box.x, y: box.y, w: box.width, h: box.height };
        } catch (e) {
          console.warn(`  [warn] ${name}: ${e.message.slice(0, 80)}`);
        }
      }
    }
  }

  fs.writeFileSync(CONFIG.LAYOUT_JSON, JSON.stringify(layout, null, 2));
  console.log('[capture] 完成,layout.json 已写出');
  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
