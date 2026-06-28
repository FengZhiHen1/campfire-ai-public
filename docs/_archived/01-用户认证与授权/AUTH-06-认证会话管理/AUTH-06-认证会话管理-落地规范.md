# 1 功能点：AUTH-06 认证会话管理 — 落地规范

> **文档生成时间**：`2026-05-26 23:15:00`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-26 23:15:00` | AI Assistant | 初始版本，基于设计文档 v1.0 和契约协调报告生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `AUTH-06-认证会话管理-设计文档.md`。

### 1.1 技术栈绑定 【对内实现】

- **必须使用**：
  - Taro 4.x — 微信小程序跨端框架，`Taro.setStorageSync` / `Taro.getStorageSync` / `Taro.removeStorageSync` 同步存储 API，`Taro.addInterceptor` 拦截器机制，`Taro.request` HTTP 客户端，`Taro.reLaunch` 路由跳转
  - Zustand 5.x — 全局状态管理库，`create()` 创建 `SessionStore`，内部通过 `set()` 更新状态
  - TypeScript — 所有接口和枚举必须使用显式类型注解，禁止 `any` 类型
- **禁止使用**：
  - 禁止绕过 `Taro.addInterceptor` 使用裸 `Taro.request` 发送 API 请求
  - 禁止在业务模块中直接操作 `Taro.setStorageSync('auth:token_pair', ...)` 读写 Token 数据
  - 禁止引入 Axios、fetch 等第三方 HTTP 库替代 `Taro.request`
  - 禁止在 `app.ts:onLaunch` 之前或之外初始化 Zustand `SessionStore`

### 1.2 文件归属 【对内实现】

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| HTTP 客户端 | `logics/shared/services/httpClient.ts` | 统一 HTTP 客户端，基于 `Taro.addInterceptor` 实现请求/响应拦截，导出 `httpClient.request<T>()` |
| Token 管理器 | `logics/shared/services/tokenManager.ts` | Token 持久化与续期模块，导出 `TokenManager` 对象：`getTokens()`, `setTokens()`, `clearTokens()`, `refreshTokens()` |
| 会话状态 Store | `logics/shared/store/userStore.ts` | Zustand SessionStore 定义，包含 `sessionState`、`tokenPair`、`refreshFailCount` 和 5 个 action 方法 |
| useAuth Hook | `logics/shared/hooks/useAuth.ts` | 认证状态桥接 Hook，导出 `useAuth()` 返回 `useAuthReturn` 接口 |
| 存储工具 | `logics/shared/utils/storage.ts` | Taro Storage 封装，定义存储键常量和安全读写方法 |
| 测试：httpClient | `tests/logics/shared/services/test_httpClient.ts` | httpClient 拦截器单元/集成测试 |
| 测试：tokenManager | `tests/logics/shared/services/test_tokenManager.ts` | Token 持久化与续期单元测试 |
| 测试：useAuth | `tests/logics/shared/hooks/test_useAuth.ts` | useAuth Hook 单元测试 |

### 1.3 输入定义 【已锁定】

**TokenPair** — 认证令牌对，由 AUTH-02 登录 API 或 AUTH-03 续期 API 返回
- 【契约引用】`docs/contracts/AUTH-06/TokenPair.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-05（登录成功时写入）、CSLT-08、PROF-07、CASE-09、TICK-09、KNOW-07（通过 httpClient 间接消费）
- 字段：`accessToken: string`（JWT 三段式，有效期 15 分钟）、`refreshToken: string`（JWT 三段式，有效期 7 天）

**AUTH-02 登录响应** — 上游模块提供的 API 响应，AUTH-06 从中提取 TokenPair
- 来源：`POST /api/v1/auth/login` 响应体
- 关注字段：`access_token: string`、`refresh_token: string`、`token_type: "Bearer"`
- 注意：AUTH-02 使用 snake_case，AUTH-06 内部转换为 camelCase（`access_token` → `accessToken`）

**AUTH-03 续期响应** — 上游模块提供的 API 响应，AUTH-06 从中提取新 TokenPair
- 来源：`POST /api/v1/auth/refresh` 响应体
- 关注字段：`access_token: string`、`refresh_token: string`
- 请求体：`{ refresh_token: string }`（JSON body，非 Authorization 头）

### 1.4 输出定义 【已锁定】

**useAuthReturn** — useAuth() Hook 的返回接口，L1a/L1b 模块的唯一认证状态桥接
- 【契约引用】`docs/contracts/AUTH-06/useAuthReturn.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-05（登录注册界面状态感知）、CSLT-07/08、PROF-06/07、CASE-08/09、TICK-08/09、KNOW-06/07（全部前端模块）
- 字段说明：`sessionState`（会话状态枚举值）、`isAuthenticated`（便捷布尔）、`user`（`{userId, roles}` 或 null）、`login`（登录函数）、`logout`（登出函数）

**httpClient** — 统一 HTTP 客户端接口，封装 Token 注入和自动续期
- 【契约引用】`docs/contracts/AUTH-06/httpClient.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-08、PROF-07、CASE-09、TICK-09、KNOW-07（全部 L1b 业务逻辑模块）
- 核心方法：`httpClient.request<T>(options: Taro.request.Option): Promise<IRequestResponse<T>>`

