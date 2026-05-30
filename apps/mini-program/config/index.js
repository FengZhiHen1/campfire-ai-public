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

const config = {
  projectName: 'campfire-ai',
  date: '2026-5-27',
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
