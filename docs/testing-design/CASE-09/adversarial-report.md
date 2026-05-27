## 功能模块落地完成：CASE-09 案例管理逻辑（对抗性验证模式）

### 涉及技术栈
前端 TypeScript / Taro 4.x / Zustand 5.x / Vitest

### 代码组织依据
严格遵循 `docs/篝火智答-项目结构.md` §6.1 的 views → Hooks → logics 三层隔离架构。

### 修改文件范围
- **新增**：
  - `apps/mini-program/src/logics/cases/services/caseApi.ts` — API 服务层（6 个函数 + AbortController + 参数校验）
  - `apps/mini-program/src/logics/cases/store/caseStore.ts` — Zustand 表单状态管理（含 30s 防抖自动保存）
  - `apps/mini-program/src/logics/cases/hooks/useCaseFormStore.ts` — 表单 Store Hook 桥接
  - `apps/mini-program/src/logics/cases/hooks/useCaseList.ts` — 列表查询 Hook（含竞态取消）
  - `apps/mini-program/src/logics/cases/hooks/useCaseDetail.ts` — 详情查询 Hook（含竞态取消）
  - `apps/mini-program/src/logics/cases/types/index.ts` — 内部类型定义
- **修改**：
  - `apps/mini-program/src/logics/cases/services/caseApiService.ts` → re-export 别名
  - `apps/mini-program/src/logics/cases/store/caseFormStore.ts` → re-export 别名
  - `apps/mini-program/vitest.config.ts` — include 模式扩展

### 对抗性验证记录

| 轮次 | 总用例 | 通过 | 失败 | 收敛状态 |
|:---|:---|:---|:---|:---|
| 1 | 149 | 116 | 33 | 初始盲测（含测试缺陷） |
| 1 (测试修正后) | 149 | 132 | 17 | improving（测试缺陷已修正，暴露实现漏洞） |
| 1 (实现修复后) | 149 | 149 | 0 | **converged** |

### 流程执行证据索引

| 阶段 | 证据文件 | 状态 | 说明 |
|:---|:---|:---|:---|
| Phase 1.1 契约提取 | `contract-expectations.md` | ✅ | 41 条契约期望（A22 + B05 + C03 + D04 + E07） |
| Phase 1.1 验证 | `validate_contract_expectations.py` 输出 | ✅ | 验证通过 |
| Phase 2 函数签名 | `function-signatures.json` | ✅ | 10 个公开函数 |
| Phase 2 验证 | `validate_function_signatures.py` 输出 | ✅ | 验证通过 |
| Phase 3 测试生成 | `test_CASE-09.adversarial.ts` + `CASE-09.adversarial.test.list.md` | ✅ | 149 个测试用例 |
| Phase 4.2 Round 1 | `failure-summary-round-1.md` | ✅ | 17 个漏洞（去重后 3 类） |
| Phase 4.5.1 测试缺陷 | `test-defects-round-1.md` | ✅ | 4 类测试缺陷（mock 路径、期望值、require 模式、超时） |
| Phase 4.5.2 SubAgent 修正 | SubAgent 调用记录 | ✅ | 测试缺陷通过 adversarial-test-generator SubAgent 修正 |
| Phase 5 Round 1 | `pending-confirmations-round-1.md` | ✅ | 无设计偏离 |
| Phase 4.4 回归检查 | 回归检查记录 | ✅ | 无退化（132→149 通过，失败 17→0） |

### 发现的漏洞与修复

#### 实现漏洞（经 Phase 5 SubAgent 修复）

1. **[AbortSignal 未检查]** 6 个 API 函数未检查传入的 signal 是否已 abort
   - 修复：每个函数入口添加 `if (signal?.aborted) return Promise.reject(new DOMException(...))`
   - 涉及契约：§1.1（请求取消策略）
   - 修复轮次：Round 1

2. **[参数空值校验缺失]** 5 个 API 函数的必填参数未校验 null/undefined
   - 修复：每个必填参数添加 null/undefined 检查，违规时 reject TypeError
   - 涉及契约：§1.5.6–§1.5.11（各函数参数类型约束）
   - 修复轮次：Round 1

