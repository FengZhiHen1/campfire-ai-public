/**
 * 模块: shared/ui/AppShell
 * 职责: 手机蒙版外壳与底部 tab 栏——一级页面共用导航容器
 * 数据来源:
 *   - docs/design/DESIGN.md: MUST — 布局与 posture 要点（仅手机端、--phone-shell-max 蒙版、
 *     宽视口设备外壳）
 *   - docs/design/pages/首页.md: MUST — 契约修订节（.tab-bar / .tab-item 四页共用、次级页不渲染）
 * 边界:
 *   - 依赖: react-router 的 NavLink（导航状态来自 URL，不另设本地状态）、shared/ui/DeviceFrame
 *   - 被依赖: app 的页面装配
 * 禁止行为:
 *   - 禁止在次级页面渲染 tab 栏（返回导航由页头承担，页面设计首页契约修订节）
 *   - 禁止把 tab 栏渲染到 DeviceFrame 之外（见下面组件注释里的包含块理由）
 *   - 禁止用 emoji 作图标（DESIGN.md 反模式）
 */

import type { ReactNode } from 'react';
import { NavLink, useLocation, useNavigationType } from 'react-router';

import { DeviceFrame } from './DeviceFrame';

/** tab 项的标识；与页面设计的一级页面集合一一对应。 */
export type TabKey = 'home' | 'consult' | 'profile' | 'settings';

// 描边与实形共用外轮廓。实形上的留白保留门、文字、书页与人像的识别特征。
const TAB_GLYPHS: Readonly<Record<TabKey, { outline: string; solid: string }>> = {
  home: {
    outline: 'M4 10.5 12 4l8 6.5v7.75A1.75 1.75 0 0 1 18.25 20H5.75A1.75 1.75 0 0 1 4 18.25z M10 20v-6h4v6',
    solid: 'M3.25 10.14 12 3l8.75 7.14v8.11a2.5 2.5 0 0 1-2.5 2.5h-4.5V14.5h-3.5v6.25h-4.5a2.5 2.5 0 0 1-2.5-2.5z',
  },
  consult: {
    outline: 'M6.5 5h11a2.5 2.5 0 0 1 2.5 2.5v6a2.5 2.5 0 0 1-2.5 2.5h-5L7 20v-4h-.5A2.5 2.5 0 0 1 4 13.5v-6A2.5 2.5 0 0 1 6.5 5Z M8 9h8m-8 3h5',
    solid: 'M6.5 4.25h11a3.25 3.25 0 0 1 3.25 3.25v6a3.25 3.25 0 0 1-3.25 3.25h-4.75L6.25 21v-4.26A3.25 3.25 0 0 1 3.25 13.5v-6A3.25 3.25 0 0 1 6.5 4.25Z M7.5 8.25h9v1.5h-9zm0 3.25h6V13h-6z',
  },
  profile: {
    outline: 'M6 5.75A1.75 1.75 0 0 1 7.75 4H14l4 4v10.25A1.75 1.75 0 0 1 16.25 20h-8.5A1.75 1.75 0 0 1 6 18.25Z M14 4v4h4m-9 4h6m-6 3.5h6',
    solid: 'M5.25 5.75a2.5 2.5 0 0 1 2.5-2.5h6.5l4.5 4.5v10.5a2.5 2.5 0 0 1-2.5 2.5h-8.5a2.5 2.5 0 0 1-2.5-2.5z M13.25 5v3.75H17zm-4.5 6.25h6.5v1.5h-6.5zm0 3.5h6.5v1.5h-6.5z',
  },
  settings: {
    outline: 'M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z M14.5 10a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z M6.75 17.8a5.75 5.75 0 0 1 10.5 0',
    solid: 'M20.75 12a8.75 8.75 0 1 1-17.5 0 8.75 8.75 0 0 1 17.5 0Z M14.65 9.6a2.65 2.65 0 1 1-5.3 0 2.65 2.65 0 0 1 5.3 0Z M7 16.9a5.3 5.3 0 0 1 10 0A7 7 0 0 1 7 16.9Z',
  },
};

function TabIcon({ tab }: { tab: TabKey }) {
  const glyph = TAB_GLYPHS[tab];
  return (
    <svg className="tab-glyph" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path className="tab-glyph-outline" d={glyph.outline} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <path className="tab-glyph-solid" d={glyph.solid} fill="currentColor" fillRule="evenodd" />
    </svg>
  );
}

/** tab 项定义；label 是图标之外的第二标识通道（不得只靠颜色区分当前项）。 */
interface TabDefinition {
  key: TabKey;
  label: string;
  to: string;
}

const TABS: readonly TabDefinition[] = [
  { key: 'home', label: '首页', to: '/' },
  { key: 'consult', label: '咨询', to: '/consult' },
  { key: 'profile', label: '档案', to: '/profile' },
  { key: 'settings', label: '我的', to: '/settings' },
];

/** AppShell props。 */
export interface AppShellProps {
  /** 页面内容。 */
  children: ReactNode;
  /**
   * 当前一级页面；提供时渲染 tab 栏并预留其高度，省略时视为次级页面（不渲染 tab 栏）。
   */
  tab?: TabKey;
  className?: string;
}

/**
 * 渲染手机蒙版外壳（+ 可选 tab 栏）。
 *
 * 前置: 无
 * 后置: 输出 DeviceFrame 包裹的 --phone-shell-max 限宽容器；tab 为真时在屏幕区内输出
 *       四项导航并给内容区预留底部高度
 * 异常: 无
 *
 * 为什么 tab 栏放进 DeviceFrame 内部
 *
 * .tab-bar 是 position: fixed。宽视口下它的包含块被 .device 的 transform 收成外壳内容盒
 * （global.css 的承重属性），因此底边贴外壳底边而不是浏览器视口底边；窄视口下外壳三层
 * 退化为 display: contents，包含块回到视口，行为与设备外壳落地前一致。
 * 反过来，把它留在 DeviceFrame 之外就等于绕过外壳——外壳落地前后它都贴在视口上。
 */
export function AppShell({ children, tab, className = '' }: AppShellProps) {
  return (
    <DeviceFrame>
      <div className={(tab === undefined ? 'phone-shell' : 'phone-shell has-tab-bar') + ' ' + className}>{children}</div>
      {tab !== undefined && <PrimaryNav tab={tab} />}
    </DeviceFrame>
  );
}

function PrimaryNav({ tab }: { tab: TabKey }) {
  const { state } = useLocation();
  const navigation = useNavigationType();
  const previousTab = (state as { previousTab?: TabKey } | null)?.previousTab;
  const animateSelection = navigation === 'PUSH' && previousTab !== undefined && previousTab !== tab;

  return (
    <nav className="tab-bar" aria-label="一级导航" data-tab-arrival={animateSelection || undefined}>
      {TABS.map((item) => (
        <NavLink className="tab-item" key={item.key} to={item.to} state={{ previousTab: tab }} end={item.to === '/'}>
          <TabIcon tab={item.key} />
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