**SessionState** — 前端会话状态枚举
- 【契约引用】`docs/contracts/AUTH-06/SessionState.json`
- 本模块作为该契约的定义方
- 消费方：AUTH-05、CSLT-07/08、PROF-06/07、CASE-08/09、TICK-08/09、KNOW-06/07
- 枚举值：`"authenticated"`（已登录）、`"refreshing"`（续期中）、`"unauthenticated"`（未登录）

### 1.5 核心逻辑步骤 【对内实现】

1. **步骤 1：应用启动，初始化会话状态**
   - **操作对象**：Zustand `SessionStore` 实例
   - **具体操作**：在 `app.ts:onLaunch` 中执行 `initSession()` 函数：(a) 调用 `Taro.getStorageSync('auth:token_pair')` 读取持久化数据；(b) 若返回为 `null` 或 `undefined` → 调用 `setUnauthenticated()`，结束；(c) 验证返回值结构——必须为 `{ accessToken: string, refreshToken: string }` 且两字段均为非空 string；(d) 使用 `Taro.getStorageSync` 读取存储时间戳 `auth:token_pair:timestamp`；(e) 校验 refreshToken 的 JWT `exp` 声明——解析 JWT payload 的 Base64 段，检查 `Date.now() < payload.exp * 1000`；(f) 若校验通过 → 调用 `setAuthenticated(tokenPair)`；若校验失败（过期/格式错误）→ 调用 `clearSession()` 清空不完整数据，调用 `setUnauthenticated()`
   - **输入来源**：Taro Storage 持久化数据
   - **输出去向**：Zustand `SessionStore` 初始化完成——`sessionState` 为 `authenticated` 或 `unauthenticated`
   - **失败行为**：`Taro.getStorageSync` 抛异常（Storage 读写异常）→ 捕获异常，调用 `setUnauthenticated()`，记录结构化日志 `logger.error("session_init_failed", error=err.message)`

2. **步骤 2：请求拦截器注入 Token**
   - **操作对象**：Taro 请求拦截器链中的第一个拦截器函数
   - **具体操作**：在 `Taro.addInterceptor` 的请求拦截器中：(a) 从 Zustand Store 读取 `tokenPair.accessToken`；(b) 若 `accessToken` 非空且请求 URL 不是续期接口 → 设置 `config.header.Authorization = "Bearer " + accessToken`；(c) 若 `accessToken` 为空且 `sessionState` 为 `authenticated`（异常情况）→ 不做注入，记录警告日志 `logger.warning("token_missing_in_authenticated_state")`
   - **输入来源**：Zustand `SessionStore.tokenPair.accessToken`
   - **输出去向**：HTTP 请求的 `Authorization` 头已填充或跳过
   - **失败行为**：不抛异常——无 Token 时不注入 `Authorization` 头（由服务端返回 401 触发后续续期流程）

3. **步骤 3：响应拦截器捕获 401 并触发续期**
   - **操作对象**：Taro 响应拦截器链中的拦截器函数
   - **具体操作**：
     (a) 检查 `response.statusCode === 401` 且 `response.config.url !== '/api/v1/auth/refresh'`。若不满足，直接返回 response；
     (b) 检查 Zustand Store `sessionState`——若为 `refreshing`，执行 `await refreshPromise`（步骤 4 创建的 Promise），续期结果出来后若成功则用 `Taro.request(originalConfig)` 重放原始请求并返回，若失败则 reject；
     (c) 若 `sessionState` 为 `unauthenticated`，直接 reject 不触发续期；
     (d) 若 `sessionState` 为 `authenticated`，保存原始请求配置 `originalConfig`，调用 `setRefreshing()`（Zustand action），进入步骤 4
   - **输入来源**：Taro 响应的 `statusCode` 字段、`response.config.url` 字段
   - **输出去向**：成功时返回重放请求的响应；失败时 reject
   - **失败行为**：401 但 URL 是续期接口本身 → 直接 reject 不重试（防止死递归）。401 且状态为 `unauthenticated` → 直接 reject

