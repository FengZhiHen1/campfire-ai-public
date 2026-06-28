> ⚠️ AI 重建文档
>
> 本文档由 AI（`code-reverse-engineering-writer`）从现有代码逆向推导生成，生成时间 2026-05-27 15:30 CST。
> 文档内容基于代码可观察结构与 AI 推断，每个推断项均标注置信度（[确定] / [推断] / [推测]）。
> **请仔细审核并修正后再作为编码输入使用。**

---

## 1 功能点：CASE-09 案例管理逻辑 — 落地规范

> **文档生成时间**：`2026-05-27 15:30 CST`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-27 15:30 CST | AI Assistant（`code-reverse-engineering-writer`） | 从源代码逆向推导初始版本 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的业务意图定义见 `CASE-09-案例管理逻辑-意图文档.md`。

### 1.1 技术栈绑定

- **必须使用**：
  - TypeScript 4.x+（前端全量类型化）
  - Taro 4.x（微信小程序框架，React 语法）
  - Zustand 5.x（前端状态管理）
  - `@campfire/ts-shared`（workspace 协议引用的共享类型包——提供 CaseCreateRequest、CaseResponse、CaseListItem 等类型）
  - `httpClient`（AUTH-06 提供的 HTTP 客户端——封装了 Token 注入和自动续期）
  - `Taro.setStorageSync` / `Taro.getStorageSync`（草稿本地持久化）
- **禁止使用**：
  - 直接调用 `wx.request` 或 `Taro.request` 裸调——必须通过 `httpClient` 统一路由
  - 在 `logics/` 层直接 import `views/` 层的组件或页面
  - 前端直连数据库或外部服务

### 1.2 文件归属

> 以下路径基于现有代码的实际位置（与项目结构设计文档存在差异——见下方 [推断] 注释）。

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| API Service | `apps/mini-program/src/logics/cases/services/caseApiService.ts` | 封装 6 个案例 CRUD API 调用 |
| 表单 Store | `apps/mini-program/src/logics/cases/store/caseFormStore.ts` | Zustand 表单状态管理，含自动保存草稿 |
| [推断] [待确认] Hooks 桥接 | `apps/mini-program/src/logics/cases/hooks/useCases.ts` | 预期存在但当前未实现，作为 views 层访问 logics 层的唯一桥梁 |
| [推断] [待确认] 类型定义 | `apps/mini-program/src/logics/cases/types/index.ts` | 预期存在但当前未实现，存放内部类型定义 |

> ⚠️ **路径差异说明**：
> - 现有代码的文件名与项目结构设计文档中预期的文件名不一致（`caseApiService.ts` → 预期 `caseApi.ts`；`caseFormStore.ts` → 预期 `caseStore.ts`）
> - 项目结构设计文档预期 `hooks/` 和 `types/` 目录应存在，但当前实际代码中缺失

### 1.3 输入定义（精确类型 / 或契约引用）

#### 对外接口类型（契约引用）

**CaseCreateRequest**
- 【契约引用】`docs/contracts/CASE-01/CaseCreateRequest.json`（预期——当前不存在）
- 本模块作为该契约的消费者
- 定义方：CASE-01 案例录入管理

**CaseUpdate**
- 【契约引用】`docs/contracts/CASE-01/CaseUpdate.json`（预期——当前不存在）
- 本模块作为该契约的消费者
- 定义方：CASE-01 案例录入管理

**CaseResponse**
- 【契约引用】`docs/contracts/CASE-01/CaseResponse.json`（预期——当前不存在）
- 本模块作为该契约的消费者
- 定义方：CASE-01 案例录入管理

**CaseListItem**
- 【契约引用】`docs/contracts/CASE-01/CaseListItem.json`（预期——当前不存在）
- 本模块作为该契约的消费者
- 定义方：CASE-01 案例录入管理

