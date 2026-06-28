# 1 功能点：CASE-09 案例管理逻辑 — 设计文档（瘦身版）

> **文档生成时间**：`2026-05-27 17:57:38`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-27 17:57:38 | AI Assistant | 初始版本（基于意图文档 v2.0，7 项技术决策自主裁决） |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `CASE-09-案例管理逻辑-意图文档.md`（已冻结于 2026-05-27 17:47:49）
> - 本模块的精确编码规格见 `CASE-09-案例管理逻辑-落地规范.md`

### 1.1 技术实现思路

本模块是案例管理群组的前端 L1b 逻辑层，采用三层结构（API Service → Zustand Store → Hooks 桥接层）实现案例 CRUD 的数据操作封装和表单状态管理。核心技术决策围绕三个主轴展开：Hooks 桥接架构、表单草稿保护、文件命名对齐。

**Hooks 桥接层是模块的边界核心**。项目结构设计文档（§6.1）明确规定 views 与 logics 的隔离必须通过 Hooks 层桥接——这是三层隔离架构的硬性约束。当前代码缺少 Hook 文件，本设计补全这一架构漏洞。三个核心 Hook 的设计为：
- `useCaseFormStore()`：直接导出 Zustand Store 的 selector/action 绑定，是表单编辑的入口。这是模式最简单的 Hook——Zustand 本身已提供良好的状态隔离，Hook 层仅做命名空间绑定和 TypeScript 类型导出。
- `useCaseList(params)`：封装分页查询、状态筛选和手动刷新逻辑，内部持有 `listCases` 的调用状态（loading/data/error）。列表刷新采用手动触发而非轮询——这是意图文档中用户确认的刷新策略（手动下拉刷新），避免了不必要的后端轮询开销。
- `useCaseDetail(caseId)`：封装详情查询，每次调用 `getCase` 获取最新数据，不含缓存逻辑——案例详情需要实时性，且乐观锁编辑要求读取最新的 `updated_at`。

选择三个独立 Hook（而非一个巨型 `useCases` Hook）的理由：表单管理、列表查询和详情查询的生命周期和依赖关系不同——表单 Hook 需要持久化草稿状态且不与组件卸载同步销毁，列表 Hook 需要分页参数驱动 refetch，详情 Hook 需要 caseId 驱动。拆分为三避免了不必要的耦合重渲染。

**表单草稿保护采用全流程本地存储策略**。30 秒防抖间隔将表单全部字段 JSON 序列化到 `Taro.Storage`，防抖计时在每次 `setField/setFields` 调用时重置。技术实现上，防抖计时器挂在 Store 的外部闭包中（而非 Zustand state 内部），确保计时器生命周期独立于 React 渲染周期——组件卸载时计时器不丢失，页面返回后计时器在 Store 销毁时被清除（通过 `resetForm` 显式调用）。应用重启后，`loadDraft()` 在 Store 初始化阶段执行，从 Storage 反序列化并合并到默认字段上。

选择 `Taro.Storage` 而非 `Taro.Cloud` 或后端自动保存的理由：意图文档明确要求重启恢复草稿，不需要跨设备同步（专家通常在单设备上完成录入）；本地存储零网络延迟，无需后端写入成本；简单可靠，与 CASE-01 设计文档中的草稿保存策略一致。

**文件命名对齐项目结构设计文档**。当前代码文件名为 `caseApiService.ts`，项目结构设计预期为 `caseApi.ts`；当前 `caseFormStore.ts` 预期为 `caseStore.ts`。本设计采用项目结构的预期命名，理由：项目结构是团队契约的基准，代码实现必须收敛到设计文档而非反过来。实现时需要物理文件重命名，旧文件名保留为 re-export 别名以避免过渡期断裂——命名迁移策略见 §1.7 注意事项。

**API 调用全部通过 AUTH-06 的 httpClient 路由**。6 个 API 函数（createCase / updateCase / submitCase / getCase / listCases / detectPii）不处理 Token 注入和续期——这些由 httpClient 的拦截器统一处理。异常传播链为：httpClient 拦截器捕获 401 → 自动续期（最多 3 次） → 续期失败则清除会话并跳转登录页。其他 HTTP 错误（404/409/422/5xx）通过 rejection 传播到 Hook 层，Hook 层负责向 views 暴露友好的错误状态。

