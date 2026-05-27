## 功能模块落地完成：CSLT-05 置信度后校验（对抗性验证模式）

### 涉及技术栈
Python 3.12, FastAPI, Pydantic v2, asyncio, ahocorasick, tenacity, pytest + pytest-asyncio

### 代码组织依据
严格遵循 `docs/篝火智答-项目结构.md` 和 `CSLT-05-置信度后校验-落地规范.md` §1.2 文件归属表

### 修改文件范围
- **新增**：
  - `apps/api-server/app/services/consult/__init__.py`
  - `apps/api-server/app/services/consult/confidence_validator.py`
  - `apps/api-server/app/services/consult/keyword_scanner.py`
  - `apps/api-server/app/services/consult/rule_validator.py`
  - `apps/api-server/app/services/consult/ticket_trigger.py`
  - `packages/py-schemas/py_schemas/consult/__init__.py`
  - `packages/py-schemas/py_schemas/consult/confidence.py`
- **修改**：
  - `packages/py-llm/py_llm/client.py`（新增 `async_chat()` 非流式方法）
- **重构**：
  - `packages/py-schemas/py_schemas/consult.py` → `consult/` 包（保留向后兼容）

### 对抗性验证记录

| 轮次 | 总用例 | 通过 | 失败 | 收敛状态 |
|:---|:---|:---|:---|:---|
| 1 | 43 | 35 | 8 | 初始盲测 |
| 1 (测试修正后) | 43 | 35 | 8 | improving（修复 mocker 依赖） |
| 1 (实现修复 + 测试修正后) | 43 | 37 | 6 | improving（3 实现漏洞修复 + mock 策略更新） |
| 1 (最终修正后) | 43 | 43 | 0 | **converged** |

### 流程执行证据索引

| 阶段 | 证据文件 | 状态 | 说明 |
|:---|:---|:---|:---|
| Phase 1.1 契约提取 | `contract-expectations.md` | ✅ | 26 条契约期望 |
| Phase 1.1 验证 | `validate_contract_expectations.py` 输出 | ✅ | valid=true |
| Phase 2 函数签名 | `function-signatures.json` | ✅ | 4 个公开函数 |
| Phase 2 验证 | `validate_function_signatures.py` 输出 | ✅ | valid=true |
| Phase 2 待确认 | `pending-confirmations.md` | ✅ | 6 项待确认（均风险可控） |
| Phase 3 测试生成 | `test_cslt05_adversarial.py` + `cslt05_adversarial_test_list.md` | ✅ | 43 测试函数 |
| Phase 4.2 Round 1 | `failure-summary-round-1.md` | ✅ | 3 个实现漏洞 |
| Phase 4.5.1 测试缺陷 R1 | `test-defects-round-1.md` | ✅ | 3 个导入/路径缺陷 |
| Phase 4.5.2 SubAgent 修正 R1 | SubAgent 调用记录 | ✅ | 修正导入路径 + sys.path |
| Phase 4.5.1 测试缺陷 R2 | `test-defects-round-2.md` | ✅ | 1 个 mocker fixture 依赖 |
| Phase 4.5.2 SubAgent 修正 R2 | SubAgent 调用记录 | ✅ | 替换为 unittest.mock.patch |
| Phase 4.5.1 测试缺陷 R3 | `test-defects-round-3.md` | ✅ | 1 个 KeywordScanner mock 策略 |
| Phase 4.5.2 SubAgent 修正 R3 | SubAgent 调用记录 | ✅ | 修正 get_instance() mock 策略 |
| Phase 5 Round 1 | `pending-confirmations-round-1.md` | ✅ | 3 个漏洞修复 |
| Phase 4.4 回归检查 | 回归检查记录 | ✅ | 无退化（最终轮 43/43） |

### 发现的漏洞与修复

#### 实现漏洞（经 Phase 5 SubAgent 修复）

1. **[关键词扫描阻断逻辑缺失]** `validate_confidence()` 对 plan_text 的关键词扫描命中后未进入 FORCE_BLOCK 路径
   - 修复：移除否定词过滤（仅对 plan_text），命中后立即短路进入 FORCE_BLOCK
   - 涉及契约：§1.5
   - 修复轮次：Round 1

2. **[工单创建失败标志未设置]** `ticket_creation_failed` 在触发工单全部重试失败后保持默认值 False
   - 修复：将工单创建从 BackgroundTasks 异步投递改为 inline await，捕获异常并设置 ticket_creation_failed=True
   - 涉及契约：§1.9
   - 修复轮次：Round 1

