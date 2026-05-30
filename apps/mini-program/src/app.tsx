import './polyfills'

import { useEffect } from 'react';
import type { ReactNode } from 'react';
import Taro from '@tarojs/taro';
import { ErrorBoundary } from './views/shared/components/ErrorBoundary';

import './app.scss';

function App(props: { children?: ReactNode }) {
  useEffect(() => {
    ensureDeviceId()
  }, [])

  return <ErrorBoundary>{props.children}</ErrorBoundary>
}

function ensureDeviceId() {
  let deviceId = Taro.getStorageSync('campfire_device_id')
  if (!deviceId) {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    deviceId = Array.from({ length: 16 }, () => chars.charAt(Math.floor(Math.random() * chars.length))).join('')
    Taro.setStorageSync('campfire_device_id', deviceId)
  }
}

export default App
