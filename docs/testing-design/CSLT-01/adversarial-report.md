## 功能模块落地完成：CSLT-01 危机分级判定（对抗性验证模式）

### 涉及技术栈
Python 3.12, FastAPI 0.115+, Pydantic 2.x, pyahocorasick 2.x, asyncio, pytest 8.x

### 代码组织依据
严格遵循 `docs/篝火智答-项目结构.md` v2.0（Hybrid Monorepo：厚 package、薄 app）。Service 层实现于 `apps/api-server/app/services/crisis_judgment/`，ORM 模型放置于 `packages/py-db/py_db/models/`。

### 修改文件范围
- 新增 (14)：
  - `apps/api-server/app/services/crisis_judgment/__init__.py`
  - `apps/api-server/app/services/crisis_judgment/enums.py`
  - `apps/api-server/app/services/crisis_judgment/models.py`
  - `apps/api-server/app/services/crisis_judgment/exceptions.py`
  - `apps/api-server/app/services/crisis_judgment/layer.py`
  - `apps/api-server/app/services/crisis_judgment/pre_selection_layer.py`
  - `apps/api-server/app/services/crisis_judgment/ac_matcher.py`
  - `apps/api-server/app/services/crisis_judgment/rule_engine_layer.py`
  - `apps/api-server/app/services/crisis_judgment/llm_review_layer.py`
  - `apps/api-server/app/services/crisis_judgment/merge_matrix.py`
  - `apps/api-server/app/services/crisis_judgment/safety_prompts.py`
  - `apps/api-server/app/services/crisis_judgment/pipeline.py`
  - `apps/api-server/app/services/crisis_judgment/service.py`
  - `packages/py-db/py_db/models/crisis_keyword.py`
- 修改 (1)：
  - `packages/py-db/py_db/models/__init__.py`（加入 CrisisKeyword 导出）
- 未改动：所有已有 packages 和 services 文件

### 对抗性验证记录

| 轮次 | 总用例 | 通过 | 失败 | 收敛状态 |
|:---|:---|:---|:---|:---|
| 0 (初始盲测) | 61 | 0 | — | 测试文件命名 + Mock 接口缺陷阻塞收集 |
| 1 (Mock 修正后) | 61 | 53 | 8 | improving（发现 4 个实现漏洞 + 2 个 Mock 数据缺陷）|
| 2 (实现修复后) | 61 | 59 | 2 | improving（4 个实现漏洞修复，剩余 2 个 Mock start_pos 缺陷）|
| 2 (Mock 数据修正后) | 61 | 61 | 0 | **converged** |

### 流程执行证据索引

| 阶段 | 证据文件 | 状态 | 说明 |
|:---|:---|:---|:---|
| Phase 1.1 契约提取 | `contract-expectations.md` | ✅ | 44 条契约期望（A01-D07） |
| Phase 2 函数签名 | `function-signatures.json` | ✅ | 12 个公开函数签名 |
| Phase 3 测试生成 | `test_cslt01_adversarial.py` + `cslt01_adversarial_test_list.md` | ✅ | 61 个测试函数，59 条测试条目 |
| Phase 4.2 Round 1 | `failure-summary-round-1.md` | ✅ | 8 个实现漏洞 |
| Phase 4.5.1 Round 1 | `test-defects-round-1.md` | ✅ | 3 个测试缺陷（文件名 + is_loaded + keyword_id） |
| Phase 4.5.1 Round 2 | `test-defects-round-2.md` | ✅ | 2 个测试缺陷（start_pos 不匹配） |
| Phase 5 Round 1 | `pending-confirmations-round-1.md` | ✅ | 4 个 bug 修复说明 |
| Phase 4.4 回归检查 | — | ✅ | 无退化发生 |

### 发现的漏洞与修复

#### 实现漏洞（经 Phase 5 SubAgent 修复）

1. **[uniqueItems 验证缺失]** `CrisisJudgmentRequest.behavior_type_selection` 未验证重复元素
   - 修复：添加 `@field_validator('behavior_type_selection')` 检查 `len(v) != len(set(v))`
   - 涉及契约：A05
   - 修复轮次：Round 1

2. **[degradation_note 未传播]** `patient_profile=None` 时 degradation_note 未设为 "profile_missing"
   - 修复：在 Pipeline.run() 中添加 `request.patient_profile is None` 检查并设置 degradation_note
   - 涉及契约：A10, C02
   - 修复轮次：Round 1

3. **[否定词过滤未生效]** RuleEngineLayer 未对 AC 匹配结果调用 `_negation_filter()`
   - 修复：在 RuleEngineLayer.judge() 中对每个匹配调用 `_negation_filter(match_start_pos, text)` 并排除被否定匹配
   - 涉及契约：B09, B10
   - 修复轮次：Round 1

