# 同步问题报告 — AUTH-05 登录注册界面

---

## [2026-05-26T23:05:00] MODULE: AUTH-05 登录注册界面

### 处理摘要
- **场景**: full_design
- **执行阶段**: s05, s06, s07, s08, s09
- **状态**: completed
- **产物**:
  - docs/功能设计/01-用户认证与授权/AUTH-05-登录注册界面/AUTH-05-登录注册界面-意图文档.md
  - docs/功能设计/01-用户认证与授权/AUTH-05-登录注册界面/AUTH-05-登录注册界面-设计文档.md
  - docs/功能设计/01-用户认证与授权/AUTH-05-登录注册界面/AUTH-05-登录注册界面-落地规范.md

### 同步矛盾

#### [high] dependency-drift: useAuth Hook (AUTH-06) 接口未定义

- **描述**: AUTH-05 的所有 API 通信均依赖于 AUTH-06 模块的 `useAuth` Hook，但 AUTH-06 尚未进入设计流程，useAuth Hook 的接口签名（`login()`, `register()`, `isLoggedIn`, `logout()`）未定义。AUTH-05 的 logics 层依赖此接口进行登录/注册请求发送和登录态感知，设计文档和落地规范均将其标记为"未开始（L3 层）"。当前落地规范采用 mock 方式先行开发，但后续需要真实接口替换。
- **来源阶段**: s07-tech-decision
- **影响模块**: AUTH-06
- **建议方案**: 建议在 AUTH-06 进入设计流程时优先定义 `useAuth` Hook 的接口签名（`login(credentials, rememberMe) -> Promise<LoginResult>`、`register(data) -> Promise<RegisterResult>`、`isLoggedIn: boolean`、`logout() -> void`），作为 AUTH-05 和 AUTH-06 的跨模块契约先行冻结，避免 AUTH-05 实现完成后接口不匹配。

#### [medium] dependency-drift: AUTH-02 登录契约缺失

- **描述**: AUTH-02（用户登录）尚无 contracts 目录或任何契约文件。AUTH-05 通过 AUTH-06 间接依赖 AUTH-02 的登录 API（`POST /api/v1/auth/login`），但 LoginRequest/LoginResponse 的请求/响应契约尚未由 AUTH-02 定义。当前登录流程的端到端契约链路不完整，AUTH-05 的登录请求参数格式和响应处理逻辑依赖未定义的接口。
- **来源阶段**: s10-contract-harmonize
- **影响模块**: AUTH-02, AUTH-06
- **建议方案**: 方案 A：AUTH-02 在后续阶段补充 LoginRequest/LoginResponse 契约文件（maturity: draft），明确登录请求字段（username、password、rememberMe）和响应字段（token、user_id、expires_in）；方案 B：由 AUTH-06 在 Hook 层面统一定义登录接口类型，降低对 AUTH-02 契约的直接依赖。

#### [medium] boundary-ambiguity: AuthLayout/TabBarLayout 切换职责归属不清

- **描述**: 项目结构 §6.1 定义了 AuthLayout 和 TabBarLayout 两个布局组件——AuthLayout 在未登录时使用，TabBarLayout 在已登录后使用。两者的切换逻辑（根据登录态决定渲染哪个 layout）应在 `app.tsx` 或路由配置中实现，但该切换职责的归属模块不明确：AUTH-05（UI 表现层）仅负责 AuthLayout 内部的表单渲染，而 layout 切换决策基于 AUTH-06 维护的登录态（`userStore.isLoggedIn`）。
- **来源阶段**: s07-tech-decision
- **影响模块**: AUTH-06
- **建议方案**: layout 切换逻辑应归属 AUTH-06（认证会话管理），因为切换决策基于登录态判断，这是 AUTH-06 的核心职责。AUTH-05 仅负责 AuthLayout 内部的 UI 渲染，不参与 layout 选择逻辑。建议在 AUTH-06 设计文档中明确 `app.tsx` 的路由守卫实现方案。

#### [medium] dependency-drift: "记住我"后端支持未知

- **描述**: AUTH-05 前端传递 `rememberMe: boolean` 参数给 `useAuth` Hook，意图文档和设计文档均将"记住我"定义为前端复选框 + Hook 参数传递，后端负责具体的会话延长逻辑。但 AUTH-02（用户登录）和 AUTH-06（认证会话管理）均未进入设计流程，是否已规划 `rememberMe` 参数支持尚不明确。若后端未规划此参数，前端"记住我"勾选将无实际效果。
- **来源阶段**: s07-tech-decision
- **影响模块**: AUTH-02, AUTH-06
- **建议方案**: 在 AUTH-02 或 AUTH-06 设计时确认 `rememberMe` 参数的支持计划。若后端不支持：方案 A——AUTH-05 移除"记住我"复选框；方案 B——降级为纯前端行为（仅记住用户名，不延长会话）。

#### [low] dependency-drift: AUTH-05 未列为 AUTH-01/UserRole 消费者

- **描述**: AUTH-01/UserRole.json 的 x-consumers 列表中未包含 AUTH-05。当前消费者列表为 `["AUTH-02", "AUTH-04"]`，但 AUTH-05 的设计文档和落地规范均依赖 UserRole 枚举进行角色映射（中文标签「家属/老师/专家」→ 英文枚举值 family/teacher/expert）。消费者列表缺失导致依赖追踪不完整。
- **来源阶段**: s10-contract-harmonize
- **影响模块**: AUTH-01
- **建议方案**: 将 AUTH-05 添加至 AUTH-01/UserRole.json 的 x-consumers 列表，完善依赖追踪。

---

### 无新增遗留问题（从上周期延续）

本模块为首次进入设计流程，无上周期遗留问题。
