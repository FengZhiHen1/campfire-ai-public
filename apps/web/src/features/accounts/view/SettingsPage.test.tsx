/**
 * 模块: src/features/accounts/SettingsPage.test
 * 职责: 设置页的组件用例——硬文案逐字、记忆页入口、登出三态（submitting/失败保留上下文/成功回登录）
 * 数据来源:
 *   - docs/design/pages/设置页.md: MUST — 全文（硬文案、记忆入口行、状态覆盖表、动效与 token）
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 6 节（登出后清状态回登录页）
 * 边界:
 *   - 依赖: features/accounts/view/SettingsPage、viewModel/sessionStore、react-router 的内存路由
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止弱化一期边界硬文案（断言逐字，含 AC-10 反向声明）
 *   - 禁止断言存在「修改密码」入口（一期不存在，只能是如实说明）
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useRoutes } from 'react-router';

import { SettingsPage } from './SettingsPage';
import type { AuthPort } from '../application/ports';
import { AuthError } from '../domain/authFailure';
import { useSessionStore } from '../viewModel/sessionStore';

/** 一期边界硬文案（页面设计成稿，逐字；AC-10 的反向如实声明）。 */
const BOUNDARY_COPY =
  '本应用尚未经专业审阅，不能替代专业服务；遇到紧急医疗情况请直接就医或拨打急救电话。';

/** 构造一个可控的认证端口替身。 */
function port(overrides: Partial<AuthPort> = {}): AuthPort {
  return {
    doesSessionExist: vi.fn(async () => true),
    signOut: vi.fn(async () => undefined),
    submitLogin: vi.fn(async () => ({ accountName: null })),
    submitRegister: vi.fn(async () => ({ accountName: null })),
    ...overrides,
  };
}

/** 渲染设置页。 */
function renderSettings(auth: AuthPort) {
  return render(
    <MemoryRouter initialEntries={['/settings']}>
      <SettingsPage auth={auth} />
    </MemoryRouter>,
  );
}

/**
 * 渲染设置页 + 一个可观测的 /login 落点，用于断言登出后的跳转。
 *
 * 用 useRoutes 而不是 createMemoryRouter：T09 实测 data router 与 jsdom 不兼容。
 */
function renderSettingsWithLoginRoute(auth: AuthPort) {
  function Probed() {
    return useRoutes([
      { path: '/settings', element: <SettingsPage auth={auth} /> },
      { path: '/login', element: <h1>登录落点</h1> },
    ]);
  }
  return render(
    <MemoryRouter initialEntries={['/settings']}>
      <Probed />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useSessionStore.setState({ session: { status: 'authenticated' }, account: { accountName: '阿澈的妈妈' } });
});

describe('设置页 · 账号与说明卡', () => {
  it('P0 账号名来自会话 store', () => {
    renderSettings(port());

    expect(screen.getByRole('heading', { name: '阿澈的妈妈' })).toBeDefined();
    expect(screen.getByText('个人账号 · 邀请码注册')).toBeDefined();
  });

  it('P0 冷启动拿不到账号名 → 如实降级，不显示空白也不编造', () => {
    useSessionStore.setState({ session: { status: 'authenticated' }, account: null });
    renderSettings(port());

    expect(screen.getByRole('heading', { name: '账号名暂不可用' })).toBeDefined();
  });

  it('P0 「关于你的数据」三行要点逐字', () => {
    renderSettings(port());

    expect(screen.getByText('咨询记录怎么用')).toBeDefined();
    expect(screen.getByText('本次输入的内容用于生成回答，并按你的确认累积到档案与记忆')).toBeDefined();
    expect(screen.getByText('谁可见')).toBeDefined();
    expect(screen.getByText('只有你的账号可以看到；登录才能使用全部功能')).toBeDefined();
    expect(screen.getByText('会送去外部模型吗')).toBeDefined();
    expect(screen.getByText('咨询内容会发送给模型服务处理后返回')).toBeDefined();
  });

  it('P0 一期边界硬文案逐字呈现（AC-10 反向声明不得弱化）', () => {
    renderSettings(port());

    expect(screen.getByText(BOUNDARY_COPY)).toBeDefined();
  });

  it('P0 不出现专业认可或临床效果类表述', () => {
    const { container } = renderSettings(port());

    expect(container.textContent).not.toMatch(/专业认可|临床效果|零幻觉/);
  });

  it('P0 页面刻意零 accent（八页里只有设置页如此）', () => {
    const { container } = renderSettings(port());

    expect(container.querySelectorAll('.btn-primary')).toHaveLength(0);
    expect(container.querySelectorAll('.flame-dot')).toHaveLength(0);
  });

  it('P0 无版本号、关于我们与反馈入口（一期无此能力，不做空壳区块）', () => {
    renderSettings(port());

    expect(screen.queryByText(/版本/)).toBeNull();
    expect(screen.queryByText('关于我们')).toBeNull();
    expect(screen.queryByText(/反馈/)).toBeNull();
  });
});

describe('设置页 · 记忆页入口', () => {
  it('P0 入口行在「关于你的数据」卡内，指向 /settings/memory', () => {
    const { container } = renderSettings(port());

    const entry = screen.getByRole('link', { name: /我提过的事/ });
    expect(entry.getAttribute('href')).toBe('/settings/memory');
    expect(entry.className).toContain('list-row');
    // 入口必须在数据卡内部（记忆属账号，与「关于你的数据」同源）。
    expect(entry.closest('.tile')).toBe(container.querySelector('#settings-data')?.closest('.tile'));
  });

  it('P0 入口说明逐字', () => {
    renderSettings(port());

    expect(screen.getByText('看看系统记住了什么，可以纠正或删除')).toBeDefined();
  });
});

