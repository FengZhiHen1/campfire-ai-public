# 失败摘要格式规范

本文档定义 Phase 4（盲测执行）向 Phase 5（修复迭代）传递的信息格式。

**orchestrator 应优先使用 `scripts/generate_failure_summary.py` 自动生成，仅在脚本无法解析时手动补充。**

---

## 核心原则

**信息隔离**：修复者只能看到"问题摘要"，不能看到完整的测试代码、具体的输入值（除非必要）、测试的组织结构。

目标：给实现者**足够信息定位问题**，但不暴露**测试细节**（避免实现者针对性地"作弊通过"）。

---

## 自动生成流程

orchestrator Phase 4 应按以下算法生成失败摘要：

### 算法：generate_failure_summary

```
输入:
    test_output: 测试框架原始输出文本
    framework: {pytest, jest, go}
    contract_expectations: 契约期望清单路径
    function_signatures: 函数签名清单路径
    round: 当前轮次编号
    max_rounds: 最大轮次

输出:
    failure-summary-round-{round}.md

步骤:
    1. 加载 function_signatures.json，提取所有函数名和参数名
    2. 加载 contract-expectations.md，建立 (函数名, 参数名) → 契约条款 的映射
    3. 根据 framework 选择解析器:
        - pytest: 解析 FAILED test_module.py::test_name 块
        - jest:   解析 ● test_name 块
        - go:     解析 --- FAIL: TestName 块
    4. 对每个失败块:
        a. 提取错误类型（TypeError, ValueError, AssertionError, ...）
        b. 提取错误消息（截断至 200 字符）
        c. 推断涉及函数（按函数名在块中匹配，优先取 traceback 中的被测函数）
        d. 推断涉及参数（按参数名在错误消息/代码行中匹配）
        e. 匹配契约条款（按函数名+参数名查询映射表）
        f. 生成修复建议（基于错误类型的规则映射）
    5. 按 (错误类型, 涉及函数, 涉及参数) 去重
    6. 分配 case ID: case-001, case-002, ...
    7. 生成分类统计表
    8. 生成修复优先级建议（按影响用例数排序）
    9. 输出 Markdown 文件
    10. 运行 validate_failure_summary.py 验证信息隔离合规性
```

### 命令

```bash
python scripts/generate_failure_summary.py \
    --test-output /tmp/pytest-output.txt \
    --framework pytest \
    --contract contract-expectations.md \
    --signatures function-signatures.json \
    --round 1 \
    --max-rounds 3 \
    --output failure-summary-round-1.md

# 验证
python scripts/validate_failure_summary.py failure-summary-round-1.md
```

---

## 失败摘要格式

```markdown
## 盲测失败摘要（第 {N} 轮）

- **测试轮次**：{N} / {max_rounds}
- **总用例数**：{total}
- **通过数**：{passed}
- **失败数**：{failed}
- **收敛状态**：{improving / stalled / regressed}

---

### 失败用例摘要

#### [case-{id}] {错误类型}: {一句话描述}
- **涉及函数**：`{函数名}`
- **涉及参数**：`{参数名}`（类型：{期望类型}）
- **契约条款**：{条款编号} — "{条款原文摘要}"
- **失败原因**：{一句话说明违反了什么契约}
- **修复建议**：{可选，如"添加参数校验"、"处理 None 值"}

#### [case-{id}] {错误类型}: {一句话描述}
...

---

### 分类统计

| 错误类型 | 数量 | 涉及函数 |
|:---|:---|:---|
| TypeError | N | func_a, func_b |
| ValueError | M | func_a |
| AssertionError | K | func_c |
| ... | ... | ... |

### 涉及的契约条款

| 条款编号 | 条款内容 | 失败次数 |
|:---|:---|:---|
| §3.2 | 输入校验 | 5 |
| §4.1 | 空值处理 | 2 |
| ... | ... | ... |

### 修复方向建议

基于本轮失败分析，建议按以下优先级修复：

1. **{高优先级}** — {问题描述}（影响 {N} 个用例）
2. **{中优先级}** — {问题描述}（影响 {M} 个用例）
3. **{低优先级}** — {问题描述}（影响 {K} 个用例）
```

---

## 信息边界

### 修复者可以看到

| 信息 | 示例 |
|:---|:---|
| 错误类型 | `TypeError`, `ValueError`, `AssertionError` |
| 涉及的函数名 | `func_name` |
| 涉及的参数名 | `param_a` |
| 参数期望类型 | `int (≥1)` |
| 违反的契约条款 | `§3.2 — 输入校验` |
| 失败原因一句话 | "参数收到 None，但契约要求 int" |
| 修复建议 | "添加参数非空校验" |
| 分类统计 | 哪类错误最多、涉及哪些函数 |

### 修复者不可以看到

