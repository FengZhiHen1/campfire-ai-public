## 1 功能点：AUTH-03 Token续期 — 设计文档（瘦身版）

> **文档生成时间**：`2026-05-26 22:55:58`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-26 22:55:58` | AI Assistant | 初始版本，基于 s06 技术预研报告（11 项决策 + 6 项待裁决推断）生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `AUTH-03-Token续期-意图文档.md`（已冻结）
> - 本模块的精确编码规格见 `AUTH-03-Token续期-落地规范.md`

### 1.1 技术实现思路

AUTH-03 的核心职责是**接收 Refresh Token、验证合法性、轮换签发新 Token 对、并标记旧 Token 失效**。这是一个无状态 API 端点，所有状态通过 JWT 签名和 Redis 黑名单协同维护。

**Refresh Token 轮换机制（防止重放攻击）**

轮换是 AUTH-03 最核心的安全机制。每次续期成功后，旧的 Refresh Token 立即失效，签发全新的 Token 对。技术实现采用"先全部校验通过，再原子标记失效"的流程：

1. JWT 签名验证（确认 Token 未被篡改、未过期）
2. Redis 黑名单查询（确认 Token 未被轮换、未被吊销）
3. 用户角色查询（从数据库获取最新角色信息）  
4. 旧 Token 原子标记轮换（Redis `SET NX` 写入 `token_blacklist:rotated:{jti}`）
5. 签发新 Token 对（Access Token + Refresh Token）

步骤 4 与步骤 5 之间存在关键竞态窗口——如果在旧 Token 标记轮换后、新 Token 签发前进程崩溃，用户将失去所有有效凭证。需要通过在 Redis 中写入时附带客户端生成的 `request_id`，允许用户用相同 `request_id` 重试（服务端幂等保护）。此细节留待落地规范 §1.9 异常处理中精确约定。

**并发续期安全**

同一 Refresh Token 可能被两个并发请求同时发起续期。若不加保护，两个请求可能同时通过校验（步骤 1-3），各自完成轮换，导致 Token 被"双重消费"。解决方案是：在步骤 4 使用 Redis `SET NX`（SET if Not Exists）原子操作——以 Refresh Token 的 `jti` 为 key 写入黑名单。仅第一个请求能成功写入，第二个请求的 `SET NX` 将失败，被判定为 Token 已轮换并拒绝。

**JWT 共享基础设施**

Access Token 与 Refresh Token 共用同一 JWT 签名密钥（HS256，`JWT_SECRET_KEY`），通过 payload 中的 `type` 字段区分（`"access"` 或 `"refresh"`）。共用密钥的理由：
- `packages/py-auth/jwt_utils.py` 已是项目 JWT 管理的单一真相来源，共用签名密钥减少密钥管理复杂度
- 两种 Token 的核心结构几乎相同（`sub`、`jti`、`exp`），区别仅在于有效期和用途
- 签发新的 Refresh Token 时复用 `create_token()` 函数（受意图文档约束，SEC-01 已定义该契约），通过 `purpose` 参数控制 `type` 字段值

**Redis 不可用降级**

采用与 AUTH-04 一致的 fail-open 策略：Redis 不可用时跳过黑名单查询（步骤 2），仅依赖 JWT 签名验证（步骤 1）。这意味着在 Redis 故障窗口（通常为秒级）内，已被轮换或吊销的 Refresh Token 将被短暂放行。但这个安全窗口与 Refresh Token 剩余有效期一致（最多 7 天），而 Redis 故障属于低概率事件。fail-closed 将导致所有续期请求被拒绝，迫使全部用户重新登录，业务影响过大。

**数据流概览**

```
客户端 POST /api/v1/auth/refresh {refresh_token: "..."}
  → Nginx (HTTPS 终结)
    → SEC-05 输入校验 (Depends, Body 格式校验)
      → SEC-04 防刷限流 (中间件, 用户级 30 req/min)
        → AUTH-03 续期处理:
          ① jwt_utils.verify_token(refresh_token) → TokenPayload
          ② 校验 type == "refresh"
          ③ redis.exists(f"token_blacklist:rotated:{jti}")
          ④ redis.exists(f"token_blacklist:revoked:{jti}")
          ⑤ user_repository.get_user_roles_by_id(sub) → roles
          ⑥ redis.set(f"token_blacklist:rotated:{jti}", "1", nx=True, ex=7days)
          ⑦ jwt_utils.create_token(sub, roles, type="access", expires=15min)
          ⑧ jwt_utils.create_token(sub, roles, type="refresh", expires=7days)
        → 响应 {access_token, refresh_token, token_type: "Bearer"}
