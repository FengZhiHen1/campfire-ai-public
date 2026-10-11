import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';
import { BackLink } from './BackLink';

describe('次级页面返回来源', () => {
  it('首页打开说明后返回首页，不误跳设置', () => {
    render(<MemoryRouter initialEntries={[{ pathname: '/guide', state: { returnTo: '/' } }]}>
      <Routes><Route path="/guide" element={<BackLink fallback="/settings" />} /><Route path="/" element={<p>首页落点</p>} /></Routes>
    </MemoryRouter>);
    fireEvent.click(screen.getByRole('link', { name: '← 返回' }));
    expect(screen.getByText('首页落点')).toBeDefined();
  });
  it('直接打开和非法外部返回地址都使用默认入口', () => {
    render(<MemoryRouter initialEntries={[{ pathname: '/cases', state: { returnTo: '//outside.example' } }]}><BackLink fallback="/" /></MemoryRouter>);
    expect(screen.getByRole('link', { name: '← 返回' }).getAttribute('href')).toBe('/');
  });
});