**PaginatedResponse\<CaseListItem\>**
- 【契约引用】`docs/contracts/CASE-01/PaginatedResponse.json`（预期——当前不存在）
- 本模块作为该契约的消费者
- 定义方：CASE-01 案例录入管理

**PiiDetectionResult**
- 【契约引用】`docs/contracts/CASE-01/PiiDetectionResult.json`（预期——当前不存在）
- 本模块作为该契约的消费者
- 定义方：CASE-01 案例录入管理

#### 内部类型（来自实际代码）

```typescript
/** 案例表单所有字段 */
interface CaseFormFields {
  // L1 字段
  title: string;                    // [确定] 案例标题
  narrative: string;                // [确定] 案例叙事文本
  source_type: string;              // [确定] 来源类型
  // L2 字段
  behavior_type: string;            // [确定] 行为类型
  age_range_min: number;            // [确定] 适用年龄段下限
  age_range_max: number;            // [确定] 适用年龄段上限
  severity: string;                 // [确定] 严重程度
  scene: string;                    // [确定] 场景
  ebp_labels: string[];             // [确定] 循证标签列表
  family_category: string;          // [确定] 家庭类别
  immediate_action: string;         // [确定] 即时干预动作
  comforting_phrase: string;        // [确定] 情绪安抚话术
  observation_metrics: string;      // [确定] 观察指标
  medical_criteria: string;         // [确定] 医疗判断标准
  evidence_level: string;           // [确定] 循证等级
  contraindications: string;        // [确定] 禁忌事项
  is_template: boolean;             // [确定] 是否为模板
  // 选填字段
  excluded_population: string;      // [确定] 排除人群
}

/** 表单校验错误（字段名 → 错误描述） */
interface FormErrors {
  [field: string]: string;
}

/** 表单 Store 状态与方法 */
interface CaseFormState {
  fields: CaseFormFields;          // [确定] 当前表单字段值
  errors: FormErrors;              // [确定] 字段校验错误映射
  isSubmitting: boolean;           // [确定] 是否正在提交
  lastSavedAt: string | null;      // [确定] 上次自动保存时间
  isDirty: boolean;                // [确定] 是否有未保存的更改

  setField(name: keyof CaseFormFields, value: string | number | boolean | string[]): void;
  setFields(partial: Partial<CaseFormFields>): void;
  resetForm(): void;
  loadDraft(): boolean;
  saveDraft(): void;
  setErrors(errors: FormErrors): void;
  clearErrors(): void;
  setSubmitting(value: boolean): void;
}
```

### 1.4 输出定义（精确类型 / 或契约引用）

本模块的对外接口输出类型均引用自 `@campfire/ts-shared`：

**CaseResponse**
- 【契约引用】`docs/contracts/CASE-01/CaseResponse.json`（预期——当前不存在）
- 本模块作为该契约的消费者
- 定义方：CASE-01 案例录入管理

**PaginatedResponse\<CaseListItem\>**
- 【契约引用】`docs/contracts/CASE-01/PaginatedResponse.json`（预期——当前不存在）
- 本模块作为该契约的消费者
- 定义方：CASE-01 案例录入管理

**PiiDetectionResult**
- 【契约引用】`docs/contracts/CASE-01/PiiDetectionResult.json`（预期——当前不存在）
- 本模块作为该契约的消费者
- 定义方：CASE-01 案例录入管理

### 1.5 核心逻辑步骤

#### 步骤组 A：表单管理（caseFormStore.ts）

1. **步骤 1：字段更新**
   - **操作对象**：`CaseFormState.fields`
   - **具体操作**：通过 `setField(name, value)` 更新单个字段，或 `setFields(partial)` 批量更新
   - **输入来源**：用户在前端表单组件中的输入事件
   - **输出去向**：更新后的 `fields` 状态对象
   - **失败行为**：无（纯状态更新，不涉及外部调用）
   - **副作用**：设置 `isDirty = true`，触发 `scheduleAutoSave()`

