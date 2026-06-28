## 1 功能点：AUTH-02 用户登录 — 设计文档（瘦身版）

> **文档生成时间**：2026-05-26 23:08:01
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 23:08:01 | AI Assistant | 初始版本，基于 s06 技术决策报告（14 项决策确定 + 6 项待裁决推断）生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `AUTH-02-用户登录-意图文档.md`（已冻结，v2.0，2026-05-26 22:47:13）
> - 本模块的精确编码规格见 `AUTH-02-用户登录-落地规范.md`

### 1.1 技术实现思路

用户登录是一个**无状态的单次请求-响应操作**——接收用户提交的凭据（用户名 + 密码），经四层验证（存在性 → 密码 → 账号状态 → 签发）后返回访问凭证，或返回统一错误提示。

**为什么选择单步登录而非多阶段流程**：意图文档 §1.5 的用户旅程包含"输入凭据 → 提交 → 验证 → 签发"四个步骤，但从技术视角看，输入凭据和提交是纯前端交互，服务端只处理一次 POST 请求。本模块将服务端实现为一个原子 HTTP endpoint——要么全部通过（返回双令牌），要么全部拒绝（返回错误提示）。不引入服务器端会话状态、不支持分步认证（如先验证用户名再验证密码），避免了分布式状态一致性开销，且符合意图文档 §1.7 的"一次性的请求-响应操作"定位。

**数据流设计**：采用"格式校验（路由层）→ 用户查询 → 密码校验 → 账号状态检查 → 令牌签发 → 审计日志"五个阶段。每阶段失败即中断并返回对应错误，不进入后续阶段。与 AUTH-01 的 7 步注册流程采用相同的编排模式（技术决策报告 #13）。

1. **格式校验阶段（路由层）**：Pydantic `LoginRequest` Schema 在路由层通过 `Depends()` 自动拦截格式错误——`username` 长度 4-32 字符、`password` 长度 >= 8。缺失必填字段或长度不满足时，FastAPI 自动返回 422（与 SEC-05 自定义 422 格式一致）。**注意**：仅校验字段存在性和长度，不校验用户名是否存在或密码是否正确——这些是 Service 层职责。
2. **用户查询阶段**：调用 `UserRepository.find_by_username_lower(username)` 执行大小写不敏感的用户名查询。该函数已在 `user_repository.py` 中实现，使用 `LOWER()` SQL 函数 + B-tree 索引，查询耗时 <5ms。若用户不存在 → 不区分"用户名不存在"和"密码错误"，统一返回"用户名或密码错误"（意图文档 §1.8.1）。
3. **密码校验阶段**：调用 `packages/py-auth/hashing.py` 的 `verify_password(plain, hashed)` 执行 bcrypt 哈希比对。该函数约耗时 250ms（与注册时 `hash_password()` 一致），在总登录响应时间（约 300ms）中占比合理。若密码不匹配 → 同样返回统一提示"用户名或密码错误"。**关键安全策略**：无论用户名是否存在，都执行 `verify_password()`（对不存在的用户使用一个 dummy hash 进行固定时间比对），防止通过响应时间侧信道泄露用户名存在性。
4. **账号状态检查阶段**：检查用户的 `is_active` 字段（见 §1.6 矛盾处理记录）。若 `is_active=False` → 返回"当前账号无法登录，请联系管理员"（意图文档 §1.8.3）。注意：此阶段在密码校验通过后才执行，避免通过错误提示差异泄露账号状态信息。
5. **令牌签发阶段**：两步并行签发——
   - **访问令牌**：调用 `create_access_token(data={"sub": user_id, "roles": [role], "jti": uuid4()})`，expires_delta 默认 15 分钟（900 秒）。
   - **续期令牌**：调用 `create_access_token(data={"sub": user_id, "roles": [role], "token_type": "refresh"}, expires_delta=timedelta(days=7))`，通过 `token_type` claim 区分令牌类型（技术决策报告 #5）。
   - `jti`（JWT ID）claim 用于支持 AUTH-04 的角色变更后 Token 实时失效（Redis 黑名单查询），和 AUTH-03 的续期令牌轮换（旧 `jti` 标记已使用）。
