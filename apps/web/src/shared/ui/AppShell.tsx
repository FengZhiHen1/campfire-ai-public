/**
 * 模块: shared/ui/AppShell
 * 职责: 手机蒙版外壳与底部 tab 栏——一级页面共用导航容器
 * 数据来源:
 *   - docs/design/DESIGN.md: MUST — 布局与 posture 要点（仅手机端、--phone-shell-max 蒙版）
 *   - docs/design/pages/首页.md: MUST — 契约修订节（.tab-bar / .tab-item 四页共用、次级页不渲染）
 * 边界:
 *   - 依赖: react-router 的 NavLink（导航状态来自 URL，不另设本地状态）
 *   - 被依赖: app 的页面装配
 * 禁止行为:
 *   - 禁止在次级页面渲染 tab 栏（返回导航由页头承担，页面设计首页契约修订节）
 *   - 禁止用 emoji 作图标（DESIGN.md 反模式）
 */

import type { ReactNode } from 'react';
import { NavLink } from 'react-router';

/** tab 项的标识；与页面设计的一级页面集合一一对应。 */
export type TabKey = 'home' | 'consult' | 'profile' | 'settings';

/**
 * tab 图标。
 *
 * 为什么内联而不是引用 assets：设计源 assets 只有品牌图标（首页页设计注明
 * 「正式页面的图标取自 assets」但 assets 里没有导航图标），因此按设计语言
 * 现画 1.6px 描边、currentColor 上色的单色图标；形状保持最简，不用 emoji。
 */
const TAB_ICONS: Readonly<Record<TabKey, ReactNode>> = {
  home: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-5h-6v5H5a1 1 0 0 1-1-1z" strokeLinejoin="round" />
    </svg>
  ),
  consult: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M4 6h16v10H9l-5 4z" strokeLinejoin="round" />
    </svg>
  ),
  profile: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M5 4h9l5 5v11H5z" strokeLinejoin="round" />
      <path d="M14 4v5h5" />
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <circle cx="12" cy="12" r="3.2" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" />
    </svg>
  ),
};

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
}

/**
 * 渲染手机蒙版外壳（+ 可选 tab 栏）。
 *
 * 前置: 无
 * 后置: 输出 --phone-shell-max 限宽的容器；tab 为真时输出四项导航并给内容区预留底部高度
 * 异常: 无
 */
export function AppShell({ children, tab }: AppShellProps) {
  return (
    <>
      <div className={tab === undefined ? 'phone-shell' : 'phone-shell has-tab-bar'}>{children}</div>
      {tab !== undefined && (
        <nav className="tab-bar" aria-label="一级导航">
          {TABS.map((item) => (
            <NavLink className="tab-item" key={item.key} to={item.to} end={item.to === '/'}>
              {TAB_ICONS[item.key]}
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
      )}
    </>
  );
}
