# 模块接口契约索引

## OBS-04 - 健康检查
- **输出**: `HealthCheckResponse {status: HealthStatus, version: str, uptime_seconds: int, components: {postgresql: ComponentHealth, redis: ComponentHealth, minio: ComponentHealth}, timestamp: str}` — /health 端点响应体
- **输出**: `ReadinessResponse {ready: bool, database: ComponentHealth, timestamp: str}` — /ready 端点响应体
- **枚举**: `ComponentStatus` = connected | disconnected
- **枚举**: `HealthStatus` = healthy | degraded | unhealthy
- **模型**: `ComponentHealth {status: ComponentStatus, error: str | null}` — 单个组件连通性详情
- **状态机**: 健康 → 降级 → 不健康（三态实时观测，非持久化）
- **模块依赖**: DEPLOY-01 (HealthCheckProbe 探针参数、ContainerServiceName 枚举), DEPLOY-05 (AppSettings 连接配置), OBS-01 (LogEntry 结构化日志), OBS-03 (HealthStatus 告警消费)
- **外部依赖**: PostgreSQL 17.x (SELECT 1 连通性验证), Redis 7.x (PING 连通性验证), MinIO (bucket_exists 连通性验证)
- **技术栈**: FastAPI>=0.115, Pydantic>=2.0, asyncio, redis>=5.0 async, minio>=7.0, SQLAlchemy>=2.0 async
- **契约文件**: `docs/contracts/OBS-04/ComponentStatus.json`, `docs/contracts/OBS-04/HealthStatus.json`, `docs/contracts/OBS-04/ComponentHealth.json`, `docs/contracts/OBS-04/HealthCheckResponse.json`, `docs/contracts/OBS-04/ReadinessResponse.json`
- **复用契约**: DEPLOY-01/HealthCheckProbe, DEPLOY-01/ContainerServiceName, DEPLOY-05/AppSettings, OBS-01/LogEntry
- **更新时间**: `2026-05-26 23:07:02`

## PROF-05 - 档案隐私控制
- **输入**: `AccessRequest {operation: AccessOperation, target_profile_id: UUID, requester_id: UUID, requester_role: UserRole, relation_type?: str}` — 档案访问请求
- **输出**: `AccessDecision {allowed: bool, visible_scope: VisibleScope, denial_reason?: str}` — 访问裁决结论
- **枚举**: `AccessOperation` = view | create | update | delete | supplement_assessment | unlink
- **枚举**: `VisibleScope` = all_fields | metadata_only | nothing
- **状态机**: 无（实时无状态裁决）
- **模块依赖**: AUTH-04 (require_role 路由级角色校验、UserRole 枚举、get_current_user 用户信息注入)
- **外部依赖**: PostgreSQL 17.x (teacher_links 表、profiles 表、professional_notes 表)
- **技术栈**: FastAPI>=0.115, SQLAlchemy>=2.0 async, Pydantic>=2.0
- **契约文件**: `docs/contracts/PROF-05/AccessOperation.json`, `docs/contracts/PROF-05/AccessRequest.json`, `docs/contracts/PROF-05/AccessDecision.json`, `docs/contracts/PROF-05/VisibleScope.json`
- **复用契约**: AUTH-04/UserRole, AUTH-04/require_role
- **更新时间**: `2026-05-26 23:02:40`