3. **[竞态请求取消未实现]** useCaseDetail hook 在 caseId 切换时未 abort 旧请求
   - 修复：在 useEffect 中 fetchDetail 前添加 `abortRef.current?.abort()`
   - 涉及契约：§1.1（caseId 变更时取消旧请求）
   - 修复轮次：Round 1

#### 测试缺陷（经 Phase 3 SubAgent 修正）

1. **[Mock 返回结构]** httpClient mock 返回裸数据而非 `{ data: T }` 结构
   - 修正：mock 工厂返回 `{ data: response }` 结构
   - 修正轮次：Round 1
   - 测试缺陷报告：`test-defects-round-1.md`

2. **[断言逻辑]** loadDraft null 值测试期望 `false`，但 `JSON.parse("null")` 是有效 JSON
   - 修正：期望改为 `true`
   - 修正轮次：Round 1

3. **[模块加载]** A20 测试使用 `require('@tarojs/taro').default` 在 ESM 环境失败
   - 修正：改用已导入的 `vi.mocked(Taro)` 覆盖 mock
   - 修正轮次：Round 1

4. **[测试超时]** D02 测试等待 15 秒超过 vitest 默认 5 秒限制
   - 修正：使用 `vi.useFakeTimers()` + `vi.advanceTimersByTime()`
   - 修正轮次：Round 1

### 模块作用简述

CASE-09 是前端 L1b 逻辑层模块，封装案例 CRUD 的 API 调用和表单状态管理。通过 Hooks 桥接层为 CASE-08（案例管理界面）提供数据操作能力，是 views 与 API 之间的唯一合法数据通道。

### 已知遗留

- `pending-confirmations.md`（Phase 2）记录的 3 项实现偏差（loadDraft 初始化时机、httpClient signal 类型适配、旧 store 文件重导出策略）为低风险设计决策，不影响功能正确性
- CASE-01 契约中 6 个类型的 `x-consumers` 缺失 CASE-09 注册（`_sync-issues.md` 已记录，low 级别），不影响运行时行为

### 对抗性测试位置

`.tmp/adversarial-tests/CASE-09/`

运行命令：
```bash
cd apps/mini-program && npx vitest run src/logics/cases/.tmp/adversarial-tests/CASE-09/test_CASE-09.adversarial.ts
```

### 建议后续操作

- CASE-08（案例管理界面）实现时，通过 CASE-09 的三个 Hooks 获取数据和操作能力，禁止直接 import `caseApi` 或 `caseStore`
- CASE-01 契约的 x-consumers 补充注册 CASE-09
- 将参数空值校验和 AbortSignal 检查模式纳入前端 API 层编码规范

---

## 诚实声明

| # | 声明 | 验证方式 | 证据文件 |
|:---|:---|:---|:---|
| 1 | 实现代码严格按落地规范和项目结构设计文档编写，未参考任何对抗性测试代码。 | Phase 2 SubAgent 仅读取设计文档和契约文件 | `function-signatures.json` |
| 2 | 对抗性测试严格按接口契约生成，未读取实现源码。 | Phase 3 SubAgent 仅读取契约清单和函数签名 | `contract-expectations.md` |
| 3 | 失败摘要仅包含错误类型和契约条款，未向实现者暴露测试代码或具体输入值。 | `validate_failure_summary.py` 信息隔离检查通过 | `failure-summary-round-1.md` |
| 4 | 所有测试误报已修正并排除在修复流程之外。 | `test-defects-round-1.md` 存在 + Phase 4.5.2 SubAgent 修正记录 | `test-defects-round-1.md` |
| 5 | 信息隔离规则在全部迭代轮次中被遵守。 | 以上 1-4 项全部通过 | 以上全部证据 |
| 6 | orchestrator 未在 Phase 4 直接修改任何测试代码文件。 | `check_isolation.py` 审计通过 + `test-defects-round-1.md` 存在 | `check_isolation.py` 输出 |
| 7 | 所有测试缺陷均通过 Phase 3 SubAgent 修正，非 orchestrator 直接处理。 | Phase 4.5.2 SubAgent 调用记录 + `test-defects-round-1.md` 存在 | Phase 4.5.2 Agent 记录 |
