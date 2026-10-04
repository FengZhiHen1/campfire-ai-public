/**
 * 模块: features/consult/view/EmergencyFormPage.test
 * 职责: 应急表单页的组件用例——八项分步流、跳过语义、随时提交与失败保留
 * 数据来源:
 *   - docs/design/pages/应急表单页.md: MUST — 布局结构、状态覆盖表
 *   - docs/技术设计/面/consult/skills/emergency-consulting.md: MUST — 第 2 节（八项）
 * 边界:
 *   - 依赖: view/EmergencyFormPage、test/consultPortStub
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止只测「填满八项」；全跳过与部分作答是本页的主用法（RQ-EMG-01）
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { EmergencyFormPage } from './EmergencyFormPage';
import { EMERGENCY_QUESTIONS } from '../domain/emergency';
import { createConsultPortStub, type ConsultPortStub } from '../test/consultPortStub';

/** 渲染应急表单页（提交成功后跳到对话页占位）。 */
function renderForm(port: ConsultPortStub) {
  return render(
    <MemoryRouter initialEntries={['/consult/emergency']}>
      <Routes>
        <Route path="/consult/emergency" element={<EmergencyFormPage consult={port} />} />
        <Route path="/consult/sessions/:sessionId" element={<p>对话页已到达</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

/** 取提交按钮。 */
function submitButton(): HTMLElement {
  return screen.getByRole('button', { name: /提交，开始分析|正在提交…/ });
}

afterEach(() => {
  // navigator.onLine 的替身在用例里改过，恢复默认。
  Object.defineProperty(window.navigator, 'onLine', { value: true, configurable: true });
});

describe('应急表单页 — 分步流', () => {
  it('一屏一题：显示首题、题号与进度条（不用百分比数字）', () => {
    const port = createConsultPortStub();
    renderForm(port);

    expect(screen.getByText('第 1 / 8 题')).toBeDefined();
    expect(screen.getByText(EMERGENCY_QUESTIONS[0]?.prompt ?? '')).toBeDefined();
    // 其余题面不在屏上（一屏一题，不是长表单）。
    expect(screen.queryByText(EMERGENCY_QUESTIONS[1]?.prompt ?? '')).toBeNull();

    const track = document.querySelector('.progress-track');
    expect(track?.getAttribute('aria-valuemax')).toBe('8');
    expect(track?.getAttribute('aria-valuenow')).toBe('1');
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it('跳过语义写在界面上（不得弱化成「暂时跳过」）', () => {
    renderForm(createConsultPortStub());
    expect(screen.getByText('跳过 = 未排除，不会当作正常')).toBeDefined();
  });

  it('下一题/上一题可来回，作答与跳过标记保留', () => {
    renderForm(createConsultPortStub());

    fireEvent.click(screen.getByRole('button', { name: '下一题' }));
    expect(screen.getByText('第 2 / 8 题')).toBeDefined();
    expect(screen.getByText(EMERGENCY_QUESTIONS[1]?.prompt ?? '')).toBeDefined();

    fireEvent.click(screen.getByRole('button', { name: '跳过这题' }));
    expect(screen.getByText(/本题已跳过（按未排除处理）/)).toBeDefined();

    fireEvent.click(screen.getByRole('button', { name: '上一题' }));
    expect(screen.getByText('第 1 / 8 题')).toBeDefined();
  });

  it('第八题时「下一题」禁用；勾选与自由补充都能记录', () => {
    renderForm(createConsultPortStub());
    for (let index = 1; index < EMERGENCY_QUESTIONS.length; index += 1) {
      fireEvent.click(screen.getByRole('button', { name: '下一题' }));
    }
    expect(screen.getByText('第 8 / 8 题')).toBeDefined();
    expect(screen.getByRole('button', { name: '下一题' }).hasAttribute('disabled')).toBe(true);

    fireEvent.click(screen.getByLabelText('不确定'));
    expect((screen.getByLabelText('不确定') as HTMLInputElement).checked).toBe(true);
  });
});

describe('应急表单页 — 提交', () => {
  it('全跳过也能提交：八项都按 skipped 上报（未作答 = 未排除）', async () => {
    const port = createConsultPortStub();
    renderForm(port);

    await act(async () => {
      fireEvent.click(submitButton());
    });

    await waitFor(() => expect(port.emergencyStart).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(port.emergencyStart).mock.calls[0]?.[0];
    expect(payload?.items).toHaveLength(8);
    expect(payload?.items.every((item) => item.skipped)).toBe(true);
    expect(payload?.items.every((item) => item.value === undefined && item.values === undefined)).toBe(true);
  });

  it('提交不需答完：答一题直接提交，该项带值、其余未排除', async () => {
    const port = createConsultPortStub();
    renderForm(port);

    fireEvent.click(screen.getByLabelText('意识改变'));
    await act(async () => {
      fireEvent.click(submitButton());
    });

    await waitFor(() => expect(port.emergencyStart).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(port.emergencyStart).mock.calls[0]?.[0];
    const redFlags = payload?.items.find((item) => item.key === 'medical_red_flags');
    expect(redFlags).toEqual({ key: 'medical_red_flags', values: ['altered_consciousness'], skipped: false });
    expect(payload?.items.filter((item) => item.skipped)).toHaveLength(7);
  });

  it('提交成功后跳转对话页（表单页即弃）', async () => {
    const port = createConsultPortStub({ emergency: { session_id: 's-emg', run_id: 'run-emg' } });
    renderForm(port);

    await act(async () => {
      fireEvent.click(submitButton());
    });

    expect(await screen.findByText('对话页已到达')).toBeDefined();
  });

  it('提交失败：显示错误卡且已填内容不清空', async () => {
    const port = createConsultPortStub({ emergency: new Error('服务不可达') });
    renderForm(port);

    fireEvent.click(screen.getByLabelText('意识改变'));
    fireEvent.click(screen.getByRole('button', { name: '下一题' }));
    fireEvent.click(screen.getByLabelText('明显'));

    await act(async () => {
      fireEvent.click(submitButton());
    });

    expect(await screen.findByText('出现了未预期的错误')).toBeDefined();
    // 回到第一题：勾选仍在（已填内容保留）。
    fireEvent.click(screen.getByRole('button', { name: '上一题' }));
    expect((screen.getByLabelText('意识改变') as HTMLInputElement).checked).toBe(true);
  });

  it('离线时不发起注定失败的请求，直接给网络提示', async () => {
    Object.defineProperty(window.navigator, 'onLine', { value: false, configurable: true });
    const port = createConsultPortStub();
    renderForm(port);

    await act(async () => {
      fireEvent.click(submitButton());
    });

    expect(await screen.findByText('网络不可用')).toBeDefined();
    expect(port.emergencyStart).not.toHaveBeenCalled();
  });
});
