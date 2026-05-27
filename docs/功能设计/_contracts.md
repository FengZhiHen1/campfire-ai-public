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

## PROF-01 - 个人档案管理
- **输入**: `ProfileCreate {nickname?: str, birth_date: date, diagnosis_type: DiagnosisType, primary_behavior: ProfileBehaviorType, language_level?: LanguageLevel, sensory_features?: list[SensoryFeature], triggers?: list[Trigger], medication_notes?: str}` — POST /api/v1/profiles 档案创建请求体，3 项必填 + 5 项可选
- **输入**: `ProfileUpdate {nickname?: str, birth_date?: date, diagnosis_type?: DiagnosisType, primary_behavior?: ProfileBehaviorType, language_level?: LanguageLevel, sensory_features?: list[SensoryFeature], triggers?: list[Trigger], medication_notes?: str}` — PUT /api/v1/profiles/{profile_id} 档案更新请求体，全部可选
- **输出**: `ProfileResponse {profile_id: UUID, nickname?: str, birth_date: date, age_range: AgeRange, diagnosis_type: DiagnosisType, primary_behavior: ProfileBehaviorType, language_level?: LanguageLevel, sensory_features: list[SensoryFeature], triggers: list[Trigger], medication_notes?: str, is_default: bool, caregiver_id: UUID, created_at: datetime, updated_at: datetime}` — 档案完整详情
- **输出**: `ProfileListItem {profile_id: UUID, nickname?: str, age_range: AgeRange, diagnosis_type: DiagnosisType, primary_behavior: ProfileBehaviorType, is_default: bool}` — 档案列表条目（精简版）
- **枚举**: `DiagnosisType` = ASD | 疑似ASD | 其他发育障碍
- **枚举**: `ProfileBehaviorType` = 刻板行为 | 情绪崩溃 | 自伤行为 | 攻击行为 | 社交退缩 | 多动（与 CASE-01/BehaviorType 同名异构，经契约协调确认保持独立——PROF-01 面向个体患者特征分类，CASE-01 面向案例审核筛选）
- **枚举**: `LanguageLevel` = 无语言 | 单字词 | 短句 | 可对话
- **枚举**: `SensoryFeature` = 听觉敏感 | 触觉敏感 | 味觉敏感 | 视觉敏感 | 前庭寻求 | 本体觉寻求
- **枚举**: `Trigger` = 噪音 | 环境变化 | 陌生人 | 任务中断 | 社交压力 | 感官过载 | 身体不适
- **枚举**: `AgeRange` = 0-3岁 | 4-6岁 | 7-12岁 | 13-18岁 | 18岁以上
- **错误码**: `ProfileLimitExceededError`（409 档案数量超限）、`ProfileConflictError`（409 乐观锁并发冲突）
- **状态机**: 无（档案为即时同步操作，无中间状态或异步流程）
- **模块依赖**: PROF-05 (AccessOperation/VisibleScope/AccessRequest/AccessDecision 权限校验), AUTH-04 (require_role 路由角色校验、UserRole 枚举), SEC-03 (预留 _pii_check 扩展点，当前 No-op)
- **外部依赖**: PostgreSQL 17.x (profiles 表 UUID PK + JSONB GIN 索引), Redis 7.x (可选默认档案缓存), Alembic (数据库迁移), packages/py-db/py-schemas/py-auth/py-config/py-logger
- **技术栈**: FastAPI>=0.115, SQLAlchemy>=2.0 async, Pydantic>=2.0, uuid, python-dateutil
- **契约文件**: `docs/contracts/PROF-01/DiagnosisType.json`, `docs/contracts/PROF-01/LanguageLevel.json`, `docs/contracts/PROF-01/SensoryFeature.json`, `docs/contracts/PROF-01/Trigger.json`, `docs/contracts/PROF-01/AgeRange.json`, `docs/contracts/PROF-01/ProfileBehaviorType.json`, `docs/contracts/PROF-01/ProfileCreate.json`, `docs/contracts/PROF-01/ProfileUpdate.json`, `docs/contracts/PROF-01/ProfileResponse.json`, `docs/contracts/PROF-01/ProfileListItem.json`, `docs/contracts/PROF-01/ProfileLimitExceededError.json`, `docs/contracts/PROF-01/ProfileConflictError.json`
- **复用契约**: PROF-05/AccessOperation, PROF-05/VisibleScope, PROF-05/AccessRequest, PROF-05/AccessDecision, AUTH-04/UserRole, AUTH-04/require_role, PaginatedResponse（项目级共享分页类型）
- **更新时间**: `2026-05-27 14:37:41`

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

