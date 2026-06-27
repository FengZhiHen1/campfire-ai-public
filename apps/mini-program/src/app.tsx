import './polyfills'

import type { ReactNode } from 'react';
import { useEffect, useRef } from 'react';
import { View } from '@tarojs/components';
import { ErrorBoundary } from './views/shared/components/ErrorBoundary';
import { useProfile } from './logics/profiles';
import { httpClient } from './logics/shared/services/httpClient';
import { useSessionStore } from './logics/shared/store/userStore';

import './app.scss';

const isH5 = process.env.TARO_ENV === 'h5';

/** H5 手机模拟器：固定 750px 舞台，通过 transform scale 缩放到最大 520px */
function H5Simulator(props: { children?: ReactNode }) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const tabbarMovedRef = useRef(false);

  useEffect(() => {
    const wrapper = wrapperRef.current;
    const stage = stageRef.current;
    const simulator = stage?.querySelector('.h5-simulator') as HTMLElement | null;
    if (!wrapper || !stage || !simulator) return;

    const DESIGN_WIDTH = 750;
    const MAX_WIDTH = 520;

    function updateScale() {
      const wrapperWidth = Math.min(window.innerWidth, MAX_WIDTH);
      const scale = wrapperWidth / DESIGN_WIDTH;

      // 使用 zoom 替代 transform: scale，zoom 会直接改变元素布局尺寸，
      // 因此 absolute 定位的 TabBar bottom: 0 会正确落在缩放后的底部，
      // 不会出现 transform scale 导致的坐标错位和截断。
      (stage.style as any).zoom = scale;

      // 让手机模拟器在垂直方向撑满浏览器视口，消除底部灰色空白。
      // 逻辑高度 = 视口高度 / zoom，缩放后实际高度正好等于视口高度。
      const simulatorHeight = window.innerHeight / scale;
      simulator.style.minHeight = `${simulatorHeight}px`;

      // Taro H5 的页面根元素 class 为 .taro_page，当前显示页面额外有 .taro_page_show。
      // 它内部通常使用 min-height: 100vh，但 100vh 指向浏览器视口，而不是被 zoom
      // 放大后的 simulator。这里强制真正的页面根元素撑满 simulator，避免 TabBar
      // 上方出现无法滚动覆盖的空白区域。
      const pageRoot = simulator.querySelector('.taro_page_show') as HTMLElement | null;
      if (pageRoot) {
        pageRoot.style.minHeight = `${simulatorHeight - 140}px`; // 减去 TabBar 高度
      }
    }

    // 将 Taro H5 渲染在 body 上的 taro-tabbar 移入舞台，使其随舞台一起缩放
    function moveTabbarIntoStage() {
      if (tabbarMovedRef.current) return;
      const tabbar = document.querySelector('taro-tabbar') as HTMLElement | null;
      if (tabbar && tabbar.parentElement !== stage) {
        stage.appendChild(tabbar);
        tabbarMovedRef.current = true;
        updateScale();
      }
    }

    const mutationObserver = new MutationObserver(() => {
      moveTabbarIntoStage();

      // 页面根元素异步渲染，一旦生成立即重算高度，避免首屏空白。
      if (simulator.querySelector('.taro_page_show')) {
        updateScale();
      }
    });
    mutationObserver.observe(document.body, { childList: true, subtree: true });

    // 初始化及窗口变化时重算缩放
    updateScale();
    window.addEventListener('resize', updateScale);

    // 内容高度变化时同步 wrapper 高度
    const resizeObserver = new ResizeObserver(updateScale);
    resizeObserver.observe(stage);

    return () => {
      window.removeEventListener('resize', updateScale);
      mutationObserver.disconnect();
      resizeObserver.disconnect();
    };
  }, []);

  return (
    <div ref={wrapperRef} className="h5-scale-wrapper">
      <div ref={stageRef} className="h5-scale-stage">
        <View className="h5-simulator">{props.children}</View>
      </div>
    </div>
  );
}

function App(props: { children?: ReactNode }) {
  const { fetchProfiles } = useProfile();

  useEffect(() => {
    fetchProfiles();
  }, [fetchProfiles]);

  useEffect(() => {
    httpClient.request<{ user_id: string; role: string; device_id: string }>({
      url: '/api/v1/auth/me',
      method: 'GET',
    }).then((res) => {
      if (res.data?.user_id) {
        useSessionStore.getState().setUser({
          userId: res.data.user_id,
          roles: [res.data.role || 'family'],
        });
      }
    }).catch(() => {
      // MVP 降级：me 端点失败不阻塞应用
    });
  }, []);

  return (
    <ErrorBoundary>
      {isH5 ? (
        <H5Simulator>{props.children}</H5Simulator>
      ) : (
        props.children
      )}
    </ErrorBoundary>
  );
}

export default App
