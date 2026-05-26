# 对抗性验证报告模板

本模板定义 Phase 6 结果汇报的标准格式。

**核心原则**：报告中的每一条声明都必须有对应的可验证证据文件支撑。用户和审查者应能通过检查证据文件独立验证流程合规性，而非只能信任 orchestrator 的口头声明。

## 报告文件

**存放路径**：`docs/testing-design/{module_id}/adversarial-report.md`

## 模板

```markdown
## 功能模块落地完成：{模块名称}（对抗性验证模式）

### 涉及技术栈
{前端/后端/全栈，具体框架和语言}

### 代码组织依据
{严格遵循项目结构设计文档（xxx-项目结构.md）中的目录规范}

### 修改文件范围
- 新增：{文件列表}
- 修改：{文件列表}
- 未改动（可复用）：{文件列表}

### 对抗性验证记录

| 轮次 | 总用例 | 通过 | 跳过 | 失败 | 收敛状态 |
|:---|:---|:---|:---|:---|:---|
| 1 | 93 | 43 | 30 | 20 | 初始盲测 |
| 2 | 93 | 58 | 30 | 5 | improving（15 修复生效） |
| 2 (修正后) | 93 | 63 | 30 | 0 | converged |

### 流程执行证据索引

> 以下每条声明的 ✅/❌ 都对应 `.tmp/adversarial-tests/{module_id}/` 下的具体证据文件。
> 如果证据文件缺失，对应声明必须为 ❌ 或 ⚠️。

| 阶段 | 证据文件 | 状态 | 说明 |
|:---|:---|:---|:---|
| Phase 1.1 契约提取 | `contract-expectations.md` | {✅/❌} | {N} 条契约期望 |
| Phase 1.1 验证 | `validate_contract_expectations.py` 输出 | {✅/❌} | 验证通过/失败 |
| Phase 2 函数签名 | `function-signatures.json` | {✅/❌} | {N} 个公开函数 |
| Phase 2 验证 | `validate_function_signatures.py` 输出 | {✅/❌} | 验证通过/失败 |
| Phase 3 测试生成 | `test_{module_id}.adversarial.py` + `{module_id}.adversarial.test.list.md` | {✅/❌} | 测试清单完整 |
| Phase 3 自检 | `detect_green_seeking.py` 输出 | {✅/❌} | toxicity_score ≤ 2 |
| Phase 4.2 Round 1 | `failure-summary-round-1.md` | {✅/❌} | {N} 个漏洞 |
| Phase 4.2 Round 2+ | `failure-summary-round-{N}.md` | {✅/❌/⏭️} | 如有后续轮次 |
| Phase 4.5.1 测试缺陷 | `test-defects-round-{N}.md` | {✅/❌/⏭️} | **判定为测试缺陷时必须有此文件** |
| Phase 4.5.2 SubAgent 修正 | SubAgent 调用记录 | {✅/❌/⏭️} | **测试缺陷必须通过 SubAgent 修正** |
| Phase 5 Round 1 | `pending-confirmations-round-1.md` | {✅/❌} | 修复说明 + 待确认事项 |
| Phase 5 Round 2+ | `pending-confirmations-round-{N}.md` | {✅/❌/⏭️} | 如有后续轮次 |
| Phase 4.4 回归检查 | 回归检查记录 | {✅/❌} | 无退化 |

**证据文件缺失的说明**：
- `test-defects-round-{N}.md` 缺失 → 该轮测试缺陷**未按 Phase 4.5.1 执行**，诚实声明第 4 条为 ❌
- `pending-confirmations-round-{N}.md` 缺失 → 该轮修复**未经过 SubAgent 待确认流程**

### 发现的漏洞与修复

#### 实现漏洞（经 Phase 5 SubAgent 修复）

1. **[输入校验缺失]** 函数 `calculate_limit` 未校验 `limit` 参数为 None 的情况
   - 修复：添加 `if limit is None: raise TypeError(...)`
   - 涉及契约：§3.2
   - 修复轮次：Round 1
   - 待确认事项：{pending-confirmations-round-1.md 中的对应条目}

2. **[边界值未处理]** 函数 `set_page_size` 未处理 `size > 100` 的情况
   - 修复：添加 `if size > 100: raise ValueError(...)`
   - 涉及契约：§3.3
   - 修复轮次：Round 1

...

#### 测试缺陷（经 Phase 3 SubAgent 修正）

> **关键区分**：测试缺陷的修正者必须是 `adversarial-test-generator` SubAgent，而非 orchestrator。

1. **[断言逻辑]** `test_A32` 使用无效 rollback_target 值
   - 修正：改为有效步骤名
   - 修正轮次：Round 2
   - 测试缺陷报告：`test-defects-round-2.md`
   - SubAgent 修正记录：{存在/缺失}

...

### 模块作用简述
{1-2 句话}

### 已知遗留
- {如有未修复项，说明原因}

### 对抗性测试位置
`.tmp/adversarial-tests/{module_id}/`
（可运行 `pytest .tmp/adversarial-tests/{module_id}/` 复现）

### 建议后续操作
- 调用 module-test-writer 生成正式验收测试
- 将已发现的漏洞模式纳入后续模块的落地规范
```

## 诚实声明（强制）

完成汇报末尾必须包含。诚实声明的每一条都必须有对应的可验证证据支撑，不能是空洞的自我声明。

```markdown
## 诚实声明

| # | 声明 | 验证方式 | 证据文件 |
|:---|:---|:---|:---|
| 1 | 实现代码严格按落地规范和项目结构设计文档编写，未参考任何对抗性测试代码。 | 代码审查 + 实现代码时间戳早于测试代码 | 实现源码文件 |
| 2 | 对抗性测试严格按接口契约生成，未读取实现源码。 | `validate_failure_summary.py` 信息隔离检查 | `failure-summary-round-*.md` |
| 3 | 失败摘要仅包含错误类型和契约条款，未向实现者暴露测试代码或具体输入值。 | `validate_failure_summary.py` 信息隔离检查 | `failure-summary-round-*.md` |
| 4 | 所有测试误报已修正并排除在修复流程之外。 | `test-defects-round-*.md` 存在 + SubAgent 修正记录 | `test-defects-round-*.md` |
| 5 | 信息隔离规则在全部迭代轮次中被遵守。 | 以上 1-4 项全部通过 | 以上全部证据 |
| 6 | orchestrator 未在 Phase 4 直接修改任何测试代码文件。 | `test-defects-round-*.md` 存在（判定为测试缺陷时必须有） | `test-defects-round-*.md` |
| 7 | 所有测试缺陷均通过 Phase 3 SubAgent 修正，非 orchestrator 直接处理。 | SubAgent 调用记录 + `test-defects-round-*.md` 存在 | `test-defects-round-*.md` |

**无法勾选？** 说明流程未完整执行。未勾选项必须在"已知遗留"中说明原因和影响。
```
