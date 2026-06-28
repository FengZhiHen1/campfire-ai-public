## 1 功能点：AUTH-05 登录注册界面 — 设计文档（瘦身版）

> **文档生成时间**：2026-05-26 22:50:37
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 22:50:37 | AI Assistant | 初始版本，基于 s06 技术决策报告（13 项已确定 + 4 项待裁决）生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `AUTH-05-登录注册界面-意图文档.md`（已冻结，v2.0，2026-05-26 22:41:33）
> - 本模块的精确编码规格见 `AUTH-05-登录注册界面-落地规范.md`

---

### 1.1 技术实现思路

AUTH-05 是一个**纯 UI 表现层模块**，负责渲染登录和注册两个表单界面并收集用户输入事件，所有数据收发和 Token 管理均通过 AUTH-06 提供的 Hook 桥接层完成。

**为什么选择单页面组件 + mode 切换而非两个独立页面**：技术决策报告 §4 决策项 2 的结论是使用同一 page 组件，通过 `mode` 参数（`login` / `register`）区分表单内容。登录和注册两个界面共享同一套 AuthLayout 布局、同一套 Zustand 状态结构（`AuthPageState`）、同一套校验工具函数（`validators.ts`）。拆分为两个独立页面将造成以下浪费：(1) 状态管理代码几乎完全重复，差异仅在于表单字段；(2) 页面切换时的 Loading 动画和 AuthLayout 重新挂载产生不必要的性能开销；(3) 两个 page 之间的状态共享需要跨页面通信通道。单组件 + mode 切换将所有 auth 相关的状态集中在一个 Zustand slice 中，页面切换（登录↔注册）通过重置 store 状态实现清空（意图文档 §1.11 约束 9），逻辑简洁且可测试。

**数据流设计**：AUTH-05 严格遵循项目结构 §6.1 的 views/logics 分层约束——views 层（`views/auth/index.tsx`）仅负责渲染 Taro UI 组件和绑定事件处理函数，不包含任何数据获取或状态变更逻辑；logics 层（`logics/auth/hooks/useAuthPage.ts`）通过 Zustand store 管理表单状态、执行前端校验、调用 `logics/shared/hooks/useAuth.ts`（AUTH-06 提供的 Hook）发送登录/注册请求。整个数据流是单向的：用户输入 → views 触发 action → logics 更新 store → views 重渲染。这种分层使得 views 层可被独立替换（如改成 Taro UI Next 或其他组件库）而不影响业务逻辑。

**校验策略的二层分离**：采用"前端字段格式校验"和"后端业务校验"二层结构。前端校验（失焦时 + 提交前）检查格式级合规性（长度、正则、必填），这是纯 front-end 逻辑，不涉及网络请求，响应在单帧内完成远快于 500ms 要求。后端返回的错误（如"用户名已被注册"、"用户名或密码错误"）由 logics 层接收后转为 Zustand 状态，通过 error 字段驱动 views 渲染。这种二层分离确保了：(1) 用户输入时获得即时反馈（不等待网络）；(2) 业务级错误由后端统一管控，前端不做重复的业务判断。

**错误反馈的视觉分层**：技术决策报告 §4 决策项 4 选择"字段下方提示文本 + 全局顶部通知条"作为错误呈现方式。字段级错误（如"密码长度至少 8 位"）使用 Taro UI Input 组件的 `error` prop，错误文本直接跟随字段，用户无需视线跳转即可定位问题。全局错误（如"用户名或密码错误"）使用顶部通知条，因为这类错误与单个字段无关（是用户名和密码的组合验证失败），标注在任一字段下方都会造成误导。

**角色选择的用户体验**：三种角色（家属/老师/专家）使用 Taro UI Radio 组 + 卡片式渲染。Radio 组保证单选语义（角色互斥），卡片式则在视觉上提供差异化——每张卡片包含图标 + 角色名 + 简短描述，满足 AC-03 中"角色标识清晰可辨"的要求。卡片设计天然支持未来扩展（如新增角色类型只需添加一张卡片），且视觉上与小程序原生风格匹配。

> **待裁决矛盾 #1**：登录页和注册页的路由路径设计。技术决策报告 §5 标记此项为业务矛盾——单入口 `/pages/auth/index` 简化实现，双入口 `/pages/auth/login` + `/pages/auth/register` 支持外部深层链接。本设计文档采用**单入口方案**（技术决策报告推荐），因为意图文档 AC-05 明确要求页面切换时清空表单数据，单入口控制更直接。若后续产品需要深层链接能力，可在单入口基础上通过 query 参数 `?mode=login` 或 `?mode=register` 实现伪深层链接。

