# SubAgent 调度 Prompt 模板

本文件定义 orchestrator 调用各 SubAgent 时的标准 prompt 模板。
每个模板使用 `{placeholder}` 标记变量部分，orchestrator 在调度时替换。

---

## 模板 1：Phase 2 实现落地

**目标 Skill**: `adversarial-implementation-executor`
**SubAgent 类型**: `coder`
**模型**: `haiku`

```
【你被 module-implementation-orchestrator 调度执行 adversarial-implementation-executor skill】
任务：按设计文档优雅实现模块。
设计文档路径：{design_doc_path}
落地规范路径：{spec_path}
项目结构文档路径：{structure_doc_path}
模块代码目录：{module_code_dir}
契约文件目录：docs/contracts/{module_id}/
输出要求：实现代码 + 函数签名清单（JSON）

**绝对约束**：
- 不运行任何测试
- 绝对禁止读取 `{module_code_dir}/.tmp/adversarial-tests/` 目录下的任何文件
- 绝对禁止搜索、查看、分析任何测试相关文件
- 你只能看到设计文档和现有代码，测试对你完全不可见

**契约约束**：
- 对外接口的类型定义必须与 `docs/contracts/{module_id}/` 下的 JSON Schema 契约一致
- 实现代码不得 import 或依赖契约文件本身（契约文件在 docs/ 下，不是代码依赖）
- 实现代码自己定义 Pydantic 模型，但字段、类型、必填性必须与契约一致

**提交前契约自检清单**（请在提交实现前逐项确认）：
- [ ] 本模块所有对外接口的 Pydantic 模型字段名、类型、必填性与 `docs/contracts/{module_id}/` 下的契约 JSON 一致
- [ ] 未在代码中引入契约文件未声明的新字段
- [ ] 若发现实现需要偏离契约，已在 `pending-confirmations.md` 中记录待确认项

**工作目录约束**：排除 `{module_code_dir}/.tmp/adversarial-tests/` 目录
```

---

## 模板 2：Phase 3 对抗性测试生成

**目标 Skill**: `adversarial-test-generator`
**SubAgent 类型**: `coder`
**模型**: `haiku`

```
【你被 module-implementation-orchestrator 调度执行 adversarial-test-generator skill】
任务：基于接口契约生成对抗性测试代码。
契约期望清单路径：{contract_expectations_path}
函数签名清单路径：{function_signatures_path}
落地规范路径：{spec_path}
技术栈：{tech_stack}
输出目录：{output_dir}

**绝对约束**：
- 绝对禁止读取实现源码
- 绝对禁止查看被测模块的实现目录
- 绝对禁止搜索、分析任何实现相关文件
- 你只拥有接口契约（函数签名、类型定义、异常条件），实现对你是完全黑盒

**工作目录约束**：排除实现源码目录，仅提供契约文档
```

---

## 模板 3：Phase 4.5.2 测试缺陷修正

**目标 Skill**: `adversarial-test-generator`
**SubAgent 类型**: `coder`
**模型**: `haiku`

```
【你被 module-implementation-orchestrator 调度执行 adversarial-test-generator skill】
任务：修正对抗性测试代码中的缺陷。
当前测试代码路径：{test_file_path}
测试缺陷报告路径：{defects_report_path}
契约期望清单路径：{contract_expectations_path}
函数签名清单路径：{function_signatures_path}
输出要求：修正后的测试代码（覆盖原文件）

**绝对约束**：
- 修正后的测试代码必须通过 `scripts/detect_green_seeking.py` 扫描（toxicity_score <= 2）
- 修正后重新运行测试，确保测试本身可运行

**SubAgent 职责**：
1. 阅读测试缺陷报告，理解每个缺陷的修复方向
2. 阅读当前测试代码，定位缺陷位置
3. 修正测试代码（修复语法错误、修正断言逻辑、移除与契约矛盾的测试）
4. 运行 `scripts/detect_green_seeking.py` 自检，不通过则继续修正
5. 运行测试确保测试本身可运行

**orchestrator 不得**：
- 自己修改测试代码文件
- 向 SubAgent 传递测试代码内容（只传递文件路径）
```

---

## 模板 4：Phase 5 修复迭代

**目标 Skill**: `adversarial-implementation-executor`
**SubAgent 类型**: `coder`
**模型**: `haiku`

```
【你被 module-implementation-orchestrator 调度执行 adversarial-implementation-executor skill】
任务：根据盲测失败摘要修复实现代码。
失败摘要路径：{failure_summary_path}
当前实现代码路径：{implementation_path}
落地规范路径：{spec_path}
模块代码目录：{module_code_dir}
契约文件目录：docs/contracts/{module_id}/
输出要求：修改后的实现代码 + 修改说明（引用 case ID）

**绝对约束**：
- 不查看任何测试代码
- 绝对禁止读取 `{module_code_dir}/.tmp/adversarial-tests/` 目录下的任何文件
- 绝对禁止搜索、查看、分析任何测试相关文件
- 你只能看到失败摘要中提供的信息，测试细节对你完全不可见

**契约约束**：
- 修复后的对外接口类型必须与契约文件一致
- 不得引入契约文件中未声明的新字段

**提交前契约自检清单**：
- [ ] 修复后的 Pydantic 模型字段名、类型、必填性与 `docs/contracts/{module_id}/` 下的契约 JSON 一致
- [ ] 未在修复中引入契约文件未声明的新字段

**工作目录约束**：排除 `{module_code_dir}/.tmp/adversarial-tests/` 目录
```

---

## 通用约束速查

所有 SubAgent 调度共享以下参数：

| 参数 | 值 |
|:---|:---|
| `subagent_type` | `"coder"` |
| `model` | `"haiku"` |

信息隔离方向：

| SubAgent | 禁止读取 |
|:---|:---|
| adversarial-implementation-executor (Phase 2/5) | `.tmp/adversarial-tests/` 下所有文件 |
| adversarial-test-generator (Phase 3/4.5.2) | 实现源码目录下所有文件 |