2. **步骤 2：自动保存调度**
   - **操作对象**：模块级 `autoSaveTimer` 变量
   - **具体操作**：每次字段变更时清除现有计时器，新建 30 秒 `setTimeout`。30 秒内无新变更则执行保存
   - **输入来源**：`AUTO_SAVE_DEBOUNCE_MS = 30000` 常量
   - **输出去向**：计时器到期后调用 `state.saveDraft()`
   - **失败行为**：无（计时器清除或创建失败不影响主流程）

3. **步骤 3：草稿保存**
   - **操作对象**：`Taro` 本地存储（key: `'case_form_draft'`）
   - **具体操作**：`Taro.setStorageSync(DRAFT_STORAGE_KEY, JSON.stringify(fields))`
   - **输入来源**：`CaseFormState.fields`
   - **输出去向**：更新 `lastSavedAt` 和 `isDirty` 状态
   - **失败行为**：try/catch 静默忽略——存储空间不足或序列化失败不阻断操作
   - **副作用**：更新 `lastSavedAt = new Date().toISOString()`，`isDirty = false`

4. **步骤 4：草稿加载**
   - **操作对象**：`Taro` 本地存储（key: `'case_form_draft'`）
   - **具体操作**：`Taro.getStorageSync(DRAFT_STORAGE_KEY)` → `JSON.parse(saved)` → 合并到 `fields`
   - **输入来源**：本地存储中的 JSON 字符串
   - **输出去向**：更新后的 `fields`、`lastSavedAt`、`isDirty`
   - **失败行为**：try/catch 静默忽略——JSON 解析失败或存储读取失败时返回 false

5. **步骤 5：表单重置**
   - **操作对象**：全部表单状态
   - **具体操作**：清除自动保存计时器，重置 `fields` 为 `DEFAULT_FIELDS`，清空 `errors`，重置提交状态，删除本地存储的草稿
   - **输入来源**：用户触发重置操作
   - **输出去向**：表单恢复初始状态
   - **失败行为**：无

#### 步骤组 B：API 调用（caseApiService.ts）

6. **步骤 6：创建案例**
   - **操作对象**：后端 API `POST /api/v1/cases`
   - **具体操作**：`httpClient.request<CaseResponse>({ url: BASE_PATH, method: 'POST', data: request })`
   - **输入来源**：`CaseCreateRequest` 对象（来自表单字段组装）
   - **输出去向**：返回 `CaseResponse`（status=draft 的案例详情）
   - **失败行为**：异常通过 httpClient 传播，由调用方（Hooks/views 层）处理

7. **步骤 7：更新案例**
   - **操作对象**：后端 API `PUT /api/v1/cases/{caseId}`
   - **具体操作**：`httpClient.request<CaseResponse>({ url: BASE_PATH/${caseId}, method: 'PUT', data: update })`
   - **输入来源**：`caseId` + `CaseUpdate`（含 `updated_at` 乐观锁字段）
   - **输出去向**：返回更新后的 `CaseResponse`
   - **失败行为**：乐观锁冲突时后端返回 409，异常由 httpClient 传播

8. **步骤 8：提交审核**
   - **操作对象**：后端 API `POST /api/v1/cases/{caseId}/submit`
   - **具体操作**：`httpClient.request<CaseResponse>({ url: BASE_PATH/${caseId}/submit, method: 'POST', data: { pii_confirmed: piiConfirmed } })`
   - **输入来源**：`caseId` + `piiConfirmed`（用户确认 PII 已处理）
   - **输出去向**：返回提交后的 `CaseResponse`（status=pending_review）
   - **失败行为**：PII 未确认或后端校验不通过时返回错误

