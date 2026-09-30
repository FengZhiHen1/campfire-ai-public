# propose_profile_item

> **权威范围**：该工具的契约——用途、参数、返回、落层分流的实现层硬约束、失败语义、验证方式。档案条目的字段与领域取值见[个性化档案](../../../technical-details/个性化档案.md)；异步写入路径见[写入路径](../../../technical-details/写入路径.md)。
> **状态**：2026-09-29 依已确认机制设计，待用户确认。**2026-09-29 领域架构与写入路径裁决后更新**：领域取十四个一级模块；本工具是档案的**唯一**写入口，落层按 `origin` 分流（不再一律写候选层）；补 `source` 参数。
> **追溯**：`RQ-MEM-02`、`RQ-MEM-04`、`RQ-MEM-05`、`AC-07`、`AC-08`、`AC-18`。

## 1. 用途

把对话中**已经出现过**的信息提成档案条目。它是档案的**唯一写入口**，因此也是唯一能改变档案的路径。

## 2. 参数

```text
support_object_id: string      # 必填
domain: string                 # 十四个一级模块之一（或「其他」）
topic: string
description: string            # 一条一句话，写可观察事实而不是宽泛标签
contexts: string[]             # 可选
manifestations: string[]       # 可选
person_report: string          # 可选，本人自述原文
probable_need: string          # 可选
helpful_support: string[]      # 可选
unhelpful_support: string[]    # 可选
origin: string                 # user_statement | guardian_observation | third_party_report
                               # | document | system_observation | ai_inference
source: object                 # 会话 id、消息定位、工具名、时间；转述者记于 relayed_by
```

`source` 是**必填**：`AC-07` 要求条目带来源，而来源定位无法从其他参数还原。`origin` 与 `source` 不可互相代替（[个性化档案](../../../technical-details/个性化档案.md)第 2 节）。

## 3. 返回

```text
pending_id: string
state: "submitted"      # 异步：已提交，尚未生效
```

`state` 只承诺"已提交"——写入经待处理记录与 Worker，**不得**回执"已保存"。

## 4. 硬约束（实现层，必须拒绝而不是纠正）

1. **落层按 `origin` 分流，由本工具硬卡**（[个性化档案](../../../technical-details/个性化档案.md)第 3 节）：
   - `user_statement`、`guardian_observation` → **直接稳定层**；
   - `third_party_report`、`document` → **直接稳定层**，`confirmation = unconfirmed`；
   - `system_observation`、`ai_inference` → **候选层**，`confirmation = unconfirmed`。
2. **推断不得冒充事实**（`RQ-MEM-04`）：`origin` 属于 `system_observation` 或 `ai_inference` 时，**不允许** `confirmation = confirmed`，也不允许直接进稳定层——请求被**拒绝**，而不是被降级改写。
3. **不覆盖已有条目**：与现有条目冲突时并列新增，不修改既有条目（当事人的表达不被监护者观察覆盖）。
4. **不推断补全**：缺字段就留空；不为了条目"完整"而编写未出现过的内容。
5. **不重复提交已知内容**：调用方须先读现有条目（`read_profile_items`）去重；已 `rejected` 的内容不得再次提交（[个性化档案](../../../technical-details/个性化档案.md)第 2 节）。
6. 写入必须在**业务事务内**落成待处理记录；工具本身不得等待异步完成。

## 5. 失败语义

| 情形 | 处置 |
|---|---|
| 把推断写成 `confirmed` 或直接进稳定层 | **拒绝**，返回明确错误码 |
| 领域名非法 | 明确失败，不静默归入「其他」 |
| `source` 缺失 | 明确失败（`AC-07` 不可满足） |
| 待处理记录写入失败 | 明确失败；**不得**回执 "submitted" |
| 同一内容重复提交 | 允许（幂等由 `pending_id` 承担），不报错 |

## 6. 验证方式

- **落层分流**：以六种 `origin` 各提交一条，验证前四种进稳定层、后两种只进候选层；后两种在摘要中不出现。
- **硬约束**：以 `ai_inference` + `confirmed` 调用，验证被拒绝且没有落库。
- **候选隔离**：以 `ai_inference` 提交后立即读稳定层，验证它不在其中。
- **口误不落库**：待处理记录写入失败时验证返回失败、且回执不是已提交。
- **并列不覆盖**：构造与现有条目冲突的提交，验证两条都在。
- **否定不回潮**：否定一条候选后再次提交同一内容，验证被拒绝。

## 7. 不在本文范围

- 确认、纠正与删除的入口（属档案面 HTTP 契约与档案机制）。
- Worker 的消费细节（见[写入路径](../../../technical-details/写入路径.md)）。