6. **审计日志阶段**：调用 `logger.critical(op_type="USER_LOGIN", extra={user_id, username, success, role, ip})`。与 AUTH-01 的 `USER_REGISTER` 日志格式完全一致（技术决策报告 #14），采用 `asyncio.create_task()` 异步投递——日志写入失败不阻塞登录成功结果。

**续期令牌轮换的职责边界**：AUTH-02 仅负责**签发**续期令牌（`token_type: "refresh"` claim），不负责其后续的轮换逻辑。续期令牌的使用和轮换（旧令牌作废 + 签发新令牌）归属 AUTH-03（Token续期）。本模块在签发续期令牌时为其分配唯一的 `jti` 和 7 天有效期，满足 AUTH-03 轮换机制的数据基础。

**暴力破解防护的职责分离**：本模块不内置登录失败计数器。登录失败事件通过审计日志（`success=False`）和结构化日志（包含 `username` 和 `ip`）输出，由 SEC-04（防刷限流）模块统一进行滑动窗口计数和限流拦截。这一分离保持 AUTH-02 的业务逻辑纯粹性，将安全策略集中在 SEC-04 中管理。

> **业务矛盾推断 #1（续期令牌轮换）**：本报告采纳技术决策报告推荐的简单轮换模式（"旧令牌作废 + 签发新令牌"），不支持轮换历史追溯。并发安全性通过 Redis SETNX 原子操作保证——两个并发续期请求中，仅第一个成功标记旧 `jti` 为已使用并签发新令牌，第二个发现旧 `jti` 已被消费则返回 401。此决策的正式确认权归属 AUTH-03（Token续期）的规范阶段，AUTH-02 仅需确保签发的续期令牌包含 `jti` 和正确 TTL。
>
> **业务矛盾推断 #2（令牌精确有效期）**：采纳技术决策报告推荐值，直接沿用技术栈预设配置——`ACCESS_TOKEN_EXPIRE_MINUTES=15`（900 秒），`REFRESH_TOKEN_EXPIRE_DAYS=7`（604800 秒）。不设过期宽容窗口（令牌过期后立即拒绝），因为在登录场景中，令牌为即时签发，不存在时钟偏差导致的"签发即过期"问题。若后续 AUTH-03 续期环节需要宽容策略，由其规范阶段决定。
>
> **业务矛盾推断 #3（暴力破解防护）**：按用户名计数（非 IP）。推荐阈值：同一用户名 5 次失败 / 15 分钟窗口 → 该用户名临时锁定 15 分钟。计数器在成功登录后重置。此策略的具体参数和 Redis 滑动窗口实现归属 SEC-04，AUTH-02 通过审计日志（`op_type="USER_LOGIN"`, `success=False`）提供计数数据源。
>
> **业务矛盾推断 #4（User 模型 is_active 字段）**：现有 `User` ORM 模型（`packages/py-db/py_db/models/auth.py`）不包含 `is_active` 字段。本报告确定该字段为**必须新增**——缺少它将导致"账号禁用"异常场景（意图文档 §1.8.3）无法实现，属于高风险项。新增方案：(1) 在 `User` 模型中添加 `is_active: bool = True` 字段；(2) 创建 Alembic 迁移脚本添加 `is_active BOOLEAN DEFAULT TRUE` 列；(3) 对 AUTH-04 的管理员禁用操作预留接口。AUTH-02 采用**优雅降级**策略：若运行时 `is_active` 字段尚不存在（迁移未执行），跳过账号状态检查，默认所有用户为活跃状态——保证登录功能不因模型变更未同步而阻塞。待迁移完成后，账号禁用检查自动生效。
>
> **业务矛盾推断 #5（HTTP 状态码选型）**：采纳技术决策报告推荐方案 A——凭据错误使用 **HTTP 401 Unauthorized**。理由：(1) 401 是 RFC 7235 定义的"需要身份验证凭据"的标准语义；(2) 与 AUTH-04 的 RBAC 拒绝（HTTP 403 Forbidden）形成自然区分——401 = "你是谁我不知道"，403 = "我知道你是谁但你没权限"；(3) 与 AUTH-01 的错误码体系一致（AUTH-01 对唯一性冲突返回 409，属于不同语义）。
>
> **业务矛盾推断 #6（字段缺失 vs 密码为空的区分）**：当 username 有值但 password 为空/缺失时，返回**字段级 422 错误**（告知用户"密码为必填字段"），因为这是输入格式错误而非业务凭据错误。当 password 有值（>=8 字符）但比对失败时，返回**统一 401 提示**"用户名或密码错误"。这两种场景的本质不同：(1) "没填密码"是用户遗漏，提供精确指导（"请填写密码"）用户体验更好；(2) "密码错误"是凭据不匹配，使用模糊提示防止信息泄露。此区分与意图文档 §1.8.1（统一模糊提示）和 §1.8.2（字段缺失明确告知）完全对齐。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：`AUTH-01-用户注册-设计文档.md`（v1.0）、`AUTH-04-五级RBAC鉴权-设计文档.md`（v1.0）、`SEC-01-传输存储安全-落地规范.md`（已冻结）、`SEC-05-输入校验防护-落地规范.md`（已冻结）、`OBS-01-结构化日志-落地规范.md`（已冻结）、`DEPLOY-05-环境配置管理-落地规范.md`（已冻结）
- **审查范围**：全量（技术决策报告 §2 已逐项交叉验证）
- **兼容性结论**：
  - **无冲突**：技术决策报告 §2 对上述文档的 6 个检查点标注"✅ 一致"。AUTH-02 的密码验证调用 `py-auth/hashing.py` 的 `verify_password()`（与 SEC-01 一致）；JWT 签发调用 `py-auth/jwt_utils.py` 的 `create_access_token()`（与 SEC-01 一致）；输入校验使用 Pydantic `Depends()` + SEC-05 自定义 422 格式（与 SEC-05 一致）；审计日志使用 `logger.critical(op_type="USER_LOGIN")`（与 OBS-01 一致）。
  - **Token 角色格式兼容**：`create_access_token()` 的 `data["roles"]` 接受列表格式 `[user.role.value]`，与 AUTH-04 的 `rbac.py` 消费端格式完全兼容（技术决策报告 #7）。
  - **get_current_user Depends 归属**：AUTH-04 设计文档 §1.1 提及 `get_current_user` 为 AUTH-02 提供的 Depends。从职责归属看，JWT 验证逻辑（签名校验、过期检查、payload 提取）应放置在 `packages/py-auth/jwt_utils.py` 中作为共享基础设施（与 `create_access_token()` 同文件），而非 AUTH-02 独有——因为 JWT 验证被 AUTH-04、SEC-05 等多个模块消费。AUTH-02 的 `get_current_user` Depends 应仅作为**薄封装**，调用 `py-auth` 的 `decode_and_validate_token()` 并注入 `request.state.user`。此方案避免代码重复，与项目"厚 package、薄 app"原则一致。
