## 1 功能点：AUTH-01 用户注册 — 设计文档（瘦身版）

> **文档生成时间**：2026-05-26 20:57:26
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 20:57:26 | AI Assistant | 初始版本，基于 s06 技术决策报告（8 项决策全部确定）生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `AUTH-01-用户注册-意图文档.md`（已冻结，v2.0，2026-05-26 20:50:52）
> - 本模块的精确编码规格见 `AUTH-01-用户注册-落地规范.md`

### 1.1 技术实现思路

用户注册是一个**无状态的单次创建操作**——接收用户提交的身份信息，经三层校验（格式→唯一性→持久化）后生成唯一标识并入库，返回成功结果或具体失败原因。

**为什么选择无状态单次操作而非多阶段注册流程**：意图文档 §1.5 的用户旅程中，注册流程包含"角色选择→填写信息→提交→创建"四个交互步骤，但从技术视角看，前三步是纯前端的表单交互（不产生服务端状态），只有第四步"提交"触发一次 API 调用。因此服务端实现为一个原子 HTTP endpoint：接收全部注册信息后一次性完成校验与创建，要么全部成功，要么全部拒绝。不引入服务器端会话、不创建临时状态、不支持分步提交——这避免了分布式一致性开销，降低了后端复杂度，且完全满足意图文档的业务需求。

**密码安全策略的特殊字符处理**：技术决策报告 §5 标记了一项业务矛盾——意图文档仅要求"至少 8 位且包含大小写字母与数字"，未明确是否允许特殊字符。本设计采用**宽松策略**：不禁止特殊字符（如 `!@#$%`），密码强度校验仅验证"是否至少包含大写字母、小写字母和数字各一个"，额外字符（特殊符号、空格等）不做限制。理由：(1) 限制特殊字符会降低密码熵，削弱安全性；(2) 意图文档未声明禁止特殊字符，采用宽松策略不违反业务约束；(3) bcrypt 对任意字节输入均可安全处理，不存在注入风险。此决策标注为"基于技术决策报告推荐方案的推断——无用户裁决记录，采纳报告建议"。

**BCRYPT_ROUNDS 配置依赖**：技术决策报告 §5 标记 DEPLOY-05 的 `AppSettings` 尚未定义 `BCRYPT_ROUNDS` 字段。本模块的 `hashing.py` 在调用 bcrypt 时使用 `settings.get("BCRYPT_ROUNDS", 12)` 模式——优先读取环境变量（运维可调），缺失时默认为 12（符合 SEC-01 §1.6 的安全/性能平衡设计）。待 DEPLOY-05 后续补全该字段后，本模块无需修改。

**数据流设计**：采用"输入校验→唯一性检查→密码哈希→数据写入→审计日志"五个阶段，每阶段失败即中断流程并返回对应错误。各阶段职责独立，不交叉：

1. **输入校验阶段**：Pydantic Schema 在路由层拦截格式错误（用户名长度/字符集、手机号格式、缺失必填字段），FastAPI `Depends()` 自动返回 422。密码强度校验（大小写+数字）因无法通过单字段 `pattern` 完整表达，下移至 Service 层，仍使用 422 错误格式。
2. **唯一性检查阶段**：在 Repository 层通过 `LOWER()` 函数实现大小写不敏感的用户名唯一性查询。手机号唯一性查询使用精确匹配。本阶段是防御层——不依赖数据库唯一约束作为唯一防线，因为 409 Conflict 需要区分是"用户名重复"还是"手机号重复"的精确错误码，而 DB 层 `UNIQUE` 约束仅抛出通用 `IntegrityError`。
3. **密码哈希阶段**：调用 `packages/py-auth/hashing.py` 的 `hash_password()`——该函数使用 bcrypt via passlib `CryptContext`，salt rounds 默认为 12（可通过环境变量覆盖）。哈希过程约耗时 250ms，该延迟包含在注册请求的总响应时间内（不影响用户体验，因为注册操作本身期望一定延迟）。
4. **数据写入阶段**：通过 SQLAlchemy Repository 的 `create()` 方法执行 INSERT。UUID 主键由 PostgreSQL `gen_random_uuid()` 在数据库层面生成（而非 Python 端 `uuid.uuid4()`），理由见 §1.6 架构权衡。
5. **审计日志阶段**：注册成功时调用 `logger.critical(op_type="USER_REGISTER")` 写入审计日志。该步骤异步执行（`asyncio.create_task()` 投递），日志写入失败不影响注册成功结果——防止日志系统的可用性问题阻塞核心业务流程。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：`SEC-01-传输存储安全-设计文档.md`（v1.0）、`SEC-05-输入校验防护-设计文档.md`（v1.0）、`DEPLOY-05-环境配置管理-设计文档.md`（v1.0）、`OBS-01-结构化日志-设计文档.md`（v1.0）、`KNOW-01-科普内容管理-设计文档.md`（v1.0）
- **兼容性结论**：
  - **无冲突**：技术决策报告 §2 对上述文档进行了逐项交叉验证，所有检查点标注"✅ 一致"。AUTH-01 的密码哈希调用 `py-auth/hashing.py`（与 SEC-01 一致）、输入校验使用 Pydantic `Depends()` + SEC-05 自定义 422 格式（与 SEC-05 一致）、审计日志使用 `logger.critical()`（与 OBS-01 一致）。
  - **配置依赖待补全**：DEPLOY-05 的 `AppSettings` 未定义 `BCRYPT_ROUNDS` 字段。本模块通过 `hashing.py` 内置默认值 12 实现自包含，不阻塞注册功能的正常运作。该配置项的正式定义将由 DEPLOY-05 后续迭代完成，不属于本模块职责范围。
