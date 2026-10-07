/**
 * 模块: src/features/accounts/LoginPage.test
 * 职责: 登录/注册页的组件用例——对照页面设计「状态覆盖」表逐格
 * 数据来源:
 *   - docs/design/pages/登录与注册.md: MUST — 状态覆盖表
 *     （untouched / invalid-after-touched / submitting / server-error / 限流触发）
 *   - docs/design/pages/登录与注册.md: MUST — 响应式与平台节（表单可粘贴、autocomplete 语义）
 * 边界:
 *   - 依赖: features/accounts/view/LoginPage、viewModel/sessionStore、react-router 的内存路由
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言守卫等于授权
 *   - 禁止用真实 SDK（端口以替身注入；真实 SDK 的映射由 authPort.test 覆盖）
 *
 * 为什么用 fireEvent 而不是 @testing-library/user-event：本包未安装 user-event，
 * 而任务包禁止引入与本次任务无关的依赖（项目 AGENTS.md 的依赖纪律）。
 * fireEvent 的 change/blur/submit 足够驱动本页的全部状态。
 * 同理不使用 jest-dom 匹配器（未安装），禁用态用原生 disabled 属性断言。
 *
 * 为什么路由用 MemoryRouter + useRoutes 而不是 createMemoryRouter：T09 实测
 * jsdom 与 data router 不兼容——createMemoryRouter 在 jsdom 下构造 Request 抛
 * AbortSignal 类身份错误（jsdom vs Node undici 不同源）。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

import { LoginPage } from './LoginPage';
import type { AuthPort } from '../application/ports';
import { AuthError } from '../domain/authFailure';
import { useSessionStore } from '../viewModel/sessionStore';
import { deferred } from '../../../test/deferred';

/** 构造一个可控的认证端口替身。 */
function port(overrides: Partial<AuthPort> = {}): AuthPort {
  return {
    doesSessionExist: vi.fn(async () => false),
    signOut: vi.fn(async () => undefined),
    submitLogin: vi.fn(async () => ({ accountName: '阿澈的妈妈' })),
    submitRegister: vi.fn(async () => ({ accountName: '阿澈的妈妈' })),
    ...overrides,
  };
}

/** 渲染登录页。 */
function renderLogin(auth: AuthPort) {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <LoginPage auth={auth} />
    </MemoryRouter>,
  );
}

/** 取值并断言是 input；避免在每个用例里重复 as HTMLInputElement。 */
function input(label: string): HTMLInputElement {
  const element = screen.getByLabelText(label);
  if (!(element instanceof HTMLInputElement)) throw new Error(`标签「${label}」不是 input`);
  return element;
}