## KNOW-01 - 科普内容管理
- **输入**: `ArticleCreate {title: str, category: ArticleCategory, content: str, related_case_ids: list[str]}` — 文章创建请求
- **输入**: `ArticleUpdate {title?: str, category?: ArticleCategory, content?: str, related_case_ids?: list[str]}` — 文章更新请求（全部可选）
- **输入**: `ArticleSearchParams {q: str, category?: ArticleCategory, page?: int, page_size?: int}` — 全文检索查询参数
- **输出**: `ArticleResponse {id: str, title: str, category: ArticleCategory, content: str, related_case_ids: list, status: ArticleStatus, published_at: datetime?, created_at: datetime, updated_at: datetime}` — 文章详情
- **输出**: `ArticleListItem {id: str, title: str, category: ArticleCategory, status: ArticleStatus, published_at: datetime?, created_at: datetime}` — 文章列表条目
- **输出**: `ArticleSearchResult {id: str, title: str, category: ArticleCategory, content_snippet: str, status: ArticleStatus, published_at: datetime?, score: float}` — 搜索结果条目
- **枚举**: `ArticleCategory` = 术语解释 | 干预方法 | 诊断标准 | 康复指南
- **枚举**: `ArticleStatus` = published | unpublished
- **状态机**: unpublished ⟷ published（简单二态）
- **模块依赖**: AUTH-04 (require_role 权限校验), CASE-01 (case_repository.exists 案例存在性校验), CASE-03 (case_repository.find_approved_ids 案例审批状态校验)
- **外部依赖**: PostgreSQL 17.x + pgvector (ts_vector GIN 索引全文检索), Redis 7.x (预留缓存), MinIO (预留附件存储)
- **技术栈**: FastAPI>=0.115, SQLAlchemy>=2.0 async, Pydantic>=2.0, Alembic
- **契约文件**: `docs/contracts/KNOW-01/ArticleCategory.json`, `docs/contracts/KNOW-01/ArticleStatus.json`, `docs/contracts/KNOW-01/ArticleCreate.json`, `docs/contracts/KNOW-01/ArticleUpdate.json`, `docs/contracts/KNOW-01/ArticleSearchParams.json`, `docs/contracts/KNOW-01/ArticleResponse.json`, `docs/contracts/KNOW-01/ArticleListItem.json`, `docs/contracts/KNOW-01/ArticleSearchResult.json`
- **复用契约**: PaginatedResponse (项目级共享分页类型)
- **更新时间**: `2026-05-26 17:21:27`

---

## DEPLOY-03 - CI/CD流水线
- **接口**: `CI`（`.github/workflows/ci.yml`）— GitHub Actions CI 工作流，触发方式 `push`/`pull_request` → `main`/`master`
- **接口**: `Deploy`（`.github/workflows/deploy.yml`）— GitHub Actions Deploy 工作流，触发方式 `workflow_run`（CI 成功）+ `workflow_dispatch`（手动）
- **模块依赖**: DEPLOY-01（`docker-compose.prod.yml` 编排配置源），DEPLOY-04（Alembic 迁移验证），QUAL-01（`pytest --cov` 测试命令）
- **契约文件**: 不产生结构化 JSON Schema 契约文件（基础设施配置模块，经 s08 契约协调确认）
- **复用契约**: `ContainerServiceName`（`docs/contracts/DEPLOY-01/ContainerServiceName.json`），`ComposeFileReference`（`docs/contracts/DEPLOY-01/ComposeFileReference.json`），`DATABASE_URL`（`docs/contracts/DEPLOY-04/DATABASE_URL.json`），`MigrationErrorCode`（`docs/contracts/DEPLOY-04/MigrationErrorCode.json`），`MigrationScript`（`docs/contracts/DEPLOY-04/MigrationScript.json`）
- **更新时间**: `2026-05-26 23:05:08`

## AUTH-02 - 用户登录
- **输入**: `LoginRequest {username: str, password: str}` — POST `/api/v1/auth/login` 请求体，接收用户用户名和密码
- **输出**: `LoginResponse {access_token: str, refresh_token: str, token_type: "Bearer", expires_in: int}` — 登录成功响应，包含双令牌和过期时间
- **输出**: `LoginErrorResponse {detail: str}` — 登录失败响应，使用统一模糊错误提示
- **状态机**: 无（一次性请求-响应操作）
- **模块依赖**: AUTH-01 (User ORM 模型、UserRepository.find_by_username_lower、密码哈希数据), AUTH-03 (消费 Refresh Token), AUTH-04 (消费 Access Token 中的 roles 字段), AUTH-05 (调用登录接口), AUTH-06 (消费登录签发的令牌用于前端会话管理), SEC-04 (消费登录失败审计日志作为暴力破解计数数据源)
- **外部依赖**: PostgreSQL 17.x (users 表), packages/py-auth/jwt_utils.py (JWT 签发), packages/py-auth/hashing.py (bcrypt 密码比对), packages/py-config/ (JWT_SECRET/ACCESS_TOKEN_EXPIRE/REFRESH_TOKEN_EXPIRE), packages/py-logger/ (审计日志)
- **技术栈**: FastAPI>=0.115, Pydantic>=2.0, python-jose[cryptography]>=3.3.0, passlib>=1.7
- **契约文件**: `docs/contracts/AUTH-02/LoginRequest.json`, `docs/contracts/AUTH-02/LoginResponse.json`, `docs/contracts/AUTH-02/LoginErrorResponse.json`
- **复用契约**: AUTH-01/UserRole
- **更新时间**: `2026-05-26 23:29:26`

