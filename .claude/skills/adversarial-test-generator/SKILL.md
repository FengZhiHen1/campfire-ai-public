---
name: adversarial-test-generator
description: |
  在不知道实现细节的前提下，仅基于接口契约（函数签名、类型定义、异常条件、边界定义）生成对抗性测试代码。
  目标是找出实现漏洞，而非验证正确行为。测试者不得接触实现源码，仅依据契约中的接口声明编写测试。
  由 module-implementation-orchestrator 调度使用。
---

# 对抗性测试生成器

## 核心原则

> **角色：你是一位专门出"陷阱题"的出题老师。**
>
> 你面前有一份课程大纲（接口契约）。你的任务不是出"送分题"验证实现正确，
> 而是出"陷阱题"找出实现没注意到的知识盲区。

1. **信息隔离（铁律）**：绝对禁止读取实现源码。不要查看、不要搜索、不要分析被测模块的实现文件。工作目录中不应包含被测模块的实现文件。
2. **契约驱动**：唯一输入是接口契约——函数签名、输入/输出类型、异常条件、前置条件、状态约束。
3. **破坏优先**：测试目标不是"验证正确"，而是"找出漏洞"。
4. **最小假设**：不对实现的内部逻辑做任何假设。只根据契约中明确声明的行为编写测试。
5. **无 Mock（修订版）**：测试代码不得使用 mock **替代被测函数本身**。
   - ❌ 禁止：mock 被测函数的内部逻辑、返回值或副作用
   - ✅ 允许：mock **外部依赖**（HTTP 客户端、数据库连接、第三方 API），但必须在测试注释中标注 `# external-dep-mock: {服务名}`
   - ✅ 允许：使用 `pytest.Monkeypatch` 修改环境变量/配置
   
   **Mock 白名单审查**：输出前自检时，扫描所有 `Mock`、`patch`、`AsyncMock` 使用点，若其 target 包含被测模块自身的函数/类，判定为 **G10（被测函数 Mock）错误，阻断输出**。
6. **零跳过（Zero Skip）**：对抗性测试中禁止任何形式的跳过机制。
   - 禁止 `pytest.skip`、`unittest.skip`、`pytest.xfail`、`@pytest.mark.skip`、`@pytest.mark.skipif`
   - 禁止条件分支绕过测试逻辑（如 `if not available: return/pass`）
   - 禁止因"模块可能不存在"而做的防御性导入包裹（如 `try/except ImportError` 后设标志位，再在测试里 `if not FLAG: skip`）
   - 如果某条契约因外部依赖（数据库、API 服务）无法在当前环境验证，测试代码仍应**完整编写并直接导入**，让导入/连接异常自然抛出，由 orchestrator 在 Phase 4 中分类记录为 `IMPORT_ERROR` 或 `EXTERNAL_DEPENDENCY`，而非由测试代码自行跳过

## 输入

- **函数签名清单**：模块暴露的所有公开函数/方法，含参数名、类型、返回值类型
- **类型契约**：Pydantic model / TypeScript interface / Go struct / Zod schema / 等类型定义
- **异常条件**：落地规范中定义的异常触发条件（如"参数 x 为负数时抛 ValueError"）
- **前置条件**：函数调用前必须满足的状态/条件
- **边界定义**：落地规范中明确的数值边界、长度限制、格式约束等
- **技术栈**：项目使用的测试框架（pytest / jest / vitest / Go testing 等）

## 输出

- 对抗性测试代码文件（存放到 orchestrator 指定的隔离目录）
- 测试清单 Markdown（每个测试的破坏意图说明）

## 对抗策略

> 详细的五类破坏策略示例、特殊值矩阵和技术栈适配代码见 `references/adversarial-strategies.md`。以下为核心策略摘要。

### 1. 边界值破坏
- 数值：最小值-1、最大值+1、0（当最小值为正时）
- 字符串：空字符串 `""`、仅空白 `"   "`、恰好长度限制、长度+1、超长（>10KB）
- 数组/列表：空数组 `[]`、单元素、恰好长度限制、长度+1、超大数组
- 对象：空对象 `{}`、缺少必填字段、多余字段

### 2. 类型破坏
- `None` / `null` / `undefined` 注入每个参数（无论是否可选）
- 错误类型替换（字符串传 int、数组传对象、布尔传字符串）
- 特殊数值：`NaN`、`Infinity`、`-Infinity`、极大/极小浮点数
- 特殊字符串：`\x00`、Unicode 控制字符、emoji、RTL 文本、零宽字符
- 非规范编码：UTF-8 无效序列（如适用）

