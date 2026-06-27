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
  // 与微信小程序设计稿宽度保持一致；H5 模拟器通过 transform scale 按 750px 舞台渲染。
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
    // H5 已限制为手机宽度模拟器，但保留 pxtransform 转换 px->rem，
    // 由 index.html 自定义脚本控制 rem 基准，使内容在 430px 容器内正确缩放。
    postcss: {
      pxtransform: {
        enable: true,
        config: {}
      }
    },
    // 禁用 Taro 默认的视口级 rem 脚本，避免大屏幕下字体被过度放大
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
