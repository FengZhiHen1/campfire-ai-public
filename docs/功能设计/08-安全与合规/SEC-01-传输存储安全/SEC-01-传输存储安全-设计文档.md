# 1 功能点：SEC-01 传输存储安全 — 设计文档（瘦身版）

> **文档生成时间**：2026-05-26 17:11:45
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 17:11:45 | AI Assistant | 初始版本，基于技术决策预研报告（全部9项决策经用户确认） |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `SEC-01-传输存储安全-意图文档.md`（已冻结，v2.0，2026-05-26 16:54:46）
> - 本模块的精确编码规格见 `SEC-01-传输存储安全-落地规范.md`

### 1.1 技术实现思路

传输存储安全模块是篝火智答平台的安全防护基座，横跨全平台所有服务端通信链路和数据落地路径。它不是独立 API 端点，而是以**中间件链 + 基础设施适配器**的形式注入到 FastAPI 应用生命周期中。

**六层安全防线按请求处理顺序级联：**

```
客户端请求 → [Nginx: HTTPS 终端/TLS 1.3] → [限流: Redis 滑动窗口] → [JWT: Token 校验] → [脱敏: 响应拦截] → [文件安全: 上传拦截]
                  ↑ L3 工程支撑层              ↑ packages/py-cache       ↑ packages/py-auth      ↑ packages/py-auth     ↑ packages/py-storage
```

密码安全（bcrypt）不在此请求链中——它在用户注册和登录时被 `auth_service.py` 显式调用 `packages/py-auth/hashing.py`。审计日志作为全链路旁路，在各层触发安全事件时写入 `audit_logs` 表。

**设计决策的核心逻辑：**

1. **Nginx 层统一 SSL 终结**（而非 FastAPI 自行处理 HTTPS）——这是项目结构 §3.1 的硬性要求。Nginx 作为反向代理处理 TLS 握手，后端 FastAPI 在内网以 HTTP 通信，避免服务间 TLS 开销，证书管理集中在单点。

2. **安全能力下沉到 packages**（而非散落在 app 中间件中）——遵循项目结构"厚 package、薄 app"原则。密码哈希（`py-auth/hashing.py`）、JWT 签发校验（`py-auth/jwt.py`）、限流计数器（`py-cache/rate_limit.py`）、文件校验（`py-storage/file_security.py`）均为独立可测的适配器。app 层仅负责在 FastAPI 中间件中注册这些适配器。

3. **Redis 故障时选 fail-open**——这是应急咨询平台的安全底线权衡。意图文档 §1.10 明确本模块的下游依赖包括应急咨询和工单系统——若 Redis 故障导致全服务拒绝请求（fail-closed），用户无法获取应急方案，影响远超短时失去限流保护。fail-open 时同时触发告警（通过 `py-logger`），运维感知后修复 Redis。

4. **文件校验三层递进**——仅校验扩展名（如 `.pdf`）可以被改后缀绕过。增加 MIME 类型检测（`python-magic` 库）和文件头魔数检测（读取文件前 4 字节比对已知签名）提供深度防御。三层校验按扩展名→MIME→魔数顺序执行，任何一层不通过即拒绝，不再执行后续层。

5. **JWT 密钥轮换采用 kid 机制**——JWT header 中嵌入 `kid`（密钥版本标识，如 `v1`/`v2`），服务端维护两个环境变量 `JWT_SECRET_KEY`（当前密钥）和 `JWT_PREVIOUS_SECRET_KEY`（上一个密钥）。签发一律使用当前密钥，校验时根据 token header 的 `kid` 选择对应密钥。轮换操作通过脚本 `scripts/rotate-jwt-key.sh` 完成：生成新密钥 → 将当前密钥移至 PREVIOUS → 新密钥写入 CURRENT → 容器滚动重启。轮换周期 90 天，共栖期 7 天。