---

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：
  - `AUTH-01 用户注册-意图文档.md`（已冻结）
  - `AUTH-01 用户注册-落地规范.md`（已冻结）
  - `AUTH-04 五级RBAC鉴权-落地规范.md`（已冻结）
  - `docs/contracts/AUTH-01/RegisterRequest.json`（maturity: draft）
  - `docs/contracts/AUTH-01/UserRole.json`（maturity: draft）
  - `docs/功能设计/_sync-issues.md`（2026-05-26 22:45 AUTH-05 节，✅ 无冲突）

- **兼容性结论**：
  - **无冲突**：AUTH-05 作为纯前端 UI 模块，不定义新的后端 API 或契约类型，不存在与已有后端规格的技术冲突。
  - **角色命名映射**：AUTH-05 界面使用中文角色标签（家属/老师/专家）作为 UI 展示文本，后端契约使用英文枚举值（`family`/`teacher`/`expert`）。此映射由 `logics/auth/utils/roleMapper.ts` 集中管理，为单向映射（前端中文 → 后端英文），返回时 AUTH-05 不参与后端角色数据的展示（角色信息展示由 AUTH-06 的 `userStore` 负责）。此设计已在 AUTH-04 的 `display_name` 属性机制中得到验证。
  - **注册字段完全对齐**：AUTH-05 注册表单的 5 个字段（roleType/username/password/phoneNumber/realName）与 `RegisterRequest.json` 的 5 个属性（role/username/password/phone/real_name）一一对应，字段约束（长度、格式、必填）完全一致。

- **复用的已有设计**：
  - `RegisterRequest` 契约（`docs/contracts/AUTH-01/RegisterRequest.json`）——注册表单字段定义的依据
  - `UserRole` 枚举（`docs/contracts/AUTH-01/UserRole.json`）——角色选择器选项的来源
  - `AuthLayout.tsx`（`apps/mini-program/src/views/shared/layouts/AuthLayout.tsx`）——项目结构 §6.1 预定义的未登录用户布局组件

---

### 1.3 依赖关系概述（技术层面）

AUTH-05 的技术依赖分为三类：**框架基础设施**（硬性前提，不可 mock）、**共享能力层**（通过 Hook 桥接，可 mock 先行开发）、**下游模块**（通过网络 API 间接调用，需接口契约先行冻结）。

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| Taro 4.x + React | 框架依赖 | 小程序运行时环境，`@tarojs/taro` 提供路由 API（`redirectTo`/`navigateTo`）；React 组件渲染与 Hooks 机制 |
| Taro UI 3.x | UI 组件依赖 | 使用 `AtInput`（文本/密码输入）、`AtButton`（提交按钮）、`AtRadio`（角色选择）、`AtCheckbox`（"记住我"）、`AtMessage`（全局通知条） |
| Zustand 5.x | 状态管理 | `authPageStore` 管理 `AuthPageState`（5 个状态）、`LoginFormState`、`RegisterFormState`；通过 `create()` 定义 slice，无需 middleware |
| AUTH-06（认证会话管理） | 跨模块 Hook 调用 | 调用 `useAuth()` Hook 的 `login(credentials, rememberMe) -> Promise<LoginResult>` 和 `register(data) -> Promise<RegisterResult>`；读取 `userStore.isLoggedIn` 判断登录态 |
| AUTH-06（认证会话管理） | 共享布局组件 | 复用 `AuthLayout.tsx` 作为未登录用户的容器布局，内部渲染登录/注册表单 |
| AUTH-01（用户注册） | 间接 API 调用 | 通过 `useAuth().register()` → httpClient → `POST /api/v1/auth/register` 发送注册请求。AUTH-05 不直接 import AUTH-01 的任何模块 |
| AUTH-02（用户登录） | 间接 API 调用 | 通过 `useAuth().login()` → httpClient → `POST /api/v1/auth/login` 发送登录请求。AUTH-05 不直接 import AUTH-02 的任何模块 |

**关键交互数据流**：
```
[用户输入] → views/auth/index.tsx (AtInput onChange)
  → logics/auth/hooks/useAuthPage.ts (action: handleInputChange)
  → authPageStore.setState() (更新 LoginFormState / RegisterFormState)
  → views/auth/index.tsx (React 重渲染，展示校验反馈)
  
[用户提交] → views/auth/index.tsx (AtButton onClick)
  → logics/auth/hooks/useAuthPage.ts (action: handleSubmit)
  → validators.ts (前端校验)
  → useAuth().login() / useAuth().register() (AUTH-06 Hook)
  → httpClient → API Server (网络请求)
  → authPageStore.setState() (更新 status → success/failure)
  → views/auth/index.tsx (重渲染，展示结果/执行跳转)
```

