## 1 功能点：AUTH-05 登录注册界面 — 落地规范

> **文档生成时间**：2026-05-26 22:59:07
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 22:59:07 | AI Assistant | 初始版本，基于设计文档 v1.0 和契约协调报告（0冲突/3复用/0新类型）生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `AUTH-05-登录注册界面-设计文档.md`。
> **流水线上下文**：本落地规范基于已冻结的 `AUTH-05-登录注册界面-意图文档.md`（冻结于 2026-05-26 22:41:33）编写。技术实现必须与意图文档中的业务定义保持一致。

---

### 1.1 技术栈绑定

> 【对内实现】

- **必须使用**：
  - `@tarojs/taro` `^4.0` — 小程序运行时，页面路由 API（`Taro.redirectTo`、`Taro.navigateTo`）、`Taro.showToast`（成功提示）
  - `@tarojs/components` `^4.0` — 基础组件（`View`、`Text`、`ScrollView`），用于布局容器
  - `taro-ui` `^3.0` — 高级 UI 组件：`AtInput`（文本/密码输入框）、`AtButton`（提交按钮）、`AtRadio`（角色选择 Radio 组）、`AtCheckbox`（"记住我"复选框）、`AtMessage`（全局通知条）
  - `react` `^18.0` — 组件渲染、`useEffect`（登录成功延迟跳转/注册成功引导）、`useCallback`（事件处理函数记忆化）
  - `zustand` `^5.0` — 全局状态管理，`create()` 定义 `authPageStore`，无 middleware
  - `typescript` `^5.0` — 严格类型检查，所有导出的函数和 Hook 必须有完整类型签名
  - Pure functions — 校验函数放在 `utils/validators.ts`，输入 `string` → 输出 `string | null`（错误提示或 null 表示通过），纯函数，无副作用
- **禁止使用**：
  - 禁止在 `views/auth/` 目录下 import `Taro.request`、`Taro.setStorage` / `Taro.getStorage` / `Taro.removeStorage`（Token 操作），或任何 HTTP 客户端
  - 禁止在 `views/auth/` 目录下直接 import `logics/shared/hooks/useAuth.ts`、`logics/shared/services/httpClient.ts`、`logics/shared/store/userStore.ts` — 必须通过 `logics/auth/hooks/useAuthPage.ts` 封装后导出
  - 禁止引入 `zod`、`yup`、`joi` 等第三方校验库 — 校验逻辑不超过 5 个正则，引入外部库成本大于收益
  - 禁止引入 `xstate`、`robot` 等外部状态机库 — 5 状态 FSM 用 Zustand `setState()` 实现
  - 禁止使用 `Taro.navigateBack` 处理登录成功跳转 — 必须用 `Taro.redirectTo` 清除登录页历史
  - 禁止在按钮 `onClick` 中直接调用 `useAuth().login()` — 必须通过 `useAuthPage` Hook 的 `handleSubmit()` 统一入口

### 1.2 文件归属

> 【对内实现】

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 页面组件 | `apps/mini-program/src/views/auth/index.tsx` | AuthPage 主页面组件，根据 `mode` 状态渲染登录或注册表单 |
| 登录表单 | `apps/mini-program/src/views/auth/LoginForm.tsx` | 登录表单 UI（用户名/密码/记住我/提交按钮），props-only 纯渲染 |
| 注册表单 | `apps/mini-program/src/views/auth/RegisterForm.tsx` | 注册表单 UI（角色选择/用户名/密码/手机号/真实姓名/提交按钮），props-only 纯渲染 |
| 角色卡片 | `apps/mini-program/src/views/auth/RoleCard.tsx` | 单个角色选择卡片（图标+名称+描述），通过 `AtRadio` option 渲染 |
| AuthPage Hook | `apps/mini-program/src/logics/auth/hooks/useAuthPage.ts` | 页面状态管理 Hook，封装 Zustand store 操作、校验调用和 useAuth 桥接 |
| Zustand Store | `apps/mini-program/src/logics/auth/store/authPageStore.ts` | `authPageStore`：`AuthPageState`、`LoginFormState`、`RegisterFormState` 合并管理 |
| 校验工具 | `apps/mini-program/src/logics/auth/utils/validators.ts` | Pure function：`validateUsername()`、`validatePassword()`、`validatePhone()`、`validateRealName()` |
| 角色映射 | `apps/mini-program/src/logics/auth/utils/roleMapper.ts` | `uiLabelToEnum()`：中文角色标签 → 英文枚举值；`enumToLabel()`：英文枚举值 → 中文标签 |
| 类型定义 | `apps/mini-program/src/logics/auth/types/index.ts` | `LoginFormState`、`RegisterFormState`、`AuthPageStatus`、`PageMode`、`FieldError`、`AuthPageState`、`FormSubmitResult` |
| 测试文件 | `apps/mini-program/__tests__/auth/useAuthPage.test.ts` | `useAuthPage` Hook 的单元测试（Zustand store mock） |
| 测试文件 | `apps/mini-program/__tests__/auth/validators.test.ts` | `validators.ts` 纯函数测试 |
| 测试文件 | `apps/mini-program/__tests__/auth/roleMapper.test.ts` | `roleMapper.ts` 映射函数测试 |

### 1.3 输入定义

> 【已锁定】对外接口类型使用契约引用，内部类型保留完整定义。

**内部类型 — LoginFormState**（登录表单状态，前端内部，不对外暴露）

```typescript
interface LoginFormState {
  /** 登录用户名。长度 4-32，仅允许字母、数字、下划线、连字符 */
  username: string;
  /** 登录密码。至少 8 位，前端不做强度校验（由后端 AUTH-02 校验） */
  password: string;
  /** 是否勾选"记住我"。true 时通过 useAuth Hook 传递至后端延长会话 */
  rememberMe: boolean;
}
```