---

## CSLT-01 - 危机分级判定
- **输入**: `CrisisJudgmentRequest {patient_profile: PatientProfileSnapshot?, behavior_type_selection: list[BehaviorTypeCategory], behavior_description: str}` — 危机分级判定请求，由 CSLT-08 编排层组装后传入 JudgmentPipeline
- **输出**: `CrisisJudgmentResult {final_level: CrisisLevel, block_deep_response: bool, manual_review_flag: bool, review_confidence: float?, judgment_sources: list[JudgmentLayerResult], degradation_note: str?}` — 危机分级判定最终结果
- **枚举**: `CrisisLevel` = mild | moderate | severe（三级危机等级，宁升勿降合并策略）
- **枚举**: `BehaviorTypeCategory` = SELF_INJURY | AGGRESSION | ELOPEMENT | MEDICATION | EMOTIONAL_MELTDOWN | STEREOTYPY | OTHER（7 类前置行为类型，前 4 类为高危）
- **模型**: `JudgmentLayerResult {layer_name: str, level: CrisisLevel, trigger_rule_id: str?, details: dict}` — 单判定层裁决记录，供审计追溯
- **状态机**: 无（无状态判定，每次咨询独立执行三层递进判定）
- **模块依赖**: CSLT-07 (上游数据来源：行为类型勾选+行为描述文本), PROF-02 (上游数据来源：患者档案快照 PatientProfileSnapshot), CSLT-03 (下游数据消费：危机等级+阻断标记), CSLT-05 (下游数据消费：复核标记+置信度), TICK-01 (下游数据消费：危机等级驱动工单生成), TICK-02 (下游数据消费：危机等级映射工单优先级), SEC-02 (共享资源：CRISIS_KEYWORDS 高危关键词库), KNOW-05 (共享资源：CRISIS_KEYWORDS 高危关键词库)
- **外部依赖**: PostgreSQL 17.x (crisis_keywords 表), Redis 7.x (keyword_dict:updates Pub/Sub channel), DeepSeek API (LLM 精调复审), packages/py-llm (DeepSeek API 客户端), packages/py-cache (Redis 客户端), packages/py-db (SQLAlchemy ORM), packages/py-config (环境配置), packages/py-logger (结构化日志)
- **技术栈**: FastAPI>=0.115, Pydantic>=2.0, SQLAlchemy>=2.0 async, Redis>=5.0 async, ahocorasick>=2.0
- **契约文件**: `docs/contracts/CSLT-01/CrisisLevel.json`, `docs/contracts/CSLT-01/BehaviorTypeCategory.json`, `docs/contracts/CSLT-01/JudgmentLayerResult.json`, `docs/contracts/CSLT-01/CrisisJudgmentRequest.json`, `docs/contracts/CSLT-01/CrisisJudgmentResult.json`
- **复用契约**: 无（CSLT-01 为全新模块，所有对外类型均自建契约）
- **更新时间**: `2026-05-27 09:23:20`

---

