# 咨询面 HTTP / SSE 契约

> **权威范围**：咨询面（日常与应急）对前端暴露的端点形状——请求与响应载荷、SSE 传输编码、并发与幂等、越权与失败语义。**事件的语义与载荷归[通用基座](../../technical-details/通用基座.md)第 7 节**；会话与对象绑定、八项采集的措辞与判据归各自拥有者（见第 9 节边界表）；本文件只定"怎么传"，不定"传什么"。
> **状态**：2026-09-30 依已确认的基座事件、支持对象、一次性引导与前端页面设计成形，**待用户确认**。不代表已实现：`surfaces/consult/` 当前只有工具注册清单。
> **追溯**：`RQ-ACC-01`、`RQ-ACC-09`、`RQ-CON-08`、`RQ-DAY-01`、`RQ-EMG-01`～`RQ-EMG-03`、`RQ-MEM-07`、`AC-02`、`AC-03`、`AC-12`、`AC-19`、`AC-25`。
> **依据**：两段式的发送与订阅形状（2026-09-30 用户裁定）；会话归属新增 `campfire_session` 表归 `modules/accounts`（2026-09-30 用户裁定，详见第 10 节）；[通用基座](../../technical-details/通用基座.md)第 2 节单真源与第 9 节失败语义；[认证与账号](../../technical-details/认证与账号.md)第 5 节凭据与 anti-CSRF。

## 1. 形状：发送与订阅分两段

一次运行分两个请求：先发消息拿 `run_id`，再订阅该运行的事件流。

```text
POST /api/consult/sessions/{id}/messages   →  202 {run_id}        # 受理，使用者消息尚未落库
GET  /api/consult/runs/{run_id}/stream     →  SSE（可续传）        # 事件流
POST /api/consult/runs/{run_id}/cancel    →  202                  # 取消（可选）
```

**为什么分两段**：对话真源是 SDK 的会话存储，一段式（POST 直返流）下连接中断即运行中断，重连等于重放一次运行——会把使用者消息二次追加进真源，并把运行跑第二遍。分段后订阅可带 `Last-Event-ID` 续传，且应急表单提交后跳页不再断流（[应急表单页](../../../design/pages/应急表单页.md)第 22 行的 `navigate` 即需要这一性质）。

## 2. 通用约定

| 约定 | 内容 |
|---|---|
| 鉴权 | 全部端点须登录（`RQ-ACC-01`）。凭据经 httpOnly cookie 自动携带；anti-CSRF 自定义头由官方前端 SDK 注入（[认证与账号](../../technical-details/认证与账号.md)第 5 节） |
| 越权 | 会话不属于当前账号 → **404**，文案与"会话不存在"逐字相同（不泄露存在性，同[支持对象](../../technical-details/支持对象.md)第 5.3 节纪律） |
| 并发 | 同一会话同时只允许一个运行；已有在跑的运行再发消息 → **409** `session_busy`。理由：单真源下两次运行交错追加会写乱会话顺序 |
| 幂等 | `client_message_id` 由前端生成；同一会话内重复提交同一键值 → 返回首次的 `run_id`，**不重复追加使用者消息** |
| 传输 | `Accept: text/event-stream`。**不得用 `EventSource`**——它无法携带 anti-CSRF 自定义头；用 `fetch` + `ReadableStream`（或官方 SDK 的 fetch 包装）自行解析 |
| 时限 | 单次运行上限 180 秒（基座第 2 节）；流最迟在此结束 |

**错误码**（全部端点共用）：

| 码 | 情形 | 前端行为 |
|---|---|---|
| 401 | 会话过期或未登录 | 清本地状态跳登录页 |
| 404 | 资源不存在或不属于当前账号 | 错误提示，不重试 |
| 409 | `session_busy` / `run_not_resumable` | 见第 4.1、4.2 节各自语义 |
| 422 | 载荷不合法（如 `content` 为空、八项 `key` 未知） | 内联错误，不重试 |
| 503 | 依赖不可用（会话存储、模型、core） | `.error-card` + 重试 |

## 3. 会话端点

### 3.1 创建会话