- **复用的已有设计**：
  - `packages/py-auth/hashing.py`：`verify_password()` 密码 bcrypt 比对（SEC-01 定义）
  - `packages/py-auth/jwt_utils.py`：`create_access_token()` JWT 签发（SEC-01 定义）
  - `packages/py-auth/blacklist.py`：`is_blacklisted()` Token 黑名单查询（SEC-01/AUTH-04 定义，AUTH-02 登录时不需要调用，但设计上为后续 get_current_user 预留）
  - `packages/py-db/models/auth.py`：`User` ORM 模型（用户名、密码哈希、角色字段）（AUTH-01 定义）
  - `packages/py-db/repositories/user_repository.py`：`find_by_username_lower()` 用户查询（AUTH-01 实现）
  - SEC-05 §1.6 自定义 422 错误响应格式：`{errors: [{field, reason, constraint}]}`
  - OBS-01 §1.1 审计日志规范：`logger.critical(op_type="...")`

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| PostgreSQL 17.x（users 表） | 读取 | `UserRepository.find_by_username_lower(username)` 查询用户记录。使用 `LOWER()` 函数 + B-tree 索引实现大小写不敏感查詢 |
| `packages/py-auth/jwt_utils.py` | 调用 | `create_access_token(data={"sub": user_id, "roles": [role], "jti": uuid4_str}, expires_delta=timedelta(minutes=15))` 签发访问令牌；二次调用 `expires_delta=timedelta(days=7)` + 额外 `token_type: "refresh"` claim 签发续期令牌。签名算法 HS256，密钥从 `SecurityConfig.JWT_SECRET` 读取 |
| `packages/py-auth/hashing.py` | 调用 | `verify_password(plain_password: str, hashed_password: str) -> bool` 执行 bcrypt 哈希比对。salt rounds 从环境变量 `BCRYPT_ROUNDS` 读取（默认 12） |
| `packages/py-db/repositories/user_repository.py` | 调用 | `find_by_username_lower(username: str) -> User | None`。该函数已在 AUTH-01 中实现，直接复用 |
| `packages/py-config/` | 调用 | `get_security_config()` 读取 `JWT_SECRET`、`ACCESS_TOKEN_EXPIRE_MINUTES`、`REFRESH_TOKEN_EXPIRE_DAYS`、`BCRYPT_ROUNDS` |
| `packages/py-logger/` | 调用 | `logger.critical(op_type="USER_LOGIN", extra={user_id, username, success, role, ip})` 成功/失败均写入审计日志。采用 `asyncio.create_task()` 异步投递 |
| `packages/py-schemas/py_schemas/auth.py` | 数据契约 | 定义 `LoginRequest`、`LoginResponse`、`LoginErrorResponse` Pydantic Schema。路由层通过 `Depends()` 注入校验 |
| AUTH-01（用户注册） | 上游数据来源 | 本模块的账号凭据（用户名、密码哈希、角色）由 AUTH-01 创建。通过共享 `User` ORM 模型访问 |
| AUTH-03（Token续期） | 下游数据消费 | 本模块签发的续期令牌（`token_type: "refresh"`）由 AUTH-03 用于刷新访问令牌。续期令牌的 `jti` 和 `exp` 是轮换机制的数据基础 |
| AUTH-04（五级RBAC鉴权） | 下游数据消费 | 本模块将 `roles` 字段注入访问令牌 payload，AUTH-04 的 `require_role()` 消费该字段进行权限判定 |
| AUTH-05（登录注册界面） | 被调用方 | 前端登录页面通过 `POST /api/v1/auth/login` 调用本模块。请求体为 `LoginRequest`，响应体为 `LoginResponse` 或 `LoginErrorResponse` |
| SEC-04（防刷限流） | 下游数据消费 | 本模块的登录失败日志为 SEC-04 提供暴力破解计数的数据源。SEC-04 按用户名维度进行滑动窗口计数和临时锁定 |
| FastAPI + Pydantic v2 | 框架依赖 | 路由使用 `APIRouter`（prefix=`/api/v1/auth`），输入校验使用 Pydantic `BaseModel` + `Field()` 声明式约束 |