**数据流宏观描述**：用户密码从注册接口进入 → `hashing.py` 生成 bcrypt 哈希 → 存入 PostgreSQL `users` 表（不存储明文）。登录时 `auth_service.py` 调用 `hashing.py` 校验 → 通过后 `jwt.py` 签发 JWT Token → 后续请求通过 `middleware/auth.py` 校验 Token。敏感数据查询时 `middleware/masking.py` 在 FastAPI 响应中间件中根据请求者角色决定是否对手机号字段脱敏。限流在请求最早阶段（auth 之前）由 `middleware/rate_limit.py` 执行 Redis 滑动窗口检查。文件上传在路由处理函数中调用 `py-storage/file_security.py` 校验 → 通过后 `py-storage` 生成预签名 URL。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：`docs/篝火智答-技术栈设计.md` §5 安全设计、`docs/篝火智答-项目结构.md` §5 分层架构
- **兼容性结论**：**无冲突**。经扫描 `docs/功能设计/` 目录，全项目范围内未发现已存在的设计文档或落地规范。本模块的六大安全维度与技术栈设计 §5 的安全表格完全对齐。安全适配器归属 `packages/py-auth/`、`packages/py-cache/`、`packages/py-storage/` 的分配符合项目结构 §6.1 目录骨架。
- **复用的已有设计**：
  - JWT 认证与 RBAC 的五级层级定义（技术栈设计 §5）
  - bcrypt 哈希参数（salt rounds ≥ 12，技术栈设计 §5）
  - Redis 滑动窗口限流参数（用户级 30 req/min，IP 级 100 req/min，技术栈设计 §5）
  - Nginx SSL 终结 + 内网 HTTP 通信（项目结构 §3.1、§5.2）
  - `packages/py-logger` 的结构化日志和 `trace_id` 机制（项目结构 §6.1）

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| Nginx（L3 工程支撑层） | 硬性基础设施 | HTTPS/TLS 1.3 终端，HTTP→HTTPS 301 重定向；`infrastructure/nginx/` 目录下的 Nginx 配置模板 |
| Redis（L2 `packages/py-cache/`） | 硬性基础设施 | 滑动窗口限流计数器，使用 `INCR + EXPIRE` 原子操作，key 格式 `ratelimit:user:{user_id}:{minute}` / `ratelimit:ip:{ip}:{minute}` |
| PostgreSQL（L2 `packages/py-db/`） | 硬性基础设施 | `audit_logs` 表持久化审计事件；`users` 表存储 bcrypt 密码哈希 |
| MinIO（L2 `packages/py-storage/`） | 硬性基础设施 | 生成预签名 URL（`PresignedGetObject`），默认有效期 1 小时（`MINIO_PRESIGNED_URL_EXPIRY_SECONDS` 可配） |
| AUTH-02 用户登录 | 共享资源（JWT 密钥） | 共享 `packages/py-auth/jwt.py` 的签发/校验函数；JWT 签名密钥（≥256 位）由 `JWT_SECRET_KEY` 环境变量统一管理 |
| SEC-04 防刷限流 | 共享基础设施 | 共享 `packages/py-cache/rate_limit.py` 的 Redis 计数器；双模块共同定义限流 key 命名规范和 429 响应格式 |
| SEC-05 输入校验 | 防线互补 | 本模块确保请求以安全加密方式到达且不超频后，SEC-05 负责 Pydantic v2 Schema 级请求体校验 |
| PII检测脱敏（SEC-03） | 下游协作 | 本模块提供 HTTPS 传输加密通道；SEC-03 在内容提交时负责内容层 PII 检测（两模块构成全链路隐私保护） |
| `packages/py-config/` | 配置来源 | 所有安全参数（`BCRYPT_ROUNDS`、`JWT_SECRET_KEY`、`JWT_PREVIOUS_SECRET_KEY`、限流阈值三参数、白名单扩展名列表、预签名 URL 过期时间）通过 `pydantic-settings` 从环境变量加载 |
| `packages/py-logger/` | 日志依赖 | 审计日志复用 `py-logger` 的结构化日志基础设施和 `trace_id` 生成机制 |

### 1.4 状态机设计（技术实现策略，如适用）

本功能点不涉及状态流转，故无需状态机。意图文档 §1.7 已确认无需状态机。

### 1.5 设计原则兑现清单（技术视角）