4. **步骤 4：执行 Token 续期**
   - **操作对象**：`tokenManager.refreshTokens()` 函数
   - **具体操作**：
     (a) 创建 `refreshPromise = tokenManager.refreshTokens()`；
     (b) `tokenManager.refreshTokens()` 内部：(i) 从 Zustand Store 读取 `tokenPair.refreshToken`；(ii) 发送 `POST /api/v1/auth/refresh`，请求体 `{ refresh_token: refreshToken }`，超时 10s；(iii) 成功（HTTP 2xx）→ 从响应提取 `{ access_token, refresh_token }`，转换为 `TokenPair { accessToken, refreshToken }`，调用 `setAuthenticated(newTokenPair)`（更新 Zustand Store），调用 `Taro.setStorageSync('auth:token_pair', JSON.stringify(newTokenPair))`（写入 Storage），重置 `refreshFailCount = 0`，记录日志 `logger.info("token_refresh_success")`；
     (c) `tokenManager.refreshTokens()` catch：(i) 失败计数 `refreshFailCount += 1`；(ii) 若 `refreshFailCount < 3` → 调用 `setAuthenticated(currentTokenPair)`（状态回 Authenticated，Token 不清除，等待下次 401 触发续期），记录日志 `logger.warning("token_refresh_fail", fail_count=refreshFailCount)`；(iii) 若 `refreshFailCount >= 3` → 调用 `clearSession()`：清除 `Taro.removeStorageSync('auth:token_pair')` + `Taro.removeStorageSync('auth:token_pair:timestamp')`，Zustand `setUnauthenticated()`，`Taro.reLaunch({url: '/pages/login/index'})`，记录日志 `logger.error("session_cleared", reason="refresh_fail_3_times")`
   - **输入来源**：Zustand Store 中的 `tokenPair.refreshToken`
   - **输出去向**：成功时更新 Zustand Store + Taro Storage；失败时 reject Promise
   - **失败行为**：网络超时（>10s）→ 视为失败，计入计数。网络断开（`wx.getNetworkType` 返回 `'none'`）→ 不计入计数

5. **步骤 5：续期成功后重放等待请求**
   - **操作对象**：所有等待 `refreshPromise` 的请求
   - **具体操作**：在 `refreshPromise.then((newTokens) => { ... })` 中：(a) 遍历所有 `await refreshPromise` 的请求；(b) 为每个原始请求配置 `originalConfig` 更新 `Authorization: Bearer <newTokens.accessToken>`；(c) 调用 `Taro.request(originalConfig)` 重发；(d) resolve 重发结果
   - **输入来源**：步骤 3(d) 保存的 `originalConfig`
   - **输出去向**：每个等待请求获得重发后的业务响应
   - **失败行为**：Promise 被 reject 时（续期失败），所有等待请求统一 reject，错误信息 `{ code: 'SESSION_EXPIRED', message: '登录已过期，请重新登录' }`

6. **步骤 6：用户主动登出**
   - **操作对象**：`useAuth().logout()` 函数
   - **具体操作**：(a) 调用 `clearSession()` 清除 Storage 数据和重置 Zustand Store；(b) 调用 `Taro.reLaunch({ url: '/pages/login/index' })`
   - **输入来源**：用户点击登出按钮或业务逻辑触发
   - **输出去向**：页面跳转至登录页
   - **失败行为**：不抛异常——Storage 清除失败仍执行 reLaunch

### 1.6 接口契约 【已锁定】

#### 1.6.1 接口 1：useAuth — 认证状态 Hook

```typescript
function useAuth(): {
  sessionState: 'authenticated' | 'refreshing' | 'unauthenticated';
  isAuthenticated: boolean;
  user: { userId: string; roles: string[] } | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}
```

