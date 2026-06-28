# 1 功能点：PROF-07 档案数据逻辑 — 设计文档（瘦身版）

> **文档生成时间**：`2026-05-27 21:37:35`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-27 21:37:35 | AI Assistant | 初始版本，基于技术预研报告（8 项决策 + 4 项业务矛盾）生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `PROF-07-档案数据逻辑-意图文档.md`（已冻结，v2.0）
> - 本模块的精确编码规格见 `PROF-07-档案数据逻辑-落地规范.md`

### 1.1 技术实现思路

PROF-07 是前端 L1b 逻辑层模块，位于 `apps/mini-program/src/logics/profiles/`，属于 L7 前端逻辑层（项目结构六层架构的最顶层逻辑层）。其核心职责是编排三个业务流程的技术数据流：冷启动引导、微问卷沉淀和档案数据管理。

**为什么用 Zustand 而非 React Query**：项目已统一选用 Zustand 5 作为全局状态管理方案（技术栈设计 §2），且档案模块是简单 CRUD，Zustand + 手动缓存策略可满足需求。React Query 的自动缓存/重取在档案场景中是过度设计——档案数据由用户主动触发变更，不存在多端实时同步需求，SWR（stale-while-revalidate）手动实现即可。

**三流程的技术实现思路**：

冷启动引导流程——由 CSLT-08 在咨询编排的第一步调用 `checkProfileExists()`（查询 profileStore.list 或触发一次 API 请求），返回 `false` 时 CSLT-08 暂停后续编排，弹出冷启动表单。用户完成 3 项下拉选择后，PROF-07 调用 `profileApi.createProfile()` → PROF-01 POST `/api/v1/profiles`，成功后 profileStore 写入新档案并标记 `is_default=true`，随后返回 `ProfileResponse` 给 CSLT-08 通知编排继续。检测结果不缓存（意图文档要求每次咨询前实时检测，用户可能在另一设备创建了档案）。

微问卷沉淀流程——CSLT-08 在 SSE 流式消费完成（`finish_reason=COMPLETE`）后调用 `triggerMicroSurvey(consultationId)`。PROF-07 的 `useMicroSurvey()` Hook 将 `MicroSurveyState` 置为 `showing`，驱动浮层组件弹出 2 题（触发因素确认 + 干预有效性反馈）。同一 `consultationId` 通过内存 `Set<string>` 去重保障不重复弹出。用户回答后，PROF-07 调用 `profileApi.updateProfile()` → PROF-01 PUT `/api/v1/profiles/{id}` 将触发因素追加到 `triggers` 数组、干预有效性反馈写入 PROF-03 事件记录（仅当用户明确回答了才写入）。用户跳过则将 `consultationId` 标记为 `skipped`，微问卷组件静默关闭。

档案数据管理流程——PROF-06 通过 `useProfile()` Hook 消费档案列表/详情和 CRUD 操作方法。列表数据采用 SWR 策略：初始化时从 `profileStore.list`（可能为空）读取并立即渲染，同时触发 `profileApi.listProfiles()` 后台请求，成功后更新 store 使 UI 响应式刷新。用户编辑提交时表单置为 `submitting` 禁用按钮（幂等防重复），提交成功更新 store 缓存并触发变更通知（fire-and-forget HTTP 调用通知 PROF-02），提交失败保留表单数据并展示错误提示。

**数据流的宏观架构**：

```
PROF-06 (views) ──useProfile()──▶ PROF-07 (logics) ──httpClient──▶ PROF-01 API (后端)
CSLT-08 (logics) ──ProfileCoordination──▶ PROF-07 (logics) ──httpClient──▶ PROF-02 API (后端)
                                                                       ──httpClient──▶ PROF-03 API (后端)
```