```text
POST /api/consult/sessions
请求：{ "support_object_id": "uuid，可选" }
响应 201：
{
  "session_id": "…",
  "support_object_id": "uuid 或 null",
  "onboarding_pending": true
}
```

- 省略 `support_object_id` 时按[支持对象](../../technical-details/支持对象.md)第 6 节推导默认对象（上一次绑定 → 创建最早的在用对象）；账号无任何在用对象时返回 `null`，**不是错误**（`AC-02` 同源）。
- 传入 `support_object_id` 时服务端以 `require_writable` 校验（归档对象不得绑定新会话）；校验失败为 **404**。
- `onboarding_pending`：账号首次创建日常会话且引导未终结时为真（查 `campfire_onboarding`，机制归[技能设计](../../technical-details/技能设计.md)第 4 节）。为真时该会话的**第一次运行**由服务端程序注入 onboarding skill；前端不感知注入内容，只照常订阅。

### 3.2 会话列表

```text
GET /api/consult/sessions?cursor=&limit=20        # limit 默认 20、上限 50
响应 200：
{
  "items": [
    { "session_id": "…", "title": "首条使用者消息摘要", "support_object_name": "… 或 null",
      "updated_at": "…", "last_message_preview": "… 或 null" }
  ],
  "next_cursor": "… 或 null"
}
```

字段即[会话列表页](../../../design/pages/会话列表页.md)第 36 行声明的四个字段；`support_object_name` 缺失（早期无绑定会话）时为 `null`，前端不渲染该字段。

### 3.3 历史水合

```text
GET /api/consult/sessions/{session_id}/messages
响应 200：
{
  "session_id": "…",
  "messages": [
    { "id": "…", "role": "user",      "parts": [ … ] },
    { "id": "…", "role": "assistant", "parts": [ … ] }
  ]
}
```

- 顺序即会话真源顺序。**水合失败显示错误与重试，不显示空对话冒充成功**（[咨询对话界面](../../technical-details/咨询对话界面.md)第 4.4 节）。
- `parts` 的形状见第 7 节。

## 4. 发送与订阅

### 4.1 发消息

请求（两种形态二选一，服务端按字段判别）：

```text
# 普通消息
{ "content": "使用者输入",
  "skill": "daily-consulting，可选；缺省或 null 表示自动匹配",
  "client_message_id": "前端生成的幂等键" }

# 一组提问的回答（当前有待作答的问题组时）
{ "answers": [ { "id": "题 id", "value": "选项 label 或自由文本" },
               { "id": "题 id", "skipped": true } ],
  "skill": "…", "client_message_id": "…" }
```

响应 202：`{ "run_id": "…", "session_id": "…" }`

- `skill` 即技能选择器的选择（`RQ-CON-08`），**发送即消费**：本次运行后前端清空选择器、回归"自动"。
- **回答的形状归基座**第 7.2 节（逐题 `id` + 选项 label 或自由文本或显式跳过）；服务端把它渲染成一条使用者消息落进会话，保留逐题对应与显式跳过标记——跳过必须是服务端可判定的事实，不能靠前端措辞或模型推断（应急"跳过即未排除"由此成立）。一组的回答**一次发完**，不接受逐题分次提交。
- **202 只表示已受理**：使用者消息此时尚未落库（`AGENT` 运行由 SDK 写入）。前端本地呈现，以服务端为真源；刷新后以第 3.3 节的水合结果为准。
- 会话处于引导待注入状态时，本次运行由服务端程序注入 onboarding；`skill` 参数被忽略。

### 4.2 订阅事件流

```text
GET /api/consult/runs/{run_id}/stream
头：Last-Event-ID: <seq>（可选，断线续传用）
```

每条事件三行：

```text
id: 17
event: text_delta
data: {"type":"text_delta","delta":"…"}
```

| 性质 | 约定 |
|---|---|
| `event` 与 `data.type` | 恒等，取基座事件名；前端按 `event` 分派，`data` 即该事件对象的 JSON |
| `id` | 本次运行内单调递增的序号；**续传的唯一依据** |
| 续传 | 带 `Last-Event-ID` 时从下一条续发；缓冲已失效或已无可续内容 → **409** `run_not_resumable`，前端改走历史水合（结果与"未知"以服务端为准） |
| 心跳 | 空注释行 `: ping`，每 15 秒；仅防代理超时，不承载语义 |
| 结束 | 终态事件（`run_finished` / `run_failed`）后服务端关闭流 |

