# 1 功能点：PROF-07 档案数据逻辑 — 落地规范

> **文档生成时间**：`2026-05-27 21:48:26`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-27 21:48:26 | AI Assistant | 初始版本，基于技术预研报告 + 设计文档 v1.0 + 契约协调报告生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `PROF-07-档案数据逻辑-设计文档.md`。

---

### 1.1 技术栈绑定

- **必须使用**：
  - `Taro >= 4.0` — 小程序运行时框架，引用方式 `import Taro from '@tarojs/taro'`
  - `React >= 18.0` — UI 框架，Hooks 从 `react` 导入
  - `Zustand >= 5.0` — 全局状态管理，`create()` 创建 Store，`useStore()` / `subscribe()` 读写
  - `TypeScript >= 5.0` — 类型系统，`strict` 模式开启
  - `AUTH-06 httpClient` — 所有 HTTP 请求统一走 `import { httpClient } from '@/logics/shared/services/httpClient'`，调用 `httpClient.request<T>(options): Promise<IRequestResponse<T>>`
  - `AUTH-06 useAuth` — 认证状态获取，通过 `import { useAuth } from '@/logics/auth/hooks/useAuth'` 导入
  - `profiles/types/index.ts` — 模块内类型定义集中在此文件
  - `packages/ts-shared/src/enums/` — 跨模块共享枚举（DiagnosisType、LanguageLevel 等）

- **禁止使用**：
  - 禁止裸调 `Taro.request()` — 所有 HTTP 请求必须通过 `httpClient`，违反将导致 Token 无法自动注入和续期
  - 禁止在 `logics/profiles/` 中 `import` 任何 `views/` 目录下的文件
  - 禁止在 Hook 实现中直接操作 DOM 或调用 `Taro.navigateTo()`（路由跳转由 views 层负责）
  - 禁止在 `useProfile()` 的 `useEffect` 中自动触发 `fetchProfiles()` — 数据获取必须由 views 层显式调用
  - 禁止引入 React Query — 技术栈已统一使用 Zustand 5 做状态管理

### 1.2 文件归属

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 档案主 Hook | `apps/mini-program/src/logics/profiles/hooks/useProfile.ts` | `useProfile()` Hook 导出，供 PROF-06 views 层消费。管理档案列表获取、CRUD 操作、默认档案切换 |
| 微问卷 Hook | `apps/mini-program/src/logics/profiles/hooks/useMicroSurvey.ts` | `useMicroSurvey()` Hook 导出。管理微问卷弹出/回答/跳过/去重状态 |
| API 服务 | `apps/mini-program/src/logics/profiles/services/profileApi.ts` | 封装所有档案相关 HTTP 调用。基于 AUTH-06 httpClient，统一处理请求/响应映射和业务错误转换 |
| 状态管理 | `apps/mini-program/src/logics/profiles/store/profileStore.ts` | Zustand Store。管理档案列表缓存、详情缓存、冷启动状态、微问卷状态、表单提交状态 |
| 类型定义 | `apps/mini-program/src/logics/profiles/types/index.ts` | 前端专有类型：`ColdStartFormData`、`MicroSurveyState`、`MicroSurveyAnswer`、`ProfileListState`、`ProfileSubmitState`、`InterventionFeedback`、`InvalidatCacheRequest` |
| 枚举定义 | `packages/ts-shared/src/enums/profiles.ts` | PROF-01 枚举映射为 TypeScript 字符串字面量联合类型：`DiagnosisType`、`LanguageLevel`、`SensoryFeature`、`Trigger`、`AgeRange`、`ProfileBehaviorType` |

---

### 1.3 输入定义

> 【已锁定】本节所有对外接口类型的完整字段定义见对应契约文件。此处仅给出契约引用和本模块作为消费方的使用上下文。

**ProfileCreate**（来自 PROF-01）
- 【契约引用】`docs/contracts/PROF-01/ProfileCreate.json`
- 本模块作为消费方，用于冷启动引导提交和档案创建表单提交
- 必填项映射：`birth_date`（Date 选择器，不能晚于当天）→ `diagnosis_type`（下拉选择 DiagnosisType）→ `primary_behavior`（下拉选择 ProfileBehaviorType）
- 可选项映射：`nickname`、`language_level`、`sensory_features`、`triggers`、`medication_notes`

**ProfileUpdate**（来自 PROF-01）
- 【契约引用】`docs/contracts/PROF-01/ProfileUpdate.json`
- 本模块作为消费方，用于档案编辑页 Merge Patch 提交
- 全部字段可选，仅传入用户实际修改的字段

**ProfileCoordination**（PROF-07 内部 TypeScript 接口）
```typescript
// logics/profiles/types/index.ts
export interface ProfileCoordination {
  // 冷启动检测：每次进入咨询前实时检测
  checkProfileExists(): Promise<boolean>;
  // 微问卷触发：CSLT-08 SSE COMPLETE 后调用，同一 consultationId 仅触发一次
  triggerMicroSurvey(consultationId: string): void;
  // 档案变更订阅：返回 unsubscribe 清理函数
  onProfileChanged(callback: (profileId: string) => void): () => void;
}
```
- 【内部类型】不写入 JSON Schema 契约
- 消费方：CSLT-08 通过 ES Module import 导入调用

**microSurvey event params**（来自 CSLT-08 事件）
```typescript
// CSLT-08 调用 triggerMicroSurvey 时传入的参数
interface MicroSurveyTriggerParams {
  consultationId: string;  // 本次咨询 ID，用于去重
  // 未来可扩展：consultationContext (可选，当前未使用)
}
```

**ColdStartFormData**（PROF-07 内部 TypeScript 类型）
```typescript
export interface ColdStartFormData {
  birth_date: string;       // "YYYY-MM-DD"，不能晚于当天
  diagnosis_type: string;   // DiagnosisType 枚举值
  primary_behavior: string; // ProfileBehaviorType 枚举值
}
```

**MicroSurveyAnswer**（PROF-07 内部 TypeScript 类型）
```typescript
export interface MicroSurveyAnswer {
  consultationId: string;
  triggerFactor?: string;       // 用户选择的触发因素（Trigger 枚举值 或 自定义 ≤10字文本）
  interventionFeedback?: string; // 用户选择的干预有效性（InterventionFeedback 三档）
}
```

### 1.4 输出定义

> 【已锁定】本节所有对外接口类型的完整字段定义见对应契约文件。

**ProfileListItem[]**（来自 PROF-01）
- 【契约引用】`docs/contracts/PROF-01/ProfileListItem.json`
- 本模块作为消费方，通过 `useProfile().profiles` 暴露给 PROF-06 views 层
- 用于档案列表页渲染：昵称、年龄区间、诊断类型、行为类型、默认标记