### 3. 状态破坏
- 前置条件未满足时调用函数
- 非法状态转换序列
- 重复调用同一操作（幂等性破坏）
- 并发/重入场景（如适用技术栈）

### 4. 资源破坏
- 超大输入（大数据量、深度嵌套 JSON）
- 循环引用（对象自我引用）
- 极端比例数据（100万条记录的列表）

### 5. 时序破坏
- 快速连续调用
- 乱序调用（违反操作顺序）
- 超时/延迟注入（如适用）

## 工作流程

### 步骤 1：解析契约

从输入的函数签名清单和类型契约中，提取每个函数的：
- 参数列表及类型
- 返回值类型
- 显式声明的异常条件（触发条件 + 异常类型）
- 前置条件
- 边界约束（数值范围、长度限制、格式正则）

**输入来源优先级**：
1. 落地规范的「输入/输出类型定义」章节
2. 落地规范的「异常处理」章节
3. 落地规范的「状态机」章节（提取状态约束）
4. 设计文档的「接口契约」章节

### 步骤 2：生成对抗性测试

对每个函数，按以下优先级生成测试：

**优先级 P0：契约明确禁止的输入**
- 若契约声明"参数 x 不能为负数"，则测试 x = -1, x = -999999
- 若契约声明"字符串不能为空"，则测试 `""`、`"   "`
- 若契约声明"数组长度不超过 N"，则测试长度 N+1 的数组

**优先级 P1：边界值**
- 数值边界：min-1, min, max, max+1
- 长度边界：0, 1, max_length, max_length+1
- 时间边界：epoch, far_future
- 精度边界：浮点数精度极限

**优先级 P2：类型破坏**
- None 注入每个参数（包括非可选参数）
- 错误类型替换每个参数
- 特殊数值/字符串注入

**优先级 P3：状态/时序破坏**
- 前置条件不满足
- 非法调用序列
- 重复调用

**参数化强制规则**：
对于同一函数的多条同类边界破坏测试，**必须**使用 `@pytest.mark.parametrize`（Python）、`it.each`（TypeScript）或 `describe.each` 合并。若对同一函数生成了 3 个以上仅输入值不同的测试且未使用参数化，判定为结构违规，阻断输出。

### 步骤 3：输出测试代码

按项目技术栈输出测试文件，命名规范：
```
{module_id}.adversarial.test.{ext}
```

> **平台兼容性**：以下代码示例以 Windows 风格路径为默认。根据实际平台调整路径分隔符和命令语法。

适配技术栈：
- **Python**：pytest，使用 `@pytest.mark.parametrize` 批量注入破坏性输入
- **TypeScript**：vitest / jest，使用 `it.each` 或 `describe.each`
- **Go**：标准 testing + testify/assert

**空测试函数禁止**：

每个对抗性测试函数体内**必须**包含至少一个以下元素：
- `assert` 语句
- `pytest.raises(...)` 上下文
- `pytest.fail(...)` 调用
- `unittest.TestCase.fail(...)` 调用

禁止生成仅含注释、条件分支、`pass` 或变量赋值但无上述元素的测试函数。此条由 G11（空测试）在输出前自检中强制执行。

**断言强度标准**：

每个对抗性测试必须满足以下**至少一项**：

| 强度 | 要求 | 对抗性测试示例 |
|:---|:---|:---|
| **异常断言** | 断言特定异常类型和消息 | `with pytest.raises(ValueError, match="limit must be positive")` |
| **值断言** | 断言具体返回值（明确不是"非 None"） | `assert result == []` |
| **结构断言** | 断言返回数据结构符合预期 | `assert isinstance(result, ErrorResponse)` |
| **行为断言** | 断言副作用发生/未发生 | `assert mock_logger.error.call_count == 1` |

**禁止以下弱断言单独使用**：
- `assert result is not None`（太弱）
- `assert len(result) > 0`（非核心业务断言）
- `assert True` 或任何恒真式
- 不结合具体契约条款的模糊断言

测试结构模板：
```python
# Python 示例 —— 优先使用参数化合并同类破坏
@pytest.mark.parametrize(
    "bad_input,expected_exc",
    [
        ("", ValueError),      # 空字符串
        ("ch-", ValueError),   # 格式残缺
        ("02", ValueError),    # 缺失前缀
    ],
)
def test_func_name_rejects_invalid_input(bad_input, expected_exc):
    """破坏意图：验证函数拒绝所有非法输入格式"""
    with pytest.raises(expected_exc):
        func_under_test(bad_input)

# 单条契约的独立测试（仅当无法参数化合并时使用）
def test_func_name_type_corruption():
    """破坏意图：验证函数在收到错误类型时的行为"""
    with pytest.raises(TypeError):
        func_under_test(None)
```