所有对外 HTTP 请求经 `logics/profiles/services/profileApi.ts` 封装，统一使用 AUTH-06 `httpClient`（项目结构 §9.4 硬性约束）。401 自动续期、Token 注入由 AUTH-06 拦截链处理，profileApi 层仅关注请求/响应映射和业务错误转换。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：
  - `PROF-01-个人档案管理-设计文档.md` v1.0 + 落地规范 v1.0（已冻结）
  - `PROF-03-事件记录管理-落地规范.md` v1.0（已冻结）
  - `PROF-05-档案隐私控制-设计文档.md` v1.0 + 落地规范 v1.0（已冻结）
  - `AUTH-06-认证会话管理-落地规范.md` v1.0（已冻结）
  - `CSLT-01~06` 应急咨询系列落地规范（已冻结）
  - `CASE-09-案例管理逻辑-落地规范.md` v1.0（已冻结，同为前端 L1b 参考实现）
  - `docs/功能设计/功能模块全拆解.md`
  - `docs/功能设计/模块依赖关系分析.md`
  - `docs/功能设计/_contracts.md`
  - `docs/篝火智答-技术栈设计.md` v1.2
  - `docs/篝火智答-项目结构.md` v2.0

- **兼容性结论**：
  - **无冲突**：PROF-07 作为前端逻辑层纯消费者，不定义新后端契约。其 TypeScript 类型直接映射 PROF-01 的 12 份契约（ProfileCreate、ProfileUpdate、ProfileResponse 等），枚举值（DiagnosisType、ProfileBehaviorType、LanguageLevel、SensoryFeature、Trigger、AgeRange）在 `packages/ts-shared/src/enums/` 中声明与后端一致。与 AUTH-06 的 4 份契约（httpClient、SessionState、useAuthReturn、TokenPair）的消费关系已在契约索引中注册。与 CASE-09 同为 L1b 模块，遵循完全一致的 views/logics 分层和 Hook 桥接模式。

- **复用的已有设计**：
  - PROF-01 的 12 份后端契约——全部通过 `profileApi.ts` 转换为 TypeScript 类型（引用模式，不重复定义字段语义）
  - PROF-01 的 6 个枚举体系——在 `packages/ts-shared/src/enums/` 中声明为同名字符串字面量联合类型
  - AUTH-06 的 httpClient 拦截链——HTTP 请求统一走 `httpClient.request<T>()`，401/Refresh 逻辑由拦截链全局处理
  - AUTH-06 的 SessionState 枚举——用于冷启动检测前校验认证状态（`authenticated` 才执行档案查询）
  - PROF-03 的 EventCreate/EventUpdate 契约——微问卷沉淀时供事件记录写入
  - CASE-09 的模块组织结构——Hooks (useXxx) → Services (xxxApi.ts) → Store (xxxStore.ts) → Types (index.ts) 四层架构

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| AUTH-06 httpClient | 框架依赖 | 所有 HTTP 调用走 `httpClient.request<T>(options): Promise<IRequestResponse<T>>`，不裸调 `Taro.request()`。401 自动续期由 AUTH-06 拦截链处理，PROF-07 不重写 |
| AUTH-06 useAuth | 上游服务 | 通过 `useAuthReturn.sessionState` 判断认证状态。`authenticated` 才执行档案数据请求，`unauthenticated` 时跳过冷启动检测（无用户上下文）
| PROF-01 档案 CRUD API | 上游服务 | `profileApi.createProfile(ProfileCreate)` → POST /api/v1/profiles；`profileApi.listProfiles()` → GET /api/v1/profiles；`profileApi.getProfile(id)` → GET /api/v1/profiles/{id}；`profileApi.updateProfile(id, ProfileUpdate)` → PUT /api/v1/profiles/{id}；`profileApi.deleteProfile(id)` → DELETE /api/v1/profiles/{id}；`profileApi.setDefault(id)` → PUT /api/v1/profiles/{id}/default。依赖 PROF-01 契约中的 ProfileLimitExceededError (409) 和 ProfileConflictError (409) 错误码 |
| PROF-02 缓存失效 API | 下游通知 | **（⚠️ 依赖缺口——PROF-02 尚未启动设计）** 档案变更后 fire-and-forget 调用 `POST /api/v1/profiles/{profileId}/invalidate-cache`，携带 `{profileId, changedFields}`。若接口不可用（404 或网络错误），降级为 `console.warn`，不阻断用户操作。接口路径为当前最佳推测，需在 PROF-02 设计完成后确认 |
| PROF-03 事件记录 API | 下游通知 | 微问卷中用户回答的触发因素必要时写入事件记录：调用 PROF-03 `POST /api/v1/events`（`EventCreate` 契约），关联当前档案的 `profile_id`。仅当用户显式回答了微问卷问题才触发写入，跳过不写入 |
| CSLT-08 `ProfileCoordination` | 横向协作 | CSLT-08 通过约定的 JS 模块导入调用 `checkProfileExists()`、`triggerMicroSurvey(consultationId)`、`onProfileChanged(callback)`。双向互动采用明确的方法调用 + 回调订阅模式，避免循环 import |
| PROF-06 views/profiles/ | 下游数据消费 | PROF-06 通过 `useProfile()` Hook 获取 `{profiles, isLoading, error}` 和 CRUD 方法。这是 views/logics 分层的唯一桥接通道（项目结构 §9.4） |
| Zustand 5 | 框架依赖 | `profileStore` 管理档案列表、详情缓存、冷启动状态、微问卷状态、表单状态。不持久化到 Taro Storage（页面关闭即清空，符合会话级缓存策略） |
| Taro 4 | 运行时依赖 | 页面路由、小程序生命周期。PROF-07 不直接使用 `Taro.navigateTo`（路由跳转由 PROF-06 views 层负责） |