describe('设置页 · 无自助找回', () => {
  it('P0 如实呈现「请联系运营者人工重置」，且不放假的修改密码入口', () => {
    renderSettings(port());

    expect(screen.getByText('忘记密码？请联系运营者人工重置')).toBeDefined();
    expect(screen.queryByRole('button', { name: /修改密码/ })).toBeNull();
    expect(screen.queryByRole('link', { name: /修改密码/ })).toBeNull();
  });
});

describe('设置页 · 登出 · 未确认态', () => {
  it('P0 初始不渲染确认单', () => {
    renderSettings(port());

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('button', { name: '退出登录' })).toBeDefined();
  });
});

describe('设置页 · 登出 · 确认单', () => {
  it('P0 点击退出 → 弹确认单，文案逐字', () => {
    renderSettings(port());

    fireEvent.click(screen.getByRole('button', { name: '退出登录' }));

    expect(screen.getByRole('dialog')).toBeDefined();
    expect(screen.getByRole('heading', { name: '退出登录？' })).toBeDefined();
    expect(screen.getByText('退出后需要重新登录')).toBeDefined();
    expect(screen.getByRole('button', { name: '取消' })).toBeDefined();
  });

  it('P0 取消关闭确认单且不调用端口', () => {
    const auth = port();
    renderSettings(auth);

    fireEvent.click(screen.getByRole('button', { name: '退出登录' }));
    fireEvent.click(screen.getByRole('button', { name: '取消' }));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(auth.signOut).not.toHaveBeenCalled();
  });
});

describe('设置页 · 登出 · submitting', () => {
  it('P0 提交中按钮进入 loading（「正在退出…」+ disabled）', async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    renderSettings(port({ signOut: vi.fn(() => gate) }));

    fireEvent.click(screen.getByRole('button', { name: '退出登录' }));
    fireEvent.click(screen.getByRole('button', { name: '退出' }));

    const pending = await screen.findByRole('button', { name: '正在退出…' });
    expect((pending as HTMLButtonElement).disabled).toBe(true);
    // 提交中取消也不可用：避免用户以为取消掉了、实际登出仍在进行。
    expect((screen.getByRole('button', { name: '取消' }) as HTMLButtonElement).disabled).toBe(true);

    release();
  });
});

describe('设置页 · 登出 · 失败', () => {
  it('P0 登出失败 → sheet 内联错误 + 重试；sheet 不自动关闭', async () => {
    renderSettings(port({ signOut: vi.fn(async () => Promise.reject(new AuthError('service-unavailable'))) }));

    fireEvent.click(screen.getByRole('button', { name: '退出登录' }));
    fireEvent.click(screen.getByRole('button', { name: '退出' }));

    expect(await screen.findByText('服务暂时不可用，请稍后再试')).toBeDefined();
    // 保留操作上下文：sheet 仍在，且按钮变成「重试」（状态覆盖表）。
    expect(screen.getByRole('dialog')).toBeDefined();
    expect(screen.getByRole('button', { name: '重试' })).toBeDefined();
  });

  it('P0 登出失败不清本地会话（否则等于假装已登出）', async () => {
    renderSettings(port({ signOut: vi.fn(async () => Promise.reject(new AuthError('service-unavailable'))) }));

    fireEvent.click(screen.getByRole('button', { name: '退出登录' }));
    fireEvent.click(screen.getByRole('button', { name: '退出' }));

    await screen.findByText('服务暂时不可用，请稍后再试');
    expect(useSessionStore.getState().session.status).toBe('authenticated');
    expect(useSessionStore.getState().account).toEqual({ accountName: '阿澈的妈妈' });
  });

  it('P1 失败后重试成功 → 清会话并回登录页', async () => {
    const signOut = vi
      .fn<() => Promise<void>>()
      .mockRejectedValueOnce(new AuthError('service-unavailable'))
      .mockResolvedValueOnce(undefined);
    renderSettingsWithLoginRoute(port({ signOut }));

    fireEvent.click(screen.getByRole('button', { name: '退出登录' }));
    fireEvent.click(screen.getByRole('button', { name: '退出' }));
    await screen.findByRole('button', { name: '重试' });
    fireEvent.click(screen.getByRole('button', { name: '重试' }));

    expect(await screen.findByRole('heading', { name: '登录落点' })).toBeDefined();
    expect(useSessionStore.getState().session.status).toBe('anonymous');
    expect(useSessionStore.getState().account).toBeNull();
  });
});

describe('设置页 · 登出 · 成功', () => {
  it('P0 成功后清会话状态并转登录页', async () => {
    renderSettingsWithLoginRoute(port());

    fireEvent.click(screen.getByRole('button', { name: '退出登录' }));
    fireEvent.click(screen.getByRole('button', { name: '退出' }));

    await waitFor(() => {
      expect(useSessionStore.getState().session.status).toBe('anonymous');
    });
    expect(await screen.findByRole('heading', { name: '登录落点' })).toBeDefined();
    expect(useSessionStore.getState().account).toBeNull();
  });
});

describe('设置页 · tab 栏与动效', () => {
  it('P0 tab 栏当前项是「我的」', () => {
    renderSettings(port());

    expect(screen.getByRole('link', { name: '我的' }).getAttribute('aria-current')).toBe('page');
  });

  it('P0 页面级零动效：内容区没有动画类（本页是全产品最安静的页面）', () => {
    const { container } = renderSettings(port());

    const tiles = container.querySelectorAll('.tile');
    expect(tiles.length).toBeGreaterThan(0);
    for (const tile of tiles) {
      expect(tile.className).not.toMatch(/anim|fade|stagger/i);
    }
  });
});