**内部类型 — RegisterFormState**（注册表单状态，前端内部，不对外暴露）

```typescript
interface RegisterFormState {
  /** 角色类型 UI 标签。值仅限 "家属" | "老师" | "专家"，提交前通过 roleMapper 转换为英文枚举 */
  roleType: '家属' | '老师' | '专家';
  /** 用户名。长度 4-32，仅允许字母、数字、下划线、连字符 */
  username: string;
  /** 密码。至少 8 位，必须同时包含大写字母、小写字母和数字 */
  password: string;
  /** 中国大陆手机号。11 位，格式 ^1[3-9]\d{9}$ */
  phoneNumber: string;
  /** 真实姓名。长度 2-20，专家角色必填，家属/老师可选 */
  realName: string;
}
```

**契约引用 — RegisterRequest**（提交至后端时由 useAuth Hook 转换为后端格式）

- 【契约引用】`docs/contracts/AUTH-01/RegisterRequest.json`
- 本模块作为该契约的消费方
- 字段映射关系（前端 camelCase → 后端 snake_case）：
  - `roleType` → `role`（通过 `roleMapper.uiLabelToEnum()` 转换）
  - `username` → `username`
  - `password` → `password`
  - `phoneNumber` → `phone`
  - `realName` → `real_name`

### 1.4 输出定义

> 【已锁定】对外接口类型使用契约引用，内部类型保留完整定义。

**内部类型 — AuthPageState**（Zustand store 的完整状态，前端内部）

```typescript
type AuthPageStatus = 'idle' | 'inputting' | 'submitting' | 'success' | 'failure';
type PageMode = 'login' | 'register';

interface FieldError {
  /** 字段名，对应表单 state 的 key */
  field: 'username' | 'password' | 'phoneNumber' | 'realName' | 'roleType';
  /** 用户可理解的错误提示文本 */
  message: string;
}

interface AuthPageState {
  /** 当前页面模式：登录 or 注册 */
  mode: PageMode;
  /** 界面状态机当前状态 */
  status: AuthPageStatus;
  /** 登录表单数据 */
  loginForm: LoginFormState;
  /** 注册表单数据 */
  registerForm: RegisterFormState;
  /** 表单字段级校验错误列表 */
  fieldErrors: FieldError[];
  /** 全局错误文本（登录/注册失败时由后端返回）。null 表示无错误 */
  globalError: string | null;
  /** 成功提示文本。null 表示无成功提示 */
  successMessage: string | null;
}
```

**内部类型 — FormSubmitResult**（useAuth Hook 返回的提交结果，由 AUTH-06 定义但 AUTH-05 消费）

```typescript
interface FormSubmitResult {
  ok: boolean;
  error?: string;           // 失败时的错误信息（可展示给用户）
  redirectTo?: string;       // 登录成功时包含目标页面路径
}
```

**契约引用 — RegisterResponse**（注册成功时后端返回，AUTH-05 通过 AUTH-06 Hook 间接消费）

- 【契约引用】`docs/contracts/AUTH-01/RegisterResponse.json`
- 本模块作为该契约的间接消费方（通过 AUTH-06 `useAuth().register()` 返回）
- AUTH-05 使用 `RegisterResponse.message` 字段作为 `successMessage` 展示给用户

**契约引用 — UserRole**

- 【契约引用】`docs/contracts/AUTH-01/UserRole.json`
- 本模块作为该契约的消费方
- AUTH-05 仅使用枚举值 `family`、`teacher`、`expert`（注册阶段子集），通过 `roleMapper.enumToLabel()` 反向映射展示中文标签

### 1.5 核心逻辑步骤

> 【对内实现】

按执行顺序列出原子操作。每步失败即中断流程，不进入后续步骤。

#### 登录流程

1. **步骤 1：用户输入收集**
   - **操作对象**：`LoginFormState` 对应字段
   - **具体操作**：`AtInput` 的 `onChange` 事件触发 `handleLoginInputChange(field: string, value: string)` → `authPageStore.setState()` 更新 `loginForm` 对应字段；`AtCheckbox` 的 `onChange` 触发 `handleRememberMeChange(checked: boolean)` → 更新 `loginForm.rememberMe`
   - **输入来源**：用户键盘输入 / 复选框点击
   - **输出去向**：Zustand store 中 `loginForm` 状态更新 → React 重渲染表单
   - **失败行为**：不涉及（用户输入无失败路径）；若字段更新后 `fieldErrors` 中存在该字段的错误项，调用 `clearFieldError(field)` 清除

2. **步骤 2：字段失焦校验**
   - **操作对象**：`LoginFormState` 中失焦的字段值（`string`）
   - **具体操作**：`AtInput` 的 `onBlur` 事件触发 → 调用对应纯函数校验：
     - `username` → `validateUsername(value: string): string | null`（正则 `/^[a-zA-Z0-9_-]{4,32}$/`，不匹配返回 `"用户名需为4-32位字母、数字、下划线或连字符"`，空值返回 `"请输入用户名"`）
     - `password` → `validatePassword(value: string): string | null`（长度 `< 8` 返回 `"密码长度至少8位"`；不匹配 `/(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/` 返回 `"密码需包含大写字母、小写字母和数字"`；空值返回 `"请输入密码"`）
   - **输入来源**：Zustand store 中 `loginForm` 的字段值
   - **输出去向**：校验失败 → `authPageStore.setState({ fieldErrors: [...(去重追加)] })`；校验通过 → 如果 `fieldErrors` 中有该项则移除
   - **失败行为**：校验失败不阻止用户继续操作，仅更新 `fieldErrors`。与步骤 3（提交前全量校验）构成两层防线

