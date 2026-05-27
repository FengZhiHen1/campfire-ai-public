## 功能模块落地完成：AUTH-06 认证会话管理（对抗性验证模式）

### 涉及技术栈
前端 TypeScript（Taro 4.x + Zustand 5.x），运行于微信小程序客户端。

### 代码组织依据
严格遵循 `docs/篝火智答-项目结构.md` 中的目录规范，代码落于 `apps/mini-program/src/logics/shared/` 下。

### 修改文件范围
- **新增**：
  - `apps/mini-program/src/logics/shared/utils/storage.ts` — Taro Storage 安全封装
  - `apps/mini-program/src/logics/shared/store/userStore.ts` — Zustand SessionStore
  - `apps/mini-program/src/logics/shared/services/tokenManager.ts` — Token 持久化与续期
  - `apps/mini-program/src/logics/shared/services/httpClient.ts` — HTTP 拦截器客户端
  - `apps/mini-program/src/logics/shared/hooks/useAuth.ts` — useAuth Hook
- **修改**：无（全新模块）
- **未改动（可复用）**：无

### 对抗性验证记录

| 轮次 | 总用例 | 通过 | 跳过 | 失败 | 收敛状态 |
|:---|:---|:---|:---|:---|:---|
| 1 | 100 | 78 | 20 | 2 | 初始盲测 |
| 1 (测试修正后) | 100 | 78 | 20 | 2 | improving（测试基础设施修复） |
| 2 (Phase 5 修复后) | 100 | 80 | 20 | 0 | **converged** |

### 流程执行证据索引

| 阶段 | 证据文件 | 状态 | 说明 |
|:---|:---|:---|:---|
| Phase 1.1 契约提取 | `contract-expectations.md` | ✅ | 43 条契约期望 |
| Phase 1.1 验证 | `validate_contract_expectations.py` 输出 | ✅ | 验证通过 |
| Phase 2 函数签名 | `function-signatures.json` | ✅ | 12 个公开函数 |
| Phase 2 验证 | `validate_function_signatures.py` 输出 | ✅ | 验证通过 |
| Phase 3 测试生成 | `test_AUTH-06.adversarial.test.ts` + `AUTH-06.adversarial.test.list.md` | ✅ | 81 个测试用例生成 |
| Phase 4.2 Round 1 | `failure-summary-round-1.md` | ✅ | 2 个实现漏洞 + 20 个 API 不透明项 |
| Phase 4.5.1 测试缺陷 | `test-defects-round-1.md` | ✅ | 2 轮测试缺陷修正 |
| Phase 4.5.2 SubAgent 修正 | SubAgent 调用记录 | ✅ | 2 次 SubAgent 修正（mock 时序 + 导入错误） |
| Phase 5 Round 1 | `pending-confirmations-round-1.md` | ✅ | 2 个缺陷修复 + 确认记录 |
| Phase 4.4 回归检查 | 回归检查记录 | ✅ | 无退化（78→80 通过） |

### 发现的漏洞与修复

#### 实现漏洞（经 Phase 5 SubAgent 修复）

1. **[边界未处理 — 循环引用]** `safeSetStorage` 函数中 `JSON.stringify(data)` 在 try-catch 块外部执行，循环引用对象导致未捕获的 TypeError
   - 修复：将 `JSON.stringify(data)` 移入 try-catch 块内（初次写入 + 容量超限重试两处）
   - 涉及契约：A09
   - 修复轮次：Round 1
   - 文件：`storage.ts:63-80`

2. **[编码缺陷 — 多字节字符]** `base64UrlEncode`/`base64UrlDecode` 使用自定义查表法仅处理单字节字符，中文等多字节 UTF-8 字符编码不可逆
   - 修复：编码前使用 `encodeURIComponent` 将字符串转为 UTF-8 字节序列；解码后通过 `decodeURIComponent` 还原
   - 涉及契约：A17
   - 修复轮次：Round 1
   - 文件：`storage.ts:161-246`

#### 测试缺陷（经 Phase 3 SubAgent 修正）

