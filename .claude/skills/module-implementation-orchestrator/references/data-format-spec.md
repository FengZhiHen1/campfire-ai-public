# 数据传递格式规范

本文件定义 orchestrator 与各 SubAgent 之间传递数据的精确格式。

所有中间产物必须经过**程序化验证**后方可进入下一阶段。验证脚本位于 `scripts/` 目录，orchestrator 应在每个阶段的输出节点自动调用。

---

## 验证工具索引

| 产物 | 验证脚本 | 用途 |
|:---|:---|:---|
| `function-signatures.json` | `scripts/validate_function_signatures.py` | 结构 + 业务规则验证 |
| `contract-expectations.md` | `scripts/validate_contract_expectations.py` | 表格结构 + 完整性验证 |
| `failure-summary-round-N.md` | `scripts/validate_failure_summary.py` | 格式 + 信息隔离验证 |

---

## function-signatures.json

由 Phase 2 的 adversarial-implementation-executor 生成，供 Phase 3 的 adversarial-test-generator 使用。

**JSON Schema**: `references/schemas/function-signatures.schema.json`

### 格式

```json
{
  "module_id": "M01",
  "module_name": "用户认证模块",
  "functions": [
    {
      "name": "authenticate_user",
      "signature": "def authenticate_user(username: str, password: str) -> AuthResult",
      "parameters": [
        {"name": "username", "type": "str", "required": true, "constraints": ["non-empty"], "bounds": {"min": 1, "max": 100}},
        {"name": "password", "type": "str", "required": true, "constraints": ["non-empty"]}
      ],
      "return_type": "AuthResult",
      "exceptions": [
        {"type": "ValueError", "trigger": "username is empty", "contract_reference": "§3.2"}
      ],
      "preconditions": ["模块已初始化"],
      "side_effects": ["记录审计日志"]
    }
  ]
}
```

### 验证命令

```bash
python scripts/validate_function_signatures.py \
    {module_code_dir}/.tmp/adversarial-tests/{module_id}/function-signatures.json
```

### 验证规则摘要

1. `module_id` 必须符合 `[A-Z]\d{2}` 模式
2. `functions` 数组非空，每项必须有 `name`、`signature`、`parameters`、`return_type`
3. 函数名唯一，参数名在函数内唯一
4. 每个参数必须出现在 `signature` 字符串中
5. `required=false` 时必须提供 `default` 字段
6. 必填参数建议有 `constraints` 或 `bounds`（否则对抗性测试无从生成输入）
7. 异常必须有 `contract_reference`（§N.N 格式）或 `trigger`

---

## contract-expectations.md（冻结文件）

由 orchestrator Phase 1 生成，供 Phase 3 的 adversarial-test-generator 使用。

**本文件为冻结状态，生成后不得修改。** 如需变更，必须经用户确认后重新生成。

### 格式

```markdown
# {模块名} 契约期望清单
> 来源：{落地规范文件名}
> 冻结时间：{YYYY-MM-DD HH:MM:SS}

| 编号 | 契约维度 | 破坏性输入 | 期望行为 | 来源章节 |
|:---|:---|:---|:---|:---|
| A01 | username 空值 | "" | 抛出 ValueError | §3.2 |
| A02 | username 类型 | None | 抛出 TypeError | §3.2 |
```

### 验证命令

```bash
python scripts/validate_contract_expectations.py \
    {module_code_dir}/.tmp/adversarial-tests/{module_id}/contract-expectations.md \
    --function-signatures {module_code_dir}/.tmp/adversarial-tests/{module_id}/function-signatures.json
```

### 验证规则摘要

1. 文件头部必须有来源和冻结时间标注
2. 表格必须包含五列：编号、契约维度、破坏性输入、期望行为、来源章节
3. 编号格式 `[A-Z]\d{2,3}`，全局唯一
4. 破坏性输入不能为空，长度 ≥3
5. 期望行为必须明确结果形式（包含"抛出"/"返回"/raise/return 等关键词）
6. 来源章节必须符合 `§N.N` 格式
7. **完整性检查**：每个公开函数在契约维度中至少出现一次

---

## failure-summary-round-N.md

由 orchestrator Phase 4 生成，供 Phase 5 的 adversarial-implementation-executor 使用。

### 自动生成（推荐）

orchestrator 应优先使用自动化脚本生成，而非手工编写：

```bash
python scripts/generate_failure_summary.py \
    --test-output /tmp/pytest-output.txt \
    --framework pytest \
    --contract {module_code_dir}/.tmp/adversarial-tests/{module_id}/contract-expectations.md \
    --signatures {module_code_dir}/.tmp/adversarial-tests/{module_id}/function-signatures.json \
    --round 1 \
    --max-rounds 3 \
    --output {module_code_dir}/.tmp/adversarial-tests/{module_id}/failure-summary-round-1.md
```

### 格式

```markdown
## 盲测失败摘要（第 {N} 轮）

- **测试轮次**：{N} / {max_rounds}
- **总用例数**：{total}
- **通过数**：{passed}
- **失败数**：{failed}

---

### 失败用例摘要

#### [case-001] TypeError: 参数收到非期望类型
- **涉及函数**：`calculate_limit`
- **涉及参数**：`limit`（类型：int (≥1)）
- **契约条款**：§3.2 — "limit 为必填参数，类型 int"
- **失败原因**：参数收到 None，但函数未进行类型校验直接参与运算
- **修复建议**：在函数入口处添加参数非空和类型校验

### 分类统计
| 错误类型 | 数量 | 涉及函数 |
|:---|:---|:---|
| TypeError | 3 | calculate_limit, validate_input |

### 涉及的契约条款
| 条款编号 | 失败次数 |
|:---|:---|
| §3.2 | 5 |

### 修复方向建议
1. **高优先级** — 添加参数非空和类型校验（影响 5 个用例）
```

### 验证命令

```bash
python scripts/validate_failure_summary.py \
    {module_code_dir}/.tmp/adversarial-tests/{module_id}/failure-summary-round-{N}.md
```

### 验证规则摘要

1. 必须包含四个标准章节：失败用例摘要、分类统计、涉及的契约条款、修复方向建议
2. **信息隔离检查**：
   - 不得包含多行代码块（>3 行的 ``` 包裹内容）
   - 不得引用测试文件路径（`test_*.py`、`.test.ts`、`*_test.go`）
   - 不得暴露 `.tmp/adversarial-tests/` 目录路径
   - 不得包含 pytest/jest 原始输出痕迹
3. 每个 case 必须有：涉及函数、契约条款、失败原因、修复建议
4. case ID 必须连续（case-001, case-002, ...）
5. 修复建议长度 ≥10 字符，不得包含模糊词（"检查"、"看看"、"可能"）
6. 修复建议不得泄露具体输入值，不得暗示修复者查看测试代码