**事件到 SSE 的映射就是恒等映射**，不重命名、不合并：

| 基座事件 | 实现状态 |
|---|---|
| `run_started`、`text_delta`、`progress`、`tool_call_started`、`tool_call_finished`、`citation`、`candidate`、`run_finished`、`run_failed` | 已在 `agent/runtime/events.py` 定义 |
| `reasoning_delta`、`question`、`action_card` | **形状已定形，事件类未落地**（2026-09-30）。载荷归[通用基座](../../technical-details/通用基座.md)第 7.1／7.2／7.3 节拥有，本文不定义；实现前须先落事件类 |

### 4.3 取消

```text
POST /api/consult/runs/{run_id}/cancel → 202
```

- 对应"停止"按钮与 `abortSignal`；已终结的运行返回 **409**。
- 取消不发终态事件（基座第 9 节）：前端自行把已渲染的 partial text 标为"本次回答中断"，不得等一个不会到达的 `run_finished`。

## 5. 应急入口

```text
POST /api/consult/emergency
请求：
{
  "support_object_id": "uuid，可选",
  "items": [
    { "key": "medical_red_flags",     "values": ["…"],      "skipped": false },
    { "key": "baseline_deviation",    "value": "marked",    "skipped": false },
    { "key": "communication",         "value": "reduced",   "skipped": false },
    { "key": "distress",              "value": "…",         "skipped": false },
    { "key": "sensory_environment",   "values": ["…"],      "skipped": false },
    { "key": "what_happened",         "value": "…",         "skipped": true  },
    { "key": "primary_risk",          "value": "medical",   "skipped": false },
    { "key": "possible_pain",         "value": "uncertain", "skipped": false }
  ]
}
响应 202：{ "session_id": "…", "run_id": "…" }
```

- 一次调用完成"建会话 → 落第一条消息（八项 + 档案与记忆预注入）→ 启动运行"，前端拿 `run_id` 直接跳对话页订阅。
- **八项的 `key` 是传输标识**，取值词表、题干与选项措辞归 [emergency-consulting](skills/emergency-consulting.md)，本文档不定义。
- `skipped: true` 时前端**不传任何值**；"跳过 = 未排除"的解释权在后端与 skill（[咨询对话界面](../../technical-details/咨询对话界面.md)第 6 节）。
- 应急会话**永不触发引导**（`RQ-EMG-03`）。

## 6. 引导跳过入口

```text
POST /api/consult/sessions/{session_id}/onboarding/skip
响应 200：{ "state": "skipped" }
```

- 即 `campfire_onboarding` 的 UI 通道；与 `finish_onboarding` 工具（写 `completed`）互不代写（[认证与账号](../../technical-details/认证与账号.md)第 8 节）。
- **幂等**：已是 `skipped` 或 `completed` 时仍返回 200，不报错。
- 本端点**不是**跳过引导对话的中途退出——它只写状态；正在跑的运行按第 4.3 节取消。

## 7. 消息 part 形状

`parts` 是消息 content 的序列化，与流式事件同源同形：

| `type` | `data` 归谁 |
|---|---|
| `text` | 本文：`{ "text": "…" }` |
| `reasoning` | [通用基座](../../technical-details/通用基座.md)第 7.1 节 |
| `tool_call` | 本文：`{ "tool_name": "…", "ok": true, "summary": "…" }` |
| `citation` | [资料与案例检索](../../technical-details/资料与案例检索.md)第 3 节返回契约 |
| `question` | [通用基座](../../technical-details/通用基座.md)第 7.2 节 |
| `action_card` | [通用基座](../../technical-details/通用基座.md)第 7.3 节 |

- `candidate` **不进历史**：它不进消息流（[项目结构设计](../../../项目结构设计.md)第 9 节），仅经 SSE 计数。
- 引用（`citation`）作为 part 与所属消息同生命周期，重放与滚动都不错位。

