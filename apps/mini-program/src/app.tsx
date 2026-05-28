import { Component, PropsWithChildren } from 'react'
import Taro from '@tarojs/taro'

import './app.scss'

class App extends Component<PropsWithChildren> {

  componentDidMount() {
    // 确保 device_id 存在
    this.ensureDeviceId()
    // 自动注册 httpClient 拦截器
    import('./logics/shared/services/httpClient')
  }

  ensureDeviceId() {
    let deviceId = Taro.getStorageSync('campfire_device_id')
    if (!deviceId) {
      const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
      deviceId = Array.from({ length: 16 }, () => chars.charAt(Math.floor(Math.random() * chars.length))).join('')
      Taro.setStorageSync('campfire_device_id', deviceId)
    }
  }

  componentDidShow() {}

  componentDidHide() {}

  render() {
    return this.props.children
  }
}

export default App
