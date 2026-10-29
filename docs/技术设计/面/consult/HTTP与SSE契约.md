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
| 时限 | 单次运行上限 300 秒（基座第 2 节；2026-10-28 由 180 秒上调，理由见该节）；流最迟在此结束 |

**错误码**（全部端点共用）：

| 码 | 情形 | 前端行为 |
|---|---|---|
| 401 | 会话过期或未登录 | 清本地状态跳登录页 |
| 404 | 资源不存在或不属于当前账号 | 错误提示，不重试。**运行事件流端点例外**：该端点上的 404 表示「这条运行的缓冲元数据不在了」（到期或不属于当前账号），客户端**按第 4.2 节的不可续传处置**（改走历史水合），不给死胡同卡片——2026-10-28 定 |
| 409 | `session_busy` / `run_not_resumable` | 见第 4.1、4.2 节各自语义 |
| 422 | 载荷不合法（如 `content` 为空、八项 `key` 未知、`skill` 值域外——2026-10-01 起，见第 4.1 节） | 内联错误，不重试 |
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
  "skill": "daily-consulting 或 profile-curation，可选；缺省或 null 表示自动匹配",
  "client_message_id": "前端生成的幂等键" }

# 一组提问的回答（当前有待作答的问题组时）
{ "answers": [ { "id": "题 id", "value": "选项 label 或自由文本" },
               { "id": "题 id", "skipped": true } ],
  "batch_id": "本组的批次标识（可选，见下方四条）",
  "skill": "…", "client_message_id": "…" }