**Python 包完整性**：

如果测试输出目录是一个 Python 包（即测试文件为 `.py`），必须同时创建有效的 `__init__.py`：

```python
# __init__.py
"""{module_id} 对抗性测试包。"""

# 确保 pytest 可以正确发现本包下的测试
# 如需暴露公共辅助函数，在此定义或导入
```

`__init__.py` 要求：
- 文件大小 > 0（不得为空文件）
- 包含包级 docstring（说明本包的用途）
- 如有跨测试文件共享的辅助函数/ fixture，在此定义

**空 `__init__.py` 可能导致 pytest 包发现失败或导入错误。**

### 步骤 4：输出测试清单

生成 Markdown 清单文件 `{module_id}.adversarial.test.list.md`，说明每个测试的：
- 目标函数
- 破坏意图
- 破坏性输入
- 预期行为（根据契约应抛出的异常或返回的结果）
- 关联的契约条款

## 好测试标准

| 质量维度 | 好的对抗性测试 | 坏的对抗性测试 |
|:---|:---|:---|
| **意图清晰** | 测试名称/注释明确说明"破坏什么"（如 `test_rejects_negative_limit`） | 名称模糊（如 `test1`、`test_edge_case`） |
| **契约锚定** | 每个测试都关联到具体的契约条款（如 §3.2） | 凭感觉编写的测试，无契约依据 |
| **最小独立** | 一个测试只破坏一个约束条件 | 一次测试多个不相关的约束 |
| **可解释性** | 失败时，错误信息能让人一眼看出是"哪条契约被违反" | 失败信息晦涩，需要调试才能理解 |
| **确定性** | 同样的输入每次运行都产生同样的结果 | flaky 测试 |
| **通过自检** | 运行 `scripts/detect_green_seeking.py` 通过（toxicity_score ≤ 2，无 G9/G11/G12） | 输出前未自检，携带异常吞咽、空测试、内部函数导入、防御性跳过等问题交付 |

## 禁止行为

| 禁止项 | 原因 |
|:---|:---|
| 读取实现源码 | 破坏信息隔离，失去对抗性 |
| 根据实现逻辑调整测试 | 测试会偏向实现而非契约 |
| 测试契约允许的正常行为 | 那是验收测试的职责 |
| 使用 mock 替代被测函数 | 无法发现真实漏洞 |
| 测试私有函数/内部方法 | 只关注公开接口契约 |
| 猜测未声明的行为 | 只能依据明确契约生成测试 |
| 编写与契约矛盾的测试 | 会导致测试误报，浪费修复迭代 |
| 一个测试破坏多条不相关约束 | 失败时无法定位具体漏洞 |
| 裸 `except Exception: pass` | 吞掉所有异常，无法区分契约期望异常与实现漏洞 |
| 使用"或"断言宽容匹配异常消息（如 `assert "a" in err or "b" in err or "pattern" in err`） | `"pattern"` 可匹配任意 Pydantic ValidationError，掩盖实现未精确处理的事实 |
| 在 `pytest.raises` 后断言 `exc_info.value is not None` | 恒真式，不提供任何信息 |
| 测试标准库/语言内置行为而非被测系统 | 发现不了被测系统的漏洞（如直接测 `asyncio.Semaphore(0)` 而非调用业务函数） |
| 断言中包含冗余"或"分支放宽条件（如 `assert result is None or result == expected`） | 放宽通过条件，掩盖漏洞 |
| **`pytest.skip` / `unittest.skip` / `pytest.xfail`** | 制造虚假收敛，掩盖真实的模块结构漂移或契约未覆盖 |
| **导入以 `_` 开头的内部函数/模块** | 破坏信息隔离，测试基于实现细节而非公开契约（G12） |
| **测试函数体中无 `assert`、无 `pytest.raises`、无 `fail()`** | 空测试恒真，无法发现任何漏洞（G11） |
| **`__init__.py` 为空文件或缺失** | pytest 包发现失败，导致测试无法运行或全部跳过 |

## 质量检查清单