**ProfileResponse**（来自 PROF-01）
- 【契约引用】`docs/contracts/PROF-01/ProfileResponse.json`
- 本模块作为消费方，`getProfile()` 和 `createProfile()` 的 Promise 返回值
- 用于档案详情页和编辑页初始数据

**UseProfileReturn**（PROF-07 内部 TypeScript 接口）
```typescript
export interface UseProfileReturn {
  // 数据
  profiles: ProfileListItem[];       // 当前家属账号下的档案列表，可能为空数组
  isLoading: boolean;                // 列表是否正在加载中
  error: Error | null;               // 最近一次操作失败的错误，成功时为 null

  // CRUD 操作
  fetchProfiles: () => Promise<void>;
  getProfile: (profileId: string) => Promise<ProfileResponse>;
  createProfile: (data: ProfileCreate) => Promise<ProfileResponse>;  // 冷启动引导用
  updateProfile: (profileId: string, data: Partial<ProfileUpdate>) => Promise<ProfileResponse>;
  deleteProfile: (profileId: string) => Promise<void>;
  setDefault: (profileId: string) => Promise<void>;
}
```
- 【内部类型】不写入 JSON Schema 契约
- 消费方：PROF-06 `views/profiles/` 通过 `const { profiles, ... } = useProfile()` 调用

**useMicroSurvey return**（PROF-07 内部 TypeScript 接口）
```typescript
export interface UseMicroSurveyReturn {
  state: MicroSurveyState;          // 当前微问卷状态
  questions: MicroSurveyQuestion[];  // 当前会话的 2 道固定题目
  submit: (answer: MicroSurveyAnswer) => Promise<void>;
  skip: () => void;
}
```
- 【内部类型】不写入 JSON Schema 契约
- 消费方：PROF-06 微问卷浮层组件

### 1.5 核心逻辑步骤

#### 流程 1：档案列表获取（useProfile.fetchProfiles）

1. **步骤 1.1：认证状态前置校验**
   - **操作对象**：`useAuth().sessionState`
   - **具体操作**：检查 `sessionState === 'authenticated'`，若 `unauthenticated` 或 `refreshing`，返回 `Promise.reject(new AuthRequiredError('请先登录'))`
   - **输入来源**：AUTH-06 useAuth Hook
   - **输出去向**：校验通过后进入步骤 1.2，失败则终止流程
   - **失败行为**：不发起 HTTP 请求，profileStore.error 置为 `AuthRequiredError`

2. **步骤 1.2：设置加载状态**
   - **操作对象**：`profileStore` 的 `listState` 字段
   - **具体操作**：执行 `profileStore.getState().setListState('loading')`。若当前 `listState === 'loading'`，忽略本次调用（幂等保护）
   - **输入来源**：步骤 1.1 通过
   - **输出去向**：状态变更触发 PROF-06 UI 展示加载指示器
   - **失败行为**：本身不失败，仅修改内存状态

3. **步骤 1.3：发起 HTTP 列表请求**
   - **操作对象**：`httpClient` 实例
   - **具体操作**：调用 `profileApi.listProfiles()` → 内部执行 `httpClient.request<ProfileListItem[]>({ method: 'GET', url: '/api/v1/profiles' })`
   - **输入来源**：步骤 1.2 store 状态 ready，无需额外参数（Token 由拦截链自动注入）
   - **输出去向**：成功响应体 `ProfileListItem[]` 进入步骤 1.5，HTTP 错误进入步骤 1.4
   - **失败行为**：见步骤 1.4

4. **步骤 1.4：列表获取失败处理**
   - **操作对象**：`profileStore` 的 `error` 和 `listState` 字段
   - **具体操作**：根据 HTTP 状态码分类处理：
     - 401 → `profileStore.setError(new AuthRequiredError('登录已过期'))` + `setListState('error')`
     - 网络错误/超时 → `profileStore.setError(new NetworkError('加载失败，请检查网络后重试'))` + `setListState('error')`
     - 其他 4xx/5xx → `profileStore.setError(new ServerError('服务异常，请稍后重试'))` + `setListState('error')`
   - **输入来源**：步骤 1.3 HTTP 错误响应
   - **输出去向**：状态变更触发 PROF-06 展示错误提示 + 重新加载按钮
   - **失败行为**：不展示空白占位。PROF-06 渲染 `error.message` 文本和"重新加载"按钮，点击触发 `fetchProfiles()` 重新进入步骤 1.1

5. **步骤 1.5：列表获取成功 → 更新缓存**
   - **操作对象**：`profileStore` 的 `list`、`listState` 和 `currentDetail` 字段
   - **具体操作**：
     - `profileStore.getState().setList(data)` — 写入完整列表
     - `profileStore.getState().setListState('ready')` — 切换状态
     - 若 `data[0]` 存在且 `profileStore.currentDetail` 为空 → 不会自动设置（等待 views 层显式调用 getProfile）
   - **输入来源**：步骤 1.3 HTTP 成功响应体 `ProfileListItem[]`
   - **输出去向**：PROF-06 通过 `useProfile().profiles` 响应式渲染列表
   - **失败行为**：不涉及

#### 流程 2：冷启动检测与档案创建（ProfileCoordination.checkProfileExists + createProfile）

1. **步骤 2.1：实时检测档案存在性**
   - **操作对象**：`profileStore.list` 和 `profileApi`
   - **具体操作**：
     - 若 `profileStore.list.length > 0` → 直接返回 `true`（已有缓存数据）
     - 若 `profileStore.list.length === 0` → 调用 `profileApi.listProfiles()`，返回 `data.length > 0`
     - 若 `sessionState !== 'authenticated'` → 返回 `false`（无用户上下文，不发起查询）
   - **输入来源**：CSLT-08 调用 `checkProfileExists()`
   - **输出去向**：返回 `boolean` 给 CSLT-08
   - **失败行为**：HTTP 失败 → 返回 `false`，不抛出异常（采用安全默认——无档案则弹出引导，网络错误时同视为无档案，不阻断用户）

2. **步骤 2.2：冷启动表单提交**
   - **操作对象**：`ColdStartFormData` 实例
   - **具体操作**：
     - 前端校验：`birth_date` 不能晚于 `new Date()`，`diagnosis_type` 必须在 `ALLOWED_DIAGNOSIS_TYPES` 中，`primary_behavior` 必须在 `ALLOWED_BEHAVIOR_TYPES` 中
     - 映射为 `ProfileCreate` 契约格式：`{ birth_date, diagnosis_type, primary_behavior }` 仅 3 项必填
     - 调用 `profileApi.createProfile(profileCreate)`
   - **输入来源**：PROF-06 冷启动表单组件的 `onSubmit` 回调
   - **输出去向**：成功 → 返回 `ProfileResponse` + 进入步骤 2.3；失败 → 进入步骤 2.4
   - **失败行为**：见步骤 2.4

