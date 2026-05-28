import { View, Text } from '@tarojs/components';
import Taro from '@tarojs/taro';
import './index.scss';

interface TabItem {
  pagePath: string;
  text: string;
  icon: string;
}

const TAB_LIST: TabItem[] = [
  { pagePath: 'views/shared/pages/home', text: '首页', icon: '🏠' },
  { pagePath: 'views/consult/pages/index', text: '咨询', icon: '💬' },
  { pagePath: 'views/cases/pages/index', text: '案例', icon: '📚' },
  { pagePath: 'views/profiles/pages/edit', text: '档案', icon: '👤' },
];

function getCurrentPagePath(): string {
  const pages = Taro.getCurrentPages();
  if (pages.length === 0) return TAB_LIST[0].pagePath;
  return pages[pages.length - 1].route ?? '';
}

export default function CustomTabBar() {
  const currentPath = getCurrentPagePath();

  const handleTabClick = (pagePath: string) => {
    if (currentPath === pagePath) return;
    Taro.switchTab({ url: `/${pagePath}` });
  };

  return (
    <View className="custom-tab-bar">
      {TAB_LIST.map((tab) => {
        const isActive = currentPath === tab.pagePath;
        return (
          <View
            key={tab.pagePath}
            className={`custom-tab-bar__item${isActive ? ' custom-tab-bar__item--active' : ''}`}
            onClick={() => handleTabClick(tab.pagePath)}
          >
            <Text className="custom-tab-bar__icon">{tab.icon}</Text>
            <Text className="custom-tab-bar__label">{tab.text}</Text>
          </View>
        );
      })}
    </View>
  );
}
