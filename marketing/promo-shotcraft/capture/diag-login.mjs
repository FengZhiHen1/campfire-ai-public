// 诊断登录流程:逐步截图 + 打印每步状态,找出失败点。
import puppeteer from 'puppeteer';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, '../out/diag');
const BASE = 'http://localhost:5174';
const ACCOUNT = { name: 'demo-parent', password: 'Demo#2026campfire' };

async function main() {
  const browser = await puppeteer.launch({ headless: true, protocolTimeout: 120000 });
  const page = await browser.newPage();
  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2 });

  // 捕获网络请求与响应
  const reqs = [];
  page.on('response', async (res) => {
    const url = res.url();
    if (url.includes('/auth') || url.includes('/api') || url.includes('login') || url.includes('signin')) {
      let body = '';
      try { body = (await res.text()).slice(0, 200); } catch { body = '(unreadable)'; }
      reqs.push({ status: res.status(), url: url.slice(0, 90), body });
    }
  });
  page.on('console', (m) => {
    if (m.type() === 'error') console.log('[console error]', m.text().slice(0, 160));
  });

  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle0' });
  await new Promise((r) => setTimeout(r, 1200));
  await page.screenshot({ path: path.join(OUT, '01-login.png') });

  // 打印表单结构
  const form = await page.evaluate(() => {
    const inputs = [...document.querySelectorAll('input')].map((i) => ({
      type: i.type, name: i.name, id: i.id, placeholder: i.placeholder,
    }));
    const btns = [...document.querySelectorAll('button')].map((b) => ({
      type: b.type, txt: (b.textContent || '').trim().slice(0, 20),
    }));
    return { inputs, btns };
  });
  console.log('表单 inputs:', JSON.stringify(form.inputs));
  console.log('表单 buttons:', JSON.stringify(form.btns));

  // 填表
  const inputs = await page.$$('input');
  await inputs[0].type(ACCOUNT.name);
  await inputs[1].type(ACCOUNT.password);
  await page.screenshot({ path: path.join(OUT, '02-filled.png') });

  // 提交
  const clicked = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('button')];
    const b = btns.find((x) => (x.textContent || '').trim() === '登录' && x.type === 'submit')
      || btns.find((x) => (x.textContent || '').trim() === '登录');
    if (b) { b.click(); return true; }
    return false;
  });
  console.log('点击登录按钮:', clicked);

  await new Promise((r) => setTimeout(r, 4000));
  console.log('提交后 URL:', page.url());
  await page.screenshot({ path: path.join(OUT, '03-after.png') });

  // 页面上的错误提示
  const err = await page.evaluate(() => {
    const el = document.querySelector('[class*="error"], [role="alert"], .error-card');
    return el ? (el.textContent || '').trim().slice(0, 160) : null;
  });
  console.log('错误提示:', err);

  console.log('\n--- 网络请求 ---');
  for (const r of reqs) console.log(`  ${r.status} ${r.url} | ${r.body?.slice(0, 120)}`);

  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