3. **步骤 2.3：冷启动创建成功 → 更新 Store + 通知**
   - **操作对象**：`profileStore` 和 `ProfileCoordination.onProfileChanged` 回调列表
   - **具体操作**：
     - `profileStore.getState().addToList(response)` — 追加新档案到列表
     - `profileStore.getState().setListState('ready')` — 状态就绪
     - 遍历 `onProfileChanged` 回调列表，每个回调执行 `callback(response.profile_id)`
     - fire-and-forget 调用 `invalidateCache(response.profile_id, ['all'])`（见流程 5）
   - **输入来源**：`ProfileResponse` 实例
   - **输出去向**：返回 `ProfileResponse` 给 CSLT-08 通知编排继续
   - **失败行为**：`invalidateCache` 失败不阻断主流程

4. **步骤 2.4：冷启动创建失败处理**
   - **操作对象**：`profileStore` 的 `submitState` 和错误信息
   - **具体操作**：
     - 422（字段校验失败）→ `profileStore.setSubmitState('idle')` + 逐字段映射后端错误到表单内联提示
     - 409 ProfileLimitExceeded → `profileStore.setSubmitState('idle')` + 弹窗"已达到档案数量上限（5个），如需新增请先删除已有档案"
     - 网络错误 → `profileStore.setSubmitState('error')` + 提示"网络异常，请重试"。**保留表单已填写数据**（Zustand store 不随组件卸载清空）
     - 409 ProfileConflict → `profileStore.setSubmitState('idle')` + 弹窗"档案已被其他设备修改，请刷新后重试"
   - **输入来源**：步骤 2.2 失败响应
   - **输出去向**：状态变更触发 PROF-06 展示错误提示或内联校验提示
   - **失败行为**：不自动重试。用户修正后手动重新提交

#### 流程 3：微问卷弹出与沉淀（triggerMicroSurvey + submit）

1. **步骤 3.1：去重检查**
   - **操作对象**：内存 `Set<string>`（变量名 `displayedConsultationIds`，模块作用域）
   - **具体操作**：`if (displayedConsultationIds.has(consultationId)) return;` — 已弹出则 no-op。否则 `displayedConsultationIds.add(consultationId)` 并进入步骤 3.2
   - **输入来源**：CSLT-08 调用 `triggerMicroSurvey(consultationId)`
   - **输出去向**：通过后触发 microSurveyStore 状态变更
   - **失败行为**：本身不失败

2. **步骤 3.2：设置显示状态**
   - **操作对象**：`microSurveyStore`（Zustand store 的子切片 `profileStore.microSurvey`）
   - **具体操作**：
     - `microSurveyStore.setState('showing')` — 弹出浮层
     - `microSurveyStore.setQuestions([{ id: 'trigger', text: '本次触发了什么因素？', type: 'single-choice-with-custom' }, { id: 'effectiveness', text: '刚才的建议是否有帮助？', type: 'single-choice', options: InterventionFeedbackValues }])` — 固定 2 题
   - **输入来源**：步骤 3.1 去重通过
   - **输出去向**：状态变更触发 PROF-06 微问卷浮层组件渲染
   - **失败行为**：不涉及

3. **步骤 3.3：用户回答 → 数据沉淀**
   - **操作对象**：`MicroSurveyAnswer` 实例
   - **具体操作**：
     - 设置 `microSurveyStore.setState('answering')`（UI 展示提交中状态）
     - 若 `answer.triggerFactor` 非空：
       - 追加到档案 `triggers` 数组（调用 `profileApi.updateProfile(profileId, { triggers: [...existingTriggers, answer.triggerFactor] })`）
       - 可选事件记录：若 `answer.triggerFactor` 为用户自定义文本（非预设 Trigger 枚举值）→ 调用 PROF-03 `POST /api/v1/events`（`EventCreate` 契约，`trigger_description = answer.triggerFactor`，`behavior_type = 当前档案的 primary_behavior`）。注：事件写入为 fire-and-forget，失败不影响主流程
     - 若 `answer.interventionFeedback` 非空：
       - 不写入档案字段。当前版本仅记录到调试日志（可后续扩展为 PROF-04 专业评估的数据源）
     - 提交完成 → `microSurveyStore.setState('submitted')`
     - 2 秒后 → `microSurveyStore.setState('hidden')`（自动关闭）
   - **输入来源**：PROF-06 微问卷浮层组件的 `onSubmit(answer)` 回调
   - **输出去向**：标签更新到 PROF-01；事件写入到 PROF-03
   - **失败行为**：
     - 标签更新失败 → `microSurveyStore.setState('showing')`（保留用户选择）+ 顶部 toast "保存失败，请重试"
     - 事件记录失败 → 静默忽略，不阻塞标签更新

4. **步骤 3.4：用户跳过**
   - **操作对象**：`microSurveyStore`
   - **具体操作**：`microSurveyStore.setState('hidden')`。`displayedConsultationIds` 中保留该 `consultationId`（阻止同一咨询再次弹出）
   - **输入来源**：PROF-06 微问卷浮层组件的 `onSkip()` 回调
   - **输出去向**：浮层关闭
   - **失败行为**：不涉及

#### 流程 4：档案编辑与默认切换（updateProfile / setDefault）

1. **步骤 4.1：档案编辑提交流程**
   - 与流程 2（冷启动创建）共用 `profileApi.updateProfile()` 和步骤 2.4 的错误处理逻辑
   - 区别：`ProfileUpdate` 全部字段可选，仅传入修改的字段（Merge Patch）
   - 提交成功后执行步骤 4.3（变更通知）

2. **步骤 4.2：默认档案切换**
   - **操作对象**：`profileStore.list` 和 `profileApi`
   - **具体操作**：
     - 调用 `profileApi.setDefault(profileId)` → 内部 HTTP `PUT /api/v1/profiles/{profileId}/default`
     - 成功后更新 `profileStore`：遍历 `list`，新默认 `is_default = true`，旧默认 `is_default = false`
     - 执行步骤 4.3（变更通知）
   - **输入来源**：PROF-06 档案列表页的"设默认"按钮
   - **输出去向**：store 更新触发 PROF-06 列表标记位置更新