```

响应 202：`{ "run_id": "…", "session_id": "…" }`

- `skill` 即技能选择器的选择（`RQ-CON-08`），**发送即消费**：本次运行后前端清空选择器、回归"自动"。
- **`batch_id`（2026-10-06 用户裁决：作答携带批次标识）**——四项逐条：
  1. **可选**，不是必填。**不带该字段的旧客户端仍被接受**（缺省即退回现状判定），
     因此这不是破坏性变更。带该字段时不得为空串或全空白（**422**：空串与缺省语义不同——
     缺省是「本次作答不声明批次」，空串是「声明了一个空批次」，后者不可判定，不得静默当作缺省）。
  2. **值只有两条来源**，都取自服务端已下发的载荷：实时路径取 SSE `question` 事件的
     `batch_id`（[通用基座](../../technical-details/通用基座.md)第 7.2 节）；水合路径取
     `question-record` part 的 `batch_id`（第 7 节）。前端**只如实回传、不做归属判断**。
  3. **缺省行为 = 现状**：服务端按「位置窗口 × 表头」判定（`session_items.question_answered_verdicts`），
     即本节改动之前的行为逐字不变。
  4. **两条路径语义不同，消费者不得假定它们等价**：水合路径的值是 `hydrated-<call_id>`，
     服务端剥掉前缀即得 `call_id`，**能正向归属**到某一组；实时路径的值是工具侧生成的裸
     `uuid4().hex` 且**不落库**，服务端**无法**把它与任何一组关联——**它既不能正向归属，
     也不构成排他凭据**（见下方判定顺序 ③）。
     **实时路径不得被理解为「能精确归属到某一组」。**
  5. **位置**：`batch_id` 的**正位是顶层**（它描述整组，见[通用基座](../../technical-details/通用基座.md)第 7.2 节）。
     服务端**同时放行**逐题位置（`answers[].batch_id`，为兼容按题携带的客户端）；两处都写时
     **必须逐字相等**，逐题之间也必须一致——不一致一律 **422**（一组作答不可能同时属于两个批次，
     矛盾胜于猜测）。普通消息形态（`content`）**不得**携带 `batch_id`：它是「一组题」的属性，
     普通消息没有批次可言，带上即 422（静默忽略会让映射错误永远看不见）。
- 服务端判定顺序为**四层：正向 > `None`（不可判定） > 排他 > 缺省**（判据落点在
  `session_items.question_answered_verdicts` / `_turn_verdict`）：
  ① **正向**：剥前缀后**命中本组** `call_id` ⇒ `True`（这一层**越过** `None`：正向是直接证据，
     让 `None` 压过它会让一次压缩就使本组永久失去补答）；
  ② **`None`（不可判定）**：无法判定（压缩复述等，见第 3 节既有三情形）⇒ 只读；
     它**越过**排他层与缺省层；
  ③ **排他**：窗口里存在一条**可验证属于别组**的声明（水合形态且不等于本组 `call_id`）
     ⇒ `False`（不得判本组被作答）；
  ④ **缺省**：没有任何可验证声明 ⇒ 退回第 3 条（位置窗口 × 表头 × 既有迟到作答收窄）。
- ⚠ **实时路径的声明不构成排他**（2026-10-07 r2 订正）：它不可验证（第 4 条），
  因此**只行使「不得判 `True`」的否决权** ⇒ 相关组判 **`None`**（只读），
  **既不得 `True` 也不得 `False`**。
  **`None` 与 `False` 的后果不同，消费方不得混用**：前端只在判定为 `false` 时才让历史
  提问卡**重新可作答**（`useQuestionBatch`），`None` 是只读。把实时声明判成 `false`
  会让**本组自己的作答**被当成「未作答」⇒ 卡片重新可作答 ⇒ **使用者重复作答**。
- **`skill` 的合法值域（2026-10-01 裁决）**：仅 `daily-consulting` 与 `profile-curation`（= 模型可见目录集）。传入 `emergency-consulting`、`onboarding` 或未知名字 → **422**——应急只走应急表单入口（第 5 节），引导由引导状态触发（[技能设计](../../technical-details/技能设计.md)第 4 节），均不可经此参数手选。非法值不得静默忽略：使用者会以为选中的技能起了作用。
- **选择消费的是"本次激活"，不是授权**：给了合法名字，服务端为本轮写入一条合成激活记录（落会话历史）；授权随激活记录跨运行持续、会话内只增不减（[技能设计](../../technical-details/技能设计.md)第 4 节）。选择器清空后的下一条消息 `skill=null` → 不写新记录 → 已有授权照常生效。**回答的形状归基座**第 7.2 节（逐题 `id` + 选项 label 或自由文本或显式跳过）；服务端把它渲染成一条使用者消息落进会话，保留逐题对应与显式跳过标记——跳过必须是服务端可判定的事实，不能靠前端措辞或模型推断（应急"跳过即未排除"由此成立）。一组的回答**一次发完**，不接受逐题分次提交。
- **202 只表示已受理**：使用者消息此时尚未落库（`AGENT` 运行由 SDK 写入）。前端本地呈现，以服务端为真源；刷新后以第 3.3 节的水合结果为准。
- **幂等命中的运行已不可续传 → 409 `run_not_resumable`（2026-10-29 定）**：幂等键活 24 小时、运行元数据只活 600 秒（第 4.2 节），因此按第 2 节的幂等承诺在十分钟后重发同一个 `client_message_id` 时，首次那次的传输态**已经不在**。此时**不得**回 `202` + 旧 `run_id`——那会把一个「订阅必然 404、也永远不会重跑」的身份交给调用方：既拿不到内容，也没有任何入口能让这条消息执行一次。服务端回 **409** `run_not_resumable` 且**不重跑**（同一键重发不得再追加使用者消息，这是幂等语义本身），前端按第 4.2／第 8 节的不可续传处置**改走历史水合**：那一次若真的跑完过，回答就在会话真源里；若没有，调用方看到的是「这次回答无法继续接收」而不是死胡同。**与 `session_busy` 同码不同义，调用方必须按 `detail` 区分**：前者要等这一轮结束，后者要重读历史；**未知的 409 不得按 `session_busy` 处理**（那会让使用者白等一个不存在的运行，并掩盖服务端新增的错误码）。
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
| 续传 | 带 `Last-Event-ID` 时从下一条续发；缓冲已失效或已无可续内容 → **409** `run_not_resumable`，前端改走历史水合（结果与"未知"以服务端为准）。**元数据不存在时该端点为 404**，客户端同样按不可续传处置（2026-10-28：实测出现过这种 404，而运行结果已在会话真源里，重读历史就能看到回答） |
| 心跳 | 空注释行 `: ping`，每 15 秒；仅防代理超时，不承载语义 |
| 结束 | 终态事件（`run_finished` / `run_failed`）后服务端关闭流 |

**事件到 SSE 的映射就是恒等映射**，不重命名、不合并：

| 基座事件 | 实现状态 |
|---|---|
| `run_started`、`text_delta`、`progress`、`tool_call_started`、`tool_call_finished`、`citation`、`candidate`、`run_finished`、`run_failed` | 已在 `agent/runtime/events.py` 定义 |
| `reasoning_delta`、`question`、`action_card` | **已在 `agent/runtime/events.py` 定义**（2026-10-06 订正：三个事件类均已落地——`ReasoningDeltaEvent`／`QuestionEvent`（`:187`）／`ActionCardEvent`（`:191`）；发出方分别是文本增量路径、`assembly.py:184` 与 `tools/emergency_card.py`）。载荷归[通用基座](../../technical-details/通用基座.md)第 7.1／7.2／7.3 节拥有，本文不定义。**实测依据**：T27 抓取的原始 SSE 帧里含 `reasoning_delta` × 2134、`question` × 2 |

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
| `citation` | [资料与案例检索](../../technical-details/资料与案例检索.md)第 3 节返回契约（**事件流与水合响应同形**，见 §7.1） |
| `question` | [通用基座](../../technical-details/通用基座.md)第 7.2 节（**仅在事件流里出现**，见下） |
| `question-record` | 本文：`{ "batch_id": "…", "items": […], "answered": true \| false \| null }`（**仅在水合响应里出现**） |
| `action_card` | [通用基座](../../technical-details/通用基座.md)第 7.3 节（**事件流与水合响应同形**，见下） |

- `candidate` **不进历史**：它不进消息流（[项目结构设计](../../../项目结构设计.md)第 9 节），仅经 SSE 计数。
- 引用（`citation`）作为 part 与所属消息同生命周期，重放与滚动都不错位。

### 7.1 `question` / `question-record` 为什么是两个 part 类型；`action_card` 与 `citation` 为什么只有一个

两者的**载荷形状**在 `batch_id` / `items` 上相同（`items` 的元素归基座 7.2 节），
差别只有一个三态字段 `answered`。分成两个 `type` 而不是给 `question` 加一个字段，理由是
**它们描述的是两个不同时刻的事实**：

- `question` 是**流出侧**（事件）的 part：它按定义描述「刚向使用者发出、尚未作答」的提问——
  基座 7.2 节的形状里没有「已作答」，因为发出即结束运行，那一刻**不可能**有答案。
  因此它**只在事件流里出现**，水合不产出它；
- `question-record` 是**回看侧**（水合）的 part：它要回答的是「这组题当时被作答了吗」。
  把回看侧的字段塞进流出侧载荷，等于把两个时刻的事实挤进一个结构（且事件侧的字段集合
  被逐字断死，见 `apps/api/tests/test_agent_questions.py`）。

`answered` 是**三态**，语义与前端处置如下（判定**由服务端给出**，前端只读、不得自行推断）：

| 取值 | 含义 | 前端呈现 |
|---|---|---|
| `true` | 已作答 | 只读记录（**不得**再次可提交） |
| `false` | 未作答 | **可作答**（刷新后仍能补答） |
| `null` | **无法判定** | 只读记录（**fail-closed**） |

为什么 `null` 必须存在而不是归入 `false`：判据（某次提问之后、下一次提问之前的窗口内
是否有一条以作答表头开头的使用者消息）在两种情形下**没有依据**——压缩会把被保留的尾部
**复述**一遍（`agent/context/compaction.py` 的 `appended_items` 追加「检查点 + 尾部原文」，
被保留的尾部因此在历史里存在两份），以及有一条使用者消息读不出文本。
猜成「可作答」会让使用者**对同一组题作答两次**；猜成「只读」最多少修一点。
**失败方向选安全的那边**（与第 8 节的失败语义同一取向）。

**`action_card` 为什么不需要第二个 part 类型**（2026-10-06 随 T32 明确）：分与不分的
判据是「回看侧要不要说一件流出侧**不可能**说的事」。提问要（`answered` 是发出之后才可能
出现的事实），因此必须分开；行动卡**不要**——回看侧要说的事实与流出侧完全一样
（同一张卡、同五个字段，形状归基座 7.3 节）：卡片的 `card_id` 由工具在产出时生成
并随成功回执落库（`{"card_id": …, "state": "emitted"}`），水合**取回那个真值**
（不派生新值），因此刷新前后是同一个 id，前端比对 `card_id` 判旧卡失效的逻辑在两个
路径上看到的是同一套值。
⇒ `action_card` 在**事件流与水合响应里字段逐字同形**，只有一个线格式 part 类型。

⚠ **「同形」是指（`card_id` / `title` / `sections` / `states` / `annotations`）五个字段
与线格式逐个对上，不是「参数可以原样搬过来」**：落库的 `function_call.arguments`
是工具的**输入形状**，其中 `annotations` 的元素是 `{line_ref, source, confidence}`，
而线格式是 `{target, kind}`（`kind = "来源:置信"`）。水合侧要做与产出侧
`_encode_annotation_kind` 同一个转换（`str(line_ref)` + `f"{source}:{confidence}"`）——
`target` 是「按七节顺序摊平后的 1 起序号」，因此 `sections` 也按七节规范顺序排列。

**`citation` 为什么也不需要第二个 part 类型**（2026-10-07 随 T36 明确；2026-10-29 随
DEMO-03 扩为九字段）：判据与 `action_card` 完全相同——回看侧要说的事实与流出侧一样
（同一批引用、同一组字段：`citation_id` / `run_id` / `source` / `reference` /
`recorded_at` / `summary` / `status` / `applicable_scope` / `withdrawn`，与
`CitationEvent.citation` 逐字同形，也与前端 `shared/types/sse.ts` 的 `CitationRecord` 一致）。
因此 `citation` 在**事件流与水合响应里字段逐字同形**，只有一个线格式 part 类型。

**九字段里后三项的语义**（2026-10-29，DEMO-03）：

| 字段 | 含义 | 何时产出 | 缺值（`null`）时 |
|---|---|---|---|
| `status` | 产生凭据时来源的发布状态（`published` / `internal` / `fictional`） | 写侧快照，**不刷新** | 界面显示「状态未知」，**不得**默认成已发表 |
| `applicable_scope` | 产生凭据时的适用范围 | 写侧快照，**不刷新** | 界面显示「适用范围未知」 |
| `withdrawn` | 该来源**现在**还能不能作为依据 | **读回时**按当前真源重判（历史水合） | `null` = 无法核对（回指解析不了／条目已不存在／取数失败），**不**等于已撤下 |

判据：前两项回答「当时依据的是什么」，是历史事实，改写即篡改；第三项回答「现在还能不能引用」，
不刷新就会把一条已撤下的来源继续呈成可用（[资料与案例检索](../../technical-details/资料与案例检索.md)第 4 节）。
三态的服务端判定点只有一处：`surfaces/consult/citations.py` 的 `refresh_citation_freshness`
（水合路径现查条目表）；前端只读，不猜。

⚠ **该 part 此前没有生产者，水合也不重建它**（`citation` 曾登记在「不重建」一侧）。
T36 补上了两半：**生产侧**由检索工具（`search_knowledge` / `search_cases`）在返回命中
条目时发出凭据，凭据同时进 `ToolResult.citations`（→ 事件流）；**水合侧**重建 part。
⇒ 这也是一处**形状之外的实现约束**：引用载荷必须落在会话条目里，
否则「刷新后引用消失」——见 §7 上方那行「与所属消息同生命周期」。

**载荷落在会话里的哪个位置**（2026-10-07 T38 定稿）：助手消息**正文分片**
（`output_text`）自己的 `annotations` 数组里，一条引用一个注解：

```json
{"type": "citation", "citation_id": "…", "run_id": "…", "source": "knowledge",
 "reference": "knowledge:…", "recorded_at": "…", "summary": null,
 "status": "published", "applicable_scope": "学龄前·家庭场景", "withdrawn": false}