## CSLT-03 - 应急方案生成
- **输入**: `EmergencyPlanInput {crisis_result: CrisisJudgmentResult, search_result: SemanticSearchResult, profile_summary: str, behavior_description: str, request_id: str, block_variant?: BlockVariant}` — 生成输入，由 CSLT-08 编排层组装后传入
- **输出**: `GenerationResult {text: str, source_list: list[str], disclaimer: str, generation_time_ms: float, is_partial: bool, referenced_slice_ids: list[str], finish_reason: GenerationStatus, ttft_ms: float}` — 生成完成后的完整结果
- **输出**: `GenerationChunk {text: str, is_final: bool, finish_reason?: str}` — 流式生成的增量块，下游 CSLT-04 消费后封装为 SSE
- **枚举**: `BlockVariant` = SELF_INJURY | AGGRESSION | ELOPEMENT | MEDICATION — 阻断场景的高危行为类型变体
- **枚举**: `GenerationStatus` = COMPLETE | PARTIAL | BLOCKED | TIMEOUT | ERROR — 生成执行状态（与 CSLT-02/RetrievalStatus 语义域不同，不可混用）
- **状态机**: 无（无状态生成服务，每次咨询独立执行）
- **模块依赖**: CSLT-01 (crisis_result CrisisJudgmentResult 消费方), CSLT-02 (search_result SemanticSearchResult/CaseSliceDto 消费方), CSLT-04 (GenerationChunk 流式输出消费方), CSLT-05 (GenerationResult 置信度后校验消费方), CSLT-06 (GenerationResult 历史持久化消费方), CSLT-08 (EmergencyPlanInput 组装输入、block_variant 选择), QUAL-02 (GenerationResult 质量评估消费方)
- **外部依赖**: DeepSeek API (LLM 流式生成), packages/py-llm (DeepSeek API 统一客户端), packages/py-logger (结构化日志), packages/py-config (环境配置), Prometheus (可观测性指标)
- **技术栈**: FastAPI>=0.115, Pydantic>=2.0, asyncio
- **契约文件**: `docs/contracts/CSLT-03/EmergencyPlanInput.json`, `docs/contracts/CSLT-03/GenerationResult.json`, `docs/contracts/CSLT-03/GenerationChunk.json`, `docs/contracts/CSLT-03/BlockVariant.json`, `docs/contracts/CSLT-03/GenerationStatus.json`
- **复用契约**: CSLT-01/CrisisJudgmentResult, CSLT-01/CrisisLevel, CSLT-02/SemanticSearchResult, CSLT-02/CaseSliceDto, CSLT-02/EvidenceLevel, CSLT-02/DegradationLevel
- **更新时间**: `2026-05-27 14:45:00`

## CSLT-02 - RAG语义检索
- **输入**: `SemanticSearchInput {query_text: str, tag_filters: TagFilterDto, top_k?: int, request_id?: str}` — 检索请求，包含查询文本、标签过滤条件和期望返回数量
- **输入**: `TagFilterDto {age_range: str, behavior_type: str, emotion_level?: str, sensory_features?: str}` — 档案标签过滤条件（临时自包含定义，待 PROF-02 落地后改为引用）
- **输出**: `SemanticSearchResult {results: list[CaseSliceDto], total_count: int, is_complete: bool, reason?: str, query_fingerprint: str, degradation_applied: bool, degradation_level: DegradationLevel, elapsed_ms: float}` — 检索结果，包含排序后的案例切片列表和状态标记
- **输出**: `CaseSliceDto {slice_id: UUID, case_id: str, slice_text: str, chunk_type: str, similarity_score: float, composite_score: float, evidence_level: EvidenceLevel, case_title?: str, source?: str, case_created_at: date, applicable_tags?: dict}` — 单条案例切片详情
- **枚举**: `EvidenceLevel` = NCAEP | INSTITUTIONAL_EXPERIENCE | CASE_OBSERVATION — 案例循证等级，用于综合排序加权
- **枚举**: `DegradationLevel` = NONE | EMOTION_RELAXED | BEHAVIOR_RELAXED | ALL_TAGS_REMOVED — 检索降级放宽层级
- **枚举**: `RetrievalStatus` = COMPLETE | PARTIAL | TIMEOUT | EMPTY — 检索执行状态
- **状态机**: 无（每次检索为独立同步请求-响应操作）
- **模块依赖**: PROF-02 (档案驱动检索过滤，上游提供标签条件), CASE-04 (案例向量化入库，上游提供向量索引), CASE-06 (案例淘汰管理，上游标记失效状态), CSLT-03 (应急方案生成，下游消费检索结果)
- **外部依赖**: PostgreSQL 17.x + pgvector (HNSW 向量索引混合检索), 阿里云 DashScope (text-embedding-v4 文本向量化，1024 维), DEPLOY-05/AppSettings (嵌入模型和 API 配置)
- **技术栈**: FastAPI>=0.115, SQLAlchemy>=2.0 async, Pydantic>=2.0, LangChain>=0.3, pgvector>=0.7, asyncio
- **契约文件**: `docs/contracts/CSLT-02/SemanticSearchInput.json`, `docs/contracts/CSLT-02/TagFilterDto.json`, `docs/contracts/CSLT-02/CaseSliceDto.json`, `docs/contracts/CSLT-02/SemanticSearchResult.json`, `docs/contracts/CSLT-02/EvidenceLevel.json`, `docs/contracts/CSLT-02/DegradationLevel.json`, `docs/contracts/CSLT-02/RetrievalStatus.json`
- **复用契约**: DEPLOY-05/AppSettings, CSLT-01/BehaviorTypeCategory
- **更新时间**: `2026-05-27 09:30:29`

