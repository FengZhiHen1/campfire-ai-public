# 档案面 HTTP 契约

> **权威范围**：档案面（支持对象档案的查看、确认、纠正、删除与对象管理）对前端暴露的端点形状——请求与响应载荷、越权与失败语义。**档案条目的字段、稳定层与候选层、十四个一级模块、纠正规则归[个性化档案](../../technical-details/个性化档案.md)**；**对象实体、生命周期、绑定与授权端口归[支持对象](../../technical-details/支持对象.md)**；本文档只定"怎么传"，不定"存什么"。
> **状态**：2026-09-30 依已确认的档案机制、支持对象与页面设计成形，**待用户确认**。不代表已实现：`modules/profile` 当前是零实现占位包。
> **追溯**：`RQ-MEM-02`～`RQ-MEM-07`、`RQ-ACC-01`、`AC-07`、`AC-08`、`AC-18`、`AC-22`、`AC-27`、`AC-32`。
> **依据**：认证不建面、会话凭据经 httpOnly cookie 与 anti-CSRF 头（[认证与账号](../../technical-details/认证与账号.md)第 5 节）；越权文案纪律（[支持对象](../../technical-details/支持对象.md)第 5.3 节）；归属判定真源 `campfire_session`（[决策记录](../../decisions/会话归属单立表归accounts.md)）。

## 1. 形状与通用约定

档案面的端点**不是**咨询面的一部分，也不经 Agent 基座——它们直接调 `modules/profile` 的用例（与认证端点同法，见[项目结构设计](../../../项目结构设计.md)第 5 节：面指"产品入口与 Agent 运行装配"，而这些端点不装配运行）。

| 约定 | 内容 |
|---|---|
| 鉴权 | 全部端点须登录（`RQ-ACC-01`）；凭据经 httpOnly cookie，anti-CSRF 头由官方前端 SDK 注入 |
| 越权 | 对象不属于当前账号 → **404**，文案与"对象不存在"逐字相同（不泄露存在性） |
| 归档对象 | **可读**（列表、摘要、条目、纠正与删除条目都可用）；**不可新增写入**——创建条目在归档对象上返回 **409** `object_archived`，且文案**区分**于越权（属主自己的对象，使用者需要知道原因才能去恢复） |
| 幂等 | 纠正与删除各自幂等；重复删除返回 200 并带 `already: true`，不报错 |
| 传输 | 普通 JSON（`application/json`），不是 SSE——本面没有流式输出 |

**错误码**：

| 码 | 情形 |
|---|---|
| 401 | 会话过期或未登录 |
| 404 | 对象／条目不存在，或不属于当前账号 |
| 409 | `object_archived`（在归档对象上新增） |
| 422 | 载荷不合法（空描述、未知领域名、纠正无变更） |

## 2. 支持对象端点

### 2.1 列表与创建

```text
GET  /api/profile/objects
响应 200：{ "items": [ { "id": "uuid", "display_name": "…", "archived_at": null } ] }

POST /api/profile/objects
请求：{ "display_name": "…" }
响应 201：{ "id": "uuid", "display_name": "…", "archived_at": null }
```

- 列表**含已归档对象**（`archived_at` 非空），前端据此在切换器里标"已归档"（[档案页](../../../design/pages/档案页.md)第 16 行）。
- 创建即[档案页](../../../design/pages/档案页.md)「+ 新建对象」表单的落点，与对话中的 `create_support_object` 工具**走同一创建用例**——对话式创建是一等入口，表单是补充路径（[决策记录](../../decisions/一次性引导对话.md)）。属主取登录态，不接受调用方传入。
- 空名（去空白后为空）→ **422**；存储层 CHECK 亦兜底。同名不拒（[支持对象](../../technical-details/支持对象.md)第 3 节）。

### 2.2 改名、归档、恢复

```text
PATCH /api/profile/objects/{id}
请求：{ "display_name": "…", "archived": true | false }
响应 200：{ "id": "uuid", "display_name": "…", "archived_at": "… 或 null" }
```

- 三个操作合在一个端点上，因为它们都是同一个状态位的赋值（`display_name` 或 `archived_at`），拆成三个端点会让"改名"与"归档"各自带一份相同的越权判定。
- **归档与恢复幂等**：重复归档不报错（只刷新 `archived_at`）；重复恢复保持为空。
- **改名不触碰档案**：历史条目的来源与内容不随改名变化。

## 3. 档案读取端点

```text
GET /api/profile/objects/{id}/summary
响应 200：{ "fields": [ { "key": "...", "label": "...", "items": [ … ] } ] }

GET /api/profile/objects/{id}/items?domain=&include_candidates=&cursor=&limit=
响应 200：{ "items": [ … ], "candidates": [ … ], "next_cursor": null }
```

- 摘要的十二个字段与取数领域归[个性化档案](../../technical-details/个性化档案.md)第 4 节；**只取稳定层**，每条带 `item_id`、`origin` 与 `last_confirmed_at`。
- 条目列表的形状即该文档第 2 节，必须含 `origin`、`confirmation`、`freshness`。
- **候选条目单独成组返回**（`candidates`），不混进 `items`：这是[档案页](../../../design/pages/档案页.md)「候选层视觉不变量」的服务端侧保证——`AC-18` 要求未确认内容只能出现在"待确认"分组，由**返回结构**保证而不是靠前端自己分。
- `confirmation = rejected` 与 `superseded_by` 非空的条目一律不返回。