## 8. 失败语义

| 情形 | 服务端 | 前端 |
|---|---|---|
| 断连 | 运行继续（订阅与运行解耦） | 带 `Last-Event-ID` 重连，指数退避 |
| 重连耗尽 | — | `.error-card` + 手动重试；**不显示空对话** |
| `run_not_resumable` | 409 | 改走历史水合；结果以服务端为准 |
| `run_failed`（检索类） | 终态事件 | 文案"检索暂时不可用"，**不得**写"未找到相关内容" |
| 会话写入失败 | `run_failed` `session_write_failed` | 明确中断；不得把未落库的对话当已保存 |
| 401 | — | 清状态跳登录 |

## 9. 边界

| 内容 | 归谁 |
|---|---|
| 事件的语义、载荷与产生方式 | [通用基座](../../technical-details/通用基座.md)第 7 节 |
| 卡片与提问的领域词表及其校验 | [emit_emergency_action_card](tools/emit_emergency_action_card.md)第 4 节、[emergency-consulting](skills/emergency-consulting.md)第 3.4 节 |
| 会话真源与落库 | [通用基座](../../technical-details/通用基座.md)第 2 节（SDK 会话存储） |
| 支持对象实体、生命周期、会话绑定与默认推导 | [支持对象](../../technical-details/支持对象.md) |
| 引导的触发判定与状态表 | [技能设计](../../technical-details/技能设计.md)第 4 节、[认证与账号](../../technical-details/认证与账号.md)第 8 节 |
| 八项采集的措辞与判据、Action Card 取值 | [emergency-consulting](skills/emergency-consulting.md) |
| 引用条目的字段 | [资料与案例检索](../../technical-details/资料与案例检索.md)第 3 节 |
| 事件的 UI 映射与 adapter | [咨询对话界面](../../technical-details/咨询对话界面.md) |
| 档案、记忆、资料库的查看/检索/确认/纠正/删除端点 | [档案面](../profile/档案面HTTP契约.md)、[记忆面](../profile/记忆面HTTP契约.md)、[资料库面](../profile/资料库面HTTP契约.md) |

## 10. 已知偏差与证据边界

- **三个事件的形状已定形、事件类未落地**（2026-09-30）：`question`（第 7.2 节，一组题）、`action_card`（第 7.3 节，通用信封）、`reasoning_delta`（第 7.1 节）的载荷由[通用基座](../../technical-details/通用基座.md)拥有并已定义，但 `agent/runtime/events.py` 的 `RunEvent` 联合里**都还没有**。实现前须先落事件类——这是提问卡、行动卡、思考区三处前端组件的数据来源。**另有一项实测前置**：`reasoning_delta` 在 SDK 事件流里的键名未实测（基座第 7.1 节），取不到时该事件不产出，不得用文本增量冒充。
- **会话归属表 `campfire_session` 尚未落地**：2026-09-30 用户裁定新增并已写入定调（[项目结构设计](../../../项目结构设计.md)第 6 节、`accounts` 用例行）与注销处置（[认证与账号](../../technical-details/认证与账号.md)第 8 节第 4 步），决策记录见[会话归属单立表归 accounts](../../decisions/会话归属单立表归accounts.md)。仍缺的是表形状与迁移，随 `modules/accounts` 实现落地。
- **事件缓冲的承载与保留时长待确认**：续传要求服务端持有本次运行的事件序列；Redis 已在技术栈内，但缓冲结构、TTL 与"运行已终结后保留多久"未定。
- **SDK 会话表仍未登记**：本契约的历史水合依赖 SDK 的 `agent_sessions` / `agent_messages`，两张表的归属与命名未定（[设计待办](../../../TODO.md)）。
- **前端文档尚未对齐本文**：[咨询对话界面](../../technical-details/咨询对话界面.md)第 3 节的 adapter 形状按"POST 直返流"写成，第 7 节的"重连上限 3 次"亦按该形状；两段式下两者需重写。登记于[设计待办](../../../TODO.md)，不在本文改动。
- **未实测**：全部端点形状均为设计结论，无运行证据；`Last-Event-ID` 续传在代理（Nginx）后的实际行为须实测。