3. **步骤 4.3：档案变更通知（变更后统一执行）**
   - **操作对象**：`httpClient` 和 `onProfileChanged` 回调列表
   - **具体操作**：
     - 遍历 `onProfileChanged` 回调，执行 `callback(profileId)`
     - fire-and-forget HTTP `POST /api/v1/profiles/{profileId}/invalidate-cache`，请求体 `{ profileId, changedFields }`
     - `try { await httpClient.request(...) } catch { console.warn('[PROF-07] invalidate cache failed, PROF-02 may not be ready', e) }`
   - **输入来源**：步骤 2.3 / 4.1 / 4.2 成功
   - **输出去向**：通知 PROF-02（若可用）和 CSLT-08（通过回调）
   - **失败行为**：HTTP 404 → 静默忽略（PROF-02 未就绪）。网络错误 → `console.warn`，不阻断用户操作

#### 流程 5：档案删除

1. **步骤 5.1：删除确认**
   - 由 PROF-06 views 层负责渲染确认弹窗
   - 用户确认后调用 `useProfile().deleteProfile(profileId)`

2. **步骤 5.2：执行删除**
   - **操作对象**：`profileApi`
   - **具体操作**：`httpClient.request({ method: 'DELETE', url: '/api/v1/profiles/{profileId}' })`
   - **成功**：`profileStore.removeFromList(profileId)`。若删除的是当前默认档案且列表非空，将列表第一个档案设为默认
   - **失败**：403 → "无权限删除"；其他 → "删除失败，请重试"
   - 成功后执行流程 4.3（变更通知）

---

### 1.6 接口契约

> 【已锁定】本章节定义本模块对外暴露的公共接口，是 Agent 生成测试文件和实现代码的核心依据。

#### 1.6.1 接口 1：useProfile

```typescript
// apps/mini-program/src/logics/profiles/hooks/useProfile.ts
export function useProfile(): UseProfileReturn {
  /**
   * 档案数据管理核心 Hook。供 PROF-06 views 层通过 React Hooks 调用获取档案数据和操作方法。
   *
   * Returns:
   *   UseProfileReturn: 包含档案列表、加载状态、错误信息和 CRUD 操作方法
   *
   * Side Effects:
   *   - fetchProfiles() 调用 profileApi.listProfiles() 发起 HTTP 请求
   *   - createProfile() 成功后写入 profileStore.list 并触发 onProfileChanged 回调
   *   - updateProfile() 成功后更新 profileStore.list 中对应条目
   *   - deleteProfile() 成功后从 profileStore.list 移除
   *   - 所有操作通过 httpClient 自动记录结构化日志
   *
   * Idempotency:
   *   fetchProfiles: loading 期间重复调用被忽略
   *   createProfile: submitting 期间按钮 disabled 防止重复
   *   setDefault: 幂等——重复设置同一档案为默认无副作用
   *
   * Thread Safety:
   *   单线程（JavaScript 主线程），Zustand store 更新通过 setState 原子操作
   */
}

export interface UseProfileReturn {
  // 数据
  profiles: ProfileListItem[];       // 【契约引用】PROF-01/ProfileListItem
  isLoading: boolean;
  error: Error | null;

  // 操作
  fetchProfiles: () => Promise<void>;
  getProfile: (profileId: string) => Promise<ProfileResponse>;  // 【契约引用】PROF-01/ProfileResponse
  createProfile: (data: ProfileCreate) => Promise<ProfileResponse>;  // 【契约引用】PROF-01/ProfileCreate
  updateProfile: (profileId: string, data: Partial<ProfileUpdate>) => Promise<ProfileResponse>;  // 【契约引用】PROF-01/ProfileUpdate
  deleteProfile: (profileId: string) => Promise<void>;
  setDefault: (profileId: string) => Promise<void>;
}
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `useProfile` — 档案数据的获取与操作入口 |
| **输入类型** | 无入参（通过 AUTH-06 httpClient 隐式获取认证上下文） |
| **输出类型** | `UseProfileReturn` — 含 profiles 数组和 7 个操作方法 |
| **异常类型** | `AuthRequiredError`、`NetworkError`、`ServerError`、`ProfileLimitExceededError`（来自 PROF-01）、`ProfileConflictError`（来自 PROF-01） |
| **副作用** | HTTP 请求、profileStore 状态变更、onProfileChanged 回调触发、结构化日志记录 |
| **幂等性** | fetchProfiles 加载中幂等、createProfile 按钮防重复、setDefault 幂等 |
| **并发安全** | 单线程，Zustand setState 原子操作 |

#### 1.6.2 接口 2：useMicroSurvey

```typescript
// apps/mini-program/src/logics/profiles/hooks/useMicroSurvey.ts
export function useMicroSurvey(): UseMicroSurveyReturn {
  /**
   * 微问卷状态管理 Hook。管理弹出、回答、跳过、去重逻辑。
   *
   * Side Effects:
   *   - submit() 调用 profileApi.updateProfile() 写入触发因素
   *   - submit() 可选调用 PROF-03 EventCreate API
   *   - 内存 Set<string> 维护 consultationId 去重
   *
   * Idempotency:
   *   同一 consultationId 的 triggerMicroSurvey 调用第二次起为 no-op
   */
}

export interface UseMicroSurveyReturn {
  state: MicroSurveyState;
  questions: MicroSurveyQuestion[];
  submit: (answer: MicroSurveyAnswer) => Promise<void>;
  skip: () => void;
}
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `useMicroSurvey` — 微问卷流程管理 |
| **输入类型** | 无直接入参（由 CSLT-08 通过 `ProfileCoordination.triggerMicroSurvey` 驱动状态变更） |
| **输出类型** | `UseMicroSurveyReturn` — 含状态枚举、题目列表和操作方法 |
| **异常类型** | `NetworkError`（标签更新失败时回退状态） |
| **副作用** | profileStore.microSurvey 状态变更、HTTP 标签更新、可选 EventCreate 写入 |
| **幂等性** | 同一 consultationId 仅弹出一次 |

#### 1.6.3 接口 3：ProfileCoordination

