import './polyfills'

import type { ReactNode } from 'react';
import { useEffect } from 'react';
import { View } from '@tarojs/components';
import { ErrorBoundary } from './views/shared/components/ErrorBoundary';
import { useProfile } from './logics/profiles';
import { httpClient } from './logics/shared/services/httpClient';
import { useSessionStore } from './logics/shared/store/userStore';

import './app.scss';

const isH5 = process.env.TARO_ENV === 'h5';

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
        <View className="h5-simulator">{props.children}</View>
      ) : (
        props.children
      )}
    </ErrorBoundary>
  );
}

export default App