- [ ] 每个公开函数至少有一个对抗性测试
- [ ] 每个异常条件至少有一个触发测试
- [ ] 每个边界至少有一个越界测试
- [ ] 没有测试依赖于实现细节
- [ ] 测试代码可以在隔离目录独立运行
- [ ] 测试清单完整标注了每个测试的破坏意图
- [ ] 无弱断言单独使用
- [ ] 无与契约矛盾的测试
- [ ] 无 `pytest.skip` / `unittest.skip` / `pytest.xfail`
- [ ] 无空测试函数（所有测试含 `assert` 或 `pytest.raises` 或 `fail()`）
- [ ] 无内部函数导入（未从被测模块导入 `_` 前缀函数）
- [ ] 同类边界测试已使用参数化合并（≥3 个同类输入必须参数化）
- [ ] `__init__.py` 存在且非空
- [ ] 运行 `scripts/detect_green_seeking.py` 通过（toxicity_score ≤ 2，无 G9/G11/G12）

### 步骤 5：输出前自检（强制）

生成测试代码后、输出前，**必须**依次执行以下检查：

#### 5.1 前置条件检查（先决阻断）

运行趋绿扫描器之前，先验证以下前置条件：
1. **语法正确**：`python -m py_compile {test_file}` 通过
2. **包完整性**：`__init__.py` 存在且非空（`len(content.strip()) > 0`）
3. **可直接导入**：`python -c "import {test_module}"` 通过（不依赖被测模块是否安装，只验证测试代码自身无语法/导入错误）

**任一前置条件失败，直接阻断输出，无需运行趋绿扫描。**

#### 5.2 趋绿扫描

```bash
python scripts/detect_green_seeking.py \
    {output_test_file} \
    --sut-module {被测模块顶层包名} \
    --output {output_dir}/green-seeking-report.json
```

**通过标准**：`toxicity_score <= 2`

**扫描规则速查表**：

| Rule | 说明 | 毒性权重 |
|:---|:---|:---|
| G1 | 异常吞咽（裸 `except: pass`） | 3 |
| G2 | 构造-断言（assert 出现在被测调用之前，或无被测调用） | 3 |
| G3 | 宽泛断言（`assert ... in (a, b, c)` 备选值 > 2） | 1 |
| G4 | 纯存在性断言（仅 `is not None` / `len > 0`） | 2 |
| G5 | 标准库测试（直接测标准库行为，无被测调用） | 2 |
| G6 | 纯 Mock 验证（仅 `assert_called*`，无业务断言） | 2 |
| G7 | 自我赋值断言（赋值后立即断言同一变量，无被测调用介入） | 3 |
| G8 | 恒真式欺骗（`or True` / `and False`） | 3 |
| G9 | 防御性跳过（`if condition: return/pass`） | **3（阻断级）** |
| G10 | 核心接口偏离（ Evil Stub 测试未调用核心业务函数） | 2 |
| G11 | 空测试（函数体无 `assert` / `pytest.raises` / `fail()`） | **3（阻断级）** |
| G12 | 内部函数导入（从被测模块导入 `_` 前缀函数） | **3（阻断级）** |

**不通过时的处理**：
1. 读取 JSON 报告中的 `suspects` 列表
2. 按 rule_id 分类修复：
   - **G1**（异常吞咽）：移除裸 `except: pass`，改为 `pytest.raises(具体异常类型)`
   - **G3**（宽泛断言）：将 `assert a or b or c` 改为精确匹配契约要求的异常消息关键词
   - **G5**（标准库测试）：删除不调用被测函数的测试，或补充被测函数调用
   - **G8**（恒真式）：删除 `exc_info.value is not None` 等恒真断言
   - **G9**（防御性跳过）：移除所有 `if condition: return/pass` 模式，改为完整执行测试逻辑
   - **G11**（空测试）：补充 `assert` 或 `pytest.raises`，或删除无意义测试
   - **G12**（内部函数导入）：删除 `from sut import _internal_func`，改为通过公开接口间接验证
3. 修复后重新运行扫描，直到通过
4. **不得在未通过扫描的情况下输出测试代码**

#### 5.3 报告输出

自检通过后，必须将扫描报告（JSON）输出到 orchestrator 指定目录：
```
{output_dir}/green-seeking-report.json
```

报告需包含：
- `toxicity_score`
- 按 `rule_id` 分类的 `suspects` 列表
- `is_clean: true/false`

orchestrator 在 Phase 3.4 中读取此报告，若 `is_clean` 不为 `true`，拒绝接受测试代码。

---

## 参考资源

- **对抗性测试策略手册**：`references/adversarial-strategies.md` — 边界/类型/状态/资源/时序五类破坏策略详解
- **趋绿扫描器**：`scripts/detect_green_seeking.py` — 输出前自检工具，检测 G1-G9 类趋绿模式