```

后三个键是 2026-10-29 加的；旧注解没有它们，读侧一律读成 `null`（未知），
「键不在」与「值为空」表示同一件事。可核对性三项随注解持久化，**不**在
`campfire_citation` 表里加列（零 schema 变更）：那张表只做 run → 回指索引。

**为什么是这里**（判据两条，都要成立）：

1. **字面满足第 5 节**——`annotations` 是**消息 content 的一部分**：它与写着正文的
   那个分片同属一个对象，不是另造的条目、也不是外挂索引；
2. **对模型不可见**——本仓用 Chat Completions 模型（`OpenAIChatCompletionsModel`），
   其输入转换器读 `content` 时**只取 `text`**（`chatcmpl_converter.py:746-747`），
   `annotations` 整段被忽略。依据区是给使用者看的，不该白占模型上下文、
   也不该让模型有机会照抄内部标识。

写侧由基座在 `add_items` **落库之前**挂上（改的是尚未落库的内存条目，
落库仍由 SDK 完成 ⇒ 会话「只追加」未破）；读侧从同一个分片读回，
**不 import 写侧实现**，键名一致由用例机械守住。判别键取 `type == "citation"`：
`annotations` 是共用字段，真实的辅助注解（例如 `url_citation`）也住在里面。

⚠ **曾经的载体（T36，已废弃）**是工具结果 JSON 的 `citations` 顶层键。
它的锚是天然的（`function_call_output.call_id` 与那次调用 1:1），
但**载荷会进模型输入**——废弃的正是这一点，不是「那条路走不通」。

## 8. 失败语义

| 情形 | 服务端 | 前端 |
|---|---|---|
| 断连 | 运行继续（订阅与运行解耦） | 带 `Last-Event-ID` 重连，指数退避 |
| 重连耗尽 | — | `.error-card` + 手动重试；**不显示空对话** |
| `run_not_resumable` | 409 | 改走历史水合；结果以服务端为准 |
| 运行流 404（元数据不在了） | 404 | 与上一行同处置：改走历史水合，**不**呈现「找不到这条内容」的死胡同卡片 |
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

- ~~**三个事件的形状已定形、事件类未落地**（2026-09-30）~~ ⇒ **已落地（2026-10-06 订正）**：`question`（第 7.2 节，一组题）、`action_card`（第 7.3 节，通用信封）、`reasoning_delta`（第 7.1 节）三个事件类**都已在 `agent/runtime/events.py` 的 `RunEvent` 联合里**（`QuestionEvent :187`、`ActionCardEvent :191`），发出方分别是 `assembly.py:184`、`tools/emergency_card.py` 与文本增量路径。**实测依据**：T27 抓取的原始 SSE 帧含 `reasoning_delta` × 2134、`question` × 2。**⇒ 提问卡、行动卡、思考区三处前端组件的数据来源均已具备。**
  **⚠ 其中一项前置也已实测解除**（2026-10-06）：原文写「`reasoning_delta` 在 SDK 事件流里的键名未实测」——
  **T27 抓取的原始 SSE 帧里 `reasoning_delta` 出现 2134 次** ⇒ **键名已确证为 `reasoning_delta`**，
  「取不到时该事件不产出、不得用文本增量冒充」这条约束**仍然有效**（它是对**未来实现**的要求，不是对现状的描述）。
- **会话归属表 `campfire_session` 尚未落地**：2026-09-30 用户裁定新增并已写入定调（[项目结构设计](../../../项目结构设计.md)第 6 节、`accounts` 用例行）与注销处置（[认证与账号](../../technical-details/认证与账号.md)第 8 节第 4 步），决策记录见[会话归属单立表归 accounts](../../decisions/会话归属单立表归accounts.md)。仍缺的是表形状与迁移，随 `modules/accounts` 实现落地。
- **事件缓冲的承载与保留时长待确认**：续传要求服务端持有本次运行的事件序列；Redis 已在技术栈内，但缓冲结构、TTL 与"运行已终结后保留多久"未定。
- **SDK 会话表仍未登记**：本契约的历史水合依赖 SDK 的 `agent_sessions` / `agent_messages`，两张表的归属与命名未定（[设计待办](../../../TODO.md)）。
- **前端文档尚未对齐本文**：[咨询对话界面](../../technical-details/咨询对话界面.md)第 3 节的 adapter 形状按"POST 直返流"写成，第 7 节的"重连上限 3 次"亦按该形状；两段式下两者需重写。登记于[设计待办](../../../TODO.md)，不在本文改动。
- **未实测**：全部端点形状均为设计结论，无运行证据；`Last-Event-ID` 续传在代理（Nginx）后的实际行为须实测。