## AUTH-03 - Token续期
- **输入**: `TokenRefreshRequest {refresh_token: str}` — Token 续期请求，仅含当前 Refresh Token（JWT 格式）
- **输出**: `TokenRefreshResponse {access_token: str, refresh_token: str, token_type: "Bearer"}` — 续期成功后返回新 Token 对
- **共享模型**: `TokenBlacklistRotatedKey {key_pattern: "token_blacklist:rotated:{jti}", operation: "SET NX", ttl_seconds: 604800}` — Redis 轮换黑名单 Key 模式
- **状态机**: Refresh Token 单向二态 valid → invalid（不可逆）
- **模块依赖**: AUTH-02 (Refresh Token 签发方), AUTH-04 (新 Access Token 消费方), AUTH-06 (前端续期调用方), SEC-04 (防刷限流保护方)
- **外部依赖**: Redis 7.x (轮换黑名单), PostgreSQL 17.x (角色查询), python-jose (JWT 签发/验证)
- **技术栈**: FastAPI>=0.115, Pydantic>=2.0, Redis>=5.0
- **契约文件**: `docs/contracts/AUTH-03/TokenRefreshRequest.json`, `docs/contracts/AUTH-03/TokenRefreshResponse.json`, `docs/contracts/AUTH-03/TokenBlacklistRotatedKey.json`
- **复用契约**: verify_token (SEC-01), TokenPayload (SEC-01), UserRole (AUTH-04)
- **更新时间**: `2026-05-26 23:06:10`

## AUTH-05 - 登录注册界面
- **输入**: `LoginFormState {username: string, password: string, rememberMe: boolean}` — 登录表单状态（前端内部类型）
- **输入**: `RegisterFormState {roleType: string, username: string, password: string, phoneNumber: string, realName?: string}` — 注册表单状态（前端内部类型）
- **输出**: `AuthPageState {mode: PageMode, status: AuthPageStatus, fieldErrors: FieldError[], globalError: string|null}` — 认证页面完整状态（前端内部类型）
- **状态机**: idle → inputting → submitting → success / failure，failure → inputting
- **模块依赖**: AUTH-01 (注册 API, 通过 AUTH-06 Hook 桥接), AUTH-02 (登录 API, 通过 AUTH-06 Hook 桥接), AUTH-06 (useAuth Hook / userStore / httpClient)
- **外部依赖**: Taro 4.x (路由), Zustand 5.x (状态管理), Taro UI 3.x (组件库), React 18.x
- **技术栈**: Taro>=4.0, React>=18.0, Zustand>=5.0, Taro UI>=3.0, TypeScript>=5.0
- **契约文件**: 无（纯 UI 模块，不定义后端 API 契约）
- **复用契约**: AUTH-01/RegisterRequest, AUTH-01/RegisterResponse, AUTH-01/UserRole
- **更新时间**: `2026-05-26 22:59:07`

## CASE-04 - 案例向量化入库
- **输入**: `enqueue(case_id: UUID) -> dict` — CASE-03 审核通过后调用，将案例投递到索引异步队列
- **输入**: `IndexTaskEnvelope {case_id: UUID, trace_id: str, enqueued_at: datetime}` — Redis List 任务载荷
- **输出**: `ChunkMetadata {behavior_type: str, age_range: str, severity: str, evidence_level: str}` — case_chunks.metadata JSONB 字段
- **枚举**: `IndexStatus` = pending | processing | indexed | indexing_failed
- **模型**: `INDEX_METADATA_KEYS` = ["behavior_type", "age_range", "severity", "evidence_level"] — JSONB 键名常量
- **状态机**: pending→processing→indexed|indexing_failed, indexing_failed→pending（手动重试）
- **模块依赖**: CASE-01 (数据依赖，案例四段式文本), CASE-03 (时序依赖，审核通过触发)
- **外部依赖**: PostgreSQL 17.x + pgvector 0.7+ (HNSW 索引), Redis 7.x (List 异步队列), 阿里 text-embedding-v4 (1024 维向量嵌入)
- **技术栈**: FastAPI>=0.115, Pydantic>=2.0, SQLAlchemy>=2.0 async, httpx>=0.27, redis>=5.0, asyncio
- **契约文件**: `docs/contracts/CASE-04/IndexStatus.json`, `docs/contracts/CASE-04/IndexTaskEnvelope.json`, `docs/contracts/CASE-04/ChunkMetadata.json`, `docs/contracts/CASE-04/INDEX_METADATA_KEYS.json`, `docs/contracts/CASE-04/enqueue.json`
- **更新时间**: `2026-05-27 09:32:11`