3. **[FORCE_BLOCK 未触发工单]** `high_risk_keyword_hit=True` 时返回了正确 verdict 但未调用工单创建
   - 修复：在 FORCE_BLOCK 分支中添加工单创建调用（与 #2 合并修复）
   - 涉及契约：§1.5
   - 修复轮次：Round 1

#### 测试缺陷（经 Phase 3 SubAgent 修正）

1. **[导入路径错误]** conftest.py 缺少 sys.path 设置，mock patch 路径使用了错误的模块前缀
   - 修正：添加 sys.path 设置 + 修正所有 patch 路径
   - 修正轮次：Round 1
   - 测试缺陷报告：`test-defects-round-1.md`

2. **[mocker fixture 依赖]** conftest.py 使用 pytest-mock 的 `mocker` fixture，但项目不依赖该包
   - 修正：全部替换为 `unittest.mock.patch` 上下文管理器
   - 修正轮次：Round 2
   - 测试缺陷报告：`test-defects-round-2.md`

3. **[KeywordScanner mock 策略]** autospec mock 无法正确拦截 `get_instance().scan_keywords()` 调用链
   - 修正：改为仅 patch `KeywordScanner.get_instance`，手动配置返回值的 scan_keywords
   - 修正轮次：Round 3
   - 测试缺陷报告：`test-defects-round-3.md`

### 模块作用简述
置信度后校验是应急咨询安全保障流水线的最后关卡，对 AI 生成的应急方案进行关键词安检和置信度双重评估，决定方案是直接交付、追加警示还是强制阻断。

### 已知遗留
- **契约间隙**：CSLT-01 `CrisisJudgmentResult` 缺少 `high_risk_keyword_hit` 字段（降级方案：从 `judgment_sources` 反推）
- **配置管理**：CSLT-05 专属配置键使用 `os.getenv()` 而非 `py_config.AppSettings` 统一管理
- **TICK-01 mock**：工单创建当前为 mock 实现，待 TICK-01 落地后替换
- **工单创建同步化**：已将工单创建从 BackgroundTasks 改为 inline await（解决了 ticket_creation_failed 如实反映的问题，但增加了主流程耗时）
- **py-llm 阻塞调用**：`LLMClient` 重试循环中使用 `time.sleep()`（非 CSLT-05 模块范围）

### 对抗性测试位置
`apps/api-server/app/services/consult/.tmp/adversarial-tests/CSLT-05/`
（可运行 `pytest apps/api-server/app/services/consult/.tmp/adversarial-tests/CSLT-05/ -v` 复现）

### 建议后续操作
- 调用 module-test-writer 生成正式验收测试（基于 AC-01~AC-07）
- 将关键词扫描 mock 策略经验纳入后续模块的测试生成指南
- 待 TICK-01 落地后替换 ticket_trigger.py 中的 mock 实现
- 评估工单创建从 BackgroundTasks 改为 inline await 对 P95 延迟的影响

---

## 诚实声明

| # | 声明 | 验证方式 | 证据文件 |
|:---|:---|:---|:---|
| 1 | 实现代码严格按落地规范和项目结构设计文档编写，未参考任何对抗性测试代码 | 代码审查 + 实现代码由 SubAgent 独立编写 | 实现源码文件 |
| 2 | 对抗性测试严格按接口契约生成，未读取实现源码 | SubAgent 隔离约束 | `contract-expectations.md` |
| 3 | 失败摘要仅包含错误类型和契约条款，未向实现者暴露测试代码或具体输入值 | 失败摘要格式审查 | `failure-summary-round-1.md` |
| 4 | 所有测试误报已修正并排除在修复流程之外 | `test-defects-round-*.md` 存在 + SubAgent 修正记录 | `test-defects-round-1.md`, `test-defects-round-2.md`, `test-defects-round-3.md` |
| 5 | 信息隔离规则在全部迭代轮次中被遵守 | 以上 1-4 项全部通过 | 以上全部证据 |
| 6 | orchestrator 未在 Phase 4 直接修改任何测试代码文件 | `check_isolation.py` 审计通过 | 审计结果: ✅ 合规 |
| 7 | 所有测试缺陷均通过 Phase 3 SubAgent 修正，非 orchestrator 直接处理 | SubAgent 调用记录 + `test-defects-round-*.md` 存在 | 3 次 SubAgent 修正记录 |
