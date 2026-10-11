
/** 首页入口回归：业务导航、草稿交接、失败保留与并发防重。 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConsultError } from '../../features/consult/domain/errors';
import { createConsultPortStub, type ConsultPortStub } from '../../features/consult/test/consultPortStub';
import { ChatPage } from '../../features/consult/view/ChatPage';
import { resetConsultRunStore } from '../../features/consult/viewModel/runStore';
import { HomePage } from './HomePage';

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="route-state">{JSON.stringify(location.state)}</output>;
}
function renderHome(port: ConsultPortStub = createConsultPortStub()) {
  return render(<MemoryRouter initialEntries={['/']}><Routes>
    <Route path="/" element={<HomePage consult={port} />} />
    <Route path="/consult/sessions/:sessionId" element={<><ChatPage consult={port} /><LocationProbe /></>} />
  </Routes></MemoryRouter>);
}
beforeEach(() => { resetConsultRunStore(); });

describe('首页 · 咨询入口', () => {
  it('初始不请求数据，输入为空不能创建空会话', () => {
    const port = createConsultPortStub();
    renderHome(port);
    expect(screen.getByRole('heading', { name: '篝火智答', level: 1 })).toBeDefined();
    expect(screen.getByRole('button', { name: '进入对话' }).hasAttribute('disabled')).toBe(true);
    expect(port.createSession).not.toHaveBeenCalled();
    expect(port.listSessions).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('想聊的事情'), { target: { value: '   ' } });
    fireEvent.submit(screen.getByRole('button', { name: '进入对话' }).closest('form') as HTMLFormElement);
    expect(port.createSession).not.toHaveBeenCalled();
  });
  it('首页草稿进入实际对话输入器；确认发送之前不启动模型，路由草稿消费后清除', async () => {
    const port = createConsultPortStub();
    renderHome(port);
    fireEvent.change(screen.getByLabelText('想聊的事情'), { target: { value: '  他不愿意出门，我想先准备一下。  ' } });
    fireEvent.click(screen.getByRole('button', { name: '进入对话' }));
    const composer = await screen.findByLabelText('发送消息');
    expect((composer as HTMLTextAreaElement).value).toBe('他不愿意出门，我想先准备一下。');
    expect(port.createSession).toHaveBeenCalledTimes(1);
    expect(port.sendCalls).toHaveLength(0);
    await waitFor(() => expect(screen.getByTestId('route-state').textContent).toBe('null'));
  });
  it('建会话失败保留草稿与重试入口，不伪装成已发送', async () => {
    const port = createConsultPortStub({ createSession: new ConsultError('unavailable', '服务暂时不可用') });
    renderHome(port);
    fireEvent.change(screen.getByLabelText('想聊的事情'), { target: { value: '需要保留的问题' } });
    fireEvent.click(screen.getByRole('button', { name: '进入对话' }));
    await screen.findByRole('alert');
    expect((screen.getByLabelText('想聊的事情') as HTMLTextAreaElement).value).toBe('需要保留的问题');
    expect(screen.getByRole('button', { name: '进入对话' }).hasAttribute('disabled')).toBe(false);
    expect(port.sendCalls).toHaveLength(0);
  });
  it('请求未完成时重复提交只创建一个会话', async () => {
    const port = createConsultPortStub();
    vi.mocked(port.createSession).mockReturnValue(new Promise(() => undefined));
    renderHome(port);
    fireEvent.change(screen.getByLabelText('想聊的事情'), { target: { value: '同一个问题' } });
    const form = screen.getByRole('button', { name: '进入对话' }).closest('form') as HTMLFormElement;
    await act(async () => { fireEvent.submit(form); fireEvent.submit(form); });
    expect(port.createSession).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: '正在进入…' }).hasAttribute('disabled')).toBe(true);
  });
});

describe('首页 · 导航与视觉边界', () => {
  it('现场求助保持直接可达，且保留独立呼吸点和说明', () => {
    const { container } = renderHome();
    expect(screen.getByRole('link', { name: '开始应急咨询' }).getAttribute('href')).toBe('/consult/emergency');
    expect(screen.getByText('在现场遇到正在发生的情况？回答几个问题，马上给你可行动的建议')).toBeDefined();
    expect(container.querySelectorAll('.flame-dot')).toHaveLength(1);
  });
  it('案例、资料、咨询历史与说明均有真实路由', () => {
    renderHome();
    expect(screen.getByRole('link', { name: /案例库/ }).getAttribute('href')).toBe('/cases');
    const knowledgeEntry = screen.getByRole('link', { name: /^资料库/ });
    expect(knowledgeEntry.getAttribute('href')).toBe('/cases?section=knowledge');
    expect(knowledgeEntry.querySelector('strong')?.textContent).toBe('资料库');
    expect(screen.queryByRole('link', { name: /资料库说明/ })).toBeNull();
    expect(screen.getByRole('link', { name: '继续之前的咨询' }).getAttribute('href')).toBe('/consult');
    expect(screen.getByRole('link', { name: '使用说明' }).getAttribute('href')).toBe('/guide');
  });
  it('四项导航在设备屏幕内，当前首页可辨，内容为导航预留空间', () => {
    const { container } = renderHome();
    const nav = screen.getByRole('navigation', { name: '一级导航' });
    expect(nav.querySelectorAll('.tab-item')).toHaveLength(4);
    expect(screen.getByRole('link', { name: '首页' }).getAttribute('aria-current')).toBe('page');
    expect(container.querySelector('.device-screen')?.contains(nav)).toBe(true);
    expect(container.querySelector('.phone-shell')?.className).toContain('has-tab-bar');
  });
});