## CSLT-04 - 流式应答推送
- **输出**: `ChunkEvent {text: str, sequence: int}` — SSE chunk 事件 data 载荷，承载文本增量与递增序列号
- **输出**: `DoneEvent {finish_reason: str, sequence?: int}` — SSE done 事件 data 载荷，标记流终止及原因
- **输出**: `ErrorEvent {error_code: str, detail: str}` — SSE error 事件 data 载荷，携带错误码与说明
- **输出**: `HeartbeatEvent {}` — SSE 心跳保活事件标记，15 秒间隔无 data 负载
- **枚举**: `StreamErrorCode` = SESSION_NOT_FOUND | GENERATION_FAILED | STREAM_TIMEOUT | CONCURRENCY_LIMIT_EXCEEDED | INTERNAL_ERROR
- **状态机**: 无（纯数据推送通道，内部 5 态生命周期纯内存不持久化）
- **模块依赖**: CSLT-03 (GenerationChunk AsyncGenerator 上游数据来源), CSLT-08 (SSE 事件流下游消费方), DEPLOY-02 (Nginx SSE 路由预配置), AUTH-04 (JWT 认证中间件)
- **外部依赖**: FastAPI StreamingResponse (SSE 封装), Uvicorn (ASGI 运行时), Nginx proxy_buffering off (实时透传)
- **技术栈**: FastAPI>=0.115, Pydantic>=2.0, asyncio
- **契约文件**: `docs/contracts/CSLT-04/ChunkEvent.json`, `docs/contracts/CSLT-04/DoneEvent.json`, `docs/contracts/CSLT-04/HeartbeatEvent.json`, `docs/contracts/CSLT-04/ErrorEvent.json`, `docs/contracts/CSLT-04/StreamErrorCode.json`
- **复用契约**: CSLT-03/GenerationChunk, CSLT-03/GenerationStatus, DEPLOY-05/AppSettings, OBS-01/LogEntry
- **更新时间**: `2026-05-27 17:45:12`

## CSLT-05 - 置信度后校验
- **输出**: `ConfidenceValidationOutput {confidence_score: float, verdict: ValidationVerdict, modified_plan_text?: str, ticket_triggered: bool, ticket_creation_failed?: bool, degradation_note?: str, validation_time_ms: int}` — 校验结果输出，含置信度分数、判定结论、工单触发状态
- **输入**: `ConfidenceValidationInput {plan_text: str, source_list: list, disclaimer: str, crisis_level: CrisisLevel, high_risk_keyword_hit: bool, judgment_layer_results: list, emergency_scene: EmergencyScene, generation_id: str}` — 校验输入参数，由 CSLT-08 编排层组装
- **枚举**: `ValidationVerdict` = PASS | APPEND_WARNING | FORCE_BLOCK
- **状态机**: 5 阶段内部流程（输入校验→关键词检测→LLM 自评估→降级规则评分→复合评分与判定）
- **模块依赖**: CSLT-01 (CrisisJudgmentResult/CrisisLevel 上游), CSLT-03 (GenerationResult 上游), CSLT-08 (编排层调用方), CSLT-06 (ConfidenceValidationOutput 持久化消费方), TICK-01 (工单触发消费方)
- **技术栈**: FastAPI, Pydantic>=2.0, AC 自动机 (pyahocorasick), BackgroundTasks (工单重试)
- **契约文件**: `docs/contracts/CSLT-05/ConfidenceValidationInput.json`, `docs/contracts/CSLT-05/ConfidenceValidationOutput.json`, `docs/contracts/CSLT-05/ValidationVerdict.json`
- **复用契约**: CSLT-01/CrisisLevel, CSLT-01/CrisisJudgmentResult, CSLT-03/GenerationResult
- **更新时间**: `2026-05-27 17:55:00`

