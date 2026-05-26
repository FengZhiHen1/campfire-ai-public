# 1 功能点：AUTH-06 认证会话管理 — 设计文档（瘦身版）

> **文档生成时间**：`2026-05-26 23:00:00`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-26 23:00:00` | AI Assistant | 初始版本，基于技术决策完整报告生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `AUTH-06-认证会话管理-意图文档.md`（已冻结于 2026-05-26 22:48:31）
> - 本模块的精确编码规格见 `AUTH-06-认证会话管理-落地规范.md`

### 1.1 技术实现思路

AUTH-06 是运行在微信小程序客户端的认证基础设施模块，承担用户会话全生命周期的前端管理。采用"**三层分离 + Promise 队列锁**"的架构模式，将 Token 持久化、HTTP 拦截器、会话状态管理拆分为三个独立但协作的技术单元。

**为什么选择三层分离？**

意图文档规定了 6 项业务约束，其中核心是"无感续期"和"并发续期互斥"。若将 Token 存储、请求拦截和状态管理耦合在单一模块中，续期流程将直接依赖存储 API 的状态，导致竞态条件难以处理——例如多个 401 响应同时尝试读写 Storage 时可能覆盖新写入的 Token 对。三层分离后，Zustand Store 作为唯一的状态源，Taro Storage 作为纯持久化层，httpClient 拦截器仅读取 Store 状态而不直接操作 Storage，彻底避免了跨层竞态。

**数据流向设计**

```
用户操作 → Taro.request() → 请求拦截器注入 Authorization 头
  → 服务端返回 401 → 响应拦截器捕获 → 检查 Zustand Store 状态
    → 若 state=Authenticated → 状态切换为 Refreshing → 创建 refreshPromise
    → 调用 tokenManager.refreshTokens() → 服务端续期接口
      → 成功：新 TokenPair 写入 Zustand Store + Taro Storage → 重放等待队列中所有请求
      → 失败：计数器 +1 → 若 <3 则状态回 Authenticated（Token 不清除，等待下次 401）
                      → 若 ≥3 则状态置 Unauthenticated → 清除 Taro Storage → reLaunch 登录页