```
/**
 * 认证状态桥接 Hook —— L1a（表现层）与 L1b（逻辑层）之间的唯一认证接口。
 * 所有 feature 模块通过此 Hook 获取当前会话状态和认证操作方法。
 *
 * Returns:
 *   sessionState: 当前会话状态枚举值，Zustand Store 驱动响应式更新
 *   isAuthenticated: sessionState === 'authenticated' 的便捷布尔值
 *   user: 当前用户信息，未登录时为 null。userId 为 UUID，roles 从 JWT 解析
 *   login: 调用 AUTH-02 登录 API，成功后自动更新 TokenPair 和 sessionState
 *   logout: 清除 Storage 和 Store，reLaunch 到登录页
 *
 * Raises:
 *   LoginError: login() 调用失败（网络错误、凭证无效、服务端错误）
 *
 * Side Effects:
 *   - login() 成功时写入 TokenPair 到 Taro Storage + Zustand Store
 *   - logout() 时清除 Taro Storage + 重置 Zustand Store + reLaunch 登录页
 *
 * Thread Safety:
 *   微信小程序单线程运行，无需考虑多线程竞争。
 *   React 组件中必须在组件顶层调用（遵守 Hooks 规则）。
 */
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `useAuth` —— 语义化 Hook 名称，表达"使用认证"的业务语义 |
| **输入类型** | 无参数（从 Zustand Store 自动订阅） |
| **输出类型** | `useAuthReturn`（详见输出定义 §1.4，契约文件 `docs/contracts/AUTH-06/useAuthReturn.json`） |
| **异常类型** | `LoginError`（详见异常与边界条件 §1.9） |
| **副作用** | login: 写入 Taro Storage + 更新 Zustand Store；logout: 清除 Storage + 重置 Store + reLaunch |
| **幂等性** | login() 在已登录状态下调用会先登出再登录；logout() 在未登录状态下调用是安全的空操作 |

#### 1.6.2 接口 2：httpClient — 统一 HTTP 客户端

```typescript
const httpClient: {
  request: <T>(options: Taro.request.Option) => Promise<Taro.request.SuccessCallbackResult<T>>;
}
```

```
/**
 * 统一 HTTP 客户端 —— 基于 Taro.addInterceptor 封装。
 * 所有 L1b 业务模块必须通过此客户端发送 API 请求，不得绕过拦截器直接使用 Taro.request。
 *
 * 自动行为：
 *   1. 请求拦截器：从 Zustand Store 读取 accessToken 并注入 Authorization: Bearer <token>
 *   2. 响应拦截器：捕获 401 响应 → 触发续期流程 → 续期成功自动重放请求
 *   3. 续期失败 3 次：清除会话 → reLaunch 登录页 → reject 所有等待请求
 *
 * Returns:
 *   Promise<T> — Taro 请求成功回调结果
 *
 * Raises:
 *   SessionExpiredError: 续期连续失败 3 次，会话已清除
 *   RefreshInProgressError: 续期正在进行中（内部使用，不对外暴露）
 *
 * Side Effects:
 *   - 每次请求自动注入 Authorization 头
 *   - 401 时可能触发续期 → 更新 Storage 和 Store
 *   - 续期失败 3 次时清除 Storage + reLaunch
 */
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `httpClient` —— 语义化，表达"HTTP 客户端"的基础设施角色 |
| **输入类型** | `Taro.request.Option`（url, method, data, header 等标准 Taro 请求参数） |
| **输出类型** | `Taro.request.SuccessCallbackResult<T>`（data, statusCode, header） |
| **异常类型** | `SessionExpiredError`（详见异常与边界条件 §1.9） |
| **副作用** | 写入 Authorization 头、可能触发 Storage 写入和 reLaunch |
| **幂等性** | 不保证幂等——每次调用发送独立 HTTP 请求。续期操作自身通过 Promise 队列锁保证不重复 |

### 1.7 依赖与集成接口 【已锁定】

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 微信小程序存储 | Taro Storage | `Taro.getStorageSync(key: string): any` | 同步读取 TokenPair 持久化数据 | `docs/篝火智答-项目结构.md` §6.1（logics/shared/services） |
| 微信小程序存储 | Taro Storage | `Taro.setStorageSync(key: string, data: any): void` | 同步写入 TokenPair 持久化数据 | `docs/篝火智答-项目结构.md` §6.1 |
| 微信小程序存储 | Taro Storage | `Taro.removeStorageSync(key: string): void` | 同步删除 TokenPair 数据 | `docs/篝火智答-项目结构.md` §6.1 |
| HTTP 请求 | Taro.request | `Taro.request(options: Option): Promise` | 发送带拦截器的 HTTP 请求 | `docs/篝火智答-项目结构.md` §6.1（httpClient.ts） |
| 拦截器 | Taro.addInterceptor | `Taro.addInterceptor(interceptor: Interceptor): void` | 注册请求/响应拦截器 | `docs/篝火智答-项目结构.md` §6.1（httpClient.ts） |
| 路由跳转 | Taro Router | `Taro.reLaunch(options: {url: string}): Promise` | 清空页面栈并跳转登录页 | `docs/篝火智答-项目结构.md` §6.1 |
| 全局状态 | Zustand | `create<T>(config: StateCreator<T>): UseBoundStore` | 创建 SessionStore 响应式状态容器 | `docs/篝火智答-项目结构.md` §6.1（store/userStore.ts） |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| AUTH-02 用户登录 | `POST /api/v1/auth/login` — 请求体 `{username, password}`，响应体 `{access_token, refresh_token, token_type}` | useAuth.login() 调用此接口获取 TokenPair | 意图文档已冻结，接口协议待 AUTH-02 spec 冻结 |
| AUTH-03 Token续期 | `POST /api/v1/auth/refresh` — 请求体 `{refresh_token}`，响应体 `{access_token, refresh_token}` | tokenManager.refreshTokens() 调用此接口续期 | 意图文档已冻结，接口协议待 AUTH-03 spec 冻结 |

> AUTH-02/AUTH-03 接口未落地时，AUTH-06 实现应使用 mock 数据：登录返回示例 TokenPair，续期返回新 TokenPair。mock 替换为真实 API 时仅需修改 `tokenManager.ts` 中的 URL 和请求体字段映射。

