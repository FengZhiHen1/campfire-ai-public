// 跑一次真实应急咨询,采「有档案」场景的真实输出。
// 条件(已核实):
//   - demo-parent 有对象「小满」,5 条 confirmed 档案(sensory/communication/risk 与超市场景相关)
//   - 新会话会自动绑定对象(bound_at = created_at, Δ=0.0s) → 走 state="present" 预取路径
//   - 案例库有「虚构样例:超市感官过载情境的现场支持」→ 命中概率高
// 情境选择:超市 + 噪音/人群 + 疼痛可能 + 走失风险(与档案、案例库都对齐)
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, '../out/real-run');
const BASE = 'http://localhost:5174';
const ACCOUNT = { name: 'demo-parent', password: 'Demo#2026campfire' };

async function settle(page, ms = 900) {
  await page.evaluate(() => document.fonts.ready);
  await new Promise((r) => setTimeout(r, ms));
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ headless: true, protocolTimeout: 600000 });
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });

  // 登录
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle0' });
  await settle(page, 700);
  const inputs = await page.$$('input');
  await inputs[0].type(ACCOUNT.name);
  await inputs[1].type(ACCOUNT.password);
  for (const b of await page.$$('button')) {
    if ((await b.evaluate((el) => el.textContent || '')).includes('登')) { await b.click(); break; }
  }
  await settle(page, 2500);
  console.log('登录后:', page.url());

  // 选中小满对象(如果首页/档案页需要)
  await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle0' });
  await settle(page, 1500);
  // 点「小满」对象 chip 确保选中
  await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button, [role="button"]')];
    const b = btns.find((x) => (x.textContent || '').trim() === '小满');
    if (b) b.click();
  });
  await settle(page, 1000);
  console.log('已选中小满对象');

  // 进入应急
  await page.goto(`${BASE}/consult/emergency`, { waitUntil: 'networkidle0' });
  await settle(page, 1500);
  console.log('进入应急表单');

  // ── 逐题作答:选一个与档案/案例库对齐的情境 ──
  // 第1题 医疗危险(多选):选「明显疼痛」
  const answerPlan = [
    { q: 1, picks: ['明显疼痛'] },
    { q: 2, picks: ['明显'] },           // 与平时相比
    { q: 3, picks: ['下降'] },           // 沟通能力
    { q: 4, picks: ['强烈'] },           // 痛苦程度
    { q: 5, picks: ['噪音', '人群'] },   // 环境
    { q: 6, text: '在超市突然蹲下捂住耳朵,周围人多' }, // 自由文本
    { q: 7, picks: ['走失'] },           // 最大风险
    { q: 8, picks: ['是'] },             // 可能疼痛
  ];

  for (const step of answerPlan) {
    // 每次作答前截屏留档
    await page.screenshot({ path: path.join(OUT, `q${step.q}-before.png`) });

    // 勾选所有匹配的选项
    const clicked = await page.evaluate((picks) => {
      const done = [];
      const clickable = [...document.querySelectorAll('label, button, [role="button"], [class*="check"], [class*="choice"], [class*="option"]')];
      for (const p of picks) {
        for (const el of clickable) {
          const t = (el.textContent || '').trim();
          if (t === p || (t.length < 24 && t.includes(p))) {
            el.click();
            done.push(p);
            break;
          }
        }
      }
      return done;
    }, step.picks || []);
    if (step.picks) console.log(`  第${step.q}题 勾选: ${clicked.join(',') || '(未匹配!)'}`);

    // 自由文本
    if (step.text) {
      const filled = await page.evaluate((txt) => {
        const ta = document.querySelector('textarea');
        if (!ta) return false;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
        setter.call(ta, txt);
        ta.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
      }, step.text);
      console.log(`  第${step.q}题 文本: ${filled ? '已填' : '(无 textarea)'}`);
    }
    await settle(page, 500);

    // 点「下一题」;第 8 题(最后一题)改为点常驻的「提交,开始分析」
    const next = await page.evaluate((isLast) => {
      const btns = [...document.querySelectorAll('button')];
      const target = isLast
        ? btns.find((x) => (x.textContent || '').trim().startsWith('提交'))
        : btns.find((x) => (x.textContent || '').trim() === '下一题');
      if (target) { target.click(); return (target.textContent || '').trim(); }
      return null;
    }, step.q === 8);
    console.log(`  → 点击: ${next}`);
    await settle(page, 900);
    if (next && next.startsWith('提交')) break;
  }

  await page.screenshot({ path: path.join(OUT, 'after-submit.png') });
  console.log('提交后 URL:', page.url());

  // ── 等分析完成(最多 8 分钟) ──
  console.log('等待分析完成…');
  let done = false;
  for (let i = 0; i < 96; i++) {
    await settle(page, 5000);
    const state = await page.evaluate(() => {
      const t = document.body.innerText || '';
      return {
        hasCard: t.includes('行动建议') || t.includes('医疗风险'),
        analyzing: t.includes('正在分析') || t.includes('分析中'),
        bodyLen: t.length,
      };
    });
    if (i % 6 === 0) console.log(`  [${(i + 1) * 5}s] 分析中=${state.analyzing} 有行动卡=${state.hasCard}`);
    if (state.hasCard && !state.analyzing) { done = true; break; }
  }
  console.log('分析完成:', done);

  // 展开全部折叠区
  await page.evaluate(() => {
    [...document.querySelectorAll('button')]
      .filter((b) => (b.textContent || '').trim() === '展开')
      .forEach((b) => b.click());
  });
  await settle(page, 2500);

  await page.screenshot({ path: path.join(OUT, 'final-viewport.png') });
  // 保存 URL 供后续采集
  fs.writeFileSync(path.join(OUT, 'session-url.txt'), page.url());
  console.log('会话 URL:', page.url());

  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