### 1.4 状态机设计（技术实现策略）

PROF-07 维护三种前端交互态，均在 Zustand store 的内存中管理，不持久化，不跨页面。设计原则：状态转换简单明确，入口从 `idle`/`hidden` 开始，出口到 `ready`/`success`/`hidden`，异常出口到 `error` 并提供回归路径。

**档案列表交互态**：

```
idle ──fetchProfiles()──▶ loading ──请求成功──▶ ready
                                  ──请求失败──▶ error ──手动重试──▶ loading
                         ready ──手动刷新──▶ loading
```

- 幂等策略：`loading` 期间忽略重复的 `fetchProfiles()` 调用。`ready` 状态时手动刷新才进入 `loading`，避免页面切换时的无效重载。

**档案提交交互态**：

```
idle ──submit──▶ submitting ──成功──▶ success ──自动──▶ idle
                            ──网络失败──▶ error ──用户重试──▶ submitting
                            ──校验失败(422)──▶ idle（表单保留 + 内联提示）
                            ──超限(409)──▶ idle（弹窗提示）
                            ──并发冲突(409)──▶ idle（弹窗提示刷新）
```

- 幂等策略：`submitting` 期间按钮 `disabled`，防止重复提交。Zustand store 中的表单数据在提交失败后不丢失，`error`→`submitting` 时恢复上次填写的表单状态。

**微问卷交互态**：

```
hidden ──triggerMicroSurvey(id)──▶ showing ──用户回答──▶ answering ──提交成功──▶ submitted（2s 后自动→hidden）
                                                         ──提交失败──▶ showing（保留用户选择）
                                        ──用户跳过──▶ hidden（标记 consultationId 为 skipped）
```