- **复用的已有设计**：
  - `packages/py-auth/hashing.py`：密码 bcrypt 哈希（SEC-01 定义）
  - SEC-05 §1.6 自定义 422 错误响应格式：`{errors: [{field, reason, constraint}]}`
  - OBS-01 §1.1 审计日志规范：`logger.critical(op_type="...")` 强制携带 `op_type`
  - `packages/py-db/models/base.py`：共享 UUID PK + Timestamp Mixin（项目结构约定）
  - pgvector 17.x 的 `gen_random_uuid()`：UUID 生成（PostgreSQL 内置函数）

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| PostgreSQL 17.x | 读写 | `users` 表存储注册结果。ORM 模型通过 SQLAlchemy 2.0 async 操作，主键 UUID 由 `gen_random_uuid()` 生成 |
| `packages/py-auth/hashing.py` | 调用 | `hash_password(plain: str) -> str` 对用户密码执行 bcrypt 哈希。salt rounds 默认为 12，通过环境变量 `BCRYPT_ROUNDS` 可选覆盖。哈希失败抛出 `HashingError` |
| `packages/py-db/models/base.py` | 继承 | ORM 模型继承共享 Base 和 UUID PK Mixin，获得 `id`（UUID）、`created_at`、`updated_at` 字段 |
| `packages/py-db/repositories/user_repository.py` | 调用 | `create(user: User) -> User`、`find_by_username_lower(username: str) -> User | None`、`find_by_phone(phone: str) -> User | None` |
| `packages/py-config/` | 调用 | `get_settings()` 读取 `BCRYPT_ROUNDS`（若环境变量定义则读取，否则 hashing.py 使用硬编码默认值 12） |
| `packages/py-logger/` | 调用 | `logger.critical(op_type="USER_REGISTER", user_id=str, ...)` 写入用户创建审计日志。采用 `asyncio.create_task()` 异步投递，日志写入失败不阻塞注册流程 |
| `packages/py-schemas/py_schemas/auth.py` | 数据契约 | 定义 `RegisterRequest`、`RegisterResponse`、`ErrorResponse` 等 Pydantic Schema。路由层通过 `Depends()` 注入校验 |
| AUTH-04（五级RBAC鉴权） | 下游数据依赖 | 注册时写入的 `role` 字段（ENUM 值 `family/teacher/expert`）是 AUTH-04 权限判定的数据基础。AUTH-01 不负责任何权限逻辑 |
| AUTH-05（登录注册界面） | 被调用方 | 前端注册页面通过 `POST /api/v1/auth/register` 调用本模块。接口契约由 `RegisterRequest` / `RegisterResponse` 定义 |
| FastAPI + Pydantic v2 | 框架依赖 | 路由使用 `APIRouter`，输入校验使用 Pydantic `BaseModel` + `Field()` 声明式约束 |

### 1.4 状态机设计

本功能点不涉及状态流转，故无需状态机。注册流程为一次性操作——用户提交信息后，系统要么创建成功（生成账号），要么拒绝创建（返回失败原因）。不涉及中间状态或后续状态转换。