> 精确的函数签名、Hook 接口定义、Zustand store schema 见落地规范。AUTH-05 不定义新的后端 API 端点或 Service 接口。

---

### 1.4 状态机设计（技术实现策略）

AUTH-05 的界面状态使用有限状态机管理，技术实现上采用 Zustand store 的 `status` 字段（`AuthPageStatus` 枚举）驱动。

**状态定义**（5 个技术状态，与意图文档 §1.7 的业务状态一一对应）：

```
idle ──userStartTyping──▶ inputting ──userSubmit──▶ submitting ──apiSuccess──▶ success
                              ▲                         │
                              │                         └──apiError/networkTimeout──▶ failure
                              │                                                      │
                              └────────────────userRetry───────────────────────────┘
```

**状态转换规则**：
- `idle → inputting`：用户在任一表单字段中输入第一个字符（`onChange` 事件且对应字段从空变为非空）。此转换是隐式自动的，不需要用户显式操作。
- `inputting → submitting`：用户点击"登录"或"注册"按钮，且所有字段通过前端格式校验。此转换通过 Zustand action `submitForm()` 显式触发。
- `submitting → success`：AUTH-06 Hook 返回 `{ ok: true }` 的 Promise resolved 结果。Zustand action `handleSubmitResult()` 处理。
- `submitting → failure`：AUTH-06 Hook 返回 `{ ok: false, error: string }` 或 Promise rejected（网络超时/异常）。Zustand action `handleSubmitError()` 处理。
- `failure → inputting`：用户修正错误字段后重新开始输入（`onChange` 事件触发，且 `fieldErrors` 和 `globalError` 被清空）。
- `success → (page redirect)`：登录成功时调用 `Taro.redirectTo()`，注册成功时展示引导信息并等待用户操作。`success` 状态本身不自动转移到其他状态——页面跳转后组件卸载，状态自然销毁。

**实现策略**：
- **不使用外部状态机库**：AUTH-05 的状态转换规则简单（5 个状态，6 条转换路径），不需要 XState 或 Robot 等外部库。Zustand 的 `setState()` 足以表达所有状态转换。
- **前端校验失败不创建新状态**：当 `inputting` 状态下点击提交但校验不通过时，状态停留在 `inputting`，仅更新 `fieldErrors` 数组。这一策略避免了在简单表单场景下引入"校验失败"的中间状态（如 `validationFailed`），减少了状态爆炸风险。意图文档 §1.8.1 的异常描述也与这一策略一致——校验不通过"阻止提交"，而非"提交后返回错误"。
- **幂等策略**：`submitting` 状态下提交按钮完全禁用（`AtButton disabled`），防止重复提交。即使用户通过其他方式触发提交（如键盘回车），`submitForm()` action 也会检查当前状态，若为 `submitting` 则直接返回不执行操作。
- **状态不持久化**：所有状态均为内存态（Zustand store），不写入 Taro Storage 或任何持久化介质。页面切换（登录↔注册）时通过 `resetFormState()` action 重置整个 store 到初始值。

---

### 1.5 设计原则兑现清单（技术视角）

对照项目结构设计文档 §三的设计原则，本模块在技术层面如何响应：

| 原则 | 原则名称 | 技术响应 |
|------|----------|----------|
| §三 | **前端表现/逻辑硬隔离** | `views/auth/index.tsx` 仅渲染 Taro UI 组件和绑定事件回调，不 import `useAuth()`、`httpClient` 或任何 API Service。所有数据获取和状态变更由 `logics/auth/hooks/useAuthPage.ts` 通过 Zustand 驱动。 |
| §三 | **前后端契约先行** | AUTH-05 的 TypeScript 类型定义（`LoginFormState`、`RegisterFormState`）完全对齐 `RegisterRequest.json` 契约和 AUTH-01 已冻结的字段约束。不新增或修改任何后端可见的数据结构。 |
| §三 | **最小化可工作** | AUTH-05 不实现"忘记密码"、"第三方登录"等未在意图文档中定义的流程，不为未来可能的双因素认证预留 UI 空间。 |
| §三 | **单向依赖** | AUTH-05 依赖方向严格单向：`views/auth/` → `logics/auth/` → `logics/shared/`（AUTH-06 Hook）。无反向 import，无同级 feature 间的直接依赖。 |
| 意图文档 §1.11.8 | **设计边界** | AUTH-05 的技术实现严格限制在 UI 渲染和事件收集。不定义任何密码加密函数、不实现 Token 解析逻辑、不编写 SQL 查询或 HTTP 客户端调用代码。 |