- 去重策略：`triggerMicroSurvey` 调用时检查内存 `Set<string>`，若 `consultationId` 已存在（已回答或已跳过），直接 no-op。`Set` 在模块加载时初始化为空，页面关闭自然清空。
- 冷启动检测无状态机——每次 `checkProfileExists()` 调用是独立的异步查询，不维护状态缓存。

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| 2.1 | 单一职责 | PROF-07 仅负责档案数据的**前端逻辑编排**：数据获取、状态管理、异常处理、变更通知。不负责 UI 渲染（归属 PROF-06）、不负责隐私判定（归属 PROF-05）、不负责持久化存储（归属 PROF-01）、不负责检索过滤（归属 PROF-02） |
| 2.2 | 接口隔离 | views/logics 分层强制隔离：PROF-06 只能通过 `useProfile()` Hook 获取数据和操作，不能直接 import `profileApi.ts` 或 `profileStore.ts`。CSLT-08 只能通过 `ProfileCoordination` 约定的方法通信，不能直接访问 store 内部状态 |
| 3.1 | 降级友好 | 当 PROF-02 API 不可用时，变更通知降级为 `console.warn` + No-op，不阻断用户操作。当网络异常时展示可读错误文案和手动重试入口，不展示空白页或无意义占位 |
| 3.3 | 数据安全 | 所有 HTTP 请求走 AUTH-06 httpClient（自动 Token 注入），绝不裸调 Taro.request。冷启动检测前校验 `sessionState === 'authenticated'`，未认证时不发起档案查询请求 |
| 3.5 | 可观测性 | 每次 HTTP 调用通过 httpClient 自动记录结构化日志（trace_id、method、url、status、latency）。存储关键用户操作（档案创建、微问卷回答）到前端埋点日志 |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 状态管理 | Zustand 5 `profileStore`（单 Store 管理全部档案状态） | React Query + 分离多个 Query | (a) 项目已统一选用 Zustand 5（技术栈设计 §2），引入新依赖违反技术统一性；(b) 档案为简单 CRUD，Zustand 手动 SWR 足够，React Query 的自动缓存/失效/重取能力过度设计；(c) 单一 Store 维护档案操作的原子性（冷启动创建后立即写入列表缓存，无需跨 Query 同步） |
| 冷启动检测触发 | CSLT-08 编排步骤中显式调用 `checkProfileExists()` | 路由守卫（Taro 页面拦截）或 CSLT-07 组件挂载时自动检测 | (a) 冷启动检测是咨询编排的第一步，由编排层触发最符合业务语义；(b) 路由守卫在 Taro 中实现复杂，且耦合咨询页面路由与档案模块，违反模块单一职责（原则 2.1）；(c) 组件挂载检测将档案逻辑泄漏到 CSLT-07 views 层，违反 views/logics 分层（原则 2.2） |
| 微问卷弹出时机 | CSLT-08 在 SSE 流完成（`finish_reason=COMPLETE`）后调用 `triggerMicroSurvey` | 固定延迟（如 1 秒后自动弹出）或咨询页面卸载时触发 | (a) SSE `COMPLETE` 是最精确的"AI 回答推送完毕"信号，无延迟无早触发；(b) 延迟方案受网络波动影响，固定延迟可能在慢网络下用户还没读完回答就弹出；(c) 页面卸载触发无法捕获用户停留在当前页但已读完内容的情况 |
| 变更通知方式 | Fire-and-forget HTTP `POST /api/v1/profiles/{profileId}/invalidate-cache` | 事件总线 EventEmitter / Zustand subscribe 跨模块 / Redis pub/sub | (a) PROF-07 是前端模块，PROF-02 是后端模块（位于不同进程），EventEmitter 和 Zustand 无法跨进程通信；(b) Redis pub/sub 需后端中间件支持，增加架构复杂度；(c) Fire-and-forget HTTP 最简单，通知抛出不等待响应，不阻塞主流程，且可通过 HTTP 状态码判断 PROF-02 是否就绪 |
| 缓存策略 | 列表 SWR（先返回缓存再后台刷新）+ 详情会话级缓存 + 冷启动不缓存 | 全部不缓存（每次请求实时获取）/ 全部内存缓存 + 固定 TTL | (a) SWR 平衡首屏速度（用户看到缓存数据）和数据新鲜度（后台静默更新）；(b) 冷启动检测必须实时——用户在另一设备创建档案后应立即生效，缓存会阻塞体验；(c) 详情缓存只在单次会话内有效（页面关闭自然失效），无需 TTL 管理 |
| 异常重试 | **手动重试**（用户点击按钮），无自动重试 | 指数退避自动重试（如 3 次，间隔 1s/3s/9s） | (a) 档案操作是用户主动触发的操作，自动重试可能在同一页面上创建多条重复记录；(b) 校验错误（422）需要用户修正输入，自动重试无意义；(c) 手动重试给用户控制权，符合意图文档 §1.8 异常策略"保留用户已填写内容并提供重试入口" |受意图文档约束 |
| 微问卷题目选择 | **固定 2 题全覆盖**：触发因素确认 + 干预有效性反馈，每次相同 | 每次随机 1 题 / 按优先级动态选择 / 基于用户档案自适应 | (a) 仅 2 题，无需选择逻辑，固定实现最简单；(b) 意图文档 §1.6.3 定义了 2 种问题类型但未指定选择算法，按最少实现原则取全部题目；(c) 自适应逻辑需要用户历史数据支持，首版不可用 |受意图文档约束 |
| 冷启动跳过频率 | **无频率上限**：每次进入咨询前都检测，无档案则弹出引导 | 同一天内限弹出 3 次 / 按跳过次数逐次降低弹窗强度（全屏→半屏→提示条） | (a) 意图文档 §1.11(1) 明确"每次进入咨询前会重新检测并提示"，未设定上限；(b) 设置频率上限可能阻止紧急用户的真实需求；(c) 若用户体验测试反馈过于频繁，可后续迭代增加频率限制——当前优先遵循意图文档 |受意图文档约束 |