/** 按标签写值（fireEvent.change 对受控输入等价于一次完整输入 + input 事件）。 */
function type(label: string, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

/** 触发 blur（fireEvent.blur 与真实失焦在 React 事件系统里同路）。 */
function blur(label: string): void {
  fireEvent.blur(screen.getByLabelText(label));
}

/** 提交表单（走 form 的 submit 事件，与点击提交按钮同路）。 */
function submitForm(): void {
  const form = screen.getByRole('button', { name: /登录$|正在登录…/ }).closest('form');
  if (form === null) throw new Error('提交按钮不在 form 内');
  fireEvent.submit(form);
}

beforeEach(() => {
  useSessionStore.setState({ session: { status: 'anonymous' }, account: null });
});

describe('登录页 · untouched', () => {
  it('P0 初始态不显示任何字段错误，也不带 aria-invalid', () => {
    renderLogin(port());

    expect(screen.queryByText('请填写账号名')).toBeNull();
    expect(screen.queryByText('请填写密码')).toBeNull();
    expect(input('账号名').getAttribute('aria-invalid')).toBe('false');
    expect(input('密码').getAttribute('aria-invalid')).toBe('false');
  });

  it('P0 登录态没有邀请码字段，也不出现邮箱字段（AC-16 反向）', () => {
    renderLogin(port());

    expect(screen.queryByLabelText('邀请码')).toBeNull();
    expect(screen.queryByLabelText(/邮箱/)).toBeNull();
  });

  it('P0 登录态渲染品牌区与表单区（页面设计的两个区块）', () => {
    renderLogin(port());

    expect(screen.getByRole('heading', { name: '篝火智答', level: 1 })).toBeDefined();
    expect(screen.getByText('每一次咨询，都有据可依')).toBeDefined();
    expect(screen.getByRole('button', { name: '登录' })).toBeDefined();
  });
});

describe('登录页 · invalid-after-touched', () => {
  it('P0 blur 空账号名 → 内联错误 + aria-invalid + role=alert', () => {
    renderLogin(port());

    blur('账号名');

    const error = screen.getByText('请填写账号名');
    expect(error.getAttribute('role')).toBe('alert');
    expect(input('账号名').getAttribute('aria-invalid')).toBe('true');
  });

  it('P0 blur 短密码 → 密码规则错误', () => {
    renderLogin(port());

    type('密码', 'abc');
    blur('密码');

    expect(screen.getByText('密码至少 8 位，且同时包含字母与数字')).toBeDefined();
  });

  it('P0 校验错误的出现不带任何动画类（错误是信息不是表演）', () => {
    renderLogin(port());

    blur('账号名');

    const errorNode = screen.getByText('请填写账号名');
    expect(errorNode.className).not.toMatch(/anim|fade|transition/i);
  });

  it('P1 touched 后按 input 即时恢复校验（先 blur 报错，再输入合法值错误消失）', async () => {
    renderLogin(port());

    blur('账号名');
    expect(screen.getByText('请填写账号名')).toBeDefined();

    type('账号名', '阿澈的妈妈');

    await waitFor(() => {
      expect(screen.queryByText('请填写账号名')).toBeNull();
    });
  });

  it('P0 已经错误时继续输入仍非法 → 错误文案保持（不是只校验一次）', () => {
    renderLogin(port());

    type('密码', 'abc');
    blur('密码');
    expect(screen.getByText('密码至少 8 位，且同时包含字母与数字')).toBeDefined();

    type('密码', 'abcdefgh');
    expect(screen.getByText('密码至少 8 位，且同时包含字母与数字')).toBeDefined();
  });

  it('P1 未触碰的字段即使有错也不显示（untouched 无红色）', () => {
    renderLogin(port());

    // 两个字段都是空的，但一个都没 blur 过，因此不该出现任何错误文案。
    expect(screen.queryByText('请填写账号名')).toBeNull();
    expect(screen.queryByText('请填写密码')).toBeNull();
  });

  it('P1 字段有错时通过 aria-describedby 指向错误节点（可达性）', () => {
    renderLogin(port());

    blur('账号名');

    expect(input('账号名').getAttribute('aria-describedby')).toBe('auth-account-error');
    expect(screen.getByText('请填写账号名').id).toBe('auth-account-error');
  });
});

describe('登录页 · submitting', () => {
  it('P0 提交中按钮文字换「正在登录…」且 disabled，字段锁定', async () => {
    const gate = deferred<{ accountName: string | null }>();
    renderLogin(port({ submitLogin: vi.fn(() => gate.promise) }));

    type('账号名', '阿澈的妈妈');
    type('密码', 'campfire2026');
    submitForm();

    const button = await screen.findByRole('button', { name: '正在登录…' });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(input('账号名').disabled).toBe(true);
    expect(input('密码').disabled).toBe(true);

    // 让挂起的提交落地并等它渲染完：不留未决状态更新，否则测试结束后 React 会
    // 报 act() 警告，而那种警告会掩盖真实的竞态问题。
    gate.resolve({ accountName: '阿澈的妈妈' });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '登录' })).toBeDefined();
    });
  });

  it('P0 提交中通过礼貌 live region 公告「正在登录…」', async () => {
    const gate = deferred<{ accountName: string | null }>();
    renderLogin(port({ submitLogin: vi.fn(() => gate.promise) }));

    type('账号名', '阿澈的妈妈');
    type('密码', 'campfire2026');
    submitForm();

    const status = await screen.findByRole('status');
    expect(status.textContent).toBe('正在登录…');

    gate.resolve({ accountName: '阿澈的妈妈' });
    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toBe('');
    });
  });

  it('P1 并发闸门在动作函数体内：提交中再次提交不发起第二次请求', async () => {
    const submitLogin = vi.fn(() => deferred<{ accountName: string | null }>().promise);
    renderLogin(port({ submitLogin }));

    type('账号名', '阿澈的妈妈');
    type('密码', 'campfire2026');
    submitForm();
    // 再触发一次 submit（模拟 Enter 键连按 / 程序化提交，绕过按钮 disabled）。
    submitForm();

    await waitFor(() => {
      expect(submitLogin).toHaveBeenCalledTimes(1);
    });
    // 用例结束时提交仍在挂起：jsdom 会连同未决 Promise 一起销毁，不产生 act 警告；
    // 这里刻意不 resolve，因为要断言的是「第二次提交根本没有调用端口」。
  });
});