### 1.8 状态机 【对内实现】

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 副作用 |
|----------|----------|----------|----------|--------|
| `unauthenticated` | `login_success` (AUTH-02 登录成功) | `authenticated` | 用户提供有效凭证，服务端返回 TokenPair | 写入 TokenPair 到 Taro Storage + Zustand Store，重置 `refreshFailCount = 0` |
| `authenticated` | `token_expired` (任意 API 返回 401，且 URL 非续期接口) | `refreshing` | 当前状态为 `authenticated`，`refreshPromise` 为 null | 创建 `refreshPromise`，设置 Zustand `sessionState = 'refreshing'` |
| `refreshing` | `refresh_success` (续期接口返回 HTTP 2xx) | `authenticated` | 续期响应格式正确，包含有效的新 TokenPair | 更新 TokenPair 到 Storage + Store，重置 `refreshFailCount = 0`，重放所有等待请求，置 `refreshPromise = null` |
| `refreshing` | `refresh_fail_soft` (续期失败，`refreshFailCount < 3`) | `authenticated` | 失败次数 < 3，Refresh Token 未清除 | `refreshFailCount += 1`，保持原 Token 不清除（等待下次 401），置 `refreshPromise = null`，所有等待请求 reject |
| `refreshing` | `refresh_fail_hard` (续期失败，`refreshFailCount >= 3`) | `unauthenticated` | 失败次数达到 3 次上限 | 清除 Taro Storage 中 `auth:token_pair` 和 `auth:token_pair:timestamp`，Zustand `setUnauthenticated()`，`Taro.reLaunch('/pages/login/index')`，所有等待请求 reject (`SESSION_EXPIRED`) |
| `authenticated` | `logout` (用户主动登出) | `unauthenticated` | 无前置条件 | 清除 Taro Storage + 重置 Zustand Store，`Taro.reLaunch('/pages/login/index')` |
| `unauthenticated` | `cold_start_expired` (冷启动检测到 Refresh Token 过期) | `unauthenticated` | `app.ts:onLaunch` 执行 `initSession()`，Storage 中无有效 TokenPair 或 Refresh Token 已过期 | 清除不完整 Storage 数据，Zustand Store 置 `unauthenticated` |

### 1.9 异常与边界条件 【对内实现】

#### 1.9.1 异常 1：Token 持久化数据损坏或格式错误
- **触发条件**：
  - `Taro.getStorageSync('auth:token_pair')` 返回值非 `{ accessToken: string, refreshToken: string }` 格式
  - `accessToken` 或 `refreshToken` 为空字符串 `""` 或非 string 类型
  - JWT 格式校验失败（非三段式 `header.payload.signature`，regex: `/^[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+$/`）
- **处理策略**：
  1. 调用 `Taro.removeStorageSync('auth:token_pair')` 和 `Taro.removeStorageSync('auth:token_pair:timestamp')` 清空损坏数据
  2. Zustand Store `setUnauthenticated()`
  3. 记录错误日志：`logger.error("token_data_corrupted", reason="invalid_format")`，上报字段：`stored_type`（实际返回的 JS 类型）、`has_access_token`（布尔）、`has_refresh_token`（布尔）
  4. 用户看到登录页，重新登录即可
- **重试参数**：不重试。数据损坏是不可恢复的状态，只能清空后重新登录。

#### 1.9.2 异常 2：续期接口从非 401 响应中捕获到异常状态码
- **触发条件**：
  - 续期接口返回 HTTP 4xx（非 401，如 403 禁止访问、422 请求体格式错误）
  - 续期接口返回 HTTP 5xx（服务端内部错误）
  - 续期接口请求超时（>10 秒，`Taro.request` 的 `timeout` 配置为 10000ms）
- **处理策略**：
  1. 计数 `refreshFailCount += 1`
  2. 若 `refreshFailCount < 3`：不更新 TokenPair（保持原值），Zustand Store 保持 `authenticated`（不清除 Token，等待下次 401 触发续期），`refreshPromise = null`，所有等待请求 reject
  3. 若 `refreshFailCount >= 3`：执行 `clearSession()`（清除 Storage + `setUnauthenticated()` + `reLaunch('/pages/login/index')`），所有等待请求 reject(`SESSION_EXPIRED`)
  4. 记录结构化日志：`logger.warning("token_refresh_api_error", status_code=xxx, fail_count=n)` 或 `logger.error("token_refresh_timeout", elapsed_ms=xxx, fail_count=n)`
  5. **特殊处理网络断开**：调用 `wx.getNetworkType()` 若返回 `'none'` → 不计入 `refreshFailCount`（网络恢复后下次请求继续尝试续期），记录日志 `logger.info("token_refresh_skipped_offline")`