9. **步骤 9：查询列表**
   - **操作对象**：后端 API `GET /api/v1/cases`
   - **具体操作**：`httpClient.request<PaginatedResponse<CaseListItem>>({ url: BASE_PATH, method: 'GET', data: { status, page, page_size } })`
   - **输入来源**：`status`（可选筛选）、`page`（页码，默认 1）、`pageSize`（每页条数，默认 15）
   - **输出去向**：返回分页的案例列表
   - **失败行为**：异常通过 httpClient 传播

10. **步骤 10：查询详情**
    - **操作对象**：后端 API `GET /api/v1/cases/{caseId}`
    - **具体操作**：`httpClient.request<CaseResponse>({ url: BASE_PATH/${caseId}, method: 'GET' })`
    - **输入来源**：`caseId`
    - **输出去向**：返回案例完整详情
    - **失败行为**：案例不存在时后端返回 404

11. **步骤 11：PII 检测**
    - **操作对象**：后端 API `POST /api/v1/cases/pii-check`
    - **具体操作**：`httpClient.request<PiiDetectionResult>({ url: BASE_PATH/pii-check, method: 'POST', data: { narrative } })`
    - **输入来源**：`narrative`（待检测的叙事文本）
    - **输出去向**：返回 `PiiDetectionResult`（含 has_pii 和 warnings）
    - **失败行为**：异常通过 httpClient 传播

### 1.6 接口契约（对外暴露的公共接口）

> 本模块的公共接口分为两部分：`caseApiService.ts` 中的 API 调用函数（供 Hooks 层或 views 层调用），以及 `caseFormStore.ts` 中的 Zustand store。

#### 1.6.1 接口 1：CaseApiService（API 调用封装）

```typescript
/**
 * 案例 CRUD 操作的 API 封装层。
 * 所有函数通过 httpClient 发送请求，返回类型与 @campfire/ts-shared 定义对齐。
 */

async function createCase(request: CaseCreateRequest): Promise<CaseResponse>
async function updateCase(caseId: string, update: CaseUpdate): Promise<CaseResponse>
async function submitCase(caseId: string, piiConfirmed?: boolean): Promise<CaseResponse>
async function getCase(caseId: string): Promise<CaseResponse>
async function listCases(status?: string, page?: number, pageSize?: number): Promise<PaginatedResponse<CaseListItem>>
async function detectPii(narrative: string): Promise<PiiDetectionResult>
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `caseApiService` —— 案例 API 服务 |
| **所属文件** | `apps/mini-program/src/logics/cases/services/caseApiService.ts` |
| **暴露函数** | 6 个 async 导出函数（createCase, updateCase, submitCase, getCase, listCases, detectPii） |
| **输入类型** | 各函数参数（见上方签名） |
| **输出类型** | `CaseResponse` / `PaginatedResponse<CaseListItem>` / `PiiDetectionResult` |
| **异常类型** | 由 `httpClient` 决定——401（Token 过期自动续期）、403（权限不足）、404（资源不存在）、409（乐观锁冲突）、422（输入校验失败）、5xx（服务端错误） |
| **副作用** | 无（纯 HTTP 请求封装，不涉及前端状态变更） |
| **幂等性** | GET 操作天然幂等；POST/PUT 由后端保证 |
| **并发安全** | 线程安全，无内部可变状态 |

#### 1.6.2 接口 2：useCaseFormStore（表单状态管理）

```typescript
/**
 * 案例表单 Zustand Store。
 * 管理所有表单字段、校验错误和自动保存状态。
 */
interface CaseFormStore {
  // 状态
  fields: CaseFormFields;
  errors: FormErrors;
  isSubmitting: boolean;
  lastSavedAt: string | null;
  isDirty: boolean;