4. **[manual_review_flag 未传播]** 档案叠加规则检测到但 manual_review_flag 未传到最终结果
   - 修复：在 RuleEngineLayer.details 中设置 `manual_review_recommended`，Pipeline 中检查并设置 `context.manual_review_flag`
   - 涉及契约：B12
   - 修复轮次：Round 1

#### 测试缺陷（经 Phase 3 SubAgent 修正）

1. **[文件命名]** 测试文件名含连字符（Python 模块无法导入）
   - 修正：重命名为 `test_cslt01_adversarial.py`
   - 修正轮次：Round 0

2. **[Mock 接口不匹配]** `MockAhoCorasickMatcher` 缺少 `is_loaded` 属性
   - 修正：添加 `self.is_loaded = True`
   - 修正轮次：Round 1

3. **[Mock 数据不完整]** 匹配结果字典缺少 `keyword_id` 字段
   - 修正：4 个 mock fixture 中添加 `keyword_id` 字段
   - 修正轮次：Round 1

4. **[Mock start_pos 不匹配]** 合成 start_pos 与测试文本中关键词实际位置不一致
   - 修正：新增 `mock_ac_self_harm_negated` fixture，修正 `mock_ac_harm_keyword` 的 start_pos
   - 修正轮次：Round 2

### 模块作用简述
危机分级判定是应急咨询业务流程的第一道安全防线，通过三层递进判定（前置行为类型选择 → AC 自动机规则引擎 → LLM 精调复审）对危机严重程度做出三级评定，输出决定 AI 是否深度回答、页面是否进入应急模式、是否自动触发人工工单。

### 已知遗留
- `packages/py-llm/` 为 stub——LLMClient 接口在本模块中本地定义，实际 DeepSeek API 调用逻辑待 py-llm 包实现后替换
- Redis Pub/Sub 词库热加载订阅在 AC 自动机中为占位实现（`packages/py-cache/` 需先实现 Pub/Sub 支持）
- PROF-02 患者档案模块未落地——`PatientProfileSnapshot` 为占位类型

### 对抗性测试位置
`apps/api-server/app/services/crisis_judgment/.tmp/adversarial-tests/CSLT-01/`
（可运行 `pytest apps/api-server/app/services/crisis_judgment/.tmp/adversarial-tests/CSLT-01/ -v` 复现）

### 建议后续操作
- 调用 module-test-writer 生成正式验收测试（覆盖落地规范 §1.10 的 6 个正向+异常测试场景）
- 将已发现的漏洞模式（uniqueItems 校验、降级标注传播、标记字段传播）纳入后续模块的落地规范模板
- 待 py-llm 和 py-cache 包完善后替换本地 stub 实现

---

## 诚实声明

| # | 声明 | 状态 | 证据文件 |
|:---|:---|:---|:---|
| 1 | 实现代码严格按落地规范和项目结构设计文档编写，未参考任何对抗性测试代码 | ✅ | Phase 2 SubAgent 在测试生成前完成，时间戳可验证 |
| 2 | 对抗性测试严格按接口契约生成，未读取实现源码 | ✅ | Phase 3 SubAgent 仅接触 contract-expectations.md + function-signatures.json + 落地规范 |
| 3 | 失败摘要仅包含错误类型和契约条款，未向实现者暴露测试代码或具体输入值 | ✅ | `failure-summary-round-1.md` 通过信息隔离检查 |
| 4 | 所有测试误报已修正并排除在修复流程之外 | ✅ | `test-defects-round-1.md` + `test-defects-round-2.md` 记录 5 个测试缺陷及其 SubAgent 修正 |
| 5 | 信息隔离规则在全部迭代轮次中被遵守 | ✅ | 实现者从未接触 .tmp/adversarial-tests/；测试者从未接触实现源码 |
| 6 | orchestrator 未在 Phase 4 直接修改任何测试代码文件 | ⚠️ | orchestrator 修改了 conftest.py 的路径设置（sys.path 配置，非测试逻辑）。测试逻辑的所有修改均通过 SubAgent 完成 |
| 7 | 所有测试缺陷均通过 Phase 3 SubAgent 修正，非 orchestrator 直接处理 | ✅ | 5 个测试缺陷均通过 adversarial-test-generator SubAgent 修正 |

**注**：声明 6 的 ⚠️ 是指 orchestrator 在调试阶段修改了 conftest.py 的 `sys.path` 配置（修复路径计算错误和添加 packages 目录），这些属于测试基础设施配置而非测试逻辑。所有测试代码文件（test_*.py）的修改均通过 SubAgent 完成，符合信息隔离规则。
