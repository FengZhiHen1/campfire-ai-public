# propose_profile_item

> **权威范围**：该工具的契约。条目字段见[个性化档案](../../../technical-details/个性化档案.md)；异步写入路径见[写入路径](../../../technical-details/写入路径.md)。
> **状态**：2026-09-29 依已确认机制设计，待用户确认。
> **追溯**：`RQ-MEM-02`、`RQ-MEM-04`、`RQ-MEM-05`、`AC-07`、`AC-08`。

## 1. 用途

把对话中**已经出现过**的信息提成档案条目候选。它是三个写工具里唯一能影响档案的一个。

## 2. 参数

```text
support_object_id: string
domain: string                 # 九个领域之一
topic: string
description: string            # 一条一句话
contexts: string[]             # 可选
manifestations: string[]       # 可选
person_report: string          # 可选，当事人自述原文
probable_need: string          # 可选
helpful_support: string[]      # 可选
unhelpful_support: string[]    # 可选
origin: string                 # user_statement | guardian_observation | third_party_report | document | system_observation | ai_inference
source: object                 # 会话 id、消息定位、工具名、时间
```

## 3. 返回

```text
pending_id: string
state: "submitted"      # 异步：已提交，尚未生效
```

## 4. 硬约束（实现层，必须拒绝而不是纠正）

1. **推断不得冒充事实**（`RQ-MEM-04`）：`origin` 属于 `system_observation` 或 `ai_inference` 时，**不允许** `confirmation = confirmed`——请求被拒绝，而不是被降级改写。
2. **只写候选层**：本工具不直接改稳定层；稳定层由使用者确认后进入。
3. **不覆盖已有条目**：与现有条目冲突时并列新增，不修改既有条目（当事人的表达不被监护者观察覆盖）。
4. **不推断补全**：缺字段就留空；不为了条目"完整"而编写未出现过的内容。
5. 写入必须在**业务事务内**落成待处理记录；工具本身不得等待异步完成。

## 5. 失败语义

| 情形 | 处置 |
|---|---|
| 把推断写成 `confirmed` | **拒绝**，返回明确错误码 |
| 领域名非法 | 明确失败 |
| 待处理记录写入失败 | 明确失败；**不得**回执 "submitted" |
| 同一内容重复提交 | 允许（幂等由 `pending_id` 承担），不报错 |

## 6. 验证方式

- **硬约束**：以 `ai_inference` + `confirmed` 调用，验证被拒绝且没有落库。
- **候选隔离**：提交后立即读稳定层，验证它不在其中。
- **口误不落库**：待处理记录写入失败时验证返回失败、且回执不是已提交。
- **并列不覆盖**：构造与现有条目冲突的提交，验证两条都在。

## 7. 不在本文范围

- 确认与纠正的入口（属页面设计与档案机制）。
- Worker 的消费细节（见[写入路径](../../../technical-details/写入路径.md)）。