```typescript
// apps/mini-program/src/logics/profiles/index.ts（模块入口导出）
export const profileCoordination: ProfileCoordination = {
  checkProfileExists: async (): Promise<boolean> => {
    // 实现见流程 2.1
  },
  triggerMicroSurvey: (consultationId: string): void => {
    // 实现见流程 3.1-3.2
  },
  onProfileChanged: (callback: (profileId: string) => void): (() => void) => {
    // 注册回调，返回 unsubscribe 函数
    const store = useProfileStore.getState();
    store.addChangeListener(callback);
    return () => store.removeChangeListener(callback);
  },
};
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `ProfileCoordination` — 与 CSLT-08 的横向协作接口 |
| **消费方** | CSLT-08 通过 `import { profileCoordination } from '@/logics/profiles'` 导入 |
| **异常类型** | `checkProfileExists` 网络失败时返回 `false`（安全默认，不抛异常） |
| **副作用** | `checkProfileExists` 可能触发 HTTP 请求；`triggerMicroSurvey` 变更 microSurveyStore 状态；`onProfileChanged` 注册全局回调 |
| **幂等性** | `triggerMicroSurvey` 同一 consultationId 幂等 |

---

### 1.7 依赖与集成接口

> 【已锁定】本章节列出本模块调用的全部外部接口，区分硬性基础设施依赖（不可 mock）和业务模块依赖（可 mock）。

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 运行时框架 | Taro 4 | `Taro.getCurrentInstance().router` | 获取当前路由参数（仅用于 types 层推断上下文，不在 Hook 层直接使用） | 项目结构 §6.1 前端框架选型 |
| 状态管理 | Zustand 5 | `create<T>()`, `useStore()`, `subscribe()` | Store 创建与订阅 | 技术栈设计 §2 |
| 类型系统 | TypeScript 5 | `strict` 模式编译 | 全量类型检查 | 技术栈设计 §2 |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| AUTH-06 httpClient | `httpClient.request<T>(options: RequestOptions): Promise<IRequestResponse<T>>` | 所有 HTTP 调用的统一入口。自动注入 Authorization header 和 Token 续期 | ✅ 已落地（PROF-07 为契约注册消费者） |
| AUTH-06 useAuth | `useAuth() => UseAuthReturn { sessionState: SessionState, ... }` | 获取当前认证状态。冷启动检测前校验 `sessionState === 'authenticated'` | ✅ 已落地 |
| PROF-01 profileApi | `POST /api/v1/profiles` → `ProfileResponse`；`GET /api/v1/profiles` → `ProfileListItem[]`；`GET /api/v1/profiles/{id}` → `ProfileResponse`；`PUT /api/v1/profiles/{id}` → `ProfileResponse`；`DELETE /api/v1/profiles/{id}` → `void`；`PUT /api/v1/profiles/{id}/default` → `void` | 档案 CRUD 操作。本模块通过 profileApi.ts 封装调用 | ✅ 已落地（12 份契约，PROF-07 为注册消费者） |
| PROF-02 缓存失效 API | `POST /api/v1/profiles/{profileId}/invalidate-cache`，请求体 `{ profileId: string, changedFields: string[] }` | 档案变更后通知 PROF-02 刷新检索缓存 | ⚠️ 依赖缺口 GAP-01（PROF-02 尚未设计）。实现时带 null-guard 降级：404 或网络错误 → console.warn |
| PROF-03 事件记录 API | `POST /api/v1/events` → `EventResponse`（`EventCreate` 契约） | 微问卷沉淀时写入事件记录。仅用户显式回答了触发因素且为自定义文本时才触发 | ✅ 已落地（PROF-07 为 EventCreate 注册消费者） |
| CSLT-08 ProfileCoordination 调用方 | `checkProfileExists(): Promise<boolean>`；`triggerMicroSurvey(consultationId: string)`；`onProfileChanged(callback)` | CSLT-08 通过 ES Module import 导入本模块的 `profileCoordination` 对象 | ⚠️ 依赖缺口 GAP-02（CSLT-08 尚未设计） |

**Mock 策略**：
- PROF-02 不在线时（404）→ 变更通知静默降级，不影响主流程
- CSLT-08 不在线时 → `profileCoordination` 对象仍可正常导出，方法内部逻辑不受影响（仅不接收调用）
- PROF-01 / PROF-03 API 不在线时 → 按异常策略返回用户可读错误

---

### 1.8 状态机

#### 1.8.1 档案列表加载状态

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 副作用 |
|----------|----------|----------|----------|--------|
| `idle` | `fetchProfiles()` | `loading` | sessionState === 'authenticated' | setListState('loading')，发起 HTTP GET /api/v1/profiles |
| `loading` | 请求成功 | `ready` | HTTP 2xx 响应 | setList(data)，setListState('ready')，React 响应式渲染列表 |
| `loading` | 请求失败 | `error` | HTTP 非 2xx 或网络错误 | setError(err)，setListState('error')，展示错误提示+重试按钮 |
| `loading` | `fetchProfiles()`（重复调用） | `loading`（忽略） | 与当前状态相同 | No-op，幂等保护 |
| `error` | 用户点击"重新加载" → `fetchProfiles()` | `loading` | — | 清除 error，重新发起 HTTP 请求 |
| `ready` | 用户下拉刷新 → `fetchProfiles()` | `loading` | — | 保留当前列表数据（SWR），后台静默刷新 |

#### 1.8.2 档案提交状态

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 副作用 |
|----------|----------|----------|----------|--------|
| `idle` | `createProfile()` 或 `updateProfile()` 调用 | `submitting` | 表单前端校验通过 | setSubmitState('submitting')，按钮 disabled |
| `submitting` | 提交成功 | `success` → 自动 `idle` | HTTP 2xx 响应 | 更新 store.list，触发 onProfileChanged 回调，invalidateCache，自动转入 idle |
| `submitting` | 校验失败（422） | `idle` | HTTP 422 | 逐字段映射后端错误到表单内联提示，保留表单数据 |
| `submitting` | 数量超限（409） | `idle` | HTTP 409 ProfileLimitExceeded | 弹窗提示超限，保留表单数据 |
| `submitting` | 并发冲突（409） | `idle` | HTTP 409 ProfileConflict | 弹窗提示刷新重试，保留表单数据 |
| `submitting` | 网络失败 | `error` | 网络超时/不可达 | setSubmitState('error')，错误文案，保留表单数据 |
| `error` | 用户点击重试 | `submitting` | 恢复上次表单数据 | 重新发起同一 HTTP 请求 |

#### 1.8.3 微问卷交互状态

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 副作用 |
|----------|----------|----------|----------|--------|
| `hidden` | CSLT-08 调用 `triggerMicroSurvey(id)` | `showing` | consultationId 不在去重 Set 中 | displayIds.add(id)，setState('showing')，浮层弹出 |
| `hidden` | `triggerMicroSurvey(id)` 但 id 已去重 | `hidden`（忽略） | — | No-op |
| `showing` | 用户点击回答 | `answering` | — | setState('answering')，展示提交中状态 |
| `answering` | 提交成功 | `submitted` | HTTP 标签更新 2xx | setState('submitted')，2s 后自动 → hidden |
| `answering` | 提交失败 | `showing` | 网络错误 | 保留用户选择，顶部 toast "保存失败，请重试" |
| `showing` | 用户点击跳过 | `hidden` | — | setState('hidden')，浮层关闭，id 保留在去重 Set |
| `submitted` | 2 秒延迟 | `hidden` | — | setState('hidden')，浮层关闭 |

---

### 1.9 异常与边界条件

#### 1.9.1 异常 1：认证令牌缺失或过期

- **触发条件**：
  - `useAuth().sessionState !== 'authenticated'`（未登录 / Token 过期 / 续期中）
  - AUTH-06 httpClient 在请求后收到 HTTP 401 响应
- **处理策略**：
  1. 前置校验（`fetchProfiles` / `checkProfileExists`）：若 `sessionState !== 'authenticated'`，抛出 `new AuthRequiredError('请先登录')`，`profileStore.listState` 置为 `error`，不发起 HTTP 请求
  2. 后置校验（HTTP 401）：由 AUTH-06 httpClient 拦截链自动处理——尝试 Token 续期，续期成功后重放原请求；续期失败 3 次后清除会话并跳转登录页。本模块不重复实现此逻辑
  3. `profileStore.error` 置为 `AuthRequiredError`，PROF-06 views 层展示"登录已过期，请重新登录"
- **重试参数**：由 AUTH-06 httpClient 拦截链控制（Token 续期最多 3 次，间隔由拦截链决定）。本模块不自行重试

#### 1.9.2 异常 2：档案列表获取失败（网络错误 / 服务端错误）

- **触发条件**：
  - HTTP 请求超时（>10 秒，由 httpClient 默认超时配置控制）
  - 网络不可达（fetch 抛出 `TypeError: Failed to fetch`）
  - 服务端返回 HTTP 5xx
- **处理策略**：
  1. 捕获具体异常类型：`TypeError`（网络不可达）→ `NetworkError`；HTTP 5xx → `ServerError`
  2. `profileStore.setListState('error')`
  3. `profileStore.setError(new NetworkError('加载失败，请检查网络后重试') 或 new ServerError('服务异常，请稍后重试'))`
  4. 不展示空白页。PROF-06 渲染错误文本 + "重新加载"按钮
  5. 若 `profileStore.list` 中已有旧数据，继续展示旧数据（SWR 容忍过期）
  6. 记录日志：`console.error('[PROF-07] listProfiles failed', { error: e.message, stack: e.stack })`
- **重试参数**：手动重试（用户点击"重新加载"按钮），无自动重试。`fetchProfiles()` 被 PROF-06 views 层再次调用时从头执行

#### 1.9.3 异常 3：档案提交失败（字段校验 / 业务规则）

- **触发条件**：
  - HTTP 422：`birth_date` 晚于当天、`diagnosis_type` 不在枚举值中、`nickname` 超过 10 字
  - HTTP 409 `ProfileLimitExceededError`：账号下已有 5 个档案
  - HTTP 409 `ProfileConflictError`：乐观锁冲突
  - 网络超时（>10 秒）
- **处理策略**：
  1. 422 → 提取后端响应体 `detail` 字段（字段名→错误信息映射）。遍历映射，逐字段设置表单内联错误提示。`submitState` 置为 `idle`。**保留表单已填写数据**（Zustand store 不清空）
  2. 409 LimitExceeded → `submitState` 置为 `idle`。PROF-06 弹窗"已达到档案数量上限（5个），如需新增请先删除已有档案"
  3. 409 Conflict → `submitState` 置为 `idle`。PROF-06 弹窗"档案已被其他设备修改，请刷新后重试"
  4. 网络错误 → `submitState` 置为 `error`。PROF-06 展示"提交失败，请检查网络后重试"。保留表单数据
- **重试参数**：手动重试。校验错误（422/409）不重试——用户修正后重新提交。网络错误 → 用户点击重试按钮后重新提交

#### 1.9.4 异常 4：微问卷标签更新失败

- **触发条件**：
  - `profileApi.updateProfile()` 调用失败（网络错误 / 服务端错误）
  - 档案的 `triggers` 数组已达合理上限（如 20 个），后端拒绝追加
- **处理策略**：
  1. 网络错误 → `microSurveyStore.setState('showing')`（回退到问题展示状态），保留用户的选择，顶部 toast "保存失败，请重试"
  2. 后端拒绝 → `microSurveyStore.setState('hidden')`，顶部 toast 具体错误原因
  3. 事件记录写入（PROF-03）失败 → 静默忽略，不影响标签更新
- **重试参数**：手动重试（用户重新点击提交）。不自动重试——避免重复追加标签

#### 1.9.5 边界条件：档案列表为空

- **触发条件**：`profileApi.listProfiles()` 返回 `[]`
- **处理策略**：
  - `profileStore.setList([])`，`setListState('ready')`
  - PROF-06 views 层根据 `profiles.length === 0` 渲染空状态引导（如"还没有档案，创建一个吧"）
  - `checkProfileExists()` 返回 `false`

#### 1.9.6 边界条件：冷启动引导被中断（小程序后台挂起）

- **触发条件**：用户在冷启动表单填写过程中将小程序切到后台
- **处理策略**：
  - 表单数据保留在 Zustand store 中（不随页面卸载清空）
  - 用户下次进入咨询时重新执行 `checkProfileExists()` → 仍为 `false` → 重新弹出冷启动引导
  - 不恢复上次的部分填写（简化实现，3 项下拉选择恢复成本高于重新填写）
- **重试参数**：不重试。用户重新填写提交

---

### 1.10 验收测试场景

#### 1.10.1 正向测试 1：新用户冷启动引导 → 成功创建档案 → 进入咨询

- **场景**：新用户首次发起应急咨询，系统检测到无档案 → 弹出冷启动引导 → 用户填写 3 项必填 → 创建成功 → 进入咨询
- **Given**:
  - 已登录用户（`sessionState = 'authenticated'`）
  - `profileApi.listProfiles()` 返回 `[]`（空数组）
  - PROF-01 `POST /api/v1/profiles` Mock 返回 `ProfileResponse`
    ```json
    {
      "profile_id": "550e8400-e29b-41d4-a716-446655440000",
      "birth_date": "2019-03-15",
      "age_range": "7-12岁",
      "diagnosis_type": "ASD",
      "primary_behavior": "刻板行为",
      "is_default": true,
      "created_at": "2026-05-27T21:00:00Z"
    }
    ```
- **When**: CSLT-08 调用 `profileCoordination.checkProfileExists()`，返回 `false` → 用户填写 `ColdStartFormData = { birth_date: '2019-03-15', diagnosis_type: 'ASD', primary_behavior: '刻板行为' }` → 调用 `useProfile().createProfile(data)`
- **Then**:
  - `profileStore.list.length === 1`，其中 `is_default === true`
  - `profileStore.listState === 'ready'`
  - `profileCoordination.checkProfileExists()` 返回 `true`（下次调用）
  - `invalidateCache` 被调用一次（fire-and-forget）

#### 1.10.2 正向测试 2：应急咨询后微问卷弹出 → 用户回答 → 标签沉淀

- **场景**：应急咨询 SSE 流式完成后，CSLT-08 触发微问卷 → 用户回答触发因素和有效性 → 提交成功 → 档案标签更新
- **Given**:
  - 当前档案 `profile_id = '550e8400-...'`，现有 `triggers = ['噪音']`
  - `microSurveyStore.state = 'hidden'`，去重 Set 为空
  - `profileApi.updateProfile()` Mock 成功返回 `ProfileResponse`
- **When**: CSLT-08 调用 `profileCoordination.triggerMicroSurvey('consult-001')` → 微问卷弹出 → 用户选择 `triggerFactor = '环境变化'`，`interventionFeedback = '有帮助'` → 调用 `useMicroSurvey().submit({ consultationId: 'consult-001', triggerFactor: '环境变化', interventionFeedback: '有帮助' })`
- **Then**:
  - `profileApi.updateProfile` 被调用一次，`triggers` 参数为 `['噪音', '环境变化']`
  - `microSurveyStore.state` 先变为 `'submitted'`，2 秒后变为 `'hidden'`
  - 去重 Set 包含 `'consult-001'`
  - 再次调用 `triggerMicroSurvey('consult-001')` → no-op

#### 1.10.3 正向测试 3：档案列表 SWR 缓存 → 后台刷新 → UI 更新

- **场景**：用户打开档案管理页面，页面先展示缓存列表 → 后台静默刷新 → 列表更新为新数据
- **Given**:
  - `profileStore.list = [旧数据]`（上次会话缓存）
  - `profileApi.listProfiles()` Mock 返回新数据（含一个新创建的档案）
- **When**: PROF-06 页面 `onMounted` 调用 `useProfile().fetchProfiles()`
- **Then**:
  - 首次渲染时 `profiles` 为旧数据（SWR 立即返回缓存）
  - 请求完成后 `profiles` 更新为新数据（React 响应式渲染）
  - `isLoading` 在请求期间为 `true`，完成后为 `false`

#### 1.10.4 异常测试 1：档案列表获取失败 → 展示错误 + 重试 → 成功

- **场景**：网络异常导致首次获取列表失败 → 页面展示错误提示和重试按钮 → 用户点击重试 → 获取成功
- **Given**:
  - `profileApi.listProfiles()` 首次调用抛 `TypeError: Failed to fetch`
  - 第二次调用（重试）返回 `ProfileListItem[]`
- **When**: 调用 `fetchProfiles()`（失败）→ PROF-06 渲染"加载失败，请检查网络后重试"按钮 → 用户点击按钮触发 `fetchProfiles()`
- **Then**:
  - 首次失败后：`listState === 'error'`，`error.message === '加载失败，请检查网络后重试'`
  - 重试成功后：`listState === 'ready'`，`error === null`，`profiles` 已更新
  - 页面从未展示空白占位

#### 1.10.5 异常测试 2：档案创建 → 422 字段校验失败 → 内联提示

- **场景**：用户提交了晚于当天的出生日期 → 后端返回 422 → 表单展示内联错误提示
- **Given**:
  - `profileApi.createProfile()` Mock 返回 HTTP 422
    ```json
    { "detail": { "birth_date": "出生日期不能晚于今天" } }
    ```
- **When**: 用户提交 `ColdStartFormData = { birth_date: '2027-01-01', diagnosis_type: 'ASD', primary_behavior: '刻板行为' }`
- **Then**:
  - `submitState === 'idle'`（非 error，非 submitting）
  - 表单保留用户已填写的 `diagnosis_type` 和 `primary_behavior`
  - PROF-06 在 `birth_date` 字段旁渲染红色内联提示"出生日期不能晚于今天"

#### 1.10.6 异常测试 3：微问卷标签更新 → 网络失败 → 回退到问题展示

- **场景**：用户回答微问卷后提交 → 网络异常 → 保留用户选择，顶部 toast 提示重试
- **Given**:
  - `microSurveyStore.state = 'answering'`
  - `profileApi.updateProfile()` Mock 抛网络错误
- **When**: `submit({ triggerFactor: '噪音' })` 调用
- **Then**:
  - `microSurveyStore.state === 'showing'`（回退，保留用户选择）
  - 顶部 toast 展示"保存失败，请重试"
  - 用户可再次点击提交

---

### 1.11 注意事项与禁止行为（编码层面）

1. **[硬性约束 1]** 所有 HTTP 请求必须通过 `import { httpClient } from '@/logics/shared/services/httpClient'` 发送。禁止在 `profileApi.ts` 中任何位置调用 `Taro.request()` 或 `fetch()`。违反此条将导致 Token 无法自动注入、401 无法自动续期、日志 trace_id 缺失。

2. **[硬性约束 2]** views/logics 分层不可破：`logics/profiles/` 下任何文件禁止 `import` 来自 `views/profiles/` 的任何导出（Pages、Components、Layouts）。禁止在 Hook 中调用 `Taro.navigateTo()`。

3. **[易错点 1]** 冷启动检测结果不缓存。`checkProfileExists()` 若 `profileStore.list` 为空，必须发起 HTTP 请求实时查询。禁止在检测过一次后缓存 `false` 结果——用户在另一设备创建档案后必须能立刻检测到。

4. **[易错点 2]** 微问卷去重 Set 是模块作用域变量（模块加载时初始化），不是 `useState` 也不是 localStorage。页面刷新后 Set 自然清空——这是可接受的行为。

5. **[易错点 3]** `createProfile` 成功后必须同时执行：追加到 `profileStore.list` + 触发 `onProfileChanged` 回调 + fire-and-forget `invalidateCache`。三项操作缺一不可。

6. **[已知缺口 1]** `invalidateCache` 调用在 PROF-02 未就绪时会 404。实现时必须 `try { await ... } catch { console.warn(...) }`，不能让异常传播到用户界面。

7. **[已知缺口 2]** CSLT-08 的 `ProfileCoordination` 导入路径为 `@/logics/profiles`，模块入口文件 `logics/profiles/index.ts` 需导出 `profileCoordination` 对象。CSLT-08 完成后可能调整接口签名——当前约定足以独立开发。

8. **[禁止行为]** 禁止在 `useProfile()` 的 `useEffect` 中自动调用 `fetchProfiles()`。数据获取必须由 PROF-06 views 层在 `useDidShow` 或用户操作回调中显式触发。理由：精确控制数据获取时机（避免重复请求、避免冷启动检测冲突）。

9. **[禁止行为]** 禁止对 `ProfileResponse.age_range` 做前端计算。年龄区间由 PROF-01 服务端根据 `birth_date` 实时计算（`0-3岁 / 4-6岁 / 7-12岁 / 13-18岁 / 18岁以上`），前端仅展示不计算。

10. **[禁止行为]** 禁止在 `profileStore` 中存储 `caregiver_id`、`created_at`、`updated_at` 等字段。这些是后端管理字段，前端不需要且不应缓存。

### 1.12 文档详细度自检清单

- [ ] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成编码
- [ ] 无偷懒表述：全文无障碍词（"等等"、"..."、"其他字段"、"类似"、"同上"、"参考其他模块"、"请根据实际情况补充"、"开发者自行决定"）
- [ ] 类型定义完整：每个外放接口都有完整 TypeScript 签名
- [ ] 逻辑步骤完整：5 条流程每条都有操作对象、具体操作、输入来源、输出去向、失败行为
- [ ] 异常处理完整：6 种异常/边界条件，每种都有精确触发阈值、处理策略、重试参数
- [ ] 无隐藏假设：所有默认值来源、条件分支、业务规则已显式写出
- [ ] 技术栈绑定明确：必须使用（7 项）和禁止使用（5 项）均已列出
- [ ] 意图一致性：已确认技术实现与已冻结的意图文档一致（见 1.15）

---

### 1.14 外部接口契约清单

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| ProfileListItem | `docs/contracts/PROF-01/ProfileListItem.json` | output | draft | PROF-01 | PROF-07 |
| ProfileResponse | `docs/contracts/PROF-01/ProfileResponse.json` | output | draft | PROF-01 | PROF-02, PROF-03, PROF-07 |
| ProfileCreate | `docs/contracts/PROF-01/ProfileCreate.json` | input | draft | PROF-01 | PROF-07 |
| ProfileUpdate | `docs/contracts/PROF-01/ProfileUpdate.json` | input | draft | PROF-01 | PROF-07 |
| DiagnosisType | `docs/contracts/PROF-01/DiagnosisType.json` | shared-enum | draft | PROF-01 | PROF-02, PROF-07 |
| LanguageLevel | `docs/contracts/PROF-01/LanguageLevel.json` | shared-enum | draft | PROF-01 | PROF-02, PROF-07 |
| SensoryFeature | `docs/contracts/PROF-01/SensoryFeature.json` | shared-enum | draft | PROF-01 | PROF-02, PROF-07 |
| Trigger | `docs/contracts/PROF-01/Trigger.json` | shared-enum | draft | PROF-01 | PROF-02, PROF-07 |
| AgeRange | `docs/contracts/PROF-01/AgeRange.json` | shared-enum | draft | PROF-01 | PROF-02, PROF-07 |
| ProfileBehaviorType | `docs/contracts/PROF-01/ProfileBehaviorType.json` | shared-enum | draft | PROF-01 | PROF-02, PROF-07 |
| ProfileLimitExceededError | `docs/contracts/PROF-01/ProfileLimitExceededError.json` | error-code | draft | PROF-01 | PROF-07 |
| ProfileConflictError | `docs/contracts/PROF-01/ProfileConflictError.json` | error-code | draft | PROF-01 | PROF-07 |
| httpClient | `docs/contracts/AUTH-06/httpClient.json` | output | draft | AUTH-06 | CSLT-08, PROF-07, CASE-09, TICK-09, KNOW-07 |
| SessionState | `docs/contracts/AUTH-06/SessionState.json` | shared-enum | draft | AUTH-06 | PROF-07 等 11 方 |
| TokenPair | `docs/contracts/AUTH-06/TokenPair.json` | shared-model | draft | AUTH-06 | PROF-07 等 6 方 |
| useAuthReturn | `docs/contracts/AUTH-06/useAuthReturn.json` | output | draft | AUTH-06 | PROF-07 等 11 方 |
| EventCreate | `docs/contracts/PROF-03/EventCreate.json` | input | draft | PROF-03 | PROF-07 |

**本模块内部类型**（不写入 JSON Schema 契约，仅 TypeScript 定义）：
- `UseProfileReturn` — 供 PROF-06 消费的 Hook 返回接口
- `ProfileCoordination` — 供 CSLT-08 消费的横向协作接口
- `MicroSurveyState` — 微问卷交互态枚举
- `ProfileListState` — 档案列表加载状态联合类型
- `ProfileSubmitState` — 档案提交状态联合类型
- `InterventionFeedback` — 干预有效性三档评价
- `InvalidatCacheRequest` — PROF-02 缓存失效通知请求体（依赖缺口）

### 1.15 意图一致性声明

- **配套意图文档**：`PROF-07-档案数据逻辑-意图文档.md`
- **冻结时间**：2026-05-27 21:26:24（v2.0）
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致。冷启动引导 3 项必填字段（出生日期、诊断类型、主要行为类型）与 1.6.1 完全一致。档案编辑 5 项可选字段（昵称、语言水平、感官特征、触发因素、用药备注）与 1.6.2 完全一致。微问卷 2 种问题类型（触发因素确认、干预有效性反馈）与 1.6.3 完全一致。
  - [x] 本落地规范中的状态机实现与意图文档中的状态业务定义一致。加载中/就绪/提交中/错误 4 个前端交互态对应意图文档 §1.7。
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致。3 类业务异常（数据获取失败、提交失败、冷启动中断）的处理方式与意图文档 §1.8 完全对应。
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准。AC-01 覆盖（正向 1 冷启动引导），AC-02/03 覆盖（正向 2 微问卷弹出 + 数据沉淀），AC-05 覆盖（正向 3 档案列表），AC-06 覆盖（异常 1 列表获取失败、异常 2 字段校验失败、异常 3 微问卷失败）。
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围。8 项技术决策全部依据技术预研报告和契约协调报告确定，无自行扩展或遗漏。
- **偏差说明**：
  1. 微问卷题目选择策略（意图文档 §1.12(3)）— 本规范固定 2 题全覆盖，优先选择最简单实现。若未来产品需求要求题目轮换或自适应，需在 `useMicroSurvey` 中增加题目选择逻辑。
  2. 变更通知接口路径（意图文档 §1.12(4)）— 本规范假设 `POST /api/v1/profiles/{profileId}/invalidate-cache`。PROF-02 完成后如接口路径或方法变更，仅需修改 `profileApi.ts` 中的 `invalidateCache` 函数。
  3. 冷启动跳过频率（意图文档 §1.11(1)）— 本规范严格遵循"每次进入咨询都检测"的无上限策略。若用户体验测试反馈弹出过于频繁，可在 `checkProfileExists` 中增加频次限制——当前版本不实现。
  4. 微问卷事件记录沉淀边界（意图文档 §1.11(7)）— 本规范仅在用户显式回答且为自定义文本时调用 PROF-03 EventCreate。若产品要求全部触发因素都写入事件记录，移除 `isCustom` 判断条件即可。