### 1.5 设计原则兑现清单（技术视角）

| 原则 | 原则名称 | 技术响应 |
|------|----------|----------|
| 项目结构 §3-1 | 厚 package、薄 app | 密码哈希逻辑封装在 `packages/py-auth/hashing.py`（复用 SEC-01 已定义接口）；ORM 模型定义在 `packages/py-db/models/auth.py`；Schema 定义在 `packages/py-schemas/auth.py`。`apps/api-server/` 仅包含路由注册（`api/v1/auth.py`）和业务编排的 Service 层（`services/auth_service.py`），不包含算法实现或数据库操作细节 |
| 项目结构 §3-2 | 单向依赖 | AUTH-01 位于认证 L2 层（依赖关系分析 §5.1），依赖 L1（py-db、py-config、py-logger、infrastructure）和 L3（py-auth、py-schemas），无反向依赖。AUTH-01 不依赖任何同级或下游业务模块（AUTH-02/04/06 的数据在本模块中不消费） |
| 项目结构 §3-5 | 最小化可工作 | 仅实现用户注册功能（username+password+role+phone+real_name 验证 → 创建 User 记录）。不处理登录（AUTH-02）、不签发 JWT（AUTH-02）、不管理角色变更（AUTH-04）、不初始化会话（AUTH-06）。微信小程序 wx.login 集成后延至后续迭代 |
| 技术栈设计 §5 | 安全纵深防御 | 注册流程的三层校验按顺序级联，任何一层失败即中止：(1) 格式层——Pydantic Field 约束拦截格式错误；(2) 唯一性层——Repository 查询拦截重复用户名/手机号；(3) 持久化层——数据库 UNIQUE 约束作为最后防线。密码在到达 hashing.py 前已通过 Pydantic 长度校验，hashing.py 的 bcrypt 自动加盐。注册成功后立即写入审计日志（不可绕过） |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 密码哈希算法 | bcrypt（passlib CryptContext） | argon2 / scrypt | bcrypt 是 OWASP 推荐方案（2025 年仍为首选）；项目技术栈和 SEC-01 已明确选择 bcrypt；argon2 虽抗 GPU 能力更强但 passlib 对其支持不如 bcrypt 成熟；scrypt 配置复杂且无显著安全优势 |
| UUID 生成位置 | PostgreSQL `gen_random_uuid()`（数据库端生成） | Python `uuid.uuid4()`（应用端生成） | 数据库端生成避免多应用实例的 UUID 时序冲突（即使当前为单机，不排斥未来扩展）；与项目全局约定一致（技术栈 §4 所有数据模型均标注 `default=gen_random_uuid()`）；`uuid.uuid4()` 的随机性在一次 DB round-trip 中无价值增加 |
| 用户名唯一性校验 | 大小写不敏感（`LOWER(username)` 查询）+ 大小写敏感保存（保留用户输入的原始大小写） | 全小写存储 + 查询 / 大小写敏感唯一性 | 保留用户输入原始大小写体现了灵活性；大多数平台（GitHub、Twitter）采用此策略；`LOWER()` 查询在 `VARCHAR(32)` 上的性能差异可忽略（B-tree 索引对函数查询可用 `CREATE INDEX ON users (LOWER(username))`） |
| 角色存储方式 | PostgreSQL ENUM 类型 `user_role` | VARCHAR 字符串 / 关联表 `roles` | ENUM 提供数据库层的类型安全（非法值被数据库拒绝）；全项目已有 ENUM 惯例（技术栈中 chunk_type、status、priority 等均为 ENUM）；五级角色层级已稳定（技术栈 §5），不存在需要"频繁新增角色"的场景；关联表引入不必要的 JOIN 复杂度，且项目无动态角色管理需求 |
| 手机号校验策略 | 纯格式校验（`^1[3-9]\d{9}$`），不使用号段白名单 | 号段白名单校验 / 短信验证码实时校验 | 中国大陆手机号号段持续新增，1-3 人团队维护白名单负担过重且容易遗漏新号段；纯格式校验覆盖 99% 合法号码；真正的手机号有效性验证由后续模块的短信验证完成（注册阶段的格式校验仅用于前置过滤） |
| 密码强度校验位置 | Pydantic 长度校验（路由层）+ 复杂字符校验（Service 层） | 全部在 Pydantic 层（单一 `pattern` 字段）/ 全部在 Service 层 | 密码需同时满足"≥8 位"和"包含大小写字母和数字"两个条件——前者适合 Pydantic `Field(min_length=8)` 声明式校验，后者需要 3 个独立的正向前瞻断言（`(?=.*[a-z])(?=.*[A-Z])(?=.*\d)`），组合在单个 `pattern` 中不够可读且错误信息不精确。分层校验既保持了声明式的简洁性，又提供了精确的错误提示（"密码必须同时包含大写字母、小写字母和数字"） |
| 唯一性冲突检测 | Repository 层显式 SELECT + INSERT（预检查模式） | 仅依赖数据库 UNIQUE 约束 + 通用 `IntegrityError` 捕获 | 意图文档 §1.8.2 要求区分"用户名已被注册"和"手机号已被注册"的精确错误码。DB 层的 `IntegrityError` 是通用异常，需要解析约束名称才能区分两个 UNIQUE 字段——这不仅脆弱（约束命名依赖迁移脚本），且违反意图文档"明确告知"的业务要求。预检查虽多一次 SELECT，但 SELECT 走索引查询（<5ms），远低于注册请求中 bcrypt 计算的 250ms 开销，不构成性能瓶颈 |