  // 方法
  setField(name: keyof CaseFormFields, value: string | number | boolean | string[]): void;
  setFields(partial: Partial<CaseFormFields>): void;
  resetForm(): void;
  loadDraft(): boolean;
  saveDraft(): void;
  setErrors(errors: FormErrors): void;
  clearErrors(): void;
  setSubmitting(value: boolean): void;
}
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `useCaseFormStore` —— 案例表单状态管理 |
| **所属文件** | `apps/mini-program/src/logics/cases/store/caseFormStore.ts` |
| **实现框架** | Zustand 5.x `create<CaseFormState>` |
| **状态字段** | fields（19 个字段）、errors、isSubmitting、lastSavedAt、isDirty |
| **副作用** | setField/setFields 触发 30 秒防抖自动保存；resetForm 清除本地存储草稿；loadDraft 读取本地存储；saveDraft 写入本地存储 |
| **幂等性** | setField/setFields 重复调用结果一致；saveDraft 重复调用每次都写入 |
| **并发安全** | Zustand 单线程模型保证原子性 |

### 1.7 依赖与集成接口

#### 1.7.1 关键基础设施依赖

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| HTTP 客户端 | httpClient（AUTH-06） | `httpClient.request<T>(config)` | 统一 API 请求，Token 注入与自动续期 | `项目结构.md` §6.1（logics/shared/services/httpClient.ts） |
| 本地存储 | Taro | `Taro.setStorageSync(key, value)` / `Taro.getStorageSync(key)` / `Taro.removeStorageSync(key)` | 表单草稿持久化 | `项目结构.md` — Taro 框架内置能力 |
| 共享类型包 | @campfire/ts-shared | 类型导入（`CaseCreateRequest`、`CaseResponse` 等） | 前端数据类型契约 | `项目结构.md` §6.1（packages/ts-shared/src/） |

#### 1.7.2 核心功能依赖

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| CASE-01 案例录入管理 | 后端 API `POST/GET/PUT /api/v1/cases/*` | 案例 CRUD 操作 | ⏭️ 待落地 |
| AUTH-06 认证会话管理 | `httpClient` | HTTP 请求认证拦截 | ⏭️ 待落地 |
| @campfire/ts-shared | TypeScript 类型定义 | 数据类型契约 | ⏭️ 待落地 |

### 1.8 状态机（如适用）

#### 表单状态机（前端）

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 副作用 |
|----------|----------|----------|----------|--------|
| IDLE | `setField` / `setFields` | DIRTY | — | 字段值变更，启动 30 秒防抖计时器 |
| DIRTY | `setField` / `setFields`（继续编辑） | DIRTY | — | 重置 30 秒防抖计时器 |
| DIRTY | 30 秒无操作（`scheduleAutoSave` 到期） | SAVED | `isDirty === true` | 调用 `saveDraft()` 写入本地存储 |
| DIRTY | `resetForm` | IDLE | — | 清除计时器、清空字段、删除本地草稿 |
| SAVED | `setField` / `setFields`（继续编辑） | DIRTY | — | 字段值变更，再次启动防抖计时器 |
| SAVED | — | IDLE | — | 保存后自动进入 IDLE（lastSavedAt 更新，isDirty=false） |
| IDLE / DIRTY | `setSubmitting(true)` | SUBMITTING | 校验通过 | 禁用表单交互 |
| SUBMITTING | 后端返回成功 | IDLE | 请求成功 | 清空字段或跳转 |
| SUBMITTING | 后端返回错误 | DIRTY | 请求失败 | 恢复表单交互，展示错误提示 |

#### 案例业务状态机（后端维护，本模块参与）

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 本模块职责 |
|----------|----------|----------|----------|-----------|
| draft | `submitCase(piiConfirmed=true)` | pending_review | PII 已确认 | 发起提交请求（步骤 8） |
| pending_review | (审核通过) | approved | CASE-03 审核流程 | 列表刷新（[推断] 由 CASE-03 通知） |
| pending_review | (审核驳回) | rejected | CASE-03 审核流程 | 列表刷新（[推断] 由 CASE-03 通知） |
| rejected | (用户编辑后重新提交) | pending_review | 用户修改后再次 submit | 发起编辑 + 提交 |

### 1.9 异常与边界条件