> 精确的函数签名、Cypher 查询模板、类名等见落地规范。

### 1.4 状态机设计

本功能点不涉及状态流转，故无需状态机。登录流程为一次性的请求-响应操作——用户提交凭据后，系统要么验证通过（签发凭证），要么验证失败（返回错误提示）。不涉及中间状态或后续状态转换（意图文档 §1.7）。

### 1.5 设计原则兑现清单（技术视角）

| 原则 | 原则名称 | 技术响应 |
|------|----------|----------|
| 项目结构 §3-1 | 厚 package、薄 app | JWT 签发和密码验证逻辑封装在 `packages/py-auth/`（复用 SEC-01 已定义接口）；数据库查询封装在 `packages/py-db/repositories/`（复用 AUTH-01 已定义接口）；Schema 定义在 `packages/py-schemas/auth.py`。`apps/api-server/` 仅包含路由注册（`api/v1/auth.py`）和业务编排的 Service 层（`services/auth_service.py`），不包含算法实现或数据库操作细节 |
| 项目结构 §3-2 | 单向依赖 | AUTH-02 位于认证 L2 层，依赖 L1（py-db、py-config、py-logger）、L3（py-auth、py-schemas）和上游 L2（AUTH-01）。被下游 AUTH-03/04/05/06 依赖，所有依赖方向为单向：L1/L3 → AUTH-02 → AUTH-03/04/05/06。无反向依赖 |
| 项目结构 §3-5 | 最小化可工作 | 仅实现登录核心功能（凭据接收 → 用户查询 → 密码验证 → 账号状态检查 → 双令牌签发 → 审计日志）。不处理 Token 续期（AUTH-03）、不处理权限校验（AUTH-04）、不处理前端存储（AUTH-06）、不处理前端页面（AUTH-05）。AUTH-02 的 `get_current_user` Depends 为薄封装——调用 `py-auth` 共享解码函数，不自行实现 JWT 验证逻辑 |
| 技术栈设计 §5 | 安全纵深防御 | 登录流程的四层验证按序级联，任何一层失败即中止：(1) 格式层——Pydantic Field 约束拦截格式错误（缺失字段、长度不足）；(2) 存在性+密码层——不区分"用户不存在"和"密码错误"，始终执行固定时间 `verify_password()` 防止侧信道；(3) 账号状态层——仅在密码通过后检查 `is_active`，防止泄露账号禁用状态；(4) tokens 签发层——`jti` 唯一标识每个令牌，支持后续黑名单失效。审计日志成功和失败均写入，不可绕过 |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| API 端点路径 | `POST /api/v1/auth/login` | `POST /api/v1/login` / `POST /api/v1/tokens` | 与 AUTH-01 的 `POST /api/v1/auth/register` 保持完全一致的路径模式，位于同一 `router`（`prefix="/api/v1/auth"`）。调用方（AUTH-05）无需记忆两套路径前缀（技术决策报告 #1） |
| 响应 HTTP 状态码 | 成功 200 OK（非 201 Created） | 201 Created | 登录是认证操作而非资源创建，200 OK 符合 REST 语义。与 AUTH-01 的 201 Created 形成区分（技术决策报告 #12） |
| 错误 HTTP 状态码 | 凭据错误 HTTP 401 / 字段缺失 HTTP 422 / 系统错误 HTTP 500 | 统一 400 Bad Request | 401 语义精确（RFC 7235），与 AUTH-04 的 403 形成自然区分（401=你是谁，403=你没权限）。422 与 AUTH-01 和 SEC-05 保持一致（技术决策报告 #10）。参见 §1.1 业务矛盾推断 #5 |
| 用户查询方式 | `find_by_username_lower()` 大小写不敏感查询 | 精确匹配 `find_by_username()` | 大小写不敏感查询避免"ZhangSan"和"zhangsan"被视为不同用户。与 AUTH-01 的唯一性校验策略一致。`LOWER()` 查询在 `VARCHAR(32)` 上的 B-tree 索引性能可忽略（<5ms） |
| 续期令牌签发方式 | 复用 `create_access_token()` + 不同 `expires_delta` 和 `token_type` claim | 独立的 `create_refresh_token()` 函数 | 复用同一 JWT 签发逻辑避免代码重复。通过 `token_type` claim 区分令牌类型（`access` vs `refresh`），通过不同 `expires_delta` 控制有效期。访问令牌和续期令牌共享签名密钥（`JWT_SECRET`），不需要额外密钥管理（技术决策报告 #5） |
| 密码比对安全策略 | 固定时间 `verify_password()`，对不存在用户使用 dummy hash | 先查用户再比密码（存在侧信道） | 若先查用户再比密码，攻击者可通过响应时间差异判断用户名是否存在（查不到用户直接返回 401，<5ms；查到用户再比密码，250ms）。固定时间比对消除了此侧信道。dummy hash 选用固定 bcrypt 哈希值，比对耗时与真实哈希一致 |
| User 模型 is_active 字段 | **必须新增**，AUTH-02 优雅降级 | 跳过账号状态检查 / 使用外部服务查询 | 缺少 `is_active` 将导致意图文档 §1.8.3 "账号状态异常"场景无法实现（技术决策报告高风险项 #1）。新增该字段需要：(1) 修改 `User` ORM 模型；(2) 创建 Alembic 迁移；(3) 对接 AUTH-04。AUTH-02 的优雅降级确保字段尚未新增时不影响登录功能。参见 §1.1 业务矛盾推断 #4 |
| 暴力破解防护 | SEC-04 集中管理，AUTH-02 只输出审计日志 | AUTH-02 内置登录失败计数器 | 将安全策略集中在 SEC-04 中，遵循单一职责原则。AUTH-02 的日志（`success=True/False`）为 SEC-04 提供完整的计数依据，不限流逻辑在 AUTH-02 内硬编码（阈值调整无需修改 AUTH-02 代码）。参见 §1.1 业务矛盾推断 #3 |
| get_current_user Depends 归属 | `packages/py-auth/jwt_utils.py` 提供 `decode_and_validate_token()`，AUTH-02 的 `get_current_user` 为薄封装 | 完整实现在 AUTH-02 内部 | JWT 解码和验证逻辑应作为共享基础设施（被 AUTH-04、SEC-05 等多个模块消费），放在 `py-auth` 包中避免代码重复。AUTH-02 仅负责将解码结果注入 `request.state.user`。此方案与项目"厚 package、薄 app"原则一致 |