```

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：
  - `AUTH-01-用户注册-设计文档.md`（v1.0，已冻结）
  - `AUTH-04-五级RBAC鉴权-设计文档.md`（v1.0，已冻结）
  - `SEC-01-传输存储安全-设计文档.md`（v1.0，已冻结）
  - `SEC-04-防刷限流-设计文档.md`（v1.0，已冻结）
  - `SEC-05-输入校验防护-设计文档.md`（v1.0，已冻结）
  - `KNOW-01-科普内容管理-设计文档.md`（v1.0，已冻结）

- **兼容性结论**：
  - **JWT 签名密钥兼容**：本模块复用 `packages/py-auth/jwt_utils.py` 的 `create_token()` 和 `verify_token()`，使用相同的 `JWT_SECRET_KEY` 和 `JWT_ALGORITHM=HS256`。与 AUTH-02（签发方）和 AUTH-04（消费方）完全兼容。
  - **TokenPayload 结构兼容**：SEC-01 定义的 `TokenPayload`（含 `sub`、`roles`、`kid`、`exp`、`iat`）为最小必需结构。本模块在此基础上增加 `jti`（JWT 标准声明，用于黑名单标识）和 `type`（区分 access/refresh Token），通过 JWT 现有声明扩展实现，不违反 SEC-01 契约的接口定义。
  - **Redis 黑名单 Key 前缀协作**：AUTH-04 当前设计使用 `token_blacklist:{jti}` 作为角色变更失效 key。本模块的轮换黑名单使用 `token_blacklist:rotated:{jti}`，通过不同前缀实现同一 Redis 实例下的命名空间隔离。建议 AUTH-04 后续迭代时将其 key 前缀调整为 `token_blacklist:revoked:{jti}`，与 `token_blacklist:rotated:{jti}` 形成清晰的命名空间体系。
  - **降级策略一致**：本模块采用与 AUTH-04 一致的 fail-open 策略（Redis 不可用时跳过黑名单查询），两模块降级行为对齐。
  - **错误响应格式一致**：使用 `{"detail": "..."}` 格式 + HTTP 401 状态码，与 AUTH-04、SEC-01、SEC-05 的统一错误格式一致。
  - **API 路径兼容**：`POST /api/v1/auth/refresh` 在项目结构设计 §7.3 场景三中已预留，不与 `POST /api/v1/auth/login` 等其他端点冲突。

- **复用的已有设计**：
  - `create_token()` 和 `verify_token()` 函数签名（SEC-01 契约）
  - `TokenPayload` 数据结构（SEC-01 契约，含 `sub`、`roles`、`kid`、`exp`、`iat`）
  - `{"detail": "..."}` 错误响应格式（KNOW-01/AUTH-04/SEC-01/SEC-05 统一规范）
  - `request.state.user` 请求状态上下文（AUTH-02 注入约定）

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| `packages/py-auth/jwt_utils.py` | 调用 | `create_token(sub, roles, **kwargs)` 签发 Access Token 和 Refresh Token；`verify_token(token)` 校验 JWT 签名、过期时间和 `type` 字段 |
| `packages/py-cache/client.py` | 读写 | Redis 黑名单操作：`sadd()`（写入吊销集合）、`get()`（查询黑名单，因本模块使用 String `SET NX` 而非 Set）、`exists()`（检查 jti 是否在轮换黑名单中）、`set()`（带 `nx=True`，原子标记轮换） |
| `packages/py-db/repositories/user_repository.py` | 只读 | `get_user_roles_by_id(user_id)` 查询用户最新角色列表，用于在新 Access Token 中携带最新角色信息 |
| `packages/py-config/config.py` | 配置来源 | 读取 `JWT_SECRET_KEY`、`JWT_ALGORITHM`、`ACCESS_TOKEN_EXPIRE_MINUTES`、`REFRESH_TOKEN_EXPIRE_DAYS`、`REDIS_URL` |
| AUTH-02 用户登录 | 上游数据来源 | 登录时签发的 Refresh Token 由 AUTH-03 消费。两模块共享 JWT 签名密钥、payload 格式（`sub`、`jti`、`type`）和 Redis 黑名单基础设施 |
| AUTH-04 五级RBAC鉴权 | 下游数据消费 | 续期后新 Access Token 中的 `roles` 字段由 AUTH-04 的 `require_role()` Depends 直接消费 |
| AUTH-06 认证会话管理 | 下游调用方 | 前端 HTTP 拦截器在 401 响应时自动调用 `POST /api/v1/auth/refresh`；本模块返回的新 Token 对由 AUTH-06 存储和注入 |
| SEC-04 防刷限流 | 受保护 | 续期端点受 SEC-04 的滑动窗口限流中间件保护（用户级 30 req/min，IP 级 100 req/min） |
| SEC-05 输入校验防护 | 上游拦截 | 续期请求体经 SEC-05 的 Depends 链校验（`refresh_token` 字段存在性校验、SQL 注入/XSS 防护），通过后才进入 AUTH-03 处理逻辑 |

### 1.4 状态机设计（技术实现策略）

Refresh Token 状态机为**单向二态**（valid → invalid），不可逆。所有路径一旦进入 `invalid` 即为终态。

```
            ┌──────────────────────────────────────────────┐
            │                                              │
            ▼                                              │
      ┌──────────┐    续期成功（轮换）     ┌──────────┐    │
      │  VALID   │ ──────────────────►    │ INVALID  │    │
      │          │                        │          │    │
      │ 可发起    │    7天自然过期         │ 拒绝续期  │    │
      │ 续期请求  │ ──────────────────►    │          │    │
      │          │                        │  （终态）  │    │
      │          │    用户注销/管理员      │          │    │
      │          │    吊销→加入黑名单       │          │    │
      └──────────┘ ──────────────────►    └──────────┘    │
            │                                              │
            └──────────────────────────────────────────────┘
                      （所有路径均不可逆）