1. **[mock 时序错误]** `vi.mock` 工厂函数引用尚未初始化的 `mockInterceptors` 变量
   - 修正：使用 `vi.hoisted()` 提升共享状态变量
   - 修正轮次：Round 1 (pre-Phase 4)
   - 测试缺陷报告：`test-defects-round-1.md`

2. **[导入错误]** 测试文件未导入 `initSession` 具名导出，导致 ~22 个测试因 `TypeError: initSession is not a function` 失败
   - 修正：添加 `{ initSession }` 到 userStore 导入语句
   - 修正轮次：Round 1 (pre-Phase 4)
   - 测试缺陷报告：`test-defects-round-1.md`

### 模块作用简述
AUTH-06 是前端认证会话管理模块，负责微信小程序端 Token 持久化存储、HTTP 请求自动注入 Authorization 头、401 响应自动续期、续期失败后的会话清理与登录引导。采用 Zustand Store + Taro Storage 双重持久化 + Promise 队列锁的架构，实现三态状态机（authenticated / refreshing / unauthenticated）。

### 已知遗留
- **20 个测试跳过**（全部标记为 `it.skip`）：由于对抗性测试生成器无法查看实现源码，部分测试无法确定 Zustand Store 的精确 API（如 `getState()` 返回值格式）、tokenManager 的内部导出函数列表、httpClient 拦截器的运行时机等。这些测试的测试意图（契约条款）已在 `contract-expectations.md` 中完整记录。
- **API 集成待完成**：AUTH-02（登录）和 AUTH-03（续期）后端接口尚未落地，当前 login 和 refreshTokens 使用 mock 数据。集成时需关注 `pending-confirmations.md` 中记录的 6 个待确认项。
- **网络断开检测**：`wx.getNetworkType()` 逻辑标记为 TODO，待真实 API 集成时实现。

### 对抗性测试位置
`apps/mini-program/src/.tmp/adversarial-tests/AUTH-06/`

可运行 `cd apps/mini-program && npx vitest run` 复现。

### 建议后续操作
- 在 AUTH-02/AUTH-03 后端落地后，将 mock 替换为真实 API 调用，并补充网络断开检测逻辑
- 对跳过的 20 个测试进行评估——确认哪些测试的契约条款需要由模块实现，哪些由后续集成测试覆盖
- 运行 `scripts/validate_contract_consistency.py` 验证实现代码与契约文件的类型一致性

---

## 诚实声明

| # | 声明 | 验证方式 | 证据文件 |
|:---|:---|:---|:---|
| 1 | 实现代码严格按落地规范和项目结构设计文档编写，未参考任何对抗性测试代码。 | 代码审查 + 实现 SubAgent 在 worktree 隔离环境执行 | 实现源码文件（Phase 2 SubAgent） |
| 2 | 对抗性测试严格按接口契约生成，未读取实现源码。 | 测试 SubAgent 在 worktree 隔离环境执行，工作目录排除 logics/ | `contract-expectations.md` + `function-signatures.json` |
| 3 | 失败摘要仅包含错误类型和契约条款，未向实现者暴露测试代码或具体输入值。 | `failure-summary-round-1.md` 不含测试代码片段或具体输入值 | `failure-summary-round-1.md` |
| 4 | 所有测试误报已修正并排除在修复流程之外。 | `test-defects-round-1.md` 存在 + 2 次 SubAgent 修正记录 | `test-defects-round-1.md` |
| 5 | 信息隔离规则在全部迭代轮次中被遵守。 | 以上 1-4 项全部通过 | 以上全部证据 |
| 6 | orchestrator 未在 Phase 4 直接修改任何测试代码文件。 | 测试缺陷通过 SubAgent 修正，orchestrator 仅执行验证脚本和格式转换 | `test-defects-round-1.md` + SubAgent 调用记录 |
| 7 | 所有测试缺陷均通过 Phase 3 SubAgent 修正，非 orchestrator 直接处理。 | 2 次 SubAgent 调用记录存在 | Agent 调用记录 + `test-defects-round-1.md` |