---

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 页面组织 | 单 page 组件 + `mode` 切换 | 两个独立 page（`login.tsx` + `register.tsx`） | 登录和注册共享 AuthLayout、Zustand store 和校验工具函数。双 page 将引入重复代码和跨页面状态同步问题。单页面的额外好处是登录/注册切换时无需路由跳转（`navigateTo`），用户体验更流畅。受意图文档 §1.11 约束 9（切换清空数据）和 AC-05 约束。 |
| 状态管理 | Zustand `authPageStore` | React `useReducer` + Context | Zustand 是项目结构 §6.1 统一选型的状态管理库。`useReducer` 适合局部复杂状态但在跨组件（AuthLayout 内部切换 views）共享时会退化为 Context + Provider 嵌套。Zustand 的 `create()` 无需 Provider 包裹，直接在组件外测试。 |
| 校验触发时机 | 失焦时校验 + 提交时全量校验 | 输入过程中实时校验（`onChange`） | `onChange` 校验在用户输入每个字符时触发提示，在移动端会造成频繁的视图抖动和键盘收起/展开问题。失焦时（`onBlur`）校验在用户离开字段后立即反馈，既给了用户完整输入的机会，又不影响即时性。提交时全量校验确保无遗漏。技术决策报告 §4 决策项 3 推荐此方案。 |
| 登录成功跳转 | `Taro.redirectTo()`（路由替换） | `Taro.navigateTo()`（路由压栈） | 登录成功后用户不应通过返回按钮回到登录页面。`redirectTo` 替换当前页面历史栈，防止用户误操作返回。受意图文档 §1.4 目标 1（"登录成功后自动跳转至应用主页面"）约束。技术决策报告 §4 决策项 10 确认此方案。 |
| 注册成功跳转 | `Taro.navigateTo()`（路由压栈） + 引导按钮 | `Taro.redirectTo()` | 注册成功后用户需要手动点击"前往登录"或页面自动判定。`navigateTo` 保留注册页历史，允许用户返回查看（虽然返回后表单已清空），符合"注册成功引导至登录页"的意图文档 AC-07。技术决策报告 §4 决策项 11 确认此方案。 |
| 错误反馈层级 | 字段下方文本 + 全局通知条 | 所有错误使用统一弹窗 | 字段级错误（格式校验）与字段直接关联，行内提示最直观。全局错误（登录失败）与任意单字段无关，使用顶部通知条全局广播。弹窗会阻断用户后续操作（必须先关闭弹窗），在小程序移动端体验较差。技术决策报告 §4 决策项 4 确认此方案。 |
| 角色选择器 | Taro UI `AtRadio` + 卡片式渲染 | 自定义 `Picker` 或下拉选择 | 三种角色属于少量固定选项，Radio 确保单选语义，卡片式提供了"图标+名称+描述"的丰富展示空间（满足 AC-03 的"清晰可辨"要求）。Picker/下拉选择适合选项较多时，三种选项下展开性差且角色图标无法展示。技术决策报告 §4 决策项 5 确认此方案。 |
| 提交防重复 | `submitting` 状态下按钮 `disabled` | 时间窗口防抖（如 2 秒内禁止） | 基于状态驱动的禁用是最干净的实现——按钮状态与 `authPageStore.status` 绑定，提交完成后自动恢复。时间窗口防抖需要在每次提交后设置 setTimeout，且如果后端 3 秒才响应，2 秒窗口会导致重复提交。技术决策报告 §4 决策项 7 确认此方案。 |
| "记住我"实现 | 前端仅收集 `rememberMe: boolean`，通过 Hook 参数传递 | 前端直接操作 Taro Storage 延长 Token | 意图文档 §1.11 约束 4 禁止 Token 操作，§1.11 约束 8 禁止鉴权逻辑。AUTH-05 只需在 UI 上收集用户的勾选意愿，具体的会话延长策略由 AUTH-06 和 AUTH-03 实现。技术决策报告 §4 决策项 6 确认此方案。 |
| 登录态检测 | AuthLayout 路由守卫（包裹组件） | 每个页面 `onLoad` 中检查 | 路由守卫模式在全局 Layout 层统一处理登录态，避免在每个业务页面重复编写检测逻辑。项目结构 §6.1 预定义了 `AuthLayout.tsx`，其职责就是"未登录时渲染登录/注册界面，已登录时渲染子页面"。AUTH-05 只负责 AuthLayout 内部的 UI，布局切换逻辑由 AuthLayout 自身或 AUTH-06 协同管理。技术决策报告 §4 决策项 12 确认此方案。 |

---