```

**关键设计决策**

1. **Token 存储使用同步 API**（`Taro.setStorageSync`/`getStorageSync`）。意图文档要求冷启动自动恢复会话，同步 API 在 `app.ts` 的 `onLaunch` 生命周期中可立即完成读取并初始化 Zustand Store，无需处理异步时序问题。微信小程序 Storage 沙箱天然隔离，无需额外加密层。

2. **续期并发锁采用 Promise 队列模式**。维护单例 `refreshPromise: Promise<TokenPair> | null`——这是持续期锁的最高效实现。第一个 401 创建 Promise 并赋给 `refreshPromise`，后续 401 检测到该变量非 null 时直接 `await` 同一 Promise，续期完成后所有并发请求同时获得新 Token。Promise 原生的 then/catch 链式回调天然支持成功统一重放、失败统一拒绝，无需引入第三方队列库。

3. **续期失败计数跨请求累计**。与"单次重试"模式的关键区别：第一次续期失败后不清空 Storage（Refresh Token 可能因网络波动暂时不可达），用户下一次操作触发 401 时再次尝试续期，而非在同一个 401 上下文中立即重试 3 次——后者会让用户连续看到 3 次超时等待。跨请求累计在正常情况下仅有一次续期请求（因为第一次成功后计数器归零），仅在网络持续不可用时逐步逼近 3 次上限，满足意图文档"对用户无感"的约束。

4. **会话状态双重持久化**。Zustand Store 管理运行时响应式状态（各 feature 模块通过 `useAuth()` Hook 同步感知），Taro Storage 作为持久化锚点（冷启动恢复）。两者分工明确：Zustand 保证跨页面响应性，Storage 保证进程间持久性。冷启动时先读 Storage，再初始化 Store，确保恢复过程中不会短暂展示"未登录"界面后突然跳变。

5. **httpClient 架构基于 `Taro.addInterceptor`**。Taro 原生拦截器机制在 framework 层注入，所有 `Taro.request()` 调用自动被拦截，无需在业务代码中手动添加 Token 注入逻辑。请求拦截器读取 Zustand Store 的 Token 写入 Authorization 头；响应拦截器捕获 401 后触发续期流程。两者通过 Zustand Store 解耦——请求拦截器不需要知道 Token 来源是登录还是续期，响应拦截器不需要操作 Storage。

6. **登录页跳转使用 `Taro.reLaunch`**。`reLaunch` 清空全部页面栈后打开登录页，防止用户通过返回按钮回到已失去会话的功能页。MVP 阶段不存储登录前页面路径——登录后统一跳转首页，简化路由状态管理。登录前路径恢复功能待后续迭代添加。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：
  - AUTH-01 用户注册-设计文档.md（已冻结）
  - AUTH-04 五级RBAC鉴权-设计文档.md（已冻结）
  - AUTH-02 用户登录-意图文档.md（已冻结）
  - AUTH-03 Token续期-意图文档.md（已冻结）
  - KNOW-01 科普内容管理-落地规范.md（已冻结）
  - `docs/功能设计/_contracts.md`（契约索引）
  - `docs/功能设计/模块依赖关系分析.md`
  - `docs/contracts/SEC-01/create_access_token.json`
  - `docs/contracts/SEC-01/verify_token.json`
  - `docs/contracts/AUTH-01/RegisterRequest.json`
  - `docs/contracts/AUTH-01/UserRole.json`
  - `docs/contracts/AUTH-04/require_role.json`

- **兼容性结论**：
  - **无冲突**：AUTH-06 是前端 TypeScript/Taro 模块，所有已有规格文档均为后端 Python/FastAPI 模块，运行在不同技术栈且通过 HTTP API 交互，不存在类型定义或接口命名冲突。
  - AUTH-02 意图文档 §1.11 约束 8 明确声明"不负责前端 Token 的持久化存储和请求拦截注入——该职责归属 AUTH-06"，边界清晰。
  - AUTH-03 意图文档 §1.11 约束 6 明确声明"不负责前端的 Token 存储和自动续期触发逻辑——该职责归属 AUTH-06"，边界清晰。
  - AUTH-04 落地规范中 `require_role()` 的 `request.state.user` 注入路径与 AUTH-06 的 Bearer Token 注入为前后端独立操作，无冲突。

- **复用的已有设计**：无直接复用的已有类型定义。AUTH-06 为项目首个前端基础设施模块，其对外接口（httpClient、tokenManager、useAuth）均为全新定义。AUTH-01 的 `UserRole` 枚举和 SEC-01 的 `create_access_token` 契约作为上游 API 协议被引用，但类型实现层由 AUTH-06 自行维护 TypeScript 对应类型定义。

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| AUTH-02 用户登录模块 | 上游数据来源 | 接收 `POST /api/v1/auth/login` 响应中的 `access_token: string`、`refresh_token: string`、`token_type: "Bearer"` 三个字段，写入 tokenManager |
| AUTH-03 Token续期模块 | 上游接口依赖 | 调用 `POST /api/v1/auth/refresh`，请求体 `{refresh_token: string}`，接收响应中的新 `access_token` 和 `refresh_token`（轮换后的 Refresh Token） |
| AUTH-04 五级RBAC鉴权模块 | 下游数据消费 | 通过 Bearer Token 注入请求头 `Authorization: Bearer <access_token>`，服务端 SEC-01 校验后从 JWT payload 提取 `sub` 和 `roles` 字段，供 AUTH-04 鉴权使用 |
| Taro.request | 框架级依赖 | 通过 `Taro.addInterceptor` 在 request 和 response 链上注入拦截逻辑。所有业务模块的 API 调用（CSLT-08、PROF-07、CASE-09、TICK-09、KNOW-07）经过拦截器时自动完成 Token 注入和 401 续期 |
| Taro Storage | 平台依赖 | 使用同步 API `Taro.setStorageSync(key, data)` 持久化 TokenPair，`Taro.getStorageSync(key)` 恢复，`Taro.removeStorageSync(key)` 清除。存储键名 `auth:token_pair`，值格式 `{accessToken, refreshToken}` |
| Zustand Store | 库依赖 | `create()` 初始化 `SessionStore` interface，管理 `sessionState`、`tokenPair` 和 5 个 action 方法。所有 feature 模块通过 `useAuth()` Hook 获取认证状态 |
| Taro Router | 平台依赖 | 会话清理后调用 `Taro.reLaunch({url: '/pages/login/index'})` 跳转登录页，关闭所有页面栈 |
| 6 个 L1b 前端逻辑模块 | 下游消费者 | CSLT-08（咨询编排）、PROF-07（档案数据逻辑）、CASE-09（案例数据逻辑）、TICK-09（工单数据逻辑）、KNOW-07（科普数据逻辑）、AUTH-05（登录注册界面）——全部通过 httpClient 发送 API 请求，通过 useAuth Hook 感知会话状态 |

> 精确的函数签名、TypeScript 类型定义见落地规范。

### 1.4 状态机设计（技术实现策略）

AUTH-06 管理前端会话的三态状态机，技术实现核心是 Zustand Store 中的 `SessionState` 枚举驱动。

```
                    ┌─────────────────────────────────────────┐
                    │                                         │
                    ▼                                         │
            ┌──────────────┐    401 响应触发续期     ┌──────────────┐
            │              │ ──────────────────────► │              │
            │ Authenticated│                         │  Refreshing  │
            │  (已登录)     │ ◄────────────────────── │  (续期中)     │
            │              │    续期成功，更新令牌      │              │
            └──────────────┘                         └──────┬───────┘
                    │                                       │
                    │ 用户主动登出                            │ 续期连续失败 3 次
                    │ 或冷启动令牌过期                         │
                    ▼                                       ▼
            ┌──────────────┐                         ┌──────────────┐
            │              │                         │              │
            │Unauthenticated│◄────────────────────────│              │
            │  (未登录)     │                         │              │
            │              │                         │              │
            └──────────────┘                         └──────────────┘
                    │
                    │ 用户重新登录成功（来自 AUTH-02）
                    └─────────────────────────────────────────────► Authenticated
