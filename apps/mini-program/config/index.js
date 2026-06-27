const TARO_ENV = process.env.TARO_ENV || 'h5'
const NODE_ENV = process.env.NODE_ENV || 'development'
const fs = require('fs')
const path = require('path')

/**
 * Resolve the API base URL for WeApp dev mode.
 * Priority: ngrok tunnel URL > localhost fallback.
 *
 * Reads .ngrok-url from the project root (written by start.py → start_ngrok.py).
 * If the file exists, uses the ngrok public URL.
 * Otherwise falls back to http://127.0.0.1:8000.
 */
function resolveApiBase() {
  if (TARO_ENV !== 'weapp' || NODE_ENV !== 'development') {
    return ''
  }
  // .ngrok-url is at monorepo root (../../.. from config/ dir)
  const ngrokUrlFile = path.resolve(__dirname, '..', '..', '..', '.ngrok-url')
  try {
    const ngrokUrl = fs.readFileSync(ngrokUrlFile, 'utf-8').trim()
    if (ngrokUrl && ngrokUrl.startsWith('https://')) {
      console.log(`[campfire] 使用 ngrok 公网地址: ${ngrokUrl}`)
      return ngrokUrl
    }
  } catch {
    // File doesn't exist — use localhost fallback
  }
  console.log('[campfire] 使用本地 API 地址: http://127.0.0.1:8000')
  return 'http://127.0.0.1:8000'
}

/**
 * 解析 MOCK 模式开关。
 * USE_MOCK=true 时返回 'true'，其余返回 ''（falsy）。
 * 由 Node.js 层环境变量控制，编译时注入为 TARO_APP_USE_MOCK。
 */
function resolveMockEnabled() {
  return process.env.USE_MOCK === 'true' ? 'true' : ''
}

const config = {
  projectName: 'campfire-ai',
  date: '2026-5-27',
  // 与微信小程序设计稿宽度保持一致；H5 模拟器通过动态 rem 根值按 750px 比例渲染。
  designWidth: 750,
  deviceRatio: {
    640: 2.34 / 2,
    750: 1,
    828: 1.81 / 2
  },
  sourceRoot: 'src',
  outputRoot: 'dist',
  plugins: [],
  defineConstants: {
    'process.env.TARO_APP_API_BASE': JSON.stringify(resolveApiBase()),
    'process.env.TARO_APP_USE_MOCK': JSON.stringify(resolveMockEnabled()),
  },
  h5: {
    webpackChain(chain) {
      const tsSharedPath = path.resolve(__dirname, '..', '..', '..', 'packages', 'ts-shared', 'src');
      chain.module.rules.store.forEach((_value, name) => {
        const rule = chain.module.rule(name);
        const uses = rule.uses.store;
        const hasBabel = uses.has('babelLoader') || [...uses.keys()].some(k => k.toLowerCase().includes('babel'));
        if (hasBabel) {
          rule.include.add(tsSharedPath);
        }
      });
    },
    // H5 保留 pxtransform 转换 px->rem。
    // iframe 模拟器方案下，rem 根值由 index.html 内联脚本手动控制，
    // 禁用 Taro 默认注入，避免与 iframe 检测逻辑冲突。
    postcss: {
      pxtransform: {
        enable: true,
        config: {}
      }
    },
    htmlPluginOption: {
      script: ''
    }
  },
  alias: {
    '@': require('path').resolve(__dirname, '..', 'src')
  },
  copy: {
    patterns: [],
    options: {}
  },
  framework: 'react',
  compiler: 'webpack5',
  mini: {
    compile: {
      include: [
        path.resolve(__dirname, '..', '..', '..', 'packages', 'ts-shared', 'src')
      ]
    },
    postcss: {
      pxtransform: {
        enable: true,
        config: {}
      }
    }
  }
}

module.exports = function (merge) {
  if (process.env.NODE_ENV === 'development') {
    return merge({}, config, require('./dev'))
  }
  return merge({}, config, require('./prod'))
}