- **重试参数**：跨请求累计，最多 3 次。每次间隔由用户的下一次 API 操作自然触发，不设固定间隔。续期成功或用户重新登录后计数归零。

#### 1.9.3 异常 3：并发 401 风暴 —— 多个请求同时返回 401
- **触发条件**：
  - 第一个请求触发续期后（`refreshPromise` 已创建），`refreshPromise` 尚未 resolve/reject
  - 其他请求也在响应拦截器中检测到 401
- **处理策略**：
  1. 后续请求检测到 `Zustand Store.sessionState === 'refreshing'` 且 `refreshPromise !== null`
  2. 执行 `await refreshPromise` 挂起当前请求
  3. 续期成功（Promise resolved）：更新原始请求配置的 `Authorization` 头为 `Bearer <newAccessToken>`，调用 `Taro.request(originalConfig)` 重发，resolve 重发结果
  4. 续期失败（Promise rejected）：根据 reject 的 error 类型——若 `refreshFailCount >= 3` 则 reject(`SESSION_EXPIRED`)；若 `refreshFailCount < 3` 则 reject(`REFRESH_IN_PROGRESS_FAILED`)，由业务模块决定是否重试
  5. 记录日志：`logger.info("concurrent_refresh_wait", waiting_requests_count=n)`
- **重试参数**：不主动重试——等待请求由 Promise 队列自动处理。若续期成功，请求重放后获得结果；若续期失败，请求 reject。

#### 1.9.4 异常 4：Taro.setStorageSync 写入失败
- **触发条件**：
  - Storage 总使用量超过微信小程序上限（同步 API 10MB），`setStorageSync` 抛出异常
  - Storage 读写权限被系统拒绝（极低概率）
- **处理策略**：
  1. 捕获 `setStorageSync` 抛出的同步异常
  2. 若为容量超限（`errMsg` 包含 "storage limit"）：先调用 `Taro.removeStorageSync('auth:token_pair')` 清除旧数据，重试 `setStorageSync`
  3. 若重试仍失败：本次登录/续期的 Token 仅保留在内存（Zustand Store）中，不持久化到 Storage。记录错误日志 `logger.error("storage_write_failed", reason="storage_limit_exceeded", retry="failed")`
  4. 后果：进程结束后 Token 丢失，下次冷启动时需重新登录。对用户透明——下次打开小程序时会看到登录页。
- **重试参数**：清除旧数据后重试 1 次。仍失败则降级为仅内存存储。

#### 1.9.5 异常 5：`Taro.reLaunch` 跳转登录页时当前已在登录页
- **触发条件**：
  - 用户在登录页时续期连续失败 3 次
  - 用户在登录页时冷启动检测到 Token 过期
- **处理策略**：
  1. 在 `clearSession()` 中调用 `Taro.reLaunch` 前检查当前页面路由
  2. 通过 `Taro.getCurrentPages()` 获取当前页面栈，检查最后一页的 `route` 字段
  3. 若当前已在 `/pages/login/index` → 跳过 `reLaunch`，仅更新 Zustand Store 和清除 Storage
  4. 记录日志：`logger.info("session_cleared_already_on_login")`
- **重试参数**：不适用。

### 1.10 验收测试场景 【对内实现】

#### 1.10.1 正向测试 1：登录后 Token 持久化并冷启动恢复

- **场景**：用户成功登录，关闭小程序后重新打开，会话自动恢复
- **Given**: 用户凭证有效，AUTH-02 登录 API mock 返回 `{access_token: "eyJ...v1", refresh_token: "eyJ...r1", token_type: "Bearer"}`
- **When**: 
  1. 调用 `useAuth().login("testuser", "password123")`
  2. 模拟小程序关闭（进程终止）
  3. 模拟小程序重新启动，`app.ts:onLaunch` 执行 `initSession()`
- **Then**:
  - 步骤 1 后：`useAuth().isAuthenticated === true`，`useAuth().sessionState === "authenticated"`
  - 步骤 1 后：`Taro.getStorageSync('auth:token_pair')` 返回 `{accessToken: "eyJ...v1", refreshToken: "eyJ...r1"}`
  - 步骤 3 后：`useAuth().isAuthenticated === true`，`useAuth().sessionState === "authenticated"`
  - 步骤 3 后：`useAuth().user` 不为 null

#### 1.10.2 正向测试 2：401 自动续期并重放原始请求

- **场景**：访问令牌过期，API 返回 401，系统自动续期并重发原始请求成功
- **Given**: 
  - Zustand Store 中有有效的 TokenPair（accessToken 已过期，refreshToken 有效）
  - AUTH-03 续期 API mock 返回 `{access_token: "eyJ...v2", refresh_token: "eyJ...r2"}`
  - 业务 API mock 在 Authorization 头为新 Token 时返回 `{data: "profile_data"}`