#### 1.9.1 异常 1：API 请求错误（网络/服务端）

- **触发条件**：
  - 后端返回 4xx/5xx 状态码
  - 网络断开或超时（Taro.request 超时）
  - Token 过期且自动续期失败（由 httpClient 处理）
- **处理策略**：
  1. httpClient 拦截器自动处理 Token 续期（401 响应时触发，最多 3 次）
  2. 续期失败后 httpClient 清除本地会话并跳转登录页
  3. 其他错误通过 Promise rejection 传递给调用方
  4. 调用方（当前缺失的 Hooks 层）应将错误展示给用户
- **重试参数**：本层不实现重试——由 Hooks/调用方或 AUTH-06 决定

#### 1.9.2 异常 2：乐观锁冲突

- **触发条件**：
  - 多人同时编辑同一案例，后提交者的 `updated_at` 与服务端当前值不匹配
- **处理策略**：
  1. 后端返回 HTTP 409 Conflict
  2. httpClient 正常传播 409 响应
  3. 调用方应提示用户"案例已被他人修改，请刷新后重试"
- **重试参数**：不重试，用户手动刷新后重新编辑

#### 1.9.3 异常 3：草稿存储/读取失败

- **触发条件**：
  - 本地存储空间不足（`Taro.setStorageSync` 抛出异常）
  - 存储的 JSON 格式异常（`JSON.parse` 抛出异常）
- **处理策略**：
  1. try/catch 静默捕获异常
  2. 不展示错误通知给用户（现有实现行为）
  3. 草稿保存失败：`lastSavedAt` 不更新，`isDirty` 保持 true
  4. 草稿加载失败：返回 false，表单使用默认空值
- **重试参数**：不重试，用户下次触发字段更新时重新启动自动保存

#### 1.9.4 异常 4：表单验证失败限制提

- **触发条件**：
  - 必填字段为空
  - 字段值不符合枚举约束
  - [推测] 四段式字段非空检查
- **处理策略**：
  1. 校验失败字段更新到 `errors` 映射中
  2. `setErrors` 更新 Store，触发 UI 展示错误标记
  3. 禁止提交（`isSubmitting` 保持 false）
  4. 用户修正后 `clearErrors` 清除指定字段的错误
- **重试参数**：不适用——用户修正后自然解除

### 1.10 验收测试场景

#### 1.10.1 正向测试 1：完整输入成功创建案例

- **场景**：用户填写全部必填字段后提交
- **Given**: 用户完整填写 CaseFormFields，所有校验通过
- **When**: 调用 `createCase(request)`
- **Then**:
  - API 返回 `CaseResponse`，`status="draft"`
  - Store 中 `isSubmitting` 从 true 变为 false
  - 表单不阻塞

#### 1.10.2 正向测试 2：自动保存草稿

- **场景**：用户编辑后等待 30 秒，草稿自动保存
- **Given**: 用户通过 `setField` 修改了标题字段
- **When**: 30 秒内无新操作
- **Then**:
  - `saveDraft` 被调用
  - `lastSavedAt` 更新为当前时间
  - `isDirty` 变为 false
  - 本地存储 key `case_form_draft` 包含当前字段的 JSON

#### 1.10.3 正向测试 3：草稿恢复

- **场景**：存在已保存的草稿，应用初始化时自动恢复
- **Given**: 本地存储中 `case_form_draft` 包含有效 JSON
- **When**: 调用 `loadDraft()`
- **Then**:
  - 返回 `true`
  - `fields` 已包含存储中的字段值（与默认值合并）
  - `lastSavedAt` 已更新

#### 1.10.4 正向测试 4：案例提交审核

- **场景**：draft 状态案例提交审核
- **Given**: `caseId` 对应一个 draft 状态的案例
- **When**: 调用 `submitCase(caseId, true)`
- **Then**:
  - API 返回 `CaseResponse`，`status="pending_review"`
  - 不在本层抛出异常

