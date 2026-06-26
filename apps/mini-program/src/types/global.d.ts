/** 编译时由 Taro defineConstants 注入的环境变量声明 */
declare namespace NodeJS {
  interface ProcessEnv {
    /** API 基础 URL — WeApp dev 模式为 http://127.0.0.1:8000，其余为空 */
    TARO_APP_API_BASE?: string;
    /** MOCK 模式开关 — USE_MOCK=true 时为 'true'，其余为空字符串 */
    TARO_APP_USE_MOCK?: string;
  }
}

declare const process: {
  env: NodeJS.ProcessEnv;
};
