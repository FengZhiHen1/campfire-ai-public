// 元素坐标实测:对每个需要用到的页面状态,实测关键元素在 viewport(390×844)中的精确 bbox。
// 输出 layout-states.json,组件按实测坐标定位,不再估算。
import puppeteer from 'puppeteer';
import { captureAccount } from './account.mjs';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, '../public/textures/states');
const LAYOUT = path.resolve(__dirname, '../src/layout-states.json');
const BASE = 'http://localhost:5174';
const ACCOUNT = captureAccount();
const SESSION_ID = 'b897534e95b74aa99fdf23fe535248d7';

async function settle(page, ms = 700) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

// 实测元素 bbox(viewport 坐标)
async function bbox(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
  }, selector);
}

// 按文本内容找元素并实测 bbox
// 关键:只取「文本的直接承载者」——要求该元素的直接子节点里有文本节点,
// 避免匹配到包含该文本的最外层容器(否则返回 body 尺寸,是早先坐标错位的根因)。
async function bboxByText(page, text, opts = {}) {
  return page.evaluate(
    ({ t, exact }) => {
      const all = [...document.querySelectorAll('*')];
      const cands = [];
      for (const el of all) {
        const own = (el.textContent || '').trim();
        const hit = exact ? own === t : own.includes(t);
        if (!hit) continue;
        // 该元素必须直接承载文本节点
        const hasDirectText = [...el.childNodes].some(
          (n) => n.nodeType === 3 && (n.textContent || '').trim().length > 0,
        );
        if (!hasDirectText) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 8 || r.height < 8) continue;
        cands.push({
          x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
          area: r.width * r.height,
        });
      }
      if (!cands.length) return null;
      // 取面积最小的(最贴近文本本身的元素)
      cands.sort((a, b) => a.area - b.area);
      const { x, y, w, h } = cands[0];
      return { x, y, w, h };
    },
    { t: text, exact: opts.exact || false },
  );
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ headless: true, protocolTimeout: 120000 });
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });
  const layout = {};

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

  // ── 首页:应急入口 ──
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle0' });
  await settle(page, 1200);
  layout.home = {
    emergency: (await bbox(page, 'article.emergency-entry')) || (await bboxByText(page, '现在需要帮助', { maxDepth: 4 })),
    daily: await bbox(page, 'a.daily-entry'),
    tabbar: await bbox(page, 'nav'),
  };

  // ── 档案页:待确认条目 ──
  await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle0' });
  await settle(page, 1500);
  layout.profile = {
    pendingGroup: await bboxByText(page, '待确认', { maxDepth: 3 }),
    pendingItem: await bbox(page, 'article.candidate-record'),
    pendingItemByText: await bboxByText(page, 'AI 归纳', { maxDepth: 6 }),
    firstConfirmed: await bbox(page, 'article.list-row:not(.candidate-record)'),
  };
  await shot(page, 'profile-top');

  // ── 案例库:虚构样例标签 ──
  await page.goto(`${BASE}/cases`, { waitUntil: 'networkidle0' });
  await settle(page, 1500);
  layout.cases = {
    fictionalTag: await bboxByText(page, '虚构样例', { exact: true, maxDepth: 2 }),
    firstCase: await bbox(page, 'article.list-row'),
    sectionHead: await bboxByText(page, '案例与资料', { maxDepth: 3 }),
  };
  await shot(page, 'cases-top');

  // ── 会话页:展开所有折叠区,实测过程链 ──
  await page.goto(`${BASE}/consult/sessions/${SESSION_ID}`, { waitUntil: 'networkidle0' });
  await settle(page, 2500);

  // 全部展开「展开」按钮
  const expandCount = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')].filter((b) => (b.textContent || '').trim() === '展开');
    btns.forEach((b) => b.click());
    return btns.length;
  });
  await settle(page, 2500);
  console.log('展开按钮数:', expandCount);

  // 过程链区(思考过程/查阅资料/查阅案例)
  layout.session = {
    thinkingRow: await bboxByText(page, '思考过程', { maxDepth: 4 }),
    resourceRow: await bboxByText(page, '查阅资料', { maxDepth: 4 }),
    caseRow: await bboxByText(page, '查阅案例', { maxDepth: 4 }),
    actionCardRow: await bboxByText(page, '生成行动卡', { maxDepth: 4 }),
    skillRow: await bboxByText(page, '启用技能', { maxDepth: 4 }),
  };
  // 截当前(展开后)的屏
  await page.evaluate(() => window.scrollTo(0, 0));
  await settle(page, 800);
  await shot(page, 'session-expanded-top');
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await settle(page, 900);
  await shot(page, 'session-expanded-bottom');

  // 滚到「思考过程」区
  const scrolled = await page.evaluate(() => {
    const all = [...document.querySelectorAll('*')];
    for (const el of all) {
      if ((el.textContent || '').includes('思考过程') && el.children.length < 6) {
        el.scrollIntoView({ block: 'start', behavior: 'instant' });
        return true;
      }
    }
    return false;
  });
  if (scrolled) {
    await settle(page, 900);
    await shot(page, 'session-thinking');
    layout.session.thinking = await bboxByText(page, '思考过程', { maxDepth: 4 });
  }

  // 滚到「医疗风险」区
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('*')];
    for (const el of all) {
      if ((el.textContent || '').includes('医疗风险') && el.children.length < 10 && el.offsetHeight < 600) {
        el.scrollIntoView({ block: 'start', behavior: 'instant' });
        return;
      }
    }
  });
  await settle(page, 900);
  await shot(page, 'session-risk');
  layout.session.risk = await bboxByText(page, '医疗风险', { maxDepth: 6 });
  layout.session.riskLine = await bboxByText(page, '来源:现场观察', { maxDepth: 4 });

  // 滚到「02 立即怎么沟通」
  await page.evaluate(() => {
    const all = [...document.querySelectorAll('*')];
    for (const el of all) {
      if ((el.textContent || '').includes('立即怎么沟通') && el.children.length < 4) {
        el.scrollIntoView({ block: 'start', behavior: 'instant' });
        return;
      }
    }
  });
  await settle(page, 900);
  await shot(page, 'session-advice');
  layout.session.adviceHead = await bboxByText(page, '立即怎么沟通', { maxDepth: 4 });

  // ── 应急表单:第 1 题与第 4 题的题干位置 ──
  await page.goto(`${BASE}/consult/emergency`, { waitUntil: 'networkidle0' });
  await settle(page, 1500);
  layout.emergency = {
    progress: await bbox(page, '.progress-track'),
    questionCard: await bbox(page, 'section.tile'),
    q1Text: await bboxByText(page, '第 1 / 8 题', { maxDepth: 4 }),
  };
  await shot(page, 'emergency-q1');

  fs.writeFileSync(LAYOUT, JSON.stringify(layout, null, 2));
  console.log('\n=== 实测坐标 ===');
  console.log(JSON.stringify(layout, null, 2));
  console.log('\nlayout-states.json 已写出');
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