#### 1.10.5 正向测试 5：分页列表查询

- **场景**：查询案例列表，支持状态筛选和分页
- **Given**: 后端存在多个案例
- **When**: 调用 `listCases(undefined, 2, 15)`
- **Then**:
  - 返回 `PaginatedResponse<CaseListItem>`
  - `page` = 2, `page_size` = 15
  - `items` 不超过 15 条

#### 1.10.6 异常测试 1：草稿 JSON 解析失败

- **场景**：本地存储中的草稿数据损坏
- **Given**: `case_form_draft` 存储值为无效 JSON（如 `"not json"`）
- **When**: 调用 `loadDraft()`
- **Then**:
  - 返回 `false`
  - 表单字段保持默认值
  - 不抛出异常

#### 1.10.7 异常测试 2：存储空间不足

- **场景**：本地存储空间已满
- **Given**: `Taro.setStorageSync` 抛出异常
- **When**: 触发自动保存（30 秒防抖到期）
- **Then**:
  - `saveDraft` 静默捕获异常
  - `lastSavedAt` 不更新
  - 主流程不受影响

### 1.11 注意事项与禁止行为（编码层面）

1. **[约束]** 所有 API 请求必须通过 `httpClient` 发送，禁止直接使用 `Taro.request` 裸调
2. **[约束]** Hooks 层（`useCases.ts`）是 views 层访问 logics 层的唯一合法通道，禁止 views 层直接 import `caseApiService` 或 `useCaseFormStore`
3. **[易错点]** 自动保存防抖计时器在 `resetForm` 中必须清除，否则已卸载组件中的计时器可能触发状态更新导致内存泄漏
4. **[易错点]** `loadDraft` 合并字段时必须使用 `{ ...DEFAULT_FIELDS, ...parsed }` 顺序——parsed 覆盖 defaults；若顺序颠倒会导致缺失字段未被默认值填充
5. **[禁止行为]** 禁止在 `caseFormStore.ts` 中直接调用 API（将 API 调用与状态管理耦合）。API 调用应保持在 `caseApiService.ts` 层，由 Hooks 层编排
6. **[禁止行为]** 禁止从 `logics/cases/` 层 import `views/cases/` 层的任何代码

### 1.12 外部接口契约清单

> 以下契约均为 CASE-01 定义、本模块消费。当前均未创建，标注为预期路径。

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| CaseCreateRequest | `docs/contracts/CASE-01/CaseCreateRequest.json` | input | draft | CASE-01 | CASE-09 |
| CaseUpdate | `docs/contracts/CASE-01/CaseUpdate.json` | input | draft | CASE-01 | CASE-09 |
| CaseResponse | `docs/contracts/CASE-01/CaseResponse.json` | output | draft | CASE-01 | CASE-09 |
| CaseListItem | `docs/contracts/CASE-01/CaseListItem.json` | output | draft | CASE-01 | CASE-09 |
| PaginatedResponse | `docs/contracts/CASE-01/PaginatedResponse.json` | shared | draft | CASE-01 | CASE-09, ... |
| PiiDetectionResult | `docs/contracts/CASE-01/PiiDetectionResult.json` | output | draft | CASE-01 | CASE-09 |

### 1.13 意图一致性声明

- **配套意图文档**：`CASE-09-案例管理逻辑-意图文档.md`
- **冻结时间**：未冻结（本文档为 AI 逆向推导草案）
- **一致性确认**：
  - [ ] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致
  - [ ] 本落地规范中的状态机实现与意图文档中的状态业务定义一致
  - [ ] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致
  - [ ] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准
  - [ ] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围
- **偏差说明**：落地规范中的输入/输出类型引用自 `@campfire/ts-shared` 包，其字段明细未直接体现在源代码中，实际定义以该包的接口为准。意图文档中的业务字段定义基于表单 Store 的 CaseFormFields 接口推断，可能存在遗漏或偏差。