| 信息 | 原因 |
|:---|:---|
| 完整测试代码 | 避免针对性作弊 |
| 具体的输入值 | 避免实现者写死特定输入的处理 |
| 测试文件路径 | 避免实现者直接读取测试 |
| 测试用例的组织结构 | 避免实现者推断测试策略 |
| 其他测试的通过情况 | 避免信息过载 |
| 断言的具体内容 | 避免实现者反向推导测试逻辑 |

---

## 具体用例的摘要示例

### 示例 1：类型校验缺失

```markdown
#### [case-001] TypeError: 参数收到非期望类型
- **涉及函数**：`calculate_limit`
- **涉及参数**：`limit`（类型：int）
- **契约条款**：§3.2 — "limit 为必填参数，类型 int"
- **失败原因**：参数收到 `None`，但函数未进行类型校验直接参与运算
- **修复建议**：在函数入口处添加参数非空和类型校验
```

### 示例 2：边界值未处理

```markdown
#### [case-042] ValueError: 参数超出允许范围
- **涉及函数**：`set_page_size`
- **涉及参数**：`size`（类型：int，范围：1-100）
- **契约条款**：§3.3 — "size 范围 [1, 100]"
- **失败原因**：参数超出上限边界，函数未抛出预期异常
- **修复建议**：添加范围校验，超出时抛出 ValueError
```

### 示例 3：空值处理缺失

```markdown
#### [case-103] AssertionError: 空输入返回非预期结果
- **涉及函数**：`process_items`
- **涉及参数**：`items`（类型：List[Item]）
- **契约条款**：§4.1 — "空数组输入应返回空结果"
- **失败原因**：空数组输入时返回了 `None`，契约要求返回空数组 `[]`
- **修复建议**：处理空数组情况，返回空结果而非 None
```

### 示例 4：状态管理缺失

```markdown
#### [case-207] RuntimeError: 非法状态转换未拦截
- **涉及函数**：`approve_order`
- **涉及参数**：`order_id`（类型：str）
- **契约条款**：§5.2 — "已取消订单不可审批"
- **失败原因**：对已处于 CANCELLED 状态的订单调用 approve，未抛出异常
- **修复建议**：在操作前检查当前状态，非法状态时抛出 RuntimeError
```

---

## 收敛状态判定

收敛状态由 orchestrator 根据连续轮次的结果自动判定：

### improving（改善中）
- 本轮失败数 < 上轮失败数
- 或有新的失败用例上轮通过（发现新漏洞也是改善）

### stalled（停滞）
- 连续两轮失败用例集合完全相同
- 或无改善也无新增失败（陷入循环）

### regressed（退化）
- 上轮通过的用例本轮失败
- 或失败数增加且无新增通过

**判定算法**：

```
function determine_convergence(current_failures, previous_failures):
    if previous_failures is None:
        return "improving"  // 首轮默认为改善

    if current_failures == previous_failures:
        return "stalled"

    if len(current_failures) > len(previous_failures):
        // 检查是否有上轮通过的用例本轮失败
        previously_passed = all_cases - previous_failures
        if any(case in current_failures for case in previously_passed):
            return "regressed"

    if len(current_failures) < len(previous_failures):
        return "improving"

    // 失败数相同但内容不同 = 发现新漏洞同时修复了旧漏洞
    return "improving"
```

---

## 修复建议生成规则

`scripts/generate_failure_summary.py` 按以下规则自动生成修复建议：

| 错误类型 | 自动生成模板 |
|:---|:---|
| TypeError | 在 `{函数名}` 入口处添加参数的类型校验和非空校验 |
| ValueError | 在 `{函数名}` 入口处添加参数的值域/格式校验 |
| AssertionError | 检查 `{函数名}` 的返回值是否符合契约要求 |
| IndexError / KeyError | 在 `{函数名}` 中添加容器访问前的边界/存在性校验 |
| TimeoutError / timeout | 检查 `{函数名}` 中的外部调用是否设置了超时和重试机制 |
| RuntimeError | 检查 `{函数名}` 中的状态校验逻辑是否完整 |
| Panic | 在 `{函数名}` 中添加 defer/recover 或前置条件校验 |
| 其他 | 检查 `{函数名}` 的实现，根据契约条款修复异常处理或返回值 |

---

## 验证检查清单

生成失败摘要后，必须运行 `scripts/validate_failure_summary.py` 确认：

- [ ] 包含四个标准章节
- [ ] 无多行代码块泄露
- [ ] 无测试文件路径暴露
- [ ] 无 `.tmp/adversarial-tests/` 路径暴露
- [ ] 无 pytest/jest 原始输出痕迹
- [ ] 每个 case 有涉及函数、契约条款、失败原因、修复建议
- [ ] case ID 连续
- [ ] 修复建议长度 ≥10 字符，不含模糊词
- [ ] 修复建议未泄露具体输入值
- [ ] 修复建议未暗示修复者查看测试
