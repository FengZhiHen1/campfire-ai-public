# 对抗性测试策略手册

本文档详细说明对抗性测试的生成策略，供 `adversarial-test-generator` 参考使用。

## 策略分类

### 1. 边界值破坏（Boundary Violation）

目标：验证实现是否正确处理了契约声明的边界。

| 数据类型 | 合法边界 | 破坏性输入 |
|:---|:---|:---|
| 正整数（≥1） | 1, 2, 100 | 0, -1, -999999 |
| 有界整数 [min, max] | min, max | min-1, max+1 |
| 浮点数 | 0.0, 1.5 | NaN, Infinity, -Infinity, 极大/极小值 |
| 非空字符串 | "a", "hello" | "", "   ", "\x00", "\n\r\t" |
| 有界长度字符串（≤N） | N-1, N | N+1, 100KB 超长字符串 |
| 数组/列表 | [item], [item] * N | [], [item] * (N+1) |
| 对象/字典 | 完整对象 | {}, 缺少必填字段, 多余字段 |
| 枚举 | 枚举定义的值 | 枚举外的值、null、undefined |
| 布尔 | True, False | null, 0, 1, "true" |
| 日期时间 | 正常日期 | epoch, 9999-12-31, 非法格式 |
| UUID | 合法 UUID | 非法格式、空字符串、带大写（若要求小写） |
| Email | 合法邮箱 | 无@、无域名、多空格、超长 |
| URL | 合法 URL | 无协议、非法字符、file://、javascript: |

### 2. 类型破坏（Type Corruption）

目标：验证类型校验是否完备。

**基本替换矩阵**：
- `int` → `None`, `"123"`, `3.14`, `True`, `[]`, `{}`
- `str` → `None`, `123`, `b"bytes"`, `[]`, `{}`
- `list` → `None`, `"[]"`, `{}`, `()`, `iter([1,2,3])`
- `dict` → `None`, `"{}"`, `[]`, `object()`
- `bool` → `None`, `1`, `0`, `"true"`, `"false"`
- `float` → `None`, `"3.14"`, `Decimal("3.14")`, `Fraction(1,3)`

**数值特殊值**：
- `NaN`（`float('nan')`）：与任何值比较都为 False，包括自身
- `Infinity`（`float('inf')`）：数学运算的边界行为
- `-Infinity`（`float('-inf')`）
- `sys.float_info.max`：浮点溢出
- `sys.float_info.min`：浮点下溢
- 极大整数（`10**1000`）：整数运算边界

**字符串特殊值**：
- 空字符串 `""`
- 空白字符串 `"   "`、`"\t\n\r"`
- 零宽字符 `"\u200b"`、`"\u200c"`、`"\u200d"`
- 方向控制字符（RTL/LTR）
- Unicode 私有区字符
- 组合字符（decomposed forms）
- 无效 UTF-8 序列（字节层面）
- 路径遍历 `"../etc/passwd"`、`"..\\windows\\system32"`
- SQL 注入片段 `"' OR '1'='1"`（如参数用于查询）
- 命令注入 `"; rm -rf /"`
- 超长字符串（1MB+）

### 3. 状态破坏（State Violation）

目标：验证状态管理和前置条件检查。

**前置条件破坏**：
- 在未初始化时调用初始化后函数
- 在已关闭的资源上执行操作
- 在未登录时调用需要认证的接口
- 在对象已删除后调用方法

**状态机破坏**：
- 从状态 A 直接跳转到非相邻状态（跳过中间状态）
- 对终态对象调用状态转换操作
- 重复执行本应一次性的操作

**幂等性破坏**：
- 重复调用同一操作，验证副作用是否被控制
- 快速连续调用，验证竞态条件

### 4. 资源破坏（Resource Exhaustion）

目标：验证资源限制和异常处理能力。

**数据量破坏**：
- 超大列表（100万+ 元素）
- 超大字符串（10MB+）
- 深度嵌套 JSON（1000+ 层）
- 宽对象（1000+ 个字段）

**递归/循环破坏**：
- 自引用对象（循环引用）
- 对象图深度过大

### 5. 时序破坏（Timing Violation）

目标：验证时序依赖和并发安全（如适用）。

**操作序列破坏**：
- 颠倒操作顺序（如先保存后验证）
- 跳过必要步骤
- 重复执行同一操作

**快速连续调用**：
- 高频调用同一接口
- 同时发起多个请求

## 策略选择优先级

对每个函数参数，按以下顺序选择破坏策略：

1. **契约明确禁止** → 直接测试禁止输入
2. **类型系统约束** → 类型破坏
3. **边界声明** → 边界值破坏
4. **前置条件/状态** → 状态破坏
5. **资源限制声明** → 资源破坏
6. **无明确约束** → 全面类型破坏 + 边界值破坏

## 技术栈适配

### Python (pytest)

```python
import pytest
from hypothesis import given, strategies as st

# 基于契约的参数化测试
@pytest.mark.parametrize("input_value,expected_error", [
    (None, TypeError),
    (-1, ValueError),
    ("not_a_number", TypeError),
    (float('inf'), ValueError),
])
def test_func_name_input_validation(input_value, expected_error):
    with pytest.raises(expected_error):
        func_name(input_value)
```

### TypeScript (vitest)

```typescript
import { describe, it, expect } from 'vitest';

describe('funcName adversarial', () => {
  it.each([
    [null, 'TypeError'],
    [-1, 'ValueError'],
    ['not_a_number', 'TypeError'],
    [Infinity, 'ValueError'],
  ])('rejects invalid input %p', (input, expectedError) => {
    expect(() => funcName(input)).toThrow(expectedError);
  });
});
```

### Go (testing)

```go
func TestFuncName_Adversarial(t *testing.T) {
    tests := []struct {
        name    string
        input   interface{}
        wantErr error
    }{
        {"nil_input", nil, ErrInvalidInput},
        {"negative", -1, ErrOutOfRange},
        {"wrong_type", "string", ErrTypeMismatch},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            _, err := FuncName(tt.input)
            assert.ErrorIs(t, err, tt.wantErr)
        })
    }
}
```