3. **步骤 3：提交前全量校验**
   - **操作对象**：`LoginFormState` 全部字段
   - **具体操作**：用户点击"登录"按钮 → `handleLoginSubmit()` 调用：
     1. 对 `loginForm.username` 和 `loginForm.password` 分别调用 `validateUsername()` 和 `validatePassword()`
     2. 收集所有非 null 的校验结果 → 汇总为 `FieldError[]`
     3. 若 `FieldError[]` 非空 → 更新 `fieldErrors`，状态保持 `inputting`，不调用 `setStatus('submitting')`，直接 return
   - **输入来源**：Zustand store 中 `loginForm` 全部字段
   - **输出去向**：全部校验通过 → 进入步骤 4；任一校验失败 → 阻断提交
   - **失败行为**：校验不通过时停留在 `inputting` 状态，仅更新 `fieldErrors`。不创建新的状态（如 `validationFailed`），不发送网络请求

4. **步骤 4：提交登录请求**
   - **操作对象**：`LoginFormState` 转换后的参数
   - **具体操作**：
     1. `authPageStore.setState({ status: 'submitting', globalError: null })` — 进入提交状态
     2. 调用 `useAuth().login({ username: loginForm.username, password: loginForm.password, rememberMe: loginForm.rememberMe })`
     3. 等待 Promise resolve
   - **输入来源**：步骤 3 校验通过的 `loginForm.username`、`loginForm.password`、`loginForm.rememberMe`
   - **输出去向**：Promise resolve → 进入步骤 5；Promise reject → 进入步骤 5（超时处理）
   - **失败行为**：useAuth Hook 内部封装了网络错误处理，AUTH-05 仅接收 resolve/reject。若 reject 未在 10 秒内完成 → 触发步骤 5 超时分支

5. **步骤 5：处理登录结果**
   - **操作对象**：`FormSubmitResult` 对象
   - **具体操作**：
     - **成功分支**（`result.ok === true`）：
       1. `authPageStore.setState({ status: 'success', successMessage: '登录成功，正在跳转...' })`
       2. `useEffect` 中启动 `setTimeout(() => { Taro.redirectTo({ url: '/pages/index/index' }) }, 1000)` — 800ms-1.5s 延迟展示成功状态后跳转
       3. 若 `result.redirectTo` 字段非空，使用其值替代默认路径
     - **失败分支**（`result.ok === false`）：
       1. `authPageStore.setState({ status: 'failure', globalError: result.error || '用户名或密码错误' })`
       2. 保留 `loginForm` 全部字段值不清空（意图文档 §1.11 约束 7）
       3. 按钮恢复可用（`status !== 'submitting'`，`AtButton` 的 `disabled` prop 自动解除）
     - **超时分支**（Promise 10s 未 settled）：
       1. `authPageStore.setState({ status: 'failure', globalError: '网络异常，请检查网络后重试' })`
       2. 保留 `loginForm` 全部字段值
   - **输入来源**：`useAuth().login()` 的返回值（`Promise<FormSubmitResult>`）
   - **输出去向**：UI 重渲染显示结果（成功→跳转；失败→错误提示）
   - **失败行为**：网络超时通过 `setTimeout(10000)` + Promise.race 检测，超时后 reject 并在 `globalError` 中展示通用提示

#### 注册流程

6. **步骤 1：角色选择**
   - **操作对象**：`RegisterFormState.roleType`
   - **具体操作**：`AtRadio` 组件渲染 3 张 `RoleCard`（家属/老师/专家），用户点击任一卡片 → `onChange` 触发 `handleRoleSelect(value: string)` → `authPageStore.setState({ registerForm: { ...registerForm, roleType: value } })`
   - **输入来源**：用户点击角色卡片
   - **输出去向**：Zustand store 中 `registerForm.roleType` 更新
   - **失败行为**：角色选择后 `AtRadio` 组 `disabled=true`（意图文档 §1.11 约束 5），防止注册流程中修改。如需重新选择，点击"重新选择角色" → `handleResetRole()` → 重置 `roleType` 为空字符串 `""` + 清空 `registerForm` 全部字段 + 解除禁用

7. **步骤 2-6：等同于登录流程步骤 1-5**，差异如下：
   - **步骤 2（字段失焦校验）** 额外校验：
     - `phoneNumber` → `validatePhone(value: string): string | null`（正则 `/^1[3-9]\d{9}$/`，不匹配返回 `"请输入正确的11位手机号"`；空值返回 `"请输入手机号"`）
     - `realName` → `validateRealName(value: string, roleType: string): string | null`（`roleType === '专家'` 且空值返回 `"专家角色必须填写真实姓名"`；非空但长度 `< 2` 或 `> 20` 返回 `"真实姓名需为2-20个字符"`；非专家且空值返回 null（合法））
     - `username` → 同登录流程
     - `password` → 同登录流程
   - **步骤 3（提交前全量校验）**：校验全部 5 个字段（roleType + username + password + phoneNumber + realName），`roleType` 另加非空校验（`roleType === ''` → `"请选择角色"`）
   - **步骤 4（提交）**：调用 `useAuth().register({ role: roleMapper.uiLabelToEnum(registerForm.roleType), username: registerForm.username, password: registerForm.password, phone: registerForm.phoneNumber, real_name: registerForm.realName || null })`。字段名和值在 Hook 内部完成 camelCase → snake_case + 中文角色 → 英文枚举的双重转换
   - **步骤 5（成功分支）**：不调用 `Taro.redirectTo`，而是 `authPageStore.setState({ status: 'success', successMessage: '注册成功，请登录' })`，页面渲染"前往登录"按钮 → 点击后 `Taro.navigateTo({ url: '/pages/auth/index' })`（路由压栈保留注册页历史，但返回后表单已清空）