### 1.7 注意事项与禁止行为（设计层面）

1. **[约束] 密码不可逆存储**：用户密码在任何存储介质（数据库、备份、日志）中均不得以明文或可逆加密形式存在。`packages/py-auth/hashing.py` 的 `hash_password()` 函数是唯一密码写入入口。审计日志（§1.1 第 5 阶段）中禁止记录密码原文或哈希值。

2. **[设计边界] AUTH-01 不签发 JWT**：注册成功后的返回体仅包含 `user_id` 和 `result: "success"`，不包含 Access Token 或 Refresh Token。JWT 签发是 AUTH-02（用户登录）的职责。前端在注册成功后应引导用户跳转至登录页，而非自动登录。

3. **[设计边界] AUTH-01 不创建会话**：注册不初始化 Redis Session 或 Taro Storage Token。会话初始化是 AUTH-06（认证会话管理）的职责。

4. **[设计边界] AUTH-01 不管理角色变更**：注册时分配的 `role` 字段一经写入即固定。角色的升级/降级、管理员分配等操作归属 AUTH-04（五级RBAC鉴权）模块。本模块仅负责在注册时写入初始角色值。

5. **[易错点] 密码强度校验的位置**：密码格式（长度≥8）在 Pydantic Schema 的 `Field(min_length=8)` 声明式校验中完成，复杂度校验（含大小写字母和数字）在 Service 层完成。不要在 Schema 层使用单一 `pattern` 陷阱式表达密码复杂度，这会失去精确的错误提示能力。

6. **[易错点] 唯一性校验的 TOCTOU 竞态**：Repository 层的预检查（SELECT）与 INSERT 之间存在极短的时间窗口，理论上两个并发请求使用相同用户名时可能同时通过唯一性检查。数据库 UNIQUE 约束是最终安全网——虽无法提供精确错误码（需回退为通用 500 或解析约束名），但保证数据一致性。在低并发注册场景（用户注册非高频操作）下，该竞态窗口的实际概率可忽略。

7. **[禁止行为] 禁止在注册流程中加载用户档案**：注册成功后，禁止自动创建 `profile` 记录或档案关联。档案初始化归属于 PROF-01（个人档案管理）的冷启动引导流程。

8. **[禁止行为] 禁止绕过审计日志**：注册成功时 `logger.critical(op_type="USER_REGISTER")` 调用不可省略、不可被 `try-except` 静默吞掉（即使采用异步投递，也需在 `asyncio.create_task()` 的回调中捕获日志写入异常并记录 warning 日志）。

### 1.8 引用：配套意图文档

- **意图文档**：`AUTH-01-用户注册-意图文档.md`
- **冻结时间**：2026-05-26 20:50:52
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。所有 10 项验收标准（AC-01~AC-10）均有明确的技术实现路径；8 项"留给规范阶段的技术决策"已由技术决策报告（`.tmp/reports/tech-decision-report-AUTH-01.md`）全部确定；2 项业务矛盾（密码特殊字符策略、BCRYPT_ROUNDS 缺失）已在 §1.1 中标注处理方式。如有歧义，以意图文档为准。
