// 5xx 可达性侦查（纯 node，用内置 fetch）：真注册拿会话 cookie，再对已登录端点发一批
// 畸形载荷，看有没有真 5xx。用途：T11 第 3 条要断言「5xx 数为 0」，那条判据必须能红；
// 要能红就得先存在一条「浏览器真能拿到 5xx」的路径。本脚本只侦查，不判定。
// Vite dev server 在本机只监听 `::1`（实测 `Get-NetTCPConnection` 的 LocalAddress=::1），
// 因此 127.0.0.1 连不上；用 localhost（解析到 ::1）与探针的 T10_BASE_URL 一致。
const BASE = 'http://localhost:5173';

let cookieHeader = '';

async function call(method, path, body) {
  const init = { method, headers: { 'Content-Type': 'application/json' } };
  if (cookieHeader !== '') init.headers.Cookie = cookieHeader;
  if (body !== null) init.body = body;
  const response = await fetch(BASE + path, init);
  for (const raw of response.headers.getSetCookie()) {
    const [pair] = raw.split(';');
    const [name] = pair.split('=');
    if (cookieHeader.includes(`${name}=`)) {
      cookieHeader = cookieHeader
        .split('; ')
        .map((c) => (c.startsWith(`${name}=`) ? pair : c))
        .join('; ');
    } else {
      cookieHeader = cookieHeader === '' ? pair : `${cookieHeader}; ${pair}`;
    }
  }
  const text = await response.text();
  return { status: response.status, text: text.slice(0, 120) };
}

(async () => {
  const up = await call('POST', '/api/auth/signup', JSON.stringify({
    formFields: [
      { id: 'email', value: `t11-fuzz-${Date.now()}@example.test` },
      { id: 'password', value: 'aaa11111' },
      { id: 'inviteCode', value: process.env.T11_INVITE },
    ],
  }));
  console.log('SIGNUP', up.status, up.text.slice(0, 80));
  console.log('COOKIES', cookieHeader.split('; ').map((c) => c.split('=')[0]).join(','));

  const UUID = '11111111-2222-3333-4444-555555555555';
  const CASES = [
    ['GET', '/api/consult/sessions', null],
    ['GET', '/api/memory/episodes?cursor=999999999999999999999999', null],
    ['GET', '/api/memory/episodes?cursor=' + '9'.repeat(300), null],
    ['GET', '/api/memory/episodes?since=notatime', null],
    ['DELETE', '/api/memory/episodes/' + UUID, null],
    ['POST', `/api/memory/episodes/${UUID}/correct`, '{}'],
    ['POST', `/api/memory/episodes/${UUID}/correct`, '{"occurred_at":"2026-01-01T00:00:00+00:00","content":""}'],
    ['POST', `/api/memory/episodes/${UUID}/correct`, '{"occurred_at":"bad","content":"x"}'],
    ['GET', '/api/profile/objects', null],
    ['POST', '/api/profile/objects', '{}'],
    ['POST', '/api/profile/objects', '{"display_name":123}'],
    ['PATCH', `/api/profile/objects/${UUID}`, '{}'],
    ['PATCH', `/api/profile/objects/${UUID}`, '{"display_name":null}'],
    ['GET', `/api/profile/objects/${UUID}/summary`, null],
    ['GET', `/api/profile/objects/${UUID}/items`, null],
    ['GET', `/api/profile/objects/${UUID}/items?include_candidates=maybe`, null],
    ['POST', `/api/profile/objects/${UUID}/items`, '{}'],
    ['POST', '/api/profile/items/' + UUID + '/confirm', '{}'],
    ['POST', '/api/profile/items/' + UUID + '/correct', '{}'],
    ['DELETE', '/api/profile/items/' + UUID, null],
    ['POST', `/api/consult/sessions/${UUID}/messages`, '{}'],
    ['POST', `/api/consult/sessions/${UUID}/messages`, '{"content":"x"}'],
    ['GET', `/api/consult/sessions/${UUID}/messages`, null],
    ['GET', `/api/consult/runs/${UUID}/stream`, null],
    ['POST', `/api/consult/runs/${UUID}/cancel`, null],
    ['POST', '/api/consult/emergency', '{}'],
    ['POST', '/api/consult/emergency', `{"object_id":"${UUID}"}`],
    ['POST', `/api/consult/sessions/${UUID}/onboarding/skip`, null],
    ['GET', '/api/library/knowledge?limit=abc', null],
    ['GET', '/api/library/knowledge?limit=-5', null],
    ['GET', '/api/library/cases?limit=999999', null],
    ['GET', '/api/library/knowledge?query=' + 'x'.repeat(20000), null],
    ['POST', '/api/auth/signin', '{"formFields":[{"id":"email","value":"x"},{"id":"password","value":null}]}'],
    ['POST', '/api/auth/signup', '{"formFields":{"id":"email"}}'],
    ['POST', '/api/auth/session/refresh', 'garbage'],
  ];

  const hits = [];
  for (const [method, path, body] of CASES) {
    let result;
    try {
      result = await call(method, path, body);
    } catch (error) {
      result = { status: -1, text: String(error).slice(0, 120) };
    }
    console.log(`${String(result.status).padStart(4)} ${method.padEnd(6)} ${path.slice(0, 58)}${result.status >= 500 ? '  <== 5xx' : ''}`);
    if (result.status >= 500) hits.push({ method, path, status: result.status, text: result.text });
  }
  console.log('HITS_5XX', JSON.stringify(hits, null, 1));
})();
