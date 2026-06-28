import { useLocation, useNavigate } from 'react-router-dom';
import type { ComponentType, SVGProps } from 'react';

export interface TabItem {
  id: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  to: string;
}

export interface TabBarProps {
  tabs: TabItem[];
}

/**
 * 底部 4 Tab 导航栏。
 * OD 规格：56px 高度，毛玻璃背景，active 顶部 3px accent 指示条。
 */
export default function TabBar({ tabs }: TabBarProps) {
  const { pathname } = useLocation();
  const navigate = useNavigate();

  return (
    <nav className="cf-tab-bar">
      {tabs.map((tab) => {
        const isActive = pathname === tab.to
          || (tab.to !== '/' && pathname.startsWith(tab.to));
        return (
          <button
            key={tab.id}
            type="button"
            className={`cf-tab-bar__item${isActive ? ' cf-tab-bar__item--active' : ''}`}
            onClick={() => navigate(tab.to)}
          >
            <tab.icon className="cf-tab-bar__icon" />
            <span className="cf-tab-bar__label">{tab.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