### 1.7 注意事项与禁止行为（设计层面）

1. **[约束] 密码不可逆验证**：登录时使用的密码在任何存储介质（日志、缓存、临时变量）中均不得以明文记录。密码哈希比对必须通过 `packages/py-auth/hashing.py` 的 `verify_password()` 完成，禁止自行实现哈希比对逻辑。

2. **[约束] 固定时间防侧信道**：无论用户名是否存在，都必须执行 `verify_password()`（对不存在用户使用固定 dummy hash）。禁止"先查用户，不存在则直接返回 401"的短路逻辑——响应时间差异会泄露用户名存在性。

3. **[设计边界] AUTH-02 不处理 Token 续期**：本模块仅负责在登录成功时**签发**续期令牌。续期令牌的使用（以旧换新）、轮换（旧令牌作废）、过期处理均归属 AUTH-03（Token续期）。AUTH-02 签发的续期令牌的 `jti` 和 `exp` 为 AUTH-03 提供数据基础。

4. **[设计边界] AUTH-02 不处理权限校验**：本模块在签发访问令牌时将 `roles` 字段写入 JWT payload，但不执行任何权限判定逻辑。请求级的角色权限校验归属 AUTH-04（五级RBAC鉴权）。

5. **[设计边界] AUTH-02 不处理前端 Token 存储**：登录成功后返回的 `access_token` 和 `refresh_token` 由调用方（AUTH-05 前端界面）自行处理持久化存储和后续请求的令牌注入。前端 Token 生命周期管理归属 AUTH-06（认证会话管理）。