| 原则 | 原则名称 | 技术响应 |
|------|----------|----------|
| 项目结构 §3-1 | 厚 package、薄 app | 安全核心逻辑（哈希、JWT、限流、文件校验）全部下沉到 `packages/py-auth/`、`packages/py-cache/`、`packages/py-storage/`；`apps/api-server/` 仅通过 FastAPI 中间件注册和 `auth_service.py` 调用适配器，不包含安全算法实现 |
| 项目结构 §3-2 | 单向依赖 | 本模块（L1 基础设施层）依赖 packages（L2 共享能力层）和 infrastructure（L3 工程支撑层），无反向依赖。app 层通过中间件注册调用 packages 适配器，遵循依赖方向 |
| 项目结构 §3-5 | 最小化可工作 | 仅实现需求文档中已定义的六大安全维度（传输加密、密码安全、JWT 凭证、脱敏、限流、文件安全）。不为未来规划预留代码实现，如微信小程序 wx.login 认证后延至后续迭代 |
| 技术栈设计 §5 | 安全纵深防御 | 六层安全防线按请求生命周期顺序级联，任何一层失败即中止请求处理——不依赖单层防护。文件安全采用三层递进（扩展名→MIME→魔数）而非单一校验，体现了纵深防御原则 |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| HTTPS 实施位置 | Nginx 层统一 SSL 终结 | FastAPI 自处理 HTTPS（uvicorn `--ssl-keyfile`） | 项目结构 §3.1 硬性要求；集中证书管理，避免多服务 TLS；内网 HTTP 通信降低延迟 |
| JWT 签名算法 | HMAC-SHA256（HS256） | RSA-256（RS256，非对称签名） | 单机/单服务部署无需公钥分发；对称签名管理成本最低；HS256 在 256 位密钥强度下安全等价 RS256 |
| JWT 密钥轮换 | 90 天轮换 + 7 天共栖期 + kid 机制 | 30 天轮换 + 3 天共栖期 / 180 天轮换 | 90 天平衡运维负担与安全窗口；7 天共栖期保障正常使用的 Refresh Token 不因轮换失效（最长 Token 有效期 7 天） |
| 限流故障策略 | Redis 不可用时 fail-open（放行+告警） | fail-closed（拒绝所有请求） | 受意图文档约束——应急咨询平台可用性优先；fail-closed 导致全服务不可用风险高于短时失去限流保护；fail-open 同时触发 `py-logger` 告警 |
| 限流参数管理 | 环境变量配置（`RATE_LIMIT_USER_PER_MINUTE` 等），修改后重启生效 | 配置中心热更新（Nacos/Apollo） | 1-3 人团队，Docker Compose 部署，配置中心增加不必要的运维复杂度；修改限流参数是低频操作 |
| bcrypt salt rounds | `BCRYPT_ROUNDS=12`（环境变量可覆盖） | rounds=13（约 500ms）或 rounds=10（约 60ms） | 12 是 OWASP 推荐的安全/性能平衡点（约 250ms/次）；提高至 13 仅增加 2 倍暴力破解成本但多 100% CPU 延迟，收益递减 |
| 文件安全校验 | 扩展名→MIME→魔数三层递进 | 仅扩展名校验 | 扩展名可被重命名绕过；三层递进是 OWASP 文件上传安全最佳实践（Cheat Sheet: File Upload） |
| 审计日志存储 | PostgreSQL `audit_logs` 表，180 天按月清理 | 应用日志文件 / ELK 系统 | 与现有技术栈（SQLAlchemy/Alembic）完全兼容；数据量极低（< 100MB/年）；无新增运维组件 |
| 手机号脱敏 | 前 3 后 4，中间 `****`，通过响应中间件拦截 | 在各端点手动脱敏 | 受意图文档 AC-05 约束；中间件统一脱敏避免各端点遗漏；预留 `Masker` 抽象类扩展点供未来新增数据类型 |
| MinIO 预签名 URL | 默认 1 小时（`MINIO_PRESIGNED_URL_EXPIRY_SECONDS` 可配） | 24 小时 / 7 天 | 1 小时覆盖单次会话场景；过期后可重新请求签名无副作用；更长时间增加 URL 泄露风险 |

### 1.7 注意事项与禁止行为（设计层面）

1. **[约束] 密码不可逆存储**：用户密码在任何存储介质（数据库、备份、日志）中均不得以明文或可逆加密形式存在。`hashing.py` 的 `hash_password()` 函数是唯一密码写入入口。审计日志中禁止记录密码原文或哈希值。

2. **[约束] 全平台 HTTPS 强制**：所有面向客户端的 API 端点仅接受 HTTPS 请求。Nginx 配置中 `listen 80` 的唯一作用是 301 重定向至 HTTPS。禁止为任何业务端点开放 HTTP 明文访问。

3. **[易错点] JWT 密钥轮换时的 token 校验**：校验 token 时必须先读取 `kid`，再根据 `kid` 选择对应密钥。禁止默认使用当前密钥校验所有 token——这会导致轮换后上一个密钥签发的有效 token 被误判为无效。

4. **[易错点] 限流 key 的粒度与过期**：Redis 限流 key 必须精确到时间窗口（如 `ratelimit:user:{user_id}:{unix_minute}`），且每个 key 设置独立 TTL（窗口大小 + 缓冲，如 120 秒）。禁止使用不设 TTL 的永久 key——会导致 Redis 内存泄漏。

5. **[易错点] 脱敏中间件的响应拦截范围**：脱敏中间件仅拦截包含手机号字段的 API 响应。禁止在未检查响应结构的情况下对所有响应执行正则扫描——可能导致将非手机号的 11 位数字错误脱敏。

6. **[设计边界] 本模块不负责的事项**：
   - 业务内容 PII 检测（SEC-03 职责）——本模块仅保障传输加密通道
   - RBAC 权限规则定义（AUTH-04 职责）——本模块仅执行 JWT roles 字段校验
   - 限流策略的具体编码实现（SEC-04 职责）——本模块仅定义限流参数和中间件注册

7. **[禁止行为]**：
   - 禁止在代码或配置文件中硬编码 JWT 签名密钥——密钥仅通过环境变量注入
   - 禁止绕过限流中间件直接处理请求——所有 API 端点必须经过限流中间件（健康检查端点可豁免，通过白名单路径配置）
   - 禁止在日志中输出密码明文、JWT Token 原文、完整的手机号——结构化日志中敏感字段必须脱敏处理
   - 禁止跳过文件安全校验直接存储上传文件——所有上传文件必须经过三层递进校验

### 1.8 引用：配套意图文档

- **意图文档**：`SEC-01-传输存储安全-意图文档.md`
- **冻结时间**：2026-05-26 16:54:46
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。6 大安全维度的实现方案完整覆盖意图文档 §1.4 的 6 项业务目标，8 项验收标准（AC-01 ~ AC-08）的设计方案均已在本设计中明确。9 项规范阶段技术决策经技术预研和用户确认后已全部确定。如有歧义，以意图文档为准。