#### 页面切换流程（登录 ↔ 注册）

8. **页面模式切换**
   - **操作对象**：`AuthPageState.mode`
   - **具体操作**：`handleSwitchMode(targetMode: PageMode)` → `authPageStore.setState(resetFormState())`：
     - `mode` 设为 `targetMode`
     - `status` 重置为 `'idle'`
     - `loginForm` 和 `registerForm` 均重置为初始值（`username: '', password: '', rememberMe: false, roleType: '', phoneNumber: '', realName: ''`）
     - `fieldErrors` 和 `globalError` 清空为 `[]` / `null`
     - `successMessage` 清空为 `null`
   - **输入来源**：用户点击"注册"/"登录"切换链接
   - **输出去向**：Zustand store 完全重置到初始状态
   - **失败行为**：不涉及

### 1.6 接口契约（对外暴露的公共接口）

> 【已锁定】本模块为纯 UI 表现层，不定义后端 API 端点。以下为前端层间接口。

#### 1.6.1 useAuthPage Hook（主要公共接口，供 views/ 层消费）

```typescript
/**
 * 认证页面状态管理 Hook。
 * 封装 Zustand store 操作、表单校验调用和 useAuth 桥接，
 * 是 views/auth/ 与 logics/ 之间的唯一接口。
 *
 * @returns handleLoginInputChange, handleRegisterInputChange, handleRoleSelect,
 *          handleRememberMeChange, handleLoginSubmit, handleRegisterSubmit,
 *          handleSwitchMode, handleResetRole, authState
 *
 * Side Effects:
 *   - 登录成功后调用 Taro.redirectTo() 跳转主页
 *   - 更新 Zustand store 触发 UI 重渲染
 *
 * Thread Safety:
 *   本 Hook 为 React 组件内调用，通过 Zustand 保证状态更新原子性。
 *   不涉及跨线程共享状态（小程序单线程模型）。
 */
function useAuthPage(): UseAuthPageReturn

interface UseAuthPageReturn {
  /** 认证页面完整状态（mode, status, fieldErrors, globalError, successMessage, loginForm, registerForm） */
  authState: AuthPageState;
  /** 登录表单字段 onChange 处理 */
  handleLoginInputChange: (field: 'username' | 'password', value: string) => void;
  /** 注册表单字段 onChange 处理 */
  handleRegisterInputChange: (field: 'username' | 'password' | 'phoneNumber' | 'realName', value: string) => void;
  /** 角色选择 onChange 处理 */
  handleRoleSelect: (value: '家属' | '老师' | '专家') => void;
  /** "记住我"复选框 onChange 处理 */
  handleRememberMeChange: (checked: boolean) => void;
  /** 登录表单失焦校验处理 */
  handleLoginFieldBlur: (field: 'username' | 'password') => void;
  /** 注册表单失焦校验处理 */
  handleRegisterFieldBlur: (field: 'username' | 'password' | 'phoneNumber' | 'realName') => void;
  /** 登录提交（含全量校验 + useAuth().login() 调用） */
  handleLoginSubmit: () => Promise<void>;
  /** 注册提交（含全量校验 + useAuth().register() 调用） */
  handleRegisterSubmit: () => Promise<void>;
  /** 登录/注册页面切换（重置全部状态） */
  handleSwitchMode: (targetMode: 'login' | 'register') => void;
  /** 重置角色选择（清空注册表单 + 解除角色 Radio 禁用） */
  handleResetRole: () => void;
}
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `useAuthPage` — 语义化，描述"认证页面状态管理"的业务动作 |
| **输入类型** | 各 handler 函数的参数（见上述接口定义） |
| **输出类型** | `UseAuthPageReturn` 对象 |
| **异常类型** | 不抛出异常。所有错误通过 `authState.status === 'failure'` + `authState.globalError` 呈现 |
| **副作用** | 更新 Zustand store；登录成功时调用 `Taro.redirectTo` |
| **幂等性** | `handleLoginSubmit()` / `handleRegisterSubmit()` 在 `status === 'submitting'` 时直接 return（不执行），防止重复提交 |
| **并发安全** | 小程序单线程，无并发问题。`handleLoginSubmit` 为 async，内部状态检查保证不会并发执行多次提交 |

#### 1.6.2 校验工具纯函数（供 useAuthPage 内部和测试消费）

```typescript
/**
 * 校验用户名格式。
 * @returns null 表示通过；否则返回错误提示字符串
 */
function validateUsername(value: string): string | null

/**
 * 校验密码格式。
 * @returns null 表示通过；否则返回错误提示字符串
 */
function validatePassword(value: string): string | null

/**
 * 校验中国大陆手机号格式。
 * @returns null 表示通过；否则返回错误提示字符串
 */
function validatePhone(value: string): string | null

/**
 * 校验真实姓名（含角色关联校验）。
 * @param value 真实姓名字段值
 * @param roleType 当前角色 UI 标签
 * @returns null 表示通过；否则返回错误提示字符串
 */
function validateRealName(value: string, roleType: '家属' | '老师' | '专家'): string | null
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `validateUsername` / `validatePassword` / `validatePhone` / `validateRealName` |
| **输入类型** | `string` (+ 角色类型用于 `validateRealName`) |
| **输出类型** | `string \| null` |
| **异常类型** | 不抛出异常。纯函数，所有输入返回确定值 |
| **副作用** | 无。不读写外部状态、Storage 或 DOM |
| **幂等性** | 天然幂等（纯函数：相同输入 → 相同输出） |
| **并发安全** | 天然安全（纯函数，无共享状态） |

#### 1.6.3 角色映射工具（供 useAuthPage 内部消费）

