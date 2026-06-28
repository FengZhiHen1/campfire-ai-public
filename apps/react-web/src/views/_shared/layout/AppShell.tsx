import { Outlet, useLocation } from 'react-router-dom';
import type { ComponentType, SVGProps } from 'react';
import TabBar from './TabBar';
import type { TabItem } from './TabBar';
import './layout.css';

/* ── Tab SVG Icons ── */

const HomeIcon: ComponentType<SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    <polyline points="9 22 9 12 15 12 15 22" />
  </svg>
);

const ConsultIcon: ComponentType<SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);

const CasesIcon: ComponentType<SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <rect x="3" y="3" width="7" height="7" />
    <rect x="14" y="3" width="7" height="7" />
    <rect x="3" y="14" width="7" height="7" />
    <rect x="14" y="14" width="7" height="7" />
  </svg>
);

const ProfilesIcon: ComponentType<SVGProps<SVGSVGElement>> = (props) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" {...props}>
    <circle cx="12" cy="9" r="4" />
    <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" />
  </svg>
);

const TABS: TabItem[] = [
  { id: 'home', label: '首页', icon: HomeIcon, to: '/' },
  { id: 'consult', label: '咨询', icon: ConsultIcon, to: '/consult' },
  { id: 'cases', label: '案例', icon: CasesIcon, to: '/cases' },
  { id: 'profiles', label: '档案', icon: ProfilesIcon, to: '/profiles' },
];

/**
 * 应用外壳：Tab 页布局 = PageContent + TabBar。
 * 非 Tab 页（如 case-submit 等子页面）仅渲染 Outlet，不显示 TabBar。
 */
export default function AppShell() {
  const { pathname } = useLocation();
  const tabPaths = ['/', '/consult', '/cases', '/profiles'];
  const isTabPage = tabPaths.includes(pathname);

  return (
    <div className="cf-app-shell">
      <div className="phone-frame">
        <div className="phone-notch" />
        <Outlet />
        {isTabPage && <TabBar tabs={TABS} />}
      </div>
    </div>
  );
}