```

**技术实现策略**：

- **状态持久化方案**：采用 Zustand Store（内存）+ Taro Storage（磁盘）双重持久化。Zustand 保证跨页面响应式状态同步，Taro Storage 保证进程间持久性。冷启动恢复流程在 `app.ts:onLaunch` 中同步执行：`getStorageSync('auth:token_pair')` → 解析并验证 → 初始化 Zustand Store → 根据 Refresh Token 过期时间判断初始状态。
- **状态转换原子性**：所有状态变更通过 Zustand Store 的 action 方法统一执行，不允许外部直接修改 `sessionState` 字段。`setRefreshing()` 方法内部检查当前状态——仅 `Authenticated` 状态下允许进入 `Refreshing`；`setUnauthenticated()` 方法内部清除 TokenPair、重置失败计数、调用 `Taro.removeStorageSync`。
- **幂等策略**：续期操作本身幂等——即使续期成功但前端未收到响应（网络闪断），因 Refresh Token 已被轮换，重复续期会失败，此时前端应清空会话（降级为 Unauthenticated）。`setRefreshing()` 方法内部检查是否已在 `Refreshing` 状态——若已在则跳过，确保并发 401 不会重复创建续期 Promise。
- **失败计数生命周期**：失败计数存储在 Zustand Store 的 `refreshFailCount` 字段中。每次续期失败 +1，续期成功或用户重新登录时归零。冷启动无计数恢复——冷启动时 Refresh Token 有效则计数为 0，Refresh Token 过期直接置 Unauthenticated 不经过计数逻辑。

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| 2.1 | 单一职责 | AUTH-06 仅负责客户端 Token 生命周期管理，不涉及服务端签发/校验（归属 AUTH-02/SEC-01）、不涉及权限判定（归属 AUTH-04）、不涉及 UI 渲染（归属 AUTH-05）。httpClient、tokenManager、useAuth 三个模块各自职责单一——httpClient 负责请求拦截和续期触发，tokenManager 负责 Storage 的 CRUD，useAuth 负责 Zustand Store 的读写封装 |
| 2.2 | 接口隔离 | useAuth Hook 作为 L1b（逻辑层）与 L1a（表现层）的唯一桥梁，只暴露 `sessionState`、`isAuthenticated`、`user`、`login`、`logout` 5 个字段/方法，不暴露 tokenManager 内部实现细节、Storage 操作接口或 httpClient 拦截器配置 |
| 3.5 | 可观测性 | 拦截器中的关键节点（Token 注入、401 捕获、续期发起、续期成功/失败）均通过 OBS-01 结构化日志上报。上报字段包含 `trace_id`（与业务请求关联）、`event_type`（token_injected / token_refresh_start / token_refresh_success / token_refresh_fail / session_cleared）、`fail_count`（当前失败计数） |
| 1.2 | 反伪契约 | tokenManager 从 Taro Storage 读取 TokenPair 后执行结构校验——验证 `accessToken` 和 `refreshToken` 均为非空 string 且格式满足 JWT 三段式（header.payload.signature），校验失败时直接清空不完整数据并置 Unauthenticated，不静默接受畸变数据 |
| 5.x | 防御性设计 | 微信小程序 Storage 同步 API 有 10MB 容量上限——`setStorageSync` 调用异常时（如 `errMsg` 包含 "storage limit exceeded"），降级策略为清除旧 Token 数据后重试写入；若仍失败则本次登录不持久化 Token（会话仅存在于内存中，进程结束后需重新登录）。这是低概率边缘情况的优雅降级 |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| Token 存储方式 | `Taro.setStorageSync` / `getStorageSync` 同步 API | `Taro.setStorage` / `getStorage` 异步 API | 同步 API 在 `app.ts:onLaunch` 中完成读取并初始化 Zustand Store 是原子操作——冷启动恢复必须在渲染前完成状态初始化，否则会出现"未登录→已登录"的界面闪跳。异步 API 需要在 Promise 回调中再初始化 Store，增加了注入初始状态的时序复杂度。（受意图文档 AC-01 约束） |
| 并发续期锁 | Promise 队列锁：`refreshPromise ??= tokenManager.refreshTokens()` | (a) 请求队列（手动维护 pending 数组）; (b) 互斥布尔标志 `isRefreshing` | Promise 队列最轻量——`refreshPromise?.then(token => retry(request))` 仅需一行即可将等待请求挂到续期完成回调。请求队列方案需要维护数组和手动 dequeue，增加代码量和管理复杂度。互斥标志方案需要手动轮询或事件订阅。（受意图文档 §1.11 约束 3 约束） |
| 续期失败重试策略 | 跨请求累计计数，无固定间隔 | 固定间隔 retry（如 500ms x3） | 意图文档要求续期对用户无感——固定间隔重试会让用户看到 3 次连续的加载等待。跨请求累计在正常情况下仅发起 1 次续期（成功后计数归零），仅在网络持续不可用时逐步逼近上限，用户体验更平滑。（受意图文档 §1.11 约束 1 约束） |
| 会话状态管理 | Zustand Store 双重持久化 | (a) 仅 Zustand 内存状态（不持久化 Token）; (b) 仅 Taro Storage 全局读写（无响应式） | (a) 不满足 AC-01（冷启动恢复）；(b) 各 feature 模块需要手动轮询 Storage 以感知状态变更，复杂度高。双重持久化兼顾响应性和持久性：Zustand 提供 O(1) 状态读取和响应式订阅，Storage 提供进程间持久化锚点。（受意图文档 AC-01、AC-07 约束） |
| 登录页跳转方式 | `Taro.reLaunch({url: '/pages/login/index'})` | (a) `Taro.redirectTo`; (b) `Taro.navigateTo` | `reLaunch` 清空全部页面栈——用户在功能页上被意外登出后不应通过返回按钮回到已失效的会话页。`redirectTo` 仅替换当前页但保留上层页面栈（如 tab 页），`navigateTo` 叠加页面栈（可返回），均存在安全隐患。MVP 阶段不存储登录前页面路径，登录后统一跳转首页。 |
| httpClient 架构 | `Taro.addInterceptor` 原生拦截器 | (a) Axios wrapper; (b) 手动在每个 API 调用中注入 Token | Taro 4.x 原生支持 `addInterceptor`，不引入额外依赖。Axios 在 Taro 中需要额外适配且增加包体积。手动注入方案需要在每个业务 API 中写 Token 注入代码，违反单一职责且无法统一处理 401 续期。（受项目技术栈设计约束） |

### 1.7 注意事项与禁止行为（设计层面）

1. **[高危耦合点]** 模块依赖关系分析 §6 耦合点 #3 明确指出：AUTH-06 的 httpClient 和 useAuth Hook 接口被 CSLT-08、PROF-07、CASE-09、TICK-09、KNOW-07、AUTH-05 共 6 个前端模块依赖。httpClient 的 Token 注入头格式（`Authorization: Bearer <token>`）和 useAuth 的 `isAuthenticated` 字段签名一旦确定后不应修改，否则将级联影响所有前端业务模块。

2. **[上游协议冻结依赖]** AUTH-06 的续期逻辑直接依赖 AUTH-02 登录接口和 AUTH-03 续期接口的请求/响应格式。若 AUTH-02/AUTH-03 的 API 协议在 AUTH-06 实现后发生变更（如 Refresh Token 传递方式从请求体改为请求头），将导致续期逻辑需要重写。**上游接口必须先于 AUTH-06 冻结。**

3. **[设计边界]** AUTH-06 不负责以下事项：
   - 服务端的 Token 签发、校验和续期逻辑（归属 AUTH-02 / SEC-01 / AUTH-03）
   - 用户角色的判断和权限校验（归属 AUTH-04）
   - 登录/注册 UI 的渲染和交互逻辑（归属 AUTH-05）
   - API 请求的业务逻辑（由各 L1b feature 模块自行调用 httpClient）
   - 服务端 Rate Limiting 和防攻击策略（归属 SEC-04）

4. **[禁止行为]**
   - 禁止在业务模块中重复实现 Token 注入逻辑——所有 API 调用必须通过 httpClient，不得绕过拦截器直接使用 `Taro.request`
   - 禁止 Token 数据以明文形式写入非 Storage 区域（如页面参数、全局变量暴露窗口）——这违反意图文档 §1.11 约束 4
   - 禁止在 `Refreshing` 状态期间发起第二个续期请求——Promise 队列锁必须严格互斥
   - 禁止会话清理时删除用户的业务数据（如草稿、本地设置、浏览历史）——仅清除 `auth:token_pair` 存储键
   - 禁止绕过 Zustand Store 的 action 方法直接修改 `sessionState` 或 `tokenPair` 字段

5. **[易错点]**
   - 续期请求本身不应被拦截器的 401 逻辑再次触发（死递归）——响应拦截器必须检查 `response.config.url` 不是续期接口
   - 冷启动恢复后可能处于"Refresh Token 存在但 Access Token 过期"状态——此时不能自动置 Authenticated，但也不能置 Unauthenticated（因为 Refresh Token 仍有效）。应置 Authenticated 然后由第一次 API 调用的 401 自然触发续期
   - `Taro.setStorageSync` 需放在 try-catch 块内——Storage 写满（>10MB）时会抛同步异常而非静默失败

### 1.8 引用：配套意图文档

- **意图文档**：`AUTH-06-认证会话管理-意图文档.md`
- **冻结时间**：`2026-05-26 22:48:31`
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。三态状态机（Authenticated / Refreshing / Unauthenticated）精确映射意图文档 §1.7；异常策略（§1.9.1-§1.9.4）的技术实现策略（§1.4、§1.6）完整覆盖意图文档 §1.8 的 4 类异常场景。如有歧义，以意图文档为准。

> **商务矛盾待裁决项**（来源：技术决策报告 §5）：
> 1. Refresh Token 快过期时的预刷新策略 — 设计文档当前采纳报告推荐方案：不进行预刷新，接受冷启动时引导重新登录
> 2. 登录后页面路径还原 — 设计文档当前采纳 MVP 简化方案：登录后统一跳转首页，不存储还原路径
> 3. 多设备令牌互斥 — 设计文档当前未纳入该功能，MVP 阶段允许多设备各自独立管理 Token 生命周期
> 4. 存储键名前缀规范 — 设计文档当前使用 `auth:token_pair` 作为键名，待项目级存储键名规范确立后调整
