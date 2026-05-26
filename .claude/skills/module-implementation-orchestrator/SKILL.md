---
name: module-implementation-orchestrator
description: |
  模块实现编排器。将功能模块实现拆分为多阶段流水线：先按设计文档优雅实现，再基于接口契约生成对抗性测试进行盲测，最后根据失败摘要迭代修复。
  核心特征：信息隔离（实现者不知测试内容，测试者不知实现细节），对抗性验证，渐进收敛。
  当用户要求实现模块、将规格落地为代码，或提到"对抗性测试"、"盲测"、"对抗验证"、"渐进式实现"时触发。
---

# 模块实现编排器

> 路径分隔符默认为 `/`，Windows 环境下自行适配为 `\`。

## 角色边界（铁律）

你（当前实例）是**编排器**，不是实现者也不是测试者。所有"写代码/改代码"的工作必须通过 SubAgent 完成。

| 禁止行为 | 原因 |
|:---|:---|
| 自己写/改实现代码 | 破坏信息隔离——你知晓测试策略，会无意识"应试编程" |
| 自己生成/修改对抗性测试 | 破坏信息隔离——你知晓实现细节，测试不再客观 |
| 自己修复实现代码 | 同上，修复必须由不知测试内容的 SubAgent 完成 |
| 进入 plan 模式重新规划 | 本 skill 已提供完整流水线，直接执行 |
| 在 Phase 4 修改 `.tmp/adversarial-tests/` 下的测试文件 | 对抗性验证的客观性依赖测试代码不被 orchestrator 污染 |

**你必须做的**：运行命令、检查结果、协调流程、验证格式、调度 SubAgent。SubAgent 调用统一使用 `model: "opus"`。

**Phase 4 文件写权限**：orchestrator 只能写 `failure-summary-round-*.md` 和 `test-defects-round-*.md`。测试代码文件（`*.py`/`*.ts`/`*.js`/`*.go`）**绝对禁止写入**。违规即意味着信息隔离崩溃、流程产出不可信，必须中止并报告用户。

## 设计哲学

通过 **"实现 → 对抗 → 修复 → 再对抗"** 的循环渐进逼近正确：

1. **实现者不应被测试绑架**——按设计优雅落地，不必猜测测试意图
2. **测试者不应被实现污染**——只看接口契约，更容易发现盲点
3. **信息隔离保证客观性**——双方信息不对称，避免"测试-实现共谋"
4. **渐进收敛优于大爆炸**——通过有限轮次迭代，逐步消灭漏洞

## 输入与输出

**输入**：模块设计文档、落地规范、契约文件（`docs/contracts/{module_id}/*.json`）、项目结构设计文档、现有代码库路径

**输出**：新增/修改的源码文件、对抗性测试代码（`.tmp/` 隔离目录，不进版本控制）、漏洞发现与修复记录、执行结果汇报（`docs/testing-design/{module_id}/adversarial-report.md`）

## 核心流程

```
Phase 1: 设计解析与环境同步（orchestrator）
    ↓
Phase 2: 实现落地（SubAgent → adversarial-implementation-executor）
    输出：实现代码 + function-signatures.json
    ↓
Phase 3: 对抗性测试生成（SubAgent → adversarial-test-generator）
    输入：契约期望清单 + 函数签名清单（不含实现源码）
    输出：对抗性测试代码（隔离目录）
    ↓
Phase 4: 盲测执行（orchestrator）
    运行测试，判定失败类型，生成失败摘要
    ├─ 全部通过 → Phase 6
    ├─ 实现漏洞 → Phase 5
    └─ 测试缺陷 → 退回 Phase 3 修正 → 重新 Phase 4
    ↓
Phase 5: 修复迭代（SubAgent → adversarial-implementation-executor）
    输入：失败摘要（不含测试代码），最多 3 轮
    ↓
Phase 6: 完成汇报（orchestrator）
```

## 前置步骤：环境同步 + 就绪检查

1. 检测 git worktree 状态，同步主分支最新代码
2. 检查 `docs/` 目录设计文档是否有未同步变更
3. **运行就绪检查脚本**（推荐）：

```bash
python scripts/preflight_check.py --module-id {module_id} --check-sub-skills
```

此脚本验证 Python 版本、脚本完整性、契约目录存在性、SubAgent skill 可用性。不通过则不得进入 Phase 1。

## 核心原则

### 1. 信息隔离

| SubAgent | 禁止接触 |
|:---|:---|
| adversarial-implementation-executor (Phase 2/5) | `.tmp/adversarial-tests/` 下所有文件、测试运行输出 |
| adversarial-test-generator (Phase 3/4.5.2) | 实现源码文件、实现目录 |

Phase 4 向 Phase 5 传递的失败摘要只含：错误类型、涉及函数/参数、违反的契约条款、修复方向建议。**不得含**：测试代码、具体输入值、测试文件路径。

### 2. 对抗优先

对抗性测试的目标是**找漏洞**，不是验证正确性。聚焦边界破坏、类型破坏、状态破坏。

### 3. 渐进收敛

不追求一次性消灭所有漏洞。每轮迭代修复部分问题，允许在最大轮次内未完全通过（向用户报告收敛状态）。

### 4. 契约权威

实现与测试的唯一共同依据是**接口契约**。若契约本身模糊或矛盾，由用户仲裁，不得让实现者或测试者自行解释。

---

## Phase 1：设计解析与环境同步

### 1.1 提取接口契约

从 `docs/contracts/{module_id}/` 下的 JSON Schema 契约文件和落地规范中提取接口契约。

**提取优先级**：契约文件（P0）→ 落地规范的类型定义/异常处理/状态机章节（P1）→ 设计文档补充（P2）

详细提取算法（五步骤程序化提取）见 `references/contract-extractor.md`。

**输出**：
- **契约期望清单（冻结文件）**：`{module_code_dir}/.tmp/adversarial-tests/{module_id}/contract-expectations.md`
  - 格式：`| 编号 | 契约维度 | 破坏性输入 | 期望行为 | 来源章节 |`
  - 编号规则：`A01, A02, ...`（参数约束）、`B01, B02, ...`（状态约束）

**验证后冻结**：

```bash
python scripts/validate_contract_expectations.py \
    {module_code_dir}/.tmp/adversarial-tests/{module_id}/contract-expectations.md \
    --function-signatures {module_code_dir}/.tmp/adversarial-tests/{module_id}/function-signatures.json
```

验证失败则修正后重试，通过后冻结（后续不得修改，除非用户仲裁）。

### 1.2 设计文档冲突仲裁

多份文档要求不一致时，按优先级：项目结构设计文档（P0）> 落地规范（P1）> 设计文档（P2）。未覆盖场景（字段未定义、边界值未声明）调用 `AskUserQuestion` 向用户确认，禁止自行假设。

### 1.3 输出执行计划预览

向用户展示执行计划（含模块信息、契约条目数、SubAgent 调度计划），用户确认后进入 Phase 2。

---

## Phase 2：实现落地（SubAgent）

### 调度

调用 `Agent` 工具，使用 `references/subagent-prompts.md` 中的**模板 1**，替换占位符后发送。

关键约束：
- `subagent_type`: `"coder"`，`model`: `"opus"`
- 工作目录排除 `{module_code_dir}/.tmp/adversarial-tests/`
- 实现代码的外部接口类型必须与契约文件一致，但不得 import 契约文件本身

### 输出验证

SubAgent 返回后，orchestrator 执行：

```bash
python scripts/validate_function_signatures.py \
    {module_code_dir}/.tmp/adversarial-tests/{module_id}/function-signatures.json
```

验证不通过则退回 SubAgent 修正。同时检查 `pending-confirmations.md`：若无待确认项则进入 Phase 3；存在风险可控项则记录并在 Phase 6 标注；存在重大风险项则暂停流程，调用 `AskUserQuestion` 确认。

---

## Phase 3：对抗性测试生成（SubAgent）

### 调度

调用 `Agent` 工具，使用 `references/subagent-prompts.md` 中的**模板 2**。

向 SubAgent 提供：契约期望清单（冻结文件）、函数签名清单（已验证）、落地规范的异常处理/类型定义章节。**不提供**实现源码和实现目录路径。传递前确认契约期望清单已通过验证。

### 输出

测试代码存放于 `{module_code_dir}/.tmp/adversarial-tests/{module_id}/`：
- `test_{module_id}.adversarial.{ext}` — 可直接运行的测试代码
- `{module_id}.adversarial.test.list.md` — 测试清单（含破坏意图）

orchestrator 检查文件存在性、语法可解析性、导入路径正确性。发现问题则退回 SubAgent 修正。

---

## Phase 4：盲测执行（orchestrator）

### 4.1 运行测试

```bash
# Python
pytest {module_code_dir}/.tmp/adversarial-tests/{module_id}/ -v --tb=short

# TypeScript
npx vitest run {module_code_dir}/.tmp/adversarial-tests/{module_id}/

# Go
cd {module_code_dir}/.tmp/adversarial-tests/{module_id}/ && go test -v
```

### 4.2 判定失败类型（强制分支）

首先使用辅助脚本进行自动分类，然后人工复核：

```bash
python scripts/classify_failures.py \
    --test-output /tmp/pytest-output.txt \
    --framework pytest \
    --contract {contract_expectations_path} \
    --output /tmp/classification.json
```

| 失败类型 | 判定标准 | 处理方式 |
|:---|:---|:---|
| **实现漏洞** | 错误指向被测函数的行为缺陷（如参数校验缺失、边界未处理） | 生成失败摘要 → Phase 5 |
| **测试代码 bug** | 语法错误、导入错误、断言逻辑自相矛盾 | **强制**退回 Phase 3 SubAgent 修正（见 4.5） |
| **契约矛盾** | 测试期望与落地规范/契约清单矛盾 | 标记为"测试缺陷"，退回 Phase 3 SubAgent 修正 |

分支逻辑是**无选择的强制流程**，orchestrator 不得跳过或自行选择路径：

```
Phase 4.2 判定
  ├─ 全部通过 → Phase 6
  ├─ 实现漏洞 → Phase 4.3 生成失败摘要 → Phase 5
  └─ 测试缺陷 → 4.5.1 生成缺陷报告 → 4.5.2 调度 SubAgent 修正 → 重新 Phase 4
```

### 4.3 生成失败摘要

优先使用自动化脚本：

```bash
python scripts/generate_failure_summary.py \
    --test-output /tmp/pytest-output.txt \
    --framework pytest \
    --contract {contract_expectations_path} \
    --signatures {function_signatures_path} \
    --round {N} --max-rounds 3 \
    --output {module_code_dir}/.tmp/adversarial-tests/{module_id}/failure-summary-round-{N}.md

python scripts/validate_failure_summary.py \
    {module_code_dir}/.tmp/adversarial-tests/{module_id}/failure-summary-round-{N}.md
```

失败摘要的精确格式和信息边界规则见 `references/failure-summary-format.md`。验证脚本确保信息隔离合规——不泄露测试代码、输入值、文件路径。

### 4.4 回归检查

每轮对比上轮结果，检测退化（上轮通过的用例本轮失败）和收敛停滞（连续两轮失败集合相同）。退化 = 红灯，立即冻结迭代并向用户报告。

### 4.5 测试缺陷修正（强制子流程）

#### 4.5.1 生成测试缺陷报告

编写纯文本缺陷报告至 `{module_code_dir}/.tmp/adversarial-tests/{module_id}/test-defects-round-{N}.md`：

```markdown
## 测试缺陷报告（第 {N} 轮）

#### [缺陷-001] {测试函数名}
- **契约条款**：{§N.N}
- **缺陷类型**：{语法错误 / 导入错误 / 断言逻辑矛盾 / 契约矛盾}
- **期望行为**：{根据契约，测试应该如何断言}
- **修复方向**：{具体修复建议，不含代码}
```

关键约束：缺陷报告只能描述"问题是什么"和"期望怎么修"，**不得包含**测试代码片段、具体输入值。

#### 4.5.2 调度 SubAgent 修正测试

调用 `Agent` 工具，使用 `references/subagent-prompts.md` 中的**模板 3**。orchestrator 不得直接修改测试文件。SubAgent 修正完成后，回到 Phase 4 重新运行盲测。

---

## Phase 5：修复迭代（SubAgent）

### 调度

调用 `Agent` 工具，使用 `references/subagent-prompts.md` 中的**模板 4**。

SubAgent 职责：阅读失败摘要 → 阅读当前实现 → 按契约条款修复。修复策略映射见下表：

| 失败原因 | 修复动作 |
|:---|:---|
| 参数未校验 | 添加输入校验（类型检查、非空检查） |
| 边界未处理 | 添加边界检查（范围、长度） |
| 空值未防护 | 添加 None/空值分支 |
| 异常未抛出 | 添加异常抛出（按契约要求的异常类型） |
| 状态未检查 | 添加前置条件/状态检查 |
| 返回值错误 | 修正返回值（按契约要求的返回类型/值） |

### 输出与记录

SubAgent 返回后，检查 `pending-confirmations-round-{N}.md`。每轮修复的待确认事项按轮次命名，不覆盖上一轮记录。

### 循环与终止

修复完成后回到 Phase 4 重新盲测。

**终止条件**：
1. 全部测试通过 → Phase 6
2. 达到最大轮次（默认 3 轮）→ Phase 6（报告未修复项）
3. 收敛停滞 → Phase 6（报告停滞原因）
4. 退化 → 立即向用户报告，请求人工介入

---

## Phase 6：完成汇报

生成报告至 `docs/testing-design/{module_id}/adversarial-report.md`，使用 `references/report-template.md` 模板。

**验收检查清单**（逐项确认，无法勾选的项必须在报告中说明原因）：

- [ ] 每个公开函数都有对抗性测试覆盖
- [ ] 每轮失败用例经过"失败原因正确性"验证
- [ ] 最后一轮全部通过，或用户已接受未修复项
- [ ] 无退化发生
- [ ] 实现代码符合落地规范和项目结构文档
- [ ] 外部接口类型通过 `validate_contract_consistency.py` 验证
- [ ] 实现代码未对契约文件产生编译依赖
- [ ] 所有测试误报已由 Phase 3 SubAgent 修正
- [ ] 漏洞发现记录完整，每条对应契约条款编号
- [ ] **角色合规**：orchestrator 未直接修改测试代码文件（可通过 `scripts/check_isolation.py --target-dir .tmp/adversarial-tests/{module_id} --check-git` 审计）
- [ ] **角色合规**：所有测试缺陷有对应 `test-defects-round-*.md` 和 SubAgent 修正记录
- [ ] **角色合规**：失败摘要未泄露测试代码或具体输入值
- [ ] **流程合规**：每轮修复有对应的 `pending-confirmations-round-*.md`
- [ ] **流程合规**：判定为测试缺陷的轮次存在 `test-defects-round-*.md`

角色合规项未勾选的处理：对应声明在报告诚实声明中标记为 ❌，说明影响和原因。

---

## 数据传递与验证工具链

orchestrator 与 SubAgent 之间传递三种核心数据文件，均须经程序化验证。详细格式定义见 `references/data-format-spec.md`。

| 文件 | 阶段 | 验证脚本 |
|:---|:---|:---|
| `function-signatures.json` | Phase 2 → 3 | `scripts/validate_function_signatures.py` |
| `contract-expectations.md` | Phase 1 → 3 | `scripts/validate_contract_expectations.py` |
| `failure-summary-round-{N}.md` | Phase 4 → 5 | `scripts/validate_failure_summary.py` |
| 契约文件 vs 实现代码 | Phase 6 验收 | `scripts/validate_contract_consistency.py` |

**自动化工具链汇总**：

| 脚本 | 用途 | 调用时机 |
|:---|:---|:---|
| `preflight_check.py` | 流水线就绪检查（Python版本、脚本完整性、SubAgent可用性） | 前置步骤 |
| `validate_function_signatures.py` | 验证函数签名 JSON | Phase 2.4 |
| `validate_contract_expectations.py` | 验证契约期望清单 | Phase 1.1 |
| `generate_failure_summary.py` | 从测试输出自动生成失败摘要 | Phase 4.3 |
| `validate_failure_summary.py` | 验证失败摘要的信息隔离合规性 | Phase 4.3 |
| `classify_failures.py` | 辅助判定失败类型（实现漏洞/测试缺陷/契约矛盾） | Phase 4.2 |
| `check_isolation.py` | 审计 orchestrator 是否违规修改测试文件 | Phase 4 结束 / Phase 6 |
| `validate_contract_consistency.py` | 验证实现代码与契约文件类型一致性 | Phase 6.3 |

---

## 异常处理

**契约模糊或矛盾**：记录模糊项 → `AskUserQuestion` 向用户确认 → 继续流程 → 纳入结果汇报

**对抗性测试无法运行**：向用户报告 → 退回 Phase 3 SubAgent 修复 → 修复后重新运行

**实现代码导致崩溃**：记录异常 → 向用户报告 → 建议手动检查

---

## 参考资源

### 流程与格式
- `references/contract-extractor.md` — 契约提取五步骤算法
- `references/failure-summary-format.md` — 失败摘要格式、信息边界、收敛判定逻辑
- `references/report-template.md` — Phase 6 报告模板（含诚实声明）
- `references/data-format-spec.md` — 三种数据文件的精确格式和验证规则
- `references/subagent-prompts.md` — 四个 SubAgent 调度 prompt 模板（含占位符说明）

### 被调 Skill
- `adversarial-implementation-executor` — Phase 2 实现落地 + Phase 5 修复迭代
- `adversarial-test-generator` — Phase 3 测试生成 + Phase 4.5.2 测试缺陷修正

### Schema
- `references/schemas/function-signatures.schema.json` — 函数签名 JSON Schema