describe('登录页 · server-error', () => {
  it('P0 凭据错误 → 横幅显示「账号名或密码不正确」，输入内容保留', async () => {
    renderLogin(port({ submitLogin: vi.fn(async () => Promise.reject(new AuthError('invalid-credentials'))) }));

    type('账号名', '阿澈的妈妈');
    type('密码', 'campfire2026');
    submitForm();

    expect(await screen.findByText('账号名或密码不正确')).toBeDefined();
    // 保留已输入内容：失败不清空（状态覆盖表 server-error 行）。
    expect(input('账号名').value).toBe('阿澈的妈妈');
    expect(input('密码').value).toBe('campfire2026');
  });

  it('P0 服务不可用 → 不把它说成「密码不正确」', async () => {
    renderLogin(port({ submitLogin: vi.fn(async () => Promise.reject(new AuthError('service-unavailable'))) }));

    type('账号名', '阿澈的妈妈');
    type('密码', 'campfire2026');
    submitForm();

    expect(await screen.findByText('服务暂时不可用，请稍后再试')).toBeDefined();
    expect(screen.queryByText('账号名或密码不正确')).toBeNull();
  });

  it('P0 提交前不满足校验 → 不发起请求，只呈现字段错误', async () => {
    const submitLogin = vi.fn(async () => ({ accountName: null }));
    renderLogin(port({ submitLogin }));

    submitForm();

    expect(await screen.findByText('请填写账号名')).toBeDefined();
    expect(submitLogin).not.toHaveBeenCalled();
  });

  it('P1 错误横幅带 role=alert（屏幕阅读器即时可闻）', async () => {
    renderLogin(port({ submitLogin: vi.fn(async () => Promise.reject(new AuthError('invalid-credentials'))) }));

    type('账号名', '阿澈的妈妈');
    type('密码', 'campfire2026');
    submitForm();

    // 按文本定位到横幅再查它的 alert 语义：页面上另有空的字段级 role="alert" 容器
    // （契约里 .field-error 的固定形态），因此不能笼统地 getByRole('alert')。
    const message = await screen.findByText('账号名或密码不正确');
    const banner = message.closest('.error-card');
    expect(banner).not.toBeNull();
    expect(banner?.getAttribute('role')).toBe('alert');
    // 设计第 46 行的「紧凑变体」= 契约的 .error-card.form-feedback（不是整块错误态）。
    expect(banner?.classList.contains('form-feedback')).toBe(true);
  });
});

describe('登录页 · 限流触发', () => {
  it('P0 429 → 同 server-error 形态，文案「尝试次数过多，请稍后再试」', async () => {
    renderLogin(port({ submitLogin: vi.fn(async () => Promise.reject(new AuthError('rate-limited'))) }));

    type('账号名', '阿澈的妈妈');
    type('密码', 'campfire2026');
    submitForm();

    const message = await screen.findByText('尝试次数过多，请稍后再试');
    // 与 server-error 同形态：同一个错误卡容器（不新增一种横幅）。
    expect(message.closest('.error-card')).not.toBeNull();
  });

  it('P0 限流文案不暴露阈值与计数逻辑', async () => {
    renderLogin(port({ submitLogin: vi.fn(async () => Promise.reject(new AuthError('rate-limited'))) }));

    type('账号名', '阿澈的妈妈');
    type('密码', 'campfire2026');
    submitForm();

    const message = await screen.findByText('尝试次数过多，请稍后再试');
    expect(message.textContent).toBe('尝试次数过多，请稍后再试');
    expect(message.textContent).not.toMatch(/\d/);
  });
});