### 1.7 注意事项与禁止行为（设计层面）

1. **[硬性约束]** 所有 HTTP 请求必须通过 `AUTH-06 httpClient` 发送，绝不允许裸调 `Taro.request()`。这是项目结构 §9.4 的硬性规定，违反将导致 Token 无法自动注入和续期。

2. **[设计边界 1]** PROF-07 不负责档案数据的服务端持久化（归属 PROF-01），不负责档案的隐私权限判定（归属 PROF-05），不负责档案标签到检索条件的转换（归属 PROF-02），不负责事件记录的详细规则校验（归属 PROF-03）。

3. **[设计边界 2]** PROF-07 不负责 UI 渲染——冷启动表单、档案列表页、编辑页的视觉呈现全部由 PROF-06 (views/profiles/) 负责。PROF-07 仅提供数据和操作方法。

4. **[易错点]** 冷启动检测结果不缓存到 Store 或 localStorage。每次 `checkProfileExists()` 调用必须实时查询 PROF-01 API（或至少查询最新 store 状态并在 store 为空时发起 API 请求）。缓存冷启动结果会导致用户在另一设备创建档案后仍被引导。

5. **[易错点]** 微问卷的 `consultationId` 去重 Set 是**内存级**的（页面刷新即清空），不是 localStorage 持久化的。如果用户刷新页面后重新查看同一次咨询，理论上会再次弹出微问卷——这是可接受的行为（小概率事件且不造成数据错误）。

6. **[已知缺口]** PROF-02 的缓存失效 API 尚未设计。本模块预留 `POST /api/v1/profiles/{profileId}/invalidate-cache` 作为通知接口，实现时带上 null-guard（HTTP 404 时静默忽略）。PROF-02 完成后需验证接口路径、HTTP 方法和参数格式的一致性。

7. **[禁止行为]** 禁止在 `logics/profiles/` 中 import 任何 `views/profiles/` 下的文件（Pages、Components）。禁止在 Hook 实现中直接操作 DOM 或调用 `Taro.navigateTo`。

8. **[禁止行为]** 禁止在 `useProfile()` Hook 的 useEffect 中自动触发 `fetchProfiles()`。数据获取必须由 PROF-06 views 层显式调用（`onMounted` → `fetchProfiles()`），以保持数据流可控且可追踪。

### 1.8 引用：配套意图文档

- **意图文档**：`PROF-07-档案数据逻辑-意图文档.md`
- **冻结时间**：2026-05-27 21:26:24（v2.0）
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。冷启动引导的 3 项必填字段、微问卷的 2 题弹出、档案变更即时通知等核心流程完全遵循意图文档的业务约束。以下 4 项设计决策在意图文档中存在歧义或缺口，本设计文档做出最佳推断（标注 "受意图文档约束"），需用户确认：
  1. **微问卷题目选择**：固定 2 题全覆盖（意图文档未指定 1 题还是 2 题），推断依据：仅 2 题，全选最为简单且不遗漏信息。
  2. **冷启动跳过频率**：无上限，每次进入咨询都检测（意图文档 §1.11(1) 明确要求"每次进入咨询前会重新检测"）。
  3. **变更通知接口**：假设 `POST /api/v1/profiles/{profileId}/invalidate-cache`（PROF-02 接口未定义），含降级策略。
  4. **微问卷数据沉淀到 PROF-03 的边界**：PROF-07 直接更新标签到 PROF-01；事件记录写入 PROF-03 仅在用户显式回答时触发。

  如有歧义，以意图文档为准。