- **When**: 调用 `httpClient.request({url: '/api/v1/profiles', method: 'GET'})`
- **Then**:
  - 第一次请求：发送 Authorization 头为旧 Token，收到 mock 401 响应
  - 系统自动调用 `POST /api/v1/auth/refresh`，请求体 `{refresh_token: "eyJ...r1"}`
  - 续期成功后：Taro Storage 中 TokenPair 更新为新值 `{accessToken: "eyJ...v2", refreshToken: "eyJ...r2"}`
  - 原始请求使用新 Token 重发，返回 `{data: "profile_data"}`
  - `useAuth().sessionState` 从 `authenticated` → `refreshing` → 短暂回到 `authenticated`
  - 用户整个过程无任何 UI 提示

#### 1.10.3 正向测试 3：用户主动登出

- **场景**：用户点击登出按钮，会话被清除并跳转登录页
- **Given**: 用户处于已登录状态，`useAuth().isAuthenticated === true`
- **When**: 调用 `useAuth().logout()`
- **Then**:
  - `useAuth().isAuthenticated === false`，`useAuth().sessionState === "unauthenticated"`
  - `Taro.getStorageSync('auth:token_pair')` 返回 null/undefined（存储已清除）
  - `useAuth().user === null`
  - `Taro.reLaunch` 被调用，参数 `{url: '/pages/login/index'}`
  - 无异常抛出

#### 1.10.4 异常测试 1：续期连续失败 3 次后会话清除

- **场景**：Refresh Token 已过期，连续 3 次 API 请求因 401 触发续期均失败
- **Given**: Zustand Store 中的 refreshToken 已过期，AUTH-03 续期 API mock 始终返回 HTTP 401
- **When**: 
  1. 第一次调用 `httpClient.request({url: '/api/v1/profiles'})` → 续期失败，`refreshFailCount = 1`
  2. 第二次调用 `httpClient.request({url: '/api/v1/cases'})` → 续期失败，`refreshFailCount = 2`
  3. 第三次调用 `httpClient.request({url: '/api/v1/tickets'})` → 续期失败，`refreshFailCount = 3`
- **Then**:
  - 第三次失败后：`Taro.removeStorageSync('auth:token_pair')` 被调用
  - `useAuth().sessionState === "unauthenticated"`
  - `Taro.reLaunch({url: '/pages/login/index'})` 被调用
  - 所有 3 个请求均被 reject，错误码 `SESSION_EXPIRED`
  - 结构化日志中记录了 `logger.error("session_cleared", reason="refresh_fail_3_times")`

#### 1.10.5 异常测试 2：并发 401 时仅发起一次续期

- **场景**：3 个请求同时返回 401，系统仅发起 1 次续期并统一处理所有等待请求
- **Given**: 
  - accessToken 已过期，refreshToken 有效
  - AUTH-03 续期 API mock 返回新 TokenPair（延迟 500ms 模拟网络）
- **When**: 几乎同时调用 3 个 `httpClient.request()` 到不同 API 端点
- **Then**:
  - `POST /api/v1/auth/refresh` 仅被调用 1 次（mock 调用计数为 1）
  - 续期成功后，3 个原始请求均使用新 Token 重发并成功返回
  - `refreshFailCount` 为 0（续期成功后归零）
  - 等待期间 `refreshPromise` 被 3 个请求共享

#### 1.10.6 异常测试 3：冷启动时存储数据损坏

- **场景**：Taro Storage 中 Token 数据格式错误（如仅有 accessToken 无 refreshToken）
- **Given**: `Taro.getStorageSync('auth:token_pair')` mock 返回 `{accessToken: "eyJ...v1"}`（缺少 refreshToken）
- **When**: 小程序冷启动，`app.ts:onLaunch` 执行 `initSession()`
- **Then**:
  - 结构校验失败：检测到 `refreshToken` 缺失
  - `Taro.removeStorageSync('auth:token_pair')` 被调用（清空不完整数据）
  - `useAuth().sessionState === "unauthenticated"`
  - 无异常抛出（优雅降级）
  - 日志记录：`logger.error("token_data_corrupted", reason="invalid_format")`

### 1.11 注意事项与禁止行为 【对内实现】

1. **[约束 1 — 接口冻结]** httpClient 和 useAuth Hook 的接口签名（§1.6 已锁定）被 6 个下游模块依赖。任何对 `httpClient.request()` 的参数签名、`useAuth()` 返回结构的变更都将级联影响所有前端 feature 模块。接口变更前必须在模块依赖关系分析中更新 Coupling Point #3 并通知所有消费方。

2. **[约束 2 — Taro Storage 同步 API 的 try-catch 包围]** `Taro.setStorageSync` 在 Storage 容量超限时会抛出同步异常。所有 `setStorageSync` 调用必须包裹在 try-catch 块内，并实现降级策略（§1.9.4）。不能假设 `setStorageSync` 总是成功。