## CSLT-06 - 咨询历史管理
- **输入**: `ConsultationHistoryCreate {user_id: str, consultation_time: str, crisis_level: CrisisLevel, user_input: str, retrieved_cases: list, generated_plan_text: str, disclaimer: str, generation_id: str, confidence_score?: float, validation_verdict?: ValidationVerdict, request_id: str}` — 归档写入模型，由 CSLT-08 组装
- **输出**: `ConsultationHistoryListItem {id: str, consultation_time: str, crisis_level: CrisisLevel, summary_text: str}` — 列表摘要条目
- **输出**: `ConsultationHistoryDetail {id, user_id, consultation_time, crisis_level, user_input, retrieved_cases, generated_plan_text, disclaimer, generation_id, confidence_score, validation_verdict, feedback_collected, request_id, created_at}` — 单次咨询完整详情
- **状态机**: 无（纯 CRUD 归档模块，即时同步操作）
- **模块依赖**: CSLT-03 (GenerationResult/GenerationStatus 上游数据源), CSLT-08 (触发归档写入), CSLT-05 (confidence_score 字段来源), TICK-01 (列表查询消费方), QUAL-03 (feedback 回填), QUAL-04 (列表查询消费方)
- **技术栈**: FastAPI, SQLAlchemy, PostgreSQL (consultations 表), PaginatedResponse 项目级分页
- **契约文件**: `docs/contracts/CSLT-06/ConsultationHistoryCreate.json`, `docs/contracts/CSLT-06/ConsultationHistoryListItem.json`, `docs/contracts/CSLT-06/ConsultationHistoryDetail.json`
- **复用契约**: CSLT-01/CrisisLevel, CSLT-03/GenerationResult, CSLT-03/GenerationStatus, AUTH-04/UserRole, PROJECT/PaginatedResponse
- **更新时间**: `2026-05-27 17:56:00`

## PROF-03 - 事件记录管理
- **输入**: `EventCreate {behavior_type: ProfileBehaviorType, event_time: str, setting?: EventSetting, severity?: SeverityLevel, description: str, response?: str, result?: str, tags?: list}` — 创建事件记录
- **输入**: `EventUpdate {behavior_type?: ProfileBehaviorType, event_time?: str, setting?: EventSetting, severity?: SeverityLevel, description?: str, response?: str, result?: str, tags?: list}` — 更新事件记录 (Merge Patch)
- **输出**: `EventResponse {id, profile_id, behavior_type, event_time, setting, severity, description, response, result, tags, recorded_by, recorded_by_role, created_at, updated_at}` — 事件完整详情
- **输出**: `EventListItem {id, behavior_type, event_time, severity, description, created_at}` — 列表精简条目
- **枚举**: `EventSetting` = 家庭 | 学校 | 社区 | 机构 | 其他
- **枚举**: `SeverityLevel` = 轻 | 中 | 重（注意：CASE-01 存在同名异构枚举 ['轻度','中度','重度']，域不同保持独立）
- **错误**: `EventLimitExceededError` — 容量超限错误 (HTTP 409，500 条上限)
- **状态机**: 无（即时同步 CRUD，无中间状态流转）
- **模块依赖**: PROF-01 (ProfileResponse/ProfileBehaviorType 上游), PROF-05 (隐私权限校验 AccessOperation/AccessRequest/AccessDecision/VisibleScope), AUTH-04 (角色鉴权 UserRole/require_role)
- **技术栈**: FastAPI, SQLAlchemy, PostgreSQL (event_logs 表, 16 字段), 三层权限校验链 (路由→档案→创建者)
- **契约文件**: `docs/contracts/PROF-03/EventCreate.json`, `docs/contracts/PROF-03/EventUpdate.json`, `docs/contracts/PROF-03/EventResponse.json`, `docs/contracts/PROF-03/EventListItem.json`, `docs/contracts/PROF-03/EventSetting.json`, `docs/contracts/PROF-03/SeverityLevel.json`, `docs/contracts/PROF-03/EventLimitExceededError.json`
- **复用契约**: PROF-01/ProfileBehaviorType, PROF-01/ProfileResponse, PROF-05/AccessOperation, PROF-05/AccessRequest, PROF-05/AccessDecision, PROF-05/VisibleScope, AUTH-04/UserRole, AUTH-04/require_role
- **更新时间**: `2026-05-27 17:57:00`