**请求超时和并发控制采用适配器模式**。每个 API 函数内部包装 `httpClient.request`，追加 AbortController 超时逻辑（默认 15 秒）。提交操作（createCase / submitCase）设置 Hook 层的 submitting 状态防止重复提交——这是前端防重入而非后端锁。列表查询的竞态处理：连续快速翻页时，新的请求通过 AbortController 取消上一个未完成的请求，避免旧页面数据覆盖新页面。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：
  - CASE-01 案例录入管理-意图文档.md（已冻结 v2.0）、设计文档.md（已冻结）、落地规范.md（已冻结）
  - CASE-04 案例向量化入库-落地规范.md（已冻结）
  - CSLT-01/02/03 智能应急咨询系列-落地规范.md（已冻结）
  - PROF-01/05 个性化档案系列-落地规范.md（已冻结）
  - AUTH-01～06 用户认证系列-落地规范.md（已冻结）
  - KNOW-01 科普内容管理-落地规范.md（已冻结）
  - OBS-01/04 结构化日志/健康检查-落地规范.md（已冻结）
  - SEC-01/04/05 安全合规系列-落地规范.md（已冻结）
  - DEPLOY-01～05 部署运维系列-落地规范.md（已冻结）

- **兼容性结论**：
  - **无冲突**：CASE-09 为前端 L1b 逻辑层，与全部已有后端规格分域隔离。CASE-09 是 CASE-01 契约（CaseCreateRequest、CaseResponse 等 12 份契约）的纯消费者，不修改或扩展这些契约的字段语义和约束。与 CASE-01 的依赖方向为单向消费，无循环风险。CASE-01 的 Storage 草稿保存策略与 CASE-09 一致，前端自动保存是后端服务的客户端实现，两者的草稿保护策略形成互补而非冲突。
  - **CASE-01 契约就绪状态**：CASE-01 的 12 份契约文件均已存在于 `docs/contracts/CASE-01/`，成熟度为 `draft`。本模块可直接通过契约引用消费，无需等待契约冻结。CASE-01 设计文档 §1.2 明确声明 CASE-09 为其契约消费方——消费关系已双向确认。
  - **AUTH-06 契约就绪状态**：AUTH-06 的 httpClient 契约（`docs/contracts/AUTH-06/httpClient.json`）已存在，SessionState 和 TokenPair 同样就绪。CASE-09 作为 httpClient 的消费者已由 AUTH-06 预登记。
  - **文件名歧义**：当前代码文件名（`caseApiService.ts`、`caseFormStore.ts`）与项目结构设计文档预期（`caseApi.ts`、`caseStore.ts`）存在差异。本设计采用项目结构文档的预期命名，在落地规范阶段提供重命名迁移方案。

