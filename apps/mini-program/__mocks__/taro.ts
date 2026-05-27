// Minimal Taro API stub for test environment
const Taro = {
  setStorageSync: (key: string, data: any) => {},
  getStorageSync: (key: string) => null,
  removeStorageSync: (key: string) => {},
  setStorage: (options: any) => Promise.resolve(),
  getStorage: (options: any) => Promise.resolve({ data: null }),
  removeStorage: (options: any) => Promise.resolve(),
  addInterceptor: (interceptor: any) => {},
  request: (options: any) => Promise.resolve({ data: {}, statusCode: 200, header: {}, errMsg: 'ok' }),
  reLaunch: (options: any) => Promise.resolve(),
  getCurrentPages: () => [],
  getNetworkType: () => Promise.resolve({ networkType: 'wifi' }),
  showToast: (options: any) => {},
  showLoading: (options: any) => {},
  hideLoading: () => {},
  navigateTo: (options: any) => Promise.resolve(),
  redirectTo: (options: any) => Promise.resolve(),
  switchTab: (options: any) => Promise.resolve(),
};
export default Taro;
export { Taro };
