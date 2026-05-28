import { useEffect } from 'react'
import Taro from '@tarojs/taro'

import './app.scss'
// 静态导入以确保 HTTP 拦截器在应用启动时立即注册
import './logics/shared/services/httpClient'

function App(props) {
  useEffect(() => {
    ensureDeviceId()
  }, [])

  return props.children
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