describe('登录页 · 注册态与可达性', () => {
  it('P0 切到注册态出现邀请码字段与 hint，且无邮箱字段', () => {
    renderLogin(port());

    fireEvent.click(screen.getByRole('button', { name: '已有邀请码？注册账号' }));

    expect(screen.getByLabelText('邀请码')).toBeDefined();
    expect(screen.getByText('邀请码由运营者发放，8 位、一次性使用')).toBeDefined();
    expect(screen.queryByLabelText(/邮箱/)).toBeNull();
  });

  it('P0 注册失败 → 「邀请码无效或已被使用」逐字呈现', async () => {
    renderLogin(port({ submitRegister: vi.fn(async () => Promise.reject(new AuthError('invite-rejected'))) }));

    fireEvent.click(screen.getByRole('button', { name: '已有邀请码？注册账号' }));
    type('账号名', 'acct');
    type('密码', 'campfire2026');
    type('邀请码', 'A1B2C3D4');
    fireEvent.click(screen.getByRole('button', { name: '注册' }));

    expect(await screen.findByText('邀请码无效或已被使用')).toBeDefined();
  });

  it('P0 注册态空邀请码 → 字段错误「请填写邀请码」', async () => {
    renderLogin(port());

    fireEvent.click(screen.getByRole('button', { name: '已有邀请码？注册账号' }));
    type('账号名', 'acct');
    type('密码', 'campfire2026');
    fireEvent.click(screen.getByRole('button', { name: '注册' }));

    expect(await screen.findByText('请填写邀请码')).toBeDefined();
  });

  it('P0 密码字段不阻止粘贴（WCAG 3.3.8 可达认证）', () => {
    renderLogin(port());

    const password = input('密码');
    // 断言的是「没有阻止默认粘贴行为」这件事本身，而不是「值被写进去了」——
    // 后者在 fireEvent 下恒成立，无法证伪任一实现。
    const pasteEvent = new Event('paste', { bubbles: true, cancelable: true });
    password.dispatchEvent(pasteEvent);

    expect(pasteEvent.defaultPrevented).toBe(false);
  });

  it('P0 autocomplete 语义：登录态用 username / current-password', () => {
    renderLogin(port());

    expect(input('账号名').getAttribute('autocomplete')).toBe('username');
    expect(input('密码').getAttribute('autocomplete')).toBe('current-password');
  });

  it('P0 autocomplete 语义：注册态密码改用 new-password，邀请码不回填', () => {
    renderLogin(port());

    fireEvent.click(screen.getByRole('button', { name: '已有邀请码？注册账号' }));

    expect(input('密码').getAttribute('autocomplete')).toBe('new-password');
    expect(input('邀请码').getAttribute('autocomplete')).toBe('off');
  });

  it('P0 显示密码切换只影响输入类型（视觉状态归 view 内部）', () => {
    renderLogin(port());

    expect(input('密码').getAttribute('type')).toBe('password');

    fireEvent.click(screen.getByRole('button', { name: '显示密码' }));

    expect(input('密码').getAttribute('type')).toBe('text');
    expect(screen.getByRole('button', { name: '隐藏密码' })).toBeDefined();
  });

  it('P0 不出现自助找回入口（一期无邮箱即无自助通道）', () => {
    renderLogin(port());

    // 正向那句「忘记密码？请联系运营者人工重置」的归属是设置页（设置页设计第 25 行），
    // 由 SettingsPage.test 逐字守；登录页设计只列三个区块，故本页不再渲染它，这里只守反向：
    // 不得出现「找回密码」这类假入口（断言按按钮/链接角色与「找回」字样查）。
    expect(screen.queryByRole('button', { name: /找回/ })).toBeNull();
    expect(screen.queryByRole('link', { name: /找回/ })).toBeNull();
  });
});

describe('登录页 · 提交成功后写入会话 store', () => {
  it('P0 成功 → 会话标为已登录并记下账号名', async () => {
    renderLogin(port());

    type('账号名', '阿澈的妈妈');
    type('密码', 'campfire2026');
    submitForm();

    await waitFor(() => {
      expect(useSessionStore.getState().session.status).toBe('authenticated');
    });
    expect(useSessionStore.getState().account).toEqual({ accountName: '阿澈的妈妈' });
  });
});