```

**技术实现策略**：

- **持久化策略**：Refresh Token 的有效性不依赖数据库行状态，而是通过**密码学签名验证**（JWT 签名校验 + `exp` 检查）+ **Redis 黑名单**（检查 `jti` 是否在黑名单中）共同判定。这种设计的优势是无需维护 Token 状态表，避免数据库写入瓶颈。
- **有效判定逻辑**：JWT 签名合法 + `exp` 未过期 + `type == "refresh"` + `jti` 不在 `token_blacklist:rotated:` 中 + `jti` 不在 `token_blacklist:revoked:` 中。
- **轮换失效机制**：续期成功时，旧 Refresh Token 的 `jti` 通过 Redis `SET NX` 原子操作写入 `token_blacklist:rotated:`，TTL = `REFRESH_TOKEN_EXPIRE_DAYS`（7 天）。
- **吊销失效机制**：用户注销或管理员吊销时，所有当前有效 Token 的 `jti` 写入 `token_blacklist:revoked:`（与 AUTH-04 角色变更失效共享此命名空间）。
- **幂等策略**：续期操作本身不是幂等的（轮换是一次性操作）。为防止并发续期导致竞态条件，在步骤 4 使用 Redis `SET NX` 原子操作确保仅一个请求能完成轮换。

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| 项目结构 §三 | 厚 package、薄 app | 续期核心逻辑集中在 `packages/py-auth/py_auth/jwt_utils.py`（签发校验）和 `packages/py-auth/py_auth/blacklist.py`（黑名单管理）。`apps/api-server` 仅通过路由端点调用，不包含 Token 处理实现 |
| 项目结构 §三 | 前后端契约先行 | `TokenRefreshRequest`、`TokenRefreshResponse`、`TokenRefreshError` 类型在 `packages/py-schemas` 中定义，与前端 `ts-shared` 中的类型一致。API 路径 `POST /api/v1/auth/refresh` 已在项目结构 §7.3 中约定 |
| 项目结构 §三 | 单向依赖 | AUTH-03 依赖 AUTH-02（JWT 签发）和 SEC-04（限流），不反向依赖任何下游模块。AUTH-04 和 AUTH-06 依赖 AUTH-03，方向正确 |
| ADR-004 | 模块化单体 | 续期逻辑通过 `packages/py-auth` package 内的函数实现，不引入独立 Token 服务。模块边界通过 Python import 维持，后续可独立拆出为微服务 |
| 技术栈设计 §5 | 安全设计 — 认证 | JWT HS256 + Refresh Token 轮换 + Redis 黑名单三重机制直接兑现技术栈设计中"Token 轮换防止重放攻击"的安全决策。续期端点受 SEC-04 限流保护，兑现"敏感操作需限流"的安全约束 |
| 技术栈设计 §3.2 | 数据流向 | 续期处理在路由处理函数中同步完成，不侵入业务逻辑，符合关注点分离原则。黑名单写入通过 `packages/py-cache` 异步写入避免阻塞响应 |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|----------|
| 轮换检测方式 | Redis SET NX 黑名单记录已轮换 jti | Token 版本号（v1/v2） / 一次性 Token 数据库表 | Redis 方案与 AUTH-04 的 jti 黑名单机制共用基础设施，无需新增数据库表。SET NX 是原子操作，天然处理并发竞态。TTL 自动过期避免无限增长 |
| 并发轮换安全 | Redis `SET NX` 原子操作 | 分布式锁（Redlock）/ 数据库悲观锁 | SET NX 比分布式锁更轻量，操作数与黑名单写入合并，减少一次 Redis 往返。锁方案需处理锁超时和死锁，复杂度更高（受意图文档约束——轮换必须即时生效，不能引入外部状态） |
| Redis 不可用降级 | fail-open（跳过黑名单查询） | fail-closed（拒绝所有续期请求） | fail-closed 将导致全部用户被强制重新登录，业务影响过大。fail-open 的安全窗口 = Refresh Token 剩余有效期（最多 7 天），与 AUTH-04 降级策略一致 |
| JWT 类型区分 | payload `type` 字段（`"access"` / `"refresh"`） | 不同加密密钥 / 不同签发函数 | `type` 字段是 JWT 标准实践，无需增加密钥管理复杂度。通过同一 `verify_token()` 函数校验时过滤 `type` 值即可防止 Refresh Token 被误用于业务端点 |
| 角色信息获取 | 续期时实时查询数据库 | 从旧 Refresh Token payload 中原样复制 | 实时查询保证新 Access Token 携带用户最新角色（受意图文档 §1.11 约束 4 约束）。从旧 Token 复制会在角色变更后延续错误信息 |
| 旧 Access Token 有效期 | 保持有效至自然过期（不提前失效） | 续期时立即失效旧 Access Token | 意图文档 AC-07 明确要求此行为。技术上，旧 Access Token 的 15 分钟并行窗口是可接受的，角色变更由 AUTH-04 的 Redis 黑名单独立处理 |
| Refresh Token 黑名单 TTL | 7 天（REFRESH_TOKEN_EXPIRE_DAYS） | 剩余有效期（动态计算） | 以最大生命周期覆盖保证安全——轮换时难以精确计算旧 Refresh Token 的剩余有效期（可能已被部分消耗）。Redis TTL 自动过期清理，不增加运维负担 |
| 续期失败错误码 | HTTP 401（所有失败场景） | 400（格式错误）/ 403（权限不足） | 401 语义"未通过认证"，与 AUTH-04 的 Token 校验失败返回码一致。续期失败本质是"Token 无法证明用户身份"，非"已认证但无权限"（403） |

**业务矛盾处理记录**（以下矛盾来自上游 s06 技术预研报告 §5，当前阶段基于报告推荐方案做出最佳推断）：

| # | 矛盾点 | 推断结论 | 推断依据 |
|---|--------|----------|----------|
| 1 | JWT 密钥轮换策略 | 采用 SEC-01 已定义的轮换机制：90 天轮换 + 7 天共栖期 + `kid` 字段标识密钥版本。续期操作中，验证时尝试新旧两个密钥（根据 `kid` 选择），任一通过即视为有效；签发时始终使用当前密钥 | SEC-01 设计文档已确立 90 天轮换 + 7 天共栖期方案，且 7 天对齐 Refresh Token 最大有效期。AUTH-03 作为 Token 消费方和签发方，直接遵循此全局约定 |
| 2 | Redis 黑名单自动清理粒度 | 仅依赖 Redis TTL 自动过期（惰性删除），不引入额外的定时主动清理。监控阈值：黑名单 key 总数 > 10000 时 Prometheus 告警 | Refresh Token 已轮换黑名单的 TTL 为 7 天，同用户每 7 天最多积累 7 个 jti 条目，设计容量可控。惰性删除无运维负担 |
| 3 | 续期接口响应体格式 | `{access_token: str, refresh_token: str, token_type: "Bearer"}` 平铺结构；错误 `{"detail": "..."}` | s06 报告推荐平铺结构，项目目前无全局 API 响应包装规范；`{"detail": "..."}` 与 KNOW-01、AUTH-04、SEC-01 已有模块一致 |
| 4 | 连续续期失败安全限制 | 时间窗口 5 分钟，阈值 5 次失败，触发后封禁该 `user_id` 的续期能力 15 分钟 + 要求重新登录。计数通过 Redis 以 `rate_limit:refresh_fail:{user_id}` 为 key 记录 | 窗口和阈值与 SEC-04 用户级限流参数（30 req/min）形成梯度防御：短时高频由 SEC-04 拦截，中频持续失败由本模块封禁。15 分钟封禁对齐 Access Token 有效期 |
| 5 | Redis 降级策略一致性 | 采用与 AUTH-04 一致的 fail-open 策略（跳过黑名单查询，仅依赖 JWT 签名验证） | s06 报告明确建议与 AUTH-04 保持一致。fail-open 的安全窗口（最多 7 天）与 Redis 低故障概率结合，风险可控 |
| 6 | 旧 Access Token 并行有效期安全性 | 接受 15 分钟并行窗口。若角色在续期间隔内变更，旧 Access Token 通过 AUTH-04 的 Redis 黑名单独立处理（角色变更时写入吊销黑名单） | 意图文档 AC-07 明确要求旧 AT 保持有效。角色变更导致的 Token 失效是 AUTH-04 的独立职责，AUTH-03 不参与此逻辑 |

> 以上推断结论未经用户确认。若用户后续有明确裁决，以用户裁决为准更新设计文档。

### 1.7 注意事项与禁止行为（设计层面）

1. **[JWT payload 字段命名一致性]** `sub`（用户 UUID 字符串）、`roles`（英文小写字符串列表）、`jti`（Token 唯一 UUID）、`exp`（UNIX 时间戳）、`type`（`"access"` 或 `"refresh"`）。所有字段名必须与 AUTH-02（签发方）和 AUTH-04（消费方）保持一致。禁止使用 `user_id` 替代 `sub`、禁止使用 `role_names` 替代 `roles`。

2. **[Redis Key 前缀隔离]** 轮换黑名单使用 `token_blacklist:rotated:{jti}`，吊销黑名单使用 `token_blacklist:revoked:{jti}`。禁止混用不同前缀的语义，禁止直接使用 `token_blacklist:{jti}`（无子命名空间），否则 AUTH-04 的角色变更失效可能与轮换黑名单发生语义混淆。

3. **[并发续期的 SET NX 原子性]** Redis `SET NX` 必须在"所有校验通过后、新 Token 签发前"执行。禁止在 SET 之前提前返回给客户端——必须确保 SET NX 成功后才签发新 Token。若 SET NX 失败（key 已存在），返回与"Token 已被轮换"相同的错误信息（信息最小化，不区分"已轮换"和"已被吊销"）。

4. **[禁止将 Refresh Token payload 中的角色原样复制到新 Token]** 续期时必须通过 `user_repository.get_user_roles_by_id()` 实时查询数据库获取最新角色，不得从旧 Refresh Token 的 `roles` 字段复制。否则角色变更无法在新 Access Token 中生效（违反意图文档 §1.11 约束 4）。

5. **[信息最小化约束]** 续期失败的响应仅返回用户可理解的业务提示（如 `"登录凭证已失败，请重新登录"`），不透露 Token 结构、签名密钥、黑名单逻辑或具体失败原因（如"Token 已轮换"vs"Token 已吊销"）。此约束直接源于意图文档 §1.11 约束 5。

6. **[设计边界]** 本模块不负责用户身份的首次认证（登录验证、密码校验——归 AUTH-02）、权限校验（归 AUTH-04）、前端的 Token 存储和自动续期触发（归 AUTH-06）、限流执行（归 SEC-04）。AUTH-03 仅负责：Refresh Token 验证、角色信息查询、Token 轮换和新 Token 签发。

7. **[禁止绕过黑名单查询]** 在任何条件下（包括 `DEBUG=True`），续期接口的第 2 步（Redis 黑名单查询）不得被跳过或短路（Redis 不可用降级除外）。严禁在代码中 via 配置开关绕过黑名单查询的安全门控。

8. **[与 AUTH-02 的 jti 格式约定]** `jti` 通过 `uuid4()` 生成，字符串格式（无连字符或标准 UUID 格式）。AUTH-02 在签发 Refresh Token 时同样使用此格式生成 `jti`，AUTH-03 必须与 AUTH-02 使用相同的 UUID 生成方式，否则 `jti` 格式不一致将导致黑名单无法匹配。

### 1.8 引用：配套意图文档

- **意图文档**：`AUTH-03-Token续期-意图文档.md`
- **冻结时间**：`2026-05-26 22:48:27`
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。如有歧义，以意图文档为准。
- **技术决策来源**：本设计文档所依据的完整技术决策分析见 `.tmp/reports/tech-decision-report-AUTH-03.md`。