## 4. 确认、纠正、删除

三个动作都是**使用者显式意图**，经 HTTP 承载（[个性化档案](../../technical-details/个性化档案.md)第 8 节：调用方是档案面与对话页的确认入口，**不是模型可见工具**）。

```text
POST /api/profile/items/{item_id}/confirm
响应 200：{ "item_id": "…", "confirmation": "confirmed" }

POST /api/profile/items/{item_id}/correct
请求：{ "description": "…", "topic": "… 可选", "contexts": [...], "manifestations": [...] }
响应 201：{ "item_id": "新条目", "supersedes": "旧条目 item_id" }

DELETE /api/profile/items/{item_id}
响应 200：{ "item_id": "…", "already": false }
```

- **确认**只能作用于候选条目（`confirmation = unconfirmed`）；对已确认或已否定的条目返回 **422**。确认后该条目进稳定层。
- **纠正 = 新增取代条目**，旧条目转 `historical` 并互指（`superseded_by`），**不物理覆盖**。纠正的载荷是**新条目的完整形状**而不是补丁字段——档案条目是"谁在何时说的"的记录，补丁会让新条目继承旧条目的来源与时间，那才是真正的污染。
- **删除须覆盖该内容在检索与衍生中的使用**（`RQ-MEM-03`、`AC-08`）。它与"纠正"的区别是：删除不留取代条目；`rejected` 是**另一条路径**（使用者否定一条候选），不在这里表达。
- **删除与纠正都带二次确认**（[档案页](../../../design/pages/档案页.md)的 `.confirm-sheet`）。二次确认是**前端交互**，服务端不做"猜你不是故意的"——重复删除幂等返回 200，不报错。

### 4.1 否定（拒绝一条候选）

```text
POST /api/profile/items/{item_id}/reject
响应 200：{ "item_id": "…", "confirmation": "rejected" }
```

与删除分开，因为语义不同：`rejected` 表示"使用者否定过这件事"，**不物理删除**（"否定过"本身是可追溯事实），此后不进摘要、不参与注入、**不得再次作为候选提出**（[个性化档案](../../technical-details/个性化档案.md)第 2 节）。放在删除端点里会丢掉这个语义。

## 5. 补充条目

```text
POST /api/profile/objects/{id}/items
请求：{ "domain": "…", "topic": "…", "description": "…", "contexts": [], "manifestations": [] }
响应 201：{ "item_id": "…" }
```

即[档案页](../../../design/pages/档案页.md)「补充一条」的落点（[个性化档案](../../technical-details/个性化档案.md)第 5.2 节允许使用者补充）。`origin` 由服务端定为 `user_statement`，**不接受调用方传入**——生成方式不是使用者可选的字段。

## 6. 失败语义

| 情形 | 服务端 | 前端 |
|---|---|---|
| 对象／条目越权或不存在 | 404，文案与"不存在"逐字相同 | 错误提示，不重试 |
| 归档对象上新增 | 409 `object_archived`，文案区分于越权 | 提示已归档 + 引导恢复 |
| 删除后取数仍返回该条目 | 不允许（`AC-08` 的验收对象） | — |
| 401 | — | 清状态跳登录 |

## 7. 边界

| 内容 | 归谁 |
|---|---|
| 条目字段、领域取值、稳定层与候选层、纠正规则 | [个性化档案](../../technical-details/个性化档案.md) |
| 对象实体、生命周期、绑定、授权端口与默认推导 | [支持对象](../../technical-details/支持对象.md) |
| 归属与访问判定 | `core/authz`（一期属主即允许） |
| 咨询面的端点与 SSE | [HTTP/SSE 契约](../consult/HTTP与SSE契约.md) |
| 记忆的查看/纠正/删除 | [记忆面契约](记忆面HTTP契约.md) |
| 案例与资料的浏览/检索 | [资料库面契约](资料库面HTTP契约.md) |
| 视觉与交互 | [档案页](../../../design/pages/档案页.md) |

## 8. 已知偏差与证据边界

- **`modules/profile` 是零实现占位包**（2026-09-30 实测：`git ls-files` 只跟踪 `__init__.py`）。本契约的全部端点与三个档案工具（`read_profile_summary`、`read_profile_items`、`propose_profile_item`）都前置于该包的实现与迁移。
- **对象创建/改名/归档的用例与本文档同批落地**：[支持对象](../../technical-details/支持对象.md)已定实体形状与生命周期，但没有 HTTP 载体，本文档是它的第一份。
- **未实测**：全部端点形状均为设计结论，无运行证据。
- **`pending_write.origin` 仍只接受四值**（缺 `third_party_report`、`document`），与本面"补充条目"及 `propose_profile_item` 的六值契约不同步；须随 `modules/profile` 实现同批补 CHECK 迁移（登记于[设计待办](../../../TODO.md)）。