### 1.7 注意事项与禁止行为（设计层面）

**设计约束**：
1. **[L1a/L1b 硬隔离]** `views/auth/` 目录下的文件禁止直接 import `logics/shared/services/httpClient.ts`、`logics/shared/hooks/useAuth.ts` 或任何 API Service。所有跨层通信必须通过 `logics/auth/hooks/useAuthPage.ts` 封装后的 Hook 暴露给 views。这是项目结构 §三中"前端表现/逻辑硬隔离"原则的严格执行。
2. **[Token 零接触]** AUTH-05 的任何文件中不得出现 Token 的读取、存储、传递或清除操作。登录成功后也不应读取 Taro Storage 中的 Token——Token 的存在性由 `userStore.isLoggedIn` 代理判断。
3. **[无 API 直连]** AUTH-05 不得直接调用 `Taro.request()`、`fetch()` 或任何 HTTP 客户端。注册和登录的网络请求完全由 AUTH-06 的 Hook 内部完成。

**易错点**：
4. **[mode 切换必须重置状态]** 从登录模式切换到注册模式（或反之）时，必须调用 `resetFormState()` 清空所有字段值、校验错误和全局错误。不能仅切换 `mode` 字段而保留表单数据——这违反意图文档 §1.11 约束 9，且会导致登录表单的用户名出现在注册表单中。
5. **[校验顺序不可颠倒]** 前端校验必须先于 Hook 调用执行。不要先调用 `useAuth().login()` 再校验——因为 (1) 网络请求的耗时远大于校验；(2) 前端可校验的格式错误不应浪费网络往返；(3) 意图文档 §1.8.1 明确要求"提交时再次校验全部字段，任一字段不合规则不允许提交"。
6. **[success 状态处理跳转时序]** 登录成功时，不要立即调用 `Taro.redirectTo()`——应在 `success` 状态停留短暂时间展示成功反馈，再执行跳转。这符合意图文档 §1.4 目标 1 的"展示成功状态"要求，且避免页面闪烁。建议延迟 800ms~1.5s。
7. **[角色选择不可逆的实现]** 注册流程中，角色卡片选定后应禁用 Radio 组交互，防止用户在填写其他字段时误修改角色。如果用户确实需要更改角色，应在 UI 上提供明确的"重新选择角色"操作（清空已填写的表单并解开 Radio 组禁用），而非简单恢复 Radio 交互。

**设计边界**：
8. AUTH-05 不负责以下技术事项：
   - 密码的加密强度校验和哈希存储（归属 AUTH-01 后端 Service + SEC-01）
   - JWT Token 的签发和 Refresh Token 轮换（归属 AUTH-02、AUTH-03）
   - 用户名/手机号的全局唯一性校验（归属 AUTH-01 后端 Repository）
   - 认证会话的生命周期管理（归属 AUTH-06）
   - `useAuth` Hook 的接口设计和实现（归属 AUTH-06，AUTH-05 仅作为消费者）
   - AuthLayout 与 TabBarLayout 的切换逻辑（归属 AUTH-06 的 app.tsx 路由层，AUTH-05 仅渲染 AuthLayout 内容）

**待裁决矛盾**：
9. **[#4 安全策略 vs 用户体验]** 前端校验阶段的格式错误提示（如"密码长度至少 8 位"、"用户名仅允许字母数字下划线和连字符"）提供了字段级别的精准反馈。后端登录失败提示（"用户名或密码错误"）则因安全策略而模糊化。两者的信息详细度不对称——前端告诉用户格式问题出在哪里，后端不告诉用户是用户名不对还是密码不对。这种不对称在当前设计中被认为是**合理的**：前端校验是防御性 UI 模式（帮助用户一次填对），后端模糊化是安全策略（防止账号探测）。format error ≠ credential error，因此错误信息的粒度不同是自然的。若产品方要求统一模糊提示，可在前端校验失败时也返回"请检查您的输入"而非具体字段——但此时用户无法定位问题字段，会显著降低可用性。

---

### 1.8 引用：配套意图文档

- **意图文档**：`AUTH-05-登录注册界面-意图文档.md`
- **冻结时间**：2026-05-26 22:41:33
- **一致性声明**：本设计文档的技术实现方案与上述意图文档中的业务定义一致。所有 9 项业务约束均已映射到设计决策中（§1.5 原则兑现表、§1.7 约束/易错点/边界）。13 项技术决策已根据 s06 技术决策报告自主确定（§1.6 权衡表），4 项业务矛盾（技术决策报告 §5 第 1-4 项）已在本设计中标注最佳推断和待裁决事项。如有歧义，以意图文档为准。