3. **[易错点 1 — 请求拦截器中避免死递归续期]** 响应拦截器捕获 401 时必须检查 `response.config.url` 不是 `/api/v1/auth/refresh`。若续期接口本身也因某种原因返回 401，不应再次触发续期（死递归）。此时应直接 reject。

4. **[易错点 2 — JWT exp 时间戳解析]** 冷启动恢复时校验 Refresh Token 过期需正确解析 JWT payload。`exp` 声明是 Unix 时间戳（秒），前端比较时需转换为毫秒：`payload.exp * 1000 > Date.now()`。注意 `JSON.parse(atob(payloadBase64))` 在微信小程序中对中文 Base64 的兼容性问题——payload 段应只含 ASCII 字符。

5. **[禁止行为]**
   - 禁止在业务模块中直接调用 `Taro.setStorageSync('auth:token_pair', ...)` 读写 Token 数据——必须通过 `tokenManager`
   - 禁止在 `login()` 或 `refreshTokens()` 的响应处理中忽略 `refresh_token` 字段——Refresh Token 轮换是安全基础
   - 禁止将 `accessToken` 或 `refreshToken` 通过 URL 查询参数、页面路径参数传递
   - 禁止绕过 Zustand Store 的 action 直接修改 `sessionState` 字段——例如 `userStore.setState({sessionState: 'authenticated'})` 而不是调用 `setAuthenticated()`
   - 禁止在 `clearSession()` 中删除 `auth:token_pair` 之外的存储键——用户的业务数据（草稿、设置等）不受会话清理影响

6. **[偷懒红线]** 绝对禁止以"这个很简单"、"和 AUTH-02 登录类似"、"参考 httpClient 最佳实践"为由省略 Token 校验、异常计数、并发锁、日志记录等任何步骤的实现细节。

### 1.12 文档详细度自检清单 【对内实现】

- [x] 文档自包含：不了解本项目代码的 Agent 仅凭此文档即可完成 AUTH-06 全部编码
- [x] 无偷懒表述：全文无 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`
- [x] 类型定义完整：4 个对外契约 JSON Schema 文件均已写入 `docs/contracts/AUTH-06/`，每个字段有 `description` + `examples` + 约束
- [x] 逻辑步骤完整：6 个核心步骤均有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：5 种异常均有精确触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值（Storage 键名 `auth:token_pair`、超时 10s、重试上限 3 次）都已显式写出
- [x] 技术栈绑定明确：Taro 4.x、Zustand 5.x、TypeScript 已列出；禁止绕过拦截器和直接读写 Storage 已明确
- [x] 意图一致性：已确认与已冻结的意图文档一致（详见 §1.15）

### 1.14 外部接口契约清单 【已锁定】

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| TokenPair | `docs/contracts/AUTH-06/TokenPair.json` | shared-model | draft | AUTH-06 | AUTH-05, CSLT-08, PROF-07, CASE-09, TICK-09, KNOW-07 |
| SessionState | `docs/contracts/AUTH-06/SessionState.json` | shared-enum | draft | AUTH-06 | AUTH-05, CSLT-07, CSLT-08, PROF-06, PROF-07, CASE-08, CASE-09, TICK-08, TICK-09, KNOW-06, KNOW-07 |
| useAuthReturn | `docs/contracts/AUTH-06/useAuthReturn.json` | output | draft | AUTH-06 | AUTH-05, CSLT-07, CSLT-08, PROF-06, PROF-07, CASE-08, CASE-09, TICK-08, TICK-09, KNOW-06, KNOW-07 |
| httpClient | `docs/contracts/AUTH-06/httpClient.json` | output | draft | AUTH-06 | CSLT-08, PROF-07, CASE-09, TICK-09, KNOW-07 |

### 1.15 意图一致性声明 【对内实现】

- **配套意图文档**：`AUTH-06-认证会话管理-意图文档.md`
- **冻结时间**：`2026-05-26 22:48:31`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档 §1.6 中的业务字段定义一致（TokenPair 映射 access_token/refresh_token → accessToken/refreshToken）
  - [x] 本落地规范中的状态机实现（§1.8）与意图文档 §1.7 中的状态业务定义一致（三态：已登录/续期中/未登录 → authenticated/refreshing/unauthenticated）
  - [x] 本落地规范中的异常处理策略（§1.9）与意图文档 §1.8 中的异常业务策略一致（4 类异常 + storage 边界异常）
  - [x] 本落地规范中的验收测试场景（§1.10）覆盖意图文档 §1.9 中的所有 8 条验收标准（AC-01 至 AC-08）
  - [x] 本落地规范中的技术实现未超出意图文档 §1.12 中"留给规范阶段的技术决策"的范围（6 项决策均已落实：Storage API 选型、并发锁实现、重试间隔、状态管理、失败判别、跳转方式）
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