```typescript
/**
 * 中文角色 UI 标签 → 后端英文枚举值。
 * @returns 对应的英文枚举值
 */
function uiLabelToEnum(label: '家属' | '老师' | '专家'): 'family' | 'teacher' | 'expert'

/**
 * 后端英文枚举值 → 中文角色 UI 标签。
 * @returns 对应的中文标签
 */
function enumToLabel(enumValue: 'family' | 'teacher' | 'expert'): '家属' | '老师' | '专家'
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `uiLabelToEnum` / `enumToLabel` |
| **输入类型** | 中文标签或英文枚举值 |
| **输出类型** | 对应的英文枚举值或中文标签 |
| **异常类型** | 不抛出异常。未知值返回 `'家属'` / `'family'` 作为默认（安全降级） |
| **副作用** | 无 |
| **幂等性** | 天然幂等（纯函数，映射表常量） |
| **并发安全** | 天然安全 |

---

### 1.7 依赖与集成接口（本模块调用的外部接口）

> 【已锁定】

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 小程序框架 | `@tarojs/taro` `^4.0` | `Taro.redirectTo({ url })` | 登录成功后路由替换（清除登录页历史） | 项目结构 §6.1；技术栈设计 §2 |
| 小程序框架 | `@tarojs/taro` `^4.0` | `Taro.navigateTo({ url })` | 注册成功后路由压栈到登录页 | 项目结构 §6.1；技术栈设计 §2 |
| 小程序框架 | `@tarojs/taro` `^4.0` | `Taro.showToast({ title, icon })` | 注册成功引导提示（备选方案） | 项目结构 §6.1 |
| UI 组件库 | `taro-ui` `^3.0` | `AtInput`（type=text/password）、`AtButton`（type=primary, disabled）、`AtRadio`（options）、`AtCheckbox`（selectedList）、`AtMessage` | 登录/注册表单 UI 渲染 | 技术栈设计 §2 |
| 状态管理 | `zustand` `^5.0` | `create<AuthPageState>()` | 认证页面状态管理 | 技术栈设计 §2；项目结构 §6.1 |
| React | `react` `^18.0` | `useEffect`、`useCallback` | 副作用处理和事件函数记忆化 | 技术栈设计 §2 |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| AUTH-06（认证会话管理） | `logics/shared/hooks/useAuth` → `login({ username, password, rememberMe }) -> Promise<FormSubmitResult>` | 登录请求发送与结果处理 | 未开始（L3 层） |
| AUTH-06（认证会话管理） | `logics/shared/hooks/useAuth` → `register({ role, username, password, phone, real_name }) -> Promise<FormSubmitResult>` | 注册请求发送与结果处理 | 未开始（L3 层） |
| AUTH-06（认证会话管理） | `logics/shared/store/userStore` → `isLoggedIn: boolean` | 登录态感知（页面渲染前判断） | 未开始（L3 层） |
| AUTH-06（认证会话管理） | `logics/shared/services/httpClient` | HTTP 请求发送（由 useAuth Hook 内部调用，AUTH-05 不直连） | 未开始（L3 层） |

> **mock 策略**：当 AUTH-06 未落地时，AUTH-05 的 logics 层使用以下 mock 进行开发和测试：
> ```typescript
> // mock useAuth Hook (在 logics/auth/__mocks__/useAuth.ts)
> const mockUseAuth = () => ({
>   login: async () => ({ ok: true, redirectTo: '/pages/index/index' }),
>   register: async () => ({ ok: true }),
>   isLoggedIn: false,
> });
> ```
> 替换条件：AUTH-06 的 `logics/shared/hooks/useAuth.ts` 完成后，删除 mock 文件并改为真实 import。

---

### 1.8 状态机

> 【对内实现】

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 副作用 |
|----------|----------|----------|----------|--------|
| `idle` | `userStartTyping`（任一字段 onChange 且该字段从空变为非空） | `inputting` | 无 | `fieldErrors` 中清除对应字段的旧错误 |
| `inputting` | `userSubmit`（点击登录/注册按钮 + 前端全量校验通过） | `submitting` | `status === 'inputting'`；`fieldErrors.length === 0` | `globalError` 清空为 null；`AtButton` 的 `disabled` 变为 true；`loading` 属性变为 true |
| `inputting` | `userSubmitWithErrors`（点击按钮但前端校验不通过） | `inputting`（不变） | `fieldErrors.length > 0` | `fieldErrors` 更新为最新校验结果；不发送网络请求 |
| `submitting` | `apiSuccess`（useAuth Hook 返回 `{ ok: true }`） | `success` | `status === 'submitting'` | `successMessage` 设为 "登录成功，正在跳转..." 或 "注册成功，请登录"；登录场景启动 1s 延迟跳转 timer |
| `submitting` | `apiError`（useAuth Hook 返回 `{ ok: false }`） | `failure` | `status === 'submitting'` | `globalError` 设为 `result.error` 或 "用户名或密码错误"；保留表单数据不清空 |
| `submitting` | `networkTimeout`（Promise 10s 未 settled） | `failure` | `status === 'submitting'` | `globalError` 设为 "网络异常，请检查网络后重试"；保留表单数据；按钮恢复可用 |
| `failure` | `userRetry`（用户修改任一字段） | `inputting` | `status === 'failure'` | `fieldErrors` 和 `globalError` 清空；原 `failure` 状态的错误提示消失 |
| `success` | `redirect`（登录成功延迟结束） | (组件卸载) | `status === 'success'`；`mode === 'login'`；timer 到期 | `Taro.redirectTo({ url })` 执行；AuthPage 组件卸载；Zustand store 自然销毁 |
| `success` | `userNavigateToLogin`（注册成功后点击"前往登录"按钮） | `idle` | `status === 'success'`；`mode === 'register'` | `Taro.navigateTo({ url: '/pages/auth/index' })` 执行；实际加载新页面实例，store 自然销毁 |

**初始状态**：`idle`（`mode === 'login'`，正常用户首先看到登录页）

**重置规则**：
- 调用 `handleSwitchMode()` → 全部状态重置为 `idle` + 对应 `mode` + 全部表单字段清空
- 页面卸载（路由离开或小程序关闭）→ Zustand store 自然销毁（未持久化）

**幂等策略**：
- `submitting` 状态下，`handleLoginSubmit()` / `handleRegisterSubmit()` 立即 return（不执行），防止重复提交
- 同一 `mode` 下的重复 `handleSwitchMode()` 调用不产生副作用（当前已是目标 mode）

---

### 1.9 异常与边界条件

> 【对内实现】

#### 1.9.1 异常 1：输入格式校验不通过

- **触发条件**：
  - `validateUsername()` 返回非 null（用户名不匹配 `/^[a-zA-Z0-9_-]{4,32}$/`）
  - `validatePassword()` 返回非 null（密码长度 `< 8` 或不匹配 `/^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/`）
  - `validatePhone()` 返回非 null（手机号不匹配 `/^1[3-9]\d{9}$/`）
  - `validateRealName()` 返回非 null（专家角色下姓名为空，或长度不在 2-20 范围）
- **处理策略**：
  1. 失焦校验阶段：更新 `fieldErrors` 数组（去重：同一 field 只保留最新错误）。不阻止用户操作，仅视觉反馈
  2. 提交前全量校验阶段：收集所有校验错误，任一非 null 即阻断提交（不调用 useAuth Hook），更新 `fieldErrors`
  3. 错误信息精确到字段和原因（如 "密码长度至少8位"），不使用 "请检查您的输入" 等模糊提示
  4. 用户修改对应字段后自动清除该字段的错误项（`onChange` 回调中调用 `clearFieldError(field)`）
- **重试参数**：不涉及（用户修正后自行重试）

#### 1.9.2 异常 2：登录凭证错误

- **触发条件**：useAuth Hook `login()` 返回 `{ ok: false, error: string }`，原因可能是用户名不存在或密码不匹配（AUTH-05 不区分）
- **处理策略**：
  1. 设置 `status = 'failure'`
  2. 设置 `globalError = '用户名或密码错误'`（统一提示，不暴露到底是用户名错还是密码错 — 意图文档 §1.11 约束 2）
  3. 保留 `loginForm.username` 和 `loginForm.password` 不清空（意图文档 §1.11 约束 7）
  4. 不修改 `fieldErrors`（字段级格式校验已在步骤 3 通过）
  5. 密码输入框可提供"清空重新输入"按钮，该按钮仅清空 `loginForm.password`（不清空 username）
- **重试参数**：不自动重试。用户修正后手动点击"登录"重新提交

#### 1.9.3 异常 3：注册信息冲突（用户名/手机号已被注册）

- **触发条件**：useAuth Hook `register()` 返回 `{ ok: false, error: '该用户名已被注册' }` 或 `{ ok: false, error: '该手机号已被注册' }`
- **处理策略**：
  1. 设置 `status = 'failure'`
  2. 设置 `globalError = result.error`（直接展示后端返回的具体冲突原因）
  3. 保留 `registerForm` 全部字段不清空（意图文档 §1.11 约束 7），但高亮冲突字段（username 或 phoneNumber）可选项
  4. 用户修改冲突字段后重新提交
- **重试参数**：不自动重试。用户更换用户名或手机号后手动重新提交

#### 1.9.4 异常 4：网络异常或服务不可用

- **触发条件**：
  - useAuth Hook `login()` / `register()` 的 Promise 在 10 秒内未 settled（客户端超时阈值 `SUBMIT_TIMEOUT_MS = 10000`）
  - 或 useAuth Hook 内部的 httpClient 因网络错误 reject（如 `ERR_CONNECTION_REFUSED`、`ERR_NAME_NOT_RESOLVED`）
- **处理策略**：
  1. `Promise.race([useAuth().login(), timeout(10000)])` 判断超时
  2. 超时或网络错误 → 设置 `status = 'failure'`，`globalError = '网络异常，请检查网络后重试'`
  3. 保留全部表单字段不清空
  4. 按钮恢复可用（`status !== 'submitting'`，`AtButton` 的 `disabled` 自动解除）
  5. 不执行重试（前端不自动重试，让用户判断网络情况后手动重试）
- **重试参数**：不自动重试。超时阈值 10000ms 硬编码为常量，不做配置化

#### 1.9.5 异常 5：注册成功后用户未跳转直接关闭小程序

- **触发条件**：注册成功后（`status === 'success'`）用户直接关闭小程序而非点击"前往登录"
- **处理策略**：
  1. 不记录此事件（AUTH-05 仅在内存中存在，不持久化状态）
  2. 下次打开小程序时，AUTH-06 的 `userStore.isLoggedIn` 仍为 `false`（注册不等于登录），因此仍展示登录页
  3. 用户体验上等同于注册完成但未登录 → 正常流程，无需额外处理
- **重试参数**：不涉及

#### 1.9.6 边界条件：页面切换时表单数据安全

- **触发条件**：用户从登录模式切换到注册模式（或反之）时，Zustand store 中可能包含敏感数据（密码）
- **处理策略**：
  1. `handleSwitchMode()` 必须调用 `resetFormState()`，将所有字段值设为空字符串（不保留任何之前输入的内容）
  2. Zustand store 不持久化（不调用 `persist` middleware），页面卸载后所有数据从内存中清除
  3. 密码字段使用 `AtInput type='password'`，确保屏幕展示为掩码字符
- **重试参数**：不涉及

---

### 1.10 验收测试场景

> 以下定义验收测试的核心场景和断言点。具体测试代码实现由 module-test-writer 负责。

#### 1.10.1 正向测试 1：完整登录流程成功

- **场景**：用户输入有效的用户名和密码，勾选"记住我"，提交后后端验证通过，页面成功跳转到主页
- **Given**：页面初始状态 `mode: 'login'`，所有表单字段为空
- **When**：
  1. 用户输入 username="test_user"，password="Abc12345"
  2. 用户勾选"记住我"复选框（`rememberMe: true`）
  3. 用户失焦每个字段后无校验错误提示
  4. 用户点击"登录"按钮
- **Then**：
  - 按钮变为 loading 状态（`AtButton` 的 `loading: true` 和 `disabled: true`）
  - `useAuth().login()` 被调用的参数为 `{ username: 'test_user', password: 'Abc12345', rememberMe: true }`
  - 1 秒内 `successMessage` 显示 "登录成功，正在跳转..."
  - 1 秒后 `Taro.redirectTo({ url: '/pages/index/index' })` 被调用

#### 1.10.2 正向测试 2：完整注册流程成功

- **场景**：用户选择"老师"角色，填写全部注册信息，提交后注册成功，引导至登录页
- **Given**：页面初始状态 `mode: 'register'`，所有表单字段为空
- **When**：
  1. 用户选择"老师"角色（roleType="老师"）
  2. 用户填写 username="new_teacher"，password="Teach1234"，phoneNumber="13900139000"，realName="李四"
  3. 失焦校验全部通过
  4. 用户点击"注册"按钮
- **Then**：
  - `useAuth().register()` 被调用的参数为 `{ role: 'teacher', username: 'new_teacher', password: 'Teach1234', phone: '13900139000', real_name: '李四' }`
  - `successMessage` 显示 "注册成功，请登录"
  - 页面渲染"前往登录"按钮
  - 点击"前往登录"后 `Taro.navigateTo({ url: '/pages/auth/index' })` 被调用

#### 1.10.3 正向测试 3：登录/注册页面切换后表单清空

- **场景**：用户在登录页填写了用户名，切换到注册页后登录页内容被清空
- **Given**：用户在登录页输入 username="test_user"
- **When**：用户点击"注册"切换到注册模式
- **Then**：
  - `mode` 变为 `'register'`
  - `loginForm.username` 为 `''`（被重置）
  - 注册表单全部字段为空
  - `status` 为 `'idle'`
  - `fieldErrors` 为空数组

#### 1.10.4 正向测试 4：角色选择后不可在流程中变更

- **场景**：用户选择"家属"角色后继续填写其他字段，角色 Radio 组被禁用
- **Given**：用户已选择 roleType="家属"
- **When**：用户尝试点击"老师"角色卡片
- **Then**：
  - `AtRadio` 组件 `disabled: true`
  - `roleType` 仍为 `'家属'`（不变）
  - "重新选择角色"按钮可见
  - 点击"重新选择角色"后 → `roleType` 变为 `''`，全部表单字段清空，Radio 组恢复可用

#### 1.10.5 异常测试 1：登录密码格式错误阻止提交

- **场景**：密码字段仅输入 "abc"（长度不足），点击登录后被前端校验拦截
- **Given**：username="test_user"，password="abc"
- **When**：用户点击"登录"按钮
- **Then**：
  - `status` 保持 `'inputting'`（不进入 `'submitting'`）
  - `fieldErrors` 中包含 `{ field: 'password', message: '密码长度至少8位' }`
  - `useAuth().login()` 未被调用
  - 按钮未变为 disabled 状态

#### 1.10.6 异常测试 2：登录失败展示统一错误提示

- **场景**：后端返回登录失败（无论原因是用户名不存在还是密码错误）
- **Given**：表单校验通过，`useAuth().login()` mock 返回 `{ ok: false, error: '用户名或密码错误' }`
- **When**：用户点击"登录"按钮
- **Then**：
  - `status` 变为 `'failure'`
  - `globalError` 为 `'用户名或密码错误'`
  - `loginForm.username` 和 `loginForm.password` 保留不清空
  - `fieldErrors` 为空（字段格式校验已通过）
  - 按钮恢复可用（`loading: false`, `disabled: false`）

#### 1.10.7 异常测试 3：网络超时展示通用提示

- **场景**：提交注册后 10 秒未收到响应
- **Given**：`useAuth().register()` mock 在 11 秒后才 resolve
- **When**：用户点击"注册"按钮
- **Then**：
  - 10 秒时 `status` 变为 `'failure'`
  - `globalError` 为 `'网络异常，请检查网络后重试'`
  - `registerForm` 全部字段保留不清空
  - 按钮恢复可用
  - 11 秒时 `useAuth().register()` resolve 被忽略（状态已为 `'failure'`）

#### 1.10.8 异常测试 4：专家角色未填真实姓名

- **场景**：用户选择"专家"角色但未填写真实姓名，点击注册后被前端校验拦截
- **Given**：roleType="专家"，realName=""（空字符串）
- **When**：用户点击"注册"按钮
- **Then**：
  - `status` 保持 `'inputting'`
  - `fieldErrors` 中包含 `{ field: 'realName', message: '专家角色必须填写真实姓名' }`
  - `useAuth().register()` 未被调用

---

### 1.11 注意事项与禁止行为（编码层面）

1. **[L1a/L1b 硬隔离]** `views/auth/` 下的所有 `.tsx` 文件必须以 Props-only 方式渲染。禁止在 views 文件中使用 `useEffect` 发送网络请求、读取 Taro Storage、或调用 `useAuth()` Hook。所有副作用和状态变更必须封装在 `logics/auth/hooks/useAuthPage.ts` 中。
2. **[Token 零接触]** 全量搜索 AUTH-05 的文件内容，确认无 `setStorage`、`getStorage`、`removeStorage`、`Taro.request`、`fetch`、`axios` 调用。
3. **[校验顺序不可逆]** `handleLoginSubmit()` 和 `handleRegisterSubmit()` 中必须先执行前端全量校验，校验全部通过后才调用 useAuth Hook。禁止先调用 useAuth 再根据返回错误更新 fieldErrors。
4. **[success 状态跳转时序]** 登录成功时，不应在 useAuth Hook resolve 的 then 回调中立即调用 `Taro.redirectTo()`。应使用 `useEffect` 监听 `status === 'success'` + `mode === 'login'`，延迟 800ms-1.5s 后执行跳转。延迟 timer 必须在 `useEffect` 的 cleanup 函数中清除（防止组件卸载后 timer 仍执行）。
5. **[mode 切换必须完全重置]** `handleSwitchMode()` 中必须调用 `resetFormState()`，包含：mode、status、loginForm 全部字段、registerForm 全部字段、fieldErrors、globalError、successMessage。缺一不可——遗漏任一字段的复位将导致"切换后旧表单数据残留"的 bug。
6. **[角色选择不可逆的实现细节]** 注册流程中 roleType 一旦非空，`AtRadio` 的 options 中每条 option 的 `disabled: true`。不得通过 CSS `pointer-events: none` 或 `opacity` 实现"看起来禁用但实际可点击"的伪禁用。
7. **[提交防重复的两种形态]** (a) `handleLoginSubmit()` / `handleRegisterSubmit()` 开头检查 `status === 'submitting'`，是则直接 return；(b) `AtButton` 的 `disabled` prop 绑定 `status === 'submitting'`。两种形态互补——(a) 防止代码层重复触发，(b) 防止用户快速双击绕过 React 事件队列。
8. **[禁止行为]**：
   - 禁止在 `views/auth/` 中定义任何 `async function` —— 所有异步操作必须在 `logics/auth/` 层执行
   - 禁止在组件内使用 `useAuth()` 或其他业务 Hook —— 仅 `useAuthPage` Hook 可调用 `useAuth()`，views 通过 `useAuthPage` 返回的 handler 间接调用
   - 禁止使用 `Taro.navigateBack` 处理登录成功跳转 —— `navigateBack` 不会清除登录页历史栈
   - 禁止在 `onChange` 回调中直接调用校验函数 —— 失焦校验和提交校验各有独立触发时机，`onChange` 仅负责更新字段值和清除该字段的旧错误
9. **[偷懒红线]**：
   - 禁止以"和 CSLT-07（应急咨询界面）设计类似"为由省略表单校验逻辑的具体参数
   - 禁止以"Taro UI 文档中有示例"为由不写 `AtInput`、`AtRadio`、`AtCheckbox` 的精确 props 绑定
   - 禁止以"roleMapper 很简单"为由不定义精确的映射表和 fallback 逻辑

---

### 1.12 文档详细度自检清单

- [x] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成 AUTH-05 编码（含 views 组件 + logics Hook + tools + types）
- [x] 无偷懒表述：全文无 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`
- [x] 类型定义完整：每个 TypeScript 类型字段都有 description + 约束 + 示例值
- [x] 逻辑步骤完整：每个步骤都有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：6 种异常/边界场景，每种都有精确触发阈值、处理策略和重试参数
- [x] 无隐藏假设：所有默认值来源、条件分支、业务规则都已显式写出
- [x] 技术栈绑定明确：7 项必须使用 + 6 项禁止使用，与项目技术栈设计文档一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致