## CASE-09 - 案例管理逻辑
- **类型**: 前端 L1b 纯消费者模块，不定义新的后端 API 契约
- **输入**: 消费 CASE-01 全部 13 份契约 (CaseCreateRequest, CaseUpdate, CaseResponse, CaseListItem, CaseStatus, SceneType, SeverityLevel, BehaviorType, FamilyDisplayCategory, SourceType, EvidenceLevel, PiiDetectionResult, PiiWarning) + AUTH-06 的 4 份契约 (TokenPair, SessionState, useAuthReturn, httpClient)
- **状态机**: 5 态前端表单 (IDLE→DIRTY→SUBMITTING→SUBMIT_SUCCESS→SUBMIT_ERROR) + 案例只读展示
- **模块依赖**: CASE-01 (案例数据契约全部复用), AUTH-06 (认证前端契约)
- **技术栈**: TypeScript 5, Taro 4, Zustand 5, AbortController (超时/竞态)
- **契约文件**: `docs/contracts/CASE-09/_module-index.json` (reference_only)
- **复用契约**: CASE-01 全部 13 份 + AUTH-06 全部 4 份
- **更新时间**: `2026-05-27 17:58:00`

## PROF-07 - 档案数据逻辑
- **类型**: 前端 L1b 纯消费者模块，不定义新的后端 API 契约
- **输入**: 消费 PROF-01 全部 12 份契约 (ProfileListItem, ProfileResponse, ProfileCreate, ProfileUpdate, DiagnosisType, LanguageLevel, SensoryFeature, Trigger, AgeRange, ProfileBehaviorType, ProfileLimitExceededError, ProfileConflictError) + AUTH-06 的 4 份契约 (TokenPair, SessionState, useAuthReturn, httpClient) + PROF-03 的 1 份契约 (EventCreate)
- **状态机**: 3 个前端交互态 — 档案列表加载 (idle→loading→ready/error)、档案提交 (idle→submitting→success/idle/error)、微问卷弹出 (hidden→showing→answering→submitted→hidden)
- **输出**: `UseProfileReturn {profiles: ProfileListItem[], isLoading: boolean, error: Error|null, fetchProfiles, getProfile, createProfile, updateProfile, deleteProfile, setDefault}` — useProfile() Hook 返回值（供 PROF-06 消费）
- **输出**: `ProfileCoordination {checkProfileExists(), triggerMicroSurvey(consultationId), onProfileChanged(callback)}` — 供 CSLT-08 消费的横向协作接口（前端 TypeScript 内部类型，不创建 JSON Schema）
- **输出**: `UseMicroSurveyReturn {state: MicroSurveyState, questions: MicroSurveyQuestion[], submit, skip}` — useMicroSurvey() Hook 返回值
- **模块依赖**: PROF-01 (档案 CRUD API), PROF-02 (缓存失效 API — 依赖缺口 GAP-01), PROF-03 (事件记录 API), AUTH-06 (httpClient + useAuth), CSLT-08 (ProfileCoordination 调用方 — 依赖缺口 GAP-02)
- **技术栈**: TypeScript 5, Taro 4, React 18, Zustand 5
- **契约文件**: `docs/contracts/PROF-07/_module-index.json` (reference_only)
- **复用契约**: PROF-01 全部 12 份 + AUTH-06 全部 4 份 + PROF-03 EventCreate
- **依赖缺口**: GAP-01 — PROF-02 缓存失效 API 未定义（降级 console.warn）；GAP-02 — CSLT-08 ProfileCoordination 接口未正式定义（当前约定可独立开发）
- **更新时间**: `2026-05-27 21:48:26`