- **复用的已有设计**：
  - CASE-01 的 19 个表单字段定义——作为 `CaseFormFields` 的字段来源
  - CASE-01 的枚举类型（BehaviorType、SeverityLevel、SceneType、EvidenceLevel、FamilyDisplayCategory、SourceType）——作为表单枚举选项的技术值
  - AUTH-06 `httpClient` 契约——API 请求的 Token 注入和自动续期
  - AUTH-06 `SessionState` 枚举——会话状态感知
  - AUTH-06 `TokenPair` 模型——Token 结构定义
  - CASE-01 `CaseStatus` 枚举（draft / pending_review / rejected）——表单列表的状态筛选值
  - 项目结构 §6.1 的 views → Hooks → logics 三层隔离架构——模块内代码组织

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| CASE-01 案例录入管理 | 上游 API 消费 | 通过 httpClient 调用 6 个后端 API 端点（POST/GET/PUT /api/v1/cases/*），消费 12 份 CaseSchema 契约。API 路径前缀 `BASE_PATH = '/api/v1/cases'`，超时 15 秒，通过 AbortController 支持请求取消 |
| AUTH-06 认证会话管理 | 基础设施依赖 | 通过 `import { httpClient } from '../../shared/services/httpClient'` 导入 HTTP 客户端。httpClient 在请求前注入 Bearer Token，在 401 响应时自动续期（最多 3 次），续期失败后清除 TokenPair 并跳转登录页 |
| CASE-03 案例审核工作流 | 横向关联（只读展示） | 本模块在列表和详情中展示 CASE-03 维护的案例审核状态（draft / pending_review / approved / rejected）。不参与状态流转判定——仅读取并渲染 CaseResponse.status 字段。状态变更后用户通过手动下拉刷新获取最新数据 |
| CASE-08 案例管理界面 | 下游数据提供 | 通过 Hooks 桥接层将数据操作能力和表单状态暴露给界面组件。views 层仅通过 Hooks 访问本模块，禁止直接 import `caseApiService` 或 `useCaseFormStore` |
| Taro.Storage | 基础设施依赖 | 草稿持久化：`Taro.setStorageSync('case_form_draft', JSON.stringify(fields))`。草稿恢复：`Taro.getStorageSync('case_form_draft')` → JSON.parse。key 常量 `DRAFT_STORAGE_KEY = 'case_form_draft'` |
| TypeScript 5.x | 语言约束 | 全量类型化，所有 API 返回值和 Store 状态通过接口约束。枚举值通过 `@campfire/ts-shared` 的枚举定义获取，不使用 magic string |
| Zustand 5.x | 框架依赖 | `create<CaseFormState>()` 创建 Store。`persist` 中间件在评估中——但当前设计方案采用手动草稿保存而非 Zustand persist，详见 §1.6 权衡 #3 |
| Taro 4.x | 运行时环境 | 微信小程序运行时，所有 Storage API 使用 Taro 的同步版本（`setStorageSync`/`getStorageSync`/`removeStorageSync`） |

> 精确的函数签名、Store 类型定义、API 端点路径见落地规范。

### 1.4 状态机设计（技术实现策略）

CASE-09 管理两类状态：表单编辑状态（前端本地）和案例业务状态（后端维护的只读展示）。

**表单状态机**覆盖 5 个运行时状态，状态转换规则如下：

```
IDLE ──setField/setFields──► DIRTY ──30s无操作──► SAVED
  ▲                            │                     │
  │                            │                     │──setField──► DIRTY
  │                            │                     │
  │                            │──resetForm──────► IDLE
  │                            │
  │                            └──setSubmitting──► SUBMITTING
  │                                                   │
  │                                          请求成功──┤──► IDLE
  │                                          请求失败──┤──► DIRTY
  └────────────resetForm───────────────────────────────┘
                          │
  (应用启动) ──loadDraft──► RESTORING ──成功──► IDLE/DIRTY
                                   └──失败──► IDLE
```

技术实现要点：
- **状态存储方式**：表单状态通过 Zustand Store 的 `isDirty`（boolean）、`isSubmitting`（boolean）、`lastSavedAt`（string|null）三个字段组合表达，不使用枚举值。理由：多个状态维度可同时活跃（如"已保存"+"编辑中"可合并为 `isDirty=true, lastSavedAt=非空`），枚举无法表达这种组合。
- **防抖计时器管理**：`autoSaveTimer` 作为模块级变量（Store 外部闭包），每次 `setField/setFields` 调用时执行 `clearTimeout(autoSaveTimer)` 再 `setTimeout(saveDraft, 30000)`。计时器在 `resetForm` 中清除，避免泄漏。
- **幂等策略**：重复调用 `setSubmitting(true)` 在 `isSubmitting=true` 时无操作（`if (get().isSubmitting) return`）。重复调用 `loadDraft()` 在非 IDLE 状态下返回 false（草稿仅在字段为空时加载）。重复调用 `saveDraft()` 每次都写入 Storage（幂等写入）。
- **RESTORING 是瞬时状态**：`loadDraft()` 在 Store 的 `create` 初始化阶段同步执行，不产生异步等待。成功则立即进入 IDLE（字段已填充）或 DIRTY（合并后发现变更），失败则进入 IDLE（使用默认字段）。`isDirty` 在恢复后设为 false——待确认项：恢复后的草稿是否应标记为 dirty？当前策略是不标记，因为草稿是上次保存的最后状态，尚未被用户修改。

**案例业务状态展示**由 CASE-03 维护。CASE-09 在 `listCases` 和 `getCase` 的返回值中读取 `CaseResponse.status` 字段，不做本地状态提取或缓存。状态筛选通过查询参数传递到后端（`listCases(status, page, pageSize)`），后端负责按状态过滤——前端不维护本地状态过滤逻辑。

### 1.5 设计原则兑现清单（技术视角）

| 原则来源 | 原则内容 | 技术响应 |
|----------|----------|----------|
| 项目结构 §6.1 | views 与 logics 三层隔离（L1a → Hooks → L1b） | Hooks 层（useCaseFormStore / useCaseList / useCaseDetail）是 views 访问 logics 的唯一合法通道。禁止 views 直接 import `caseApiService` 或 `useCaseFormStore` 的原始 Store——必须通过 Hook 封装 |
| 项目结构 §6.1 | L1b 逻辑层职责：数据操作+状态管理 | API Service（caseApi.ts）纯 HTTP 封装，Store（caseStore.ts）纯状态管理，两者互不调用。编排逻辑集中在 Hooks 层——Hook 调用 API Service 获取数据后更新 Store |
| 项目结构 §三 | 前后端契约先行 | 所有 API 输入/输出类型引用自 `@campfire/ts-shared` 中的 CASE-01 类型定义。表单字段 `CaseFormFields` 接口的字段名、类型和约束与 CASE-01 的 `CaseCreateRequest` 契约对齐 |
| ADR-004 | 模块化单体边界纪律 | CASE-09 仅通过 httpClient 调用 CASE-01 的 API 端点，不直接读取数据库或绕过 API 层。不 import CASE-03 的代码——状态读取通过 CASE-01 的 CaseResponse.status 字段透传 |
| 技术栈设计 §2 | Zustand 5.x 前端状态管理 | 使用 `create<CaseFormState>()` 创建单一 Store，不引入 Redux 或额外的状态管理层。Store 操作通过 Hooks 暴露，不使用 `useStore(selector)` 直接访问内部结构 |
| 技术栈设计 §2 | Taro.Storage 本地持久化 | 草稿保存使用 `Taro.setStorageSync`（同步写入避免异步竞态），key 使用常量 `DRAFT_STORAGE_KEY` 避免硬编码散落 |
| CLAUDE.md §2 | 简单性优先 | 表单校验在提交前执行全量校验（一个 `validateAllFields()` 函数），不引入第三方校验库（Formik / Yup / Zod）——当前 19 个字段的校验规则（非空+枚举值）用原生函数实现代码量 <50 行，引入库反而增加依赖和学习成本 |
| 技术栈设计 §6.3 | 前端可观测性等价 | API 调用失败时通过 Hook 层的 `error` 状态向 views 暴露，views 通过 Taro UI 的 Toast 组件展示。不实现前端日志收集（小程序环境限制），不影响后端结构化日志的完备性 |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 文件命名 | `caseApi.ts` + `caseStore.ts` | 保持现状 `caseApiService.ts` + `caseFormStore.ts` | 项目结构设计文档是团队基准，代码必须收敛到设计文档的预期命名。Service 后缀冗余——文件名所在的 `services/` 目录已表明其职责，`Form` 后缀同样冗余。迁移期间通过旧文件名 re-export 保留兼容 |
| Hooks 拆分粒度 | 3 个独立 Hook（useCaseFormStore / useCaseList / useCaseDetail） | 1 个巨型 useCases Hook | 表单、列表、详情三者的生命周期和依赖驱动不同——表单 Hook 不随组件卸载销毁草稿状态，列表 Hook 由分页参数驱动，详情 Hook 由 caseId 驱动。拆分为三避免不必要的耦合重渲染和状态重置 |
| 防抖实现 | 模块级 `setTimeout` + `clearTimeout` | lodash.debounce / Zustand persist 中间件 | 原生计时器引入零依赖，逻辑<10行。lodash.debounce 的方案需要手动管理 `.cancel()` 调用时机，引入抽象层的收益不足以覆盖其复杂度。Zustand persist 中间件在每次状态变更时写入 Storage，缺少 30 秒防抖窗口——不符合意图文档 §1.11 约束 1 |
| 草稿合并策略 | `{ ...DEFAULT_FIELDS, ...parsed }` | 全量替换 / 深度合并 | 稀疏合并：parsed 中的字段覆盖 defaults，parsed 中不存在的字段保留 defaults。这允许新增表单字段时不破坏旧草稿的兼容性——旧草稿缺新字段时自动使用默认值。全量替换会让已填写的旧字段丢失；深度合并引入了不必要的复杂度 |
| 请求取消策略 | AbortController（fetch API 标准） | axios CancelToken / 无取消 | AbortController 是 Web 标准 API，Taro.request 已支持。每个 Hook 的请求函数创建独立的 AbortController，新请求自动取消旧请求。axios CancelToken 已被 axios 官方废弃（v0.22+），不应在新项目引入 |
| 错误提示位置 | Hooks 层暴露 `error: string|null`，views 层渲染 | API Service 层直接 Toast / Store 中存 error | Hooks 是 views 与 logics 的唯一桥梁，错误状态通过 Hook 返回。API Service 是纯函数不应有 UI 副作用。Store 层存 error 会与表单字段状态耦合——错误是请求级而非实体级 |
| 分页竞态处理 | AbortController 取消上一个未完成请求 | 请求序列号（token/id 比对丢弃旧响应） | AbortController 从根本上取消网络请求节省带宽，同时满足小程序网络并发限制。序列号方案不取消请求本身只是丢弃结果，浪费网络资源且在小程序环境中可能触发请求队列堆积 |

> 决策 #3（防抖实现）直接受意图文档 §1.11 约束 1 约束——30 秒防抖为硬约束，任何方案必须满足此项。
> 决策 #5（请求取消策略）为额外决策——意图文档 §1.12 技术决策第 6 项要求确定"请求超时与并发控制"，本设计将 AbortController 作为超时和并发控制的统一实现。

### 1.7 注意事项与禁止行为（设计层面）

1. **[Hooks 桥接硬约束]** views 层（`views/cases/`）只能通过本模块的 Hooks 访问数据。禁止 views 层直接 import `caseApi.ts` 的函数或 `useCaseFormStore` 的原始 Store。违反此约束将破坏 L1a/L1b 的三层隔离架构——一旦 views 直接依赖 API Service，Hook 层就成了无法强制执行的架空层。

2. **[文件命名迁移]** 本设计的落地规范将以 `caseApi.ts` 和 `caseStore.ts` 命名。实现时，旧文件保留为 re-export 别名：
   - 新建 `logics/cases/services/caseApi.ts`（新实现）
   - 保留 `logics/cases/services/caseApiService.ts`（`export * from './caseApi'`）
   - 旧文件名在确认所有引用已迁移后删除。这避免了过渡期 `git blame` 中断和 CI 构建失败。

3. **[禁止在 API Service 中操作 Store]** `caseApi.ts` 中的函数仅发送 HTTP 请求并返回 Promise，不得修改 Store 状态。API 调用结果由 Hook 层消费后写入 Store。API Service 中耦合 Store 会将数据获取与状态管理混淆，使单元测试无法独立测试 API 层。

4. **[禁止在 Store 中调用 API]** `caseStore.ts` 仅管理表单状态，不发起网络请求。Store 中的 `saveDraft()` 仅写入 Storage，`loadDraft()` 仅读取 Storage。违反此约束会使 Store 的纯状态变为不可预测的副作用容器。

5. **[设计边界]** 本模块不负责以下事项，禁止在本模块代码中实现：
   - 附件上传管线的编排（归属 CASE-02）——本模块不调用 `uploadAttachment` 或类似的附件接口
   - 审核工作流的状态流转判定（归属 CASE-03）——本模块仅通过 `CaseResponse.status` 读取并展示，不写入或判定状态变更
   - 案例文本的切片与向量化（归属 CASE-04）
   - 案例版本的迭代历史管理（归属 CASE-05）
   - 案例的失效标记与强制下架（归属 CASE-06）
   - 从多案例提炼标准化模板（归属 CASE-07）
   - 案例管理界面的 UI 渲染（归属 CASE-08）——本模块是 L1b 数据层，不包含 JSX 组件

6. **[防御性草稿合并]** `loadDraft()` 合并字段时必须使用 `{ ...DEFAULT_FIELDS, ...parsedDraft }` 顺序——默认字段先展开，草稿数据后展开覆盖。顺序颠倒会导致：旧草稿缺少某字段时，该字段在合并后为 `undefined` 而非默认值，可能引发提交校验的假阳性。

7. **[防抖计时器泄漏预防]** `autoSaveTimer` 在以下场景必须被 `clearTimeout`：(1) `resetForm()` 调用时；(2) 新一次 `setField/setFields` 触发防抖重置时；(3) Store 销毁时（React 严格模式下组件可能双挂载，计时器必须可重复清除）。常见错误是仅在组件卸载时清除——但计时器挂载在 Store 外部闭包，与组件生命周期无关。

8. **[偷懒红线]** 禁止以下简化：
   - 禁止以"列表和详情的 API 差不多"为由省略分页逻辑或详情查询独立测试
   - 禁止以"PII 检测在 CASE-01 是提醒功能"为由跳过前端 `detectPii` 的调用封装
   - 禁止以"以后再加"为由跳过 Hooks 层的实现——这直接违反项目结构设计文档的三层隔离架构，是阻塞级问题

### 1.8 引用：配套意图文档

- **意图文档**：`CASE-09-案例管理逻辑-意图文档.md`
- **冻结时间**：`2026-05-27 17:47:49`
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。意图文档 §1.12 列出的 7 项技术决策（TypeScript 类型定义、Hooks 桥接层架构、防抖精确参数、状态管理策略、异常处理技术方案、超时与并发控制、文件命名与目录结构）均已在本文档各章节中给出明确的技术裁决。上游 s05-spec-prepare 的一致性检查确认与 25 份已有规格文档零冲突。CASE-03（审核工作流）和 CASE-08（管理界面）尚未设计，本模块首次定义 Hooks 桥接接口时已预留扩展点——Hooks 的返回类型使用接口定义，CASE-08 可直接消费。如有歧义，以意图文档为准。