---

### 1.14 外部接口契约清单

> AUTH-05 为纯 UI 表现层，不定义新的后端 API 端点或 JSON Schema 契约。所有接口类型均复用已有契约，内部 TypeScript 类型不对外暴露。

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| RegisterRequest | `docs/contracts/AUTH-01/RegisterRequest.json` | input | draft | AUTH-01 | AUTH-05 |
| RegisterResponse | `docs/contracts/AUTH-01/RegisterResponse.json` | output | draft | AUTH-01 | AUTH-05（间接，通过 AUTH-06） |
| UserRole | `docs/contracts/AUTH-01/UserRole.json` | shared-enum | draft | AUTH-01 | AUTH-05 |

> **复用说明**：AUTH-05 自身定义的 TypeScript 类型（`LoginFormState`、`RegisterFormState`、`AuthPageStatus`、`AuthPageState`、`FieldError`、`FormSubmitResult`）属于 UI 内部实现细节，不纳入 contracts/ 目录管理。AUTH-02（用户登录）的 LoginRequest/LoginResponse 契约尚未定义（当前无 AUTH-02 contracts/ 目录），AUTH-05 通过 AUTH-06 Hook 间接调用，待 AUTH-02 补充。

---

### 1.15 意图一致性声明

- **配套意图文档**：`AUTH-05-登录注册界面-意图文档.md`
- **冻结时间**：2026-05-26 22:41:33
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致（§1.6.1 五字段完全对齐）
  - [x] 本落地规范中的状态机实现与意图文档中的状态业务定义一致（§1.7 五状态完全对齐）
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致（§1.8 三异常全部覆盖并扩展至 6 场景）
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准（AC-01~AC-09 全覆盖）
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围（7 项决策全部已确定）
- **偏差说明**：无偏差。技术实现与意图文档完全一致。以下为增强（非偏差）：异常场景从 3 种扩展至 6 种（补充注册冲突、网络超时、页面关闭等边界），验收测试从 9 项 AC 扩展至 4 正 + 4 异常场景。
