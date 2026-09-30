# emit_emergency_action_card

> **权威范围**：该工具的契约——用途、参数、返回、失败语义、验证方式。**卡片事件的传输形状（通用信封）归[通用基座](../../../technical-details/通用基座.md)第 7.3 节**；七节的语义与取值词表归[emergency-consulting](../skills/emergency-consulting.md)第 3.4 节；本文档只定义"工具这一侧接受什么、拒什么"。
> **状态**：2026-09-30 依「卡片由产品侧工具产出」的裁决定形，**待用户确认**。不代表已实现。
> **追溯**：`RQ-EMG-01`～`RQ-EMG-04`、`RQ-CON-06`、`RQ-LIM-01`、`RQ-LIM-02`、`AC-03`、`AC-05`、`AC-21`。

## 1. 用途

发出一张应急现场行动卡。模型调用它后，基座把工具返回的卡片翻成 `action_card` 事件下发；**运行不因此结束**（卡片之后可继续输出追问或收尾文字）。

它是应急 skill 唯一的**结构化输出通道**：卡片的七个分节、四个状态字段、来源六类与置信四档都经它的参数进入事件，**不由模型写自由文本再由前端解析**——这是"结构可校验"的前提。

## 2. 参数

```text
sections:                       # 七节，按固定顺序；每节非空
    key: string                 # 枚举：status / communicate / do_now / avoid /
                                #       medical_checks / safety / when_to_escalate
                                #       依次对应应急 skill 第 3.4 节的：当前状态 / 立即怎么沟通 /
                                #       立即做 / 不要做 / 需要的医疗检查 / 安全措施 / 何时升级
    heading: string
    lines: string[]             # 每节至少一行；动词开头、可执行
states:                         # 四个状态字段，取值受枚举硬校验
    key: string                 # 枚举：deviation / communication / sensory_load / medical_risk
    value: string               # 各键的词表见第 4 节
annotations:                    # 可为空；逐条动作的来源与置信
    line_ref: string            # 指向 sections 内某条 line 的稳定序号
    source: string              # 枚举六类：self_report / family_report / onsite_observation /
                                #           history / medical_record / ai_inference
                                #           依次对应：本人报告 / 家属报告 / 现场观察 /
                                #           历史记录 / 医疗记录 / AI 推断（emergency-consulting 第 3.4 节）
    confidence: string          # 枚举四档：confirmed / likely / possible / unknown
```

不收 `support_object_id`——卡片的取数在注入侧已完成（档案八组与近期记忆由应用预注入），本工具只承载输出形状。

## 3. 返回

```text
card_id: string      # 本次卡片的标识；前端凭它区分新旧卡（重复评估时旧卡标失效）
```

## 4. 词表硬校验（本工具的机械边界）

以下取值由 `args_model` 的枚举在**参数解析期**拒绝，不是提示词约束：

| 状态键 | 取值 |
|---|---|
| `deviation` | `none` / `mild` / `moderate` / `marked` / `unknown` |
| `communication` | `baseline` / `reduced` / `severely_reduced` / `unavailable` |
| `sensory_load` | `low` / `moderate` / `high` / `extreme` |
| `medical_risk` | `stable` / `uncertain` / `high_risk` |

**为什么在这里卡而不是在提示词里**：`AC-21` 要求医疗风险只出现"稳定 / 未排除 / 高风险"三种表述。写在 skill 指令里是提示词层约束，**可以绕过**（`RQ-LIM-05` 已明确这一层不构成安全边界）；落在参数模型的枚举上，越界载荷根本到不了事件。

**`unknown` 不得被渲染为"无变化"**：`deviation`、`communication`、`sensory_load` 取 `unknown`（或缺失）时按"未排除"处理，与现场采集的跳过语义同源——这一条由前端呈现保证（[对话页](../../../../design/pages/对话页.md)的 `.action-card`），工具侧只保证取值合法。

## 5. 失败语义

| 情形 | 处理 |
|---|---|
| 状态取值越界（如 `medical_risk: "critical"`） | `tool_invalid_arguments`，带越界字段名；**不静默替换成合法值** |
| `sections` 缺节或某节为空 | `tool_invalid_arguments`；七节是硬结构，缺节不发残缺卡片 |
| 未激活 `emergency-consulting` 时调用 | 明确拒绝（工具范围硬边界，`tool_not_available`） |
| 未登录 | 明确失败（`RQ-ACC-01`） |

**不因校验失败而降级**：模型编不出合法卡片时，本次运行继续（它可以改用文本作答并明确标注无结构化结果），但**不得**发出一张取值被改写的卡片——那会让使用者看到一张"看起来合法但值是猜的"行动卡。

## 6. 验证方式

- **取值枚举**：以 `medical_risk` 的四个候选（含越界的 `critical`）各调一次，验证只有三个合法值通过、越界者返回 `tool_invalid_arguments` 且**没有**发出事件（`AC-21` 的机械端）。
- **七节完整**：构造缺 `avoid` 节的调用，验证被拒且无残缺卡片。
- **不静默改写**：越界载荷被拒后，验证事件流里没有 `action_card`。
- **越界调用**：未激活应急 skill 时调用，被服务端拒绝。
- **重复评估**：连续两张卡片，`card_id` 不同且前端把旧卡标失效（呈现侧由[对话页](../../../../design/pages/对话页.md)拥有）。
- **unknown 不误读**：`deviation: unknown` 时前端不呈现为"无变化"。

## 7. 不在本文范围

- 事件载荷的传输形状与 SSE 编码（[通用基座](../../../technical-details/通用基座.md)第 7.3 节、[HTTP/SSE 契约](../HTTP与SSE契约.md)第 4.2 节）。
- 七节的语义、措辞模板、来源六类与置信四档的写法（[emergency-consulting](../skills/emergency-consulting.md)第 3.4 节与其 `references/action-card.md`）。
- 卡片的视觉呈现与失效态（[对话页](../../../../design/pages/对话页.md)）。
- 工具的实现归属（装配处注册；本工具不写领域逻辑，只做校验与形状映射）。