6. **[易错点] 统一错误提示的严格实现**：用户名不存在和密码错误两种情况必须返回**完全相同的字符串**——`"用户名或密码错误，请重新输入"`（意图文档 §1.8.1 的精确文本）。禁止追加任何差别性信息（如错误码、内部标识），禁止通过不同的 HTTP Header 或响应体字段区分两种场景。验收标准 AC-09 要求"前端无法区分两种失败原因"。

7. **[易错点] 字段缺失与密码错误的区分边界**：当 `username` 有值但 `password` 为空字符串时，返回 422 字段级错误（告知"密码为必填字段"），而非 401 统一提示。当 `username` 有值且 `password` 非空但密码错误时，返回 401 统一提示。两者的边界条件需在落地规范中精确到空字符串和 None 值的处理。参见 §1.1 业务矛盾推断 #6。

8. **[易错点] 令牌 payload 的 `roles` 字段格式**：`create_access_token()` 的 `data["roles"]` 参数接受**字符串列表**（如 `["family"]`），而非单个字符串。AUTH-04 的 `rbac.py` 消费端期望 `List[str]` 格式。格式不匹配将导致所有鉴权请求被拒绝。注意：`data["sub"]` 应为 `str` 类型（UUID 字符串），不是 `UUID` 对象——否则 JWT 编码时会被序列化为不可解析的格式。

9. **[禁止行为] 禁止在登录成功响应中暴露敏感信息**：`LoginResponse` 中禁止返回 `password_hash`、用户的完整 `User` 对象、或任何非必要的个人信息（如手机号、真实姓名）。仅返回四字段：`access_token`、`refresh_token`、`token_type`、`expires_in`。

10. **[禁止行为] 禁止绕过审计日志**：登录成功和失败时 `logger.critical(op_type="USER_LOGIN")` 调用不可省略、不可被 `try-except` 静默吞掉（与 AUTH-01 的 §1.7 规定一致）。失败日志中禁止包含密码原文或哈希值。

### 1.8 引用：配套意图文档

- **意图文档**：`AUTH-02-用户登录-意图文档.md`
- **冻结时间**：2026-05-26 22:47:13
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。所有 10 项验收标准（AC-01~AC-10）均有明确的技术实现路径；9 项"留给规范阶段的技术决策"已由技术决策报告（`.tmp/reports/tech-decision-report-AUTH-02.md`）的 14 项决策确定；6 项业务矛盾已在 §1.1 中标注处理方式和推断依据。如有歧义，以意图文档为准。
