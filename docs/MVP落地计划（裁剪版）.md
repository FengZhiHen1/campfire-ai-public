# 篝火智答 (Campfire-AI) — MVP 落地计划（裁剪版）

> 版本：v1.0  
> 日期：2026-05-27  
> 约束条件：**忽略全部认证层（AUTH-01 ~ AUTH-06）**，仅聚焦核心功能闭环  
> 目标：实现「匿名用户即可完成的应急咨询端到端闭环 + 案例库基础管理」

---

## 一、范围定义：什么进 MVP，什么砍掉

### 1.1 明确纳入 MVP 的功能

| 功能域 | 纳入范围 | 说明 |
|:---|:---|:---|
| **应急咨询（CSLT）** | CSLT-02 RAG 语义检索、CSLT-03 应急方案生成、CSLT-04 流式应答推送、CSLT-06 咨询历史管理 | 核心闭环，必须完整 |
| **个性化档案（PROF）** | PROF-01 个人档案管理（简化版）、PROF-02 档案驱动检索过滤、PROF-03 事件记录管理（简化版） | 去掉隐私控制和冷启动引导，保留标签驱动检索 |
| **真实案例库（CASE）** | CASE-01 案例录入管理、CASE-03 案例审核工作流（简化版：专家终审即可，去掉 AI 预审）、CASE-04 案例向量化入库 | 保证案例能进入 RAG 索引 |
| **系统可观测性（OBS）** | OBS-01 结构化日志、OBS-04 健康检查 | 已有实现，保留 |
| **安全与合规（SEC）** | SEC-05 输入校验防护（Pydantic）、SEC-04 防刷限流 | 已有实现，保留；PII 检测降级为提示而非阻断 |
| **部署与运维（DEPLOY）** | DEPLOY-01 容器编排（开发环境）、DEPLOY-04 数据库迁移 | 生产 Nginx/SSL 可后延 |

### 1.2 明确砍掉/延期的功能

| 功能域 | 处理方式 | 理由 |
|:---|:---|:---|
| **全部认证（AUTH）** | ❌ 完全跳过 | 约束条件；前端不区分角色，后端所有接口开放访问 |
| **危机分级判定（CSLT-01）** | ⏸️ 降级为硬编码提示 | 去掉三层递进判定，改为咨询输出中固定追加免责声明；危机关键词检测保留但仅用于日志标记 |
| **置信度后校验（CSLT-05）** | ⏸️ 降级为前端展示分数 | 不触发自动工单，仅展示 LLM 返回的 confidence 字段 |
| **人工兜底通道（TICK）** | ❌ 完全跳过 | P1 功能，MVP 无认证则工单系统无法指派 |
| **科普查阅（KNOW）** | ❌ 完全跳过 | P2 功能 |
| **案例版本迭代 / 淘汰 / 模板提炼（CASE-05/06/07）** | ❌ 跳过 | 降低案例管理复杂度 |
| **案例附件管理（CASE-02）** | ⏸️ 跳过附件上传 | 案例仅支持纯文本录入，暂不支持文件上传 |
| **AI 预审（CASE-03 子功能）** | ❌ 跳过 | 减少实现复杂度，仅保留专家终审 |
| **专业评估补充（PROF-04）** | ❌ 跳过 | 降低档案共建复杂度 |
| **档案隐私控制（PROF-05）** | ❌ 跳过 | 无认证则无角色，隐私控制无意义；档案全公开读写 |
| **档案冷启动引导（PROF-07 子功能）** | ⏸️ 降级为静态提示 | 首次使用时弹窗提示填写 3 个必填标签 |
| **Prometheus/Grafana 监控** | ❌ 跳过 | 仅保留结构化日志 |
| **RAG 质量评估流水线（QUAL-02）** | ❌ 跳过 | 后延 |
| **Token 用量追踪（QUAL-04）** | ⏸️ 降级为日志打印 | 不建表持久化，仅通过 py-logger 输出 |

### 1.3 匿名用户策略（替代认证层）

既然跳过认证，需要一个极简的身份标识机制来区分不同用户的数据：

```
方案：设备匿名 ID（device_anonymous_id）
- 小程序启动时调用 wx.getStorageSync('campfire_device_id')
- 若不存在，生成一个 16 位随机字符串存入 Storage
- 所有 API 请求在 Header 中携带 X-Device-Id: <device_id>
- 后端不校验该 ID 的合法性，仅用它作为 users 表的外键替代
```

后端数据层调整：
- `users` 表不再通过注册创建，而是在首次收到未知 `device_id` 时自动插入一条匿名用户记录
- 字段极度简化：`id`（UUID）、`device_id`（VARCHAR 16, UNIQUE）、`created_at`
- 档案、咨询历史、案例均通过 `device_id` 关联
- 无密码、无角色、无 JWT

---

## 二、阻塞性问题修复清单（必须先解决）

按执行顺序排列：

| # | 任务 | 影响 | 预估工时 |
|:---|:---|:---|:---|
| 1 | **补全 Alembic 迁移脚本（MVP 核心表）** | 系统无法运行任何 CRUD | 1 天 |
| 2 | **实现 `api-server/app/main.py` + 路由注册** | 后端无法启动 | 0.5 天 |
| 3 | **实现 Worker `case_indexer.py` + 消费循环** | RAG 检索永为空 | 2 天 |
| 4 | **前端 Taro 工程初始化 + 应用骨架** | 无可用界面 | 1 天 |

这四项是**所有后续开发的前置条件**，必须在 Phase 0 全部完成。

---

## 三、分阶段落地计划

> 估算基于 **1 名后端 + 1 名前端** 的 2 人并行团队，每日有效工时 6 小时。

---

### Phase 0：地基抢修（第 1-3 天）

**目标**：让后端能启动、数据库有表、前端能编译预览、Worker 能消费任务。

#### 后端任务

| 任务 | 详情 | 验收标准 |
|:---|:---|:---|
| P0-B1 | 补全 Alembic 迁移脚本 | 创建以下表的迁移（可基于现有 ORM 模型）：`users`（极简匿名版）、`profiles`、`cases`、`case_chunks`、`consultations`、`consultation_logs`、`reviews`。执行 `alembic upgrade head` 后所有表存在 |
| P0-B2 | 实现 `app/main.py` | FastAPI 实例创建、lifespan（启动时初始化 DB 连接池）、挂载全部路由（health、consult、profiles、cases、reviews）、CORS 中间件、全局异常处理器 |
| P0-B3 | 验证 Docker Compose 开发环境 | `docker compose up -d` 后 postgres/redis/minio 均健康；`uvicorn app.main:app --reload` 能启动且不报错 |

#### 前端任务

| 任务 | 详情 | 验收标准 |
|:---|:---|:---|
| P0-F1 | Taro 工程初始化 | 安装 `@tarojs/cli`、`@tarojs/webpack5-runner`、`@tarojs/components` 等核心依赖；补充 `app.tsx`、`app.config.ts`、`project.config.json`；执行 `pnpm dev:weapp` 能编译出 `dist/` 且微信开发者工具可预览 |
| P0-F2 | 建立 API Service 骨架 | 实现 `logics/shared/services/httpClient.ts`：封装 `Taro.request`、注入 `X-Device-Id`、统一错误处理；实现 `logics/shared/services/tokenManager.ts`（本 MVP 中仅管理 device_id，无 JWT） |

#### Worker 任务

| 任务 | 详情 | 验收标准 |
|:---|:---|:---|
| P0-W1 | 实现 Worker 主循环 | `apps/worker/src/worker/main.py`：Redis 队列监听循环（可用 `redis` 的 `blpop` 做简单队列）、优雅关闭信号处理 |
| P0-W2 | 实现案例索引任务 | `apps/worker/src/worker/tasks/case_indexer.py`：从 Redis 队列取出 `case_id` → 读取案例全文 → 调用 `py_rag.splitters` 切片 → 调用 `py_rag.embedding.encode_text` 向量化 → 写入 `case_chunks` 表 → 更新 `cases.status='approved'`。失败重试 3 次，最终失败标记 `indexing_failed` |
| P0-W3 | Worker Docker 验证 | `docker compose -f docker-compose.yml`（或单独命令）能启动 worker 容器，且 worker 能连接 Redis 消费任务 |

**Phase 0 验收**：
- [ ] `docker compose up -d` 启动全部基础设施
- [ ] `uvicorn app.main:app --reload` 启动 API Server，Swagger UI (`/docs`) 可访问
- [ ] Worker 容器启动并监听 Redis 队列
- [ ] 微信开发者工具可加载小程序并显示首页（哪怕只是 "Hello Campfire"）
- [ ] `alembic upgrade head` 后数据库包含全部 MVP 核心表

---

### Phase 1：应急咨询核心闭环（第 4-9 天）

**目标**：用户能在小程序输入行为描述 → 后端 RAG 检索 + LLM 生成 → SSE 流式返回 → 前端渲染结果。

#### 后端任务

| 任务 | 详情 | 验收标准 |
|:---|:---|:---|
| P1-B1 | 补全咨询触发端点 | `POST /api/v1/consult`：接收 `behavior_description` + `profile_id`（可选），调用 `consult_service` 编排：①读取档案标签 → ②调用 `py_rag.retrieval.hybrid_search` → ③调用 `py_llm.client` 流式生成 → ④注册 SSE Generator → ⑤返回 `{session_id}` |
| P1-B2 | 连接现有 SSE 流式端点 | `GET /api/v1/consult/stream/{session_id}` 已有实现，需确认与 P1-B1 的 `SseStreamingService` 注册逻辑衔接正常 |
| P1-B3 | 咨询历史管理 | `GET /api/v1/consultations`（列表）、`GET /api/v1/consultations/{id}`（详情）：基于 `device_id` 过滤，返回历史咨询记录 |
| P1-B4 | 简化档案管理 | `POST /api/v1/profiles`（创建/更新）、`GET /api/v1/profiles/me`（查询当前 device_id 关联的档案）：仅保留核心字段（出生日期/诊断类型/主要行为类型/标签 JSONB）。**跳过 RBAC 和隐私控制** |
| P1-B5 | 档案标签注入检索 | 在 `consult_service` 中，若用户携带 `profile_id`，从档案提取 `age_range`、`behavior_type`、`emotion_level` 注入 `hybrid_search` 的 `tag_filters` |
| P1-B6 | 应急方案 Prompt 调优 | 在 `py_rag/prompts.py`（或现有 `prompt_builder.py`）中确认 Prompt 已包含：①系统角色设定 ②四段式输出约束 ③免责声明 ④来源溯源要求。确保 LLM 输出结构稳定 |

#### 前端任务

| 任务 | 详情 | 验收标准 |
|:---|:---|:---|
| P1-F1 | 应急咨询主页面 | `views/consult/pages/index.tsx`：①行为描述输入框（多行文本）②档案标签选择器（年龄/行为类型/情绪等级，若已有档案则自动填充）③提交按钮。纯 UI，数据通过 `useConsult` Hook 驱动 |
| P1-F2 | 应急方案流式渲染组件 | `views/consult/components/StreamOutput.tsx`：消费 SSE 事件流，逐句渲染四段式结构（即时动作/安抚话术/观察指标/就医判断）。支持高亮和来源引用展示 |
| P1-F3 | 咨询编排 Hook | `logics/consult/hooks/useConsult.ts`：①提交行为描述 → 接收 `session_id` → 建立 SSE 连接（`Taro.request` + `enableChunked: true`）②解析 chunk/done/error 事件 ③更新 consultStore ③连接中断自动重连（最多 3 次） |
| P1-F4 | 咨询历史页面 | `views/consult/pages/history.tsx`：列表展示历史咨询（行为描述摘要、生成时间），点击进入详情页展示完整方案和来源 |
| P1-F5 | 档案编辑页面 | `views/profiles/pages/edit.tsx`：表单编辑档案必填字段（出生日期、诊断类型、主要行为类型）和标签。提交后调用 `profileApi` |

**Phase 1 验收**：
- [ ] 小程序端可输入行为描述 + 选择标签，点击提交后 3 秒内开始流式输出
- [ ] 流式输出按四段式结构渲染，包含免责声明
- [ ] 历史页面可查看过往咨询记录
- [ ] 档案编辑后，再次咨询时 RAG 检索自动使用档案标签过滤

---

### Phase 2：案例库基础管理（第 10-14 天）

**目标**：老师/专家能提交案例 → 专家终审 → Worker 异步索引入库 → RAG 检索能命中新案例。

#### 后端任务

| 任务 | 详情 | 验收标准 |
|:---|:---|:---|
| P2-B1 | 案例提交端点 | `POST /api/v1/cases`：接收案例字段（场景描述、行为表现、干预动作、结果反馈、适用人群标签、循证等级）。Pydantic 校验必填四段式字段 |
| P2-B2 | 案例审核端点（简化版） | `POST /api/v1/cases/{id}/review`：专家执行 `approve` / `reject` + 修改意见。状态机：`draft` → `pending_review` → `approved` / `rejected`。审核通过后投递 Redis 队列触发 Worker 索引 |
| P2-B3 | 案例查询列表 | `GET /api/v1/cases`：支持按状态（`pending_review` / `approved`）和行为类型筛选；分页每页 15 条 |
| P2-B4 | 案例详情查询 | `GET /api/v1/cases/{id}`：返回完整案例字段和审核意见 |
| P2-B5 | 确认 Worker 索引链路 | 案例审核通过后，Worker 能在 10 秒内完成切片 + 向量化 + 写入 `case_chunks`。查询 `case_chunks` 表可见新记录 |

#### 前端任务

| 任务 | 详情 | 验收标准 |
|:---|:---|:---|
| P2-F1 | 案例提交页面 | `views/cases/pages/submit.tsx`：四段式表单（场景描述、行为表现、干预动作、结果反馈）+ 标签选择器。提交后跳转列表页 |
| P2-F2 | 案例列表页面 | `views/cases/pages/index.tsx`：卡片列表，支持按状态和行为类型筛选。专家视角展示待审核标签 |
| P2-F3 | 案例详情/审核页面 | `views/cases/pages/detail.tsx`：展示完整案例内容。若状态为 `pending_review` 且当前用户角色为专家（本 MVP 中前端硬编码判断或不做判断），展示通过/驳回按钮 |
| P2-F4 | 审核状态同步 | 审核操作后自动刷新列表，并提示「案例已进入索引队列」 |

**Phase 2 验收**：
- [ ] 可提交完整案例，四段式字段非空校验生效
- [ ] 专家可在详情页执行审核通过
- [ ] 审核通过后，Worker 自动完成索引入库
- [ ] 新案例可被 RAG 检索命中（可通过提交一个与案例内容高度相似的行为描述来验证）

---

### Phase 3：质量收敛与端到端打磨（第 15-18 天）

**目标**：修复已知缺陷、补齐测试、确保核心链路稳定。

#### 后端任务

| 任务 | 详情 | 验收标准 |
|:---|:---|:---|
| P3-B1 | 修复对抗性测试缺陷（后端） | 按 `testing-design/*/adversarial-report.md` 和 `test-defects-round-*.md` 中的记录，优先修复 CSLT-02/03/04、CASE-01/03/04、PROF-01/02 相关缺陷 |
| P3-B2 | 输入校验与边界加固 | 所有 API 入参增加边界校验（字符串长度、数值范围、枚举值合法性）；Pydantic `ValidationError` 返回统一格式 |
| P3-B3 | 种子数据导入 | 准备 20-30 条种子案例（覆盖自伤/攻击/刻板/逃跑/ meltdown 等行为类型），通过脚本 `scripts/seed.sh` 一键导入并触发索引 |
| P3-B4 | 限流中间件挂载 | 确认 `middleware/rate_limit.py` 已在 `main.py` 中注册，IP 级限流 100 req/min 生效 |

#### 前端任务

| 任务 | 详情 | 验收标准 |
|:---|:---|:---|
| P3-F1 | 错误状态与加载态 | 所有页面增加加载指示器、网络错误重试、空状态展示。提交按钮防重复点击 |
| P3-F2 | 表单校验与反馈 | 案例提交表单前端预校验（四段式字段非空、字数下限）；错误提示在 500ms 内呈现 |
| P3-F3 | 响应式适配 | 核心页面在微信小程序 iPhone/Android 主流机型上视觉正常，无溢出或截断 |
| P3-F4 | 联调 Bug 修复 | 前后端字段对齐（特别注意日期格式、枚举值大小写、分页参数） |

#### 测试任务

| 任务 | 详情 | 验收标准 |
|:---|:---|:---|
| P3-T1 | 核心路径集成测试 | 编写 3-5 个 pytest 集成测试：①提交咨询并验证 SSE 输出非空 ②提交案例→审核通过→验证 case_chunks 新增记录 ③档案更新后咨询携带正确标签过滤 |
| P3-T2 | 数据库迁移可重复性验证 | 全新数据库执行 `alembic upgrade head` → 跑种子脚本 → 跑集成测试，全程无报错 |

**Phase 3 验收**：
- [ ] 20-30 条种子案例已入库，RAG 检索有实质性内容返回
- [ ] 集成测试全部通过（≥3 个用例）
- [ ] 主要对抗性缺陷已修复或已评估为可接受
- [ ] 小程序在真机/模拟器上核心链路无阻塞性 Bug

---

### Phase 4：部署验证与交付准备（第 19-21 天）

**目标**：开发环境一键启动，代码可稳定运行，交付物齐备。

| 任务 | 详情 | 验收标准 |
|:---|:---|:---|
| P4-1 | 开发环境一键脚本 | `scripts/dev.sh`：启动 docker compose → 执行 alembic upgrade → 启动 uvicorn → 启动 worker。单命令完成 |
| P4-2 | 种子数据脚本固化 | `scripts/seed.sh`：清空并重新导入种子案例，自动触发 Worker 索引。5 分钟内完成 |
| P4-3 | README 更新 | 根目录 `README.md` 补充：快速启动命令、环境变量说明、核心功能截图/录屏、已知限制（无认证、无工单、无科普） |
| P4-4 | 代码清理 | 删除 `.tmp/` 下与 MVP 无关的对抗性测试产物（保留 `testing-design/` 文档本身）；清理 `__pycache__` 和未使用导入 |
| P4-5 | 全量 Docker 验证 | `docker compose up --build` 成功启动全部服务；API `/health` 返回 200；Worker 日志显示监听中；小程序可连接本地 API 完成一次完整咨询 |

**Phase 4 验收**：
- [ ] 新成员 clone 项目后，按 README 能在 10 分钟内看到运行中的系统
- [ ] `docker compose up` 启动后所有服务健康
- [ ] 小程序能完成「建档 → 咨询 → 看历史 → 提交案例 → 审核 → 再次咨询命中新案例」完整闭环

---

## 四、数据库 Schema 极简版（MVP 专用）

因跳过认证，Schema 大幅简化。仅列出与标准设计文档的差异：

```sql
-- users 表：极简匿名设备标识
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(32) UNIQUE NOT NULL,  -- 小程序生成的匿名 ID
    created_at TIMESTAMPTZ DEFAULT now()
);

-- profiles 表：去掉 created_by/updated_by/visibility，增加 user_id 外键
CREATE TABLE profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    age INT,
    diagnosis_type VARCHAR(100),
    tags JSONB DEFAULT '{}',  -- {behavior_types:[], emotion_triggers:[], ...}
    guardian_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- cases 表：去掉 author_id/reviewer_id 外键（保留字段为可选），附件字段移除
CREATE TABLE cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(200) NOT NULL,
    status VARCHAR(20) DEFAULT 'draft',  -- draft / pending_review / approved / rejected / indexing_failed
    scene_description TEXT NOT NULL,
    behavior_manifestation TEXT NOT NULL,
    intervention_action TEXT NOT NULL,
    result_feedback TEXT NOT NULL,
    applicable_population JSONB,
    behavior_type VARCHAR(50),
    emotion_level VARCHAR(20),
    evidence_level VARCHAR(50),
    review_comment TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- consultations 表：增加 user_id 外键，去掉 disclaimer_served/complex sources
CREATE TABLE consultations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    behavior_description TEXT NOT NULL,
    retrieved_case_ids UUID[],
    generated_plan JSONB,  -- {immediate_action, soothing_script, observation, medical_judgment}
    confidence_score DECIMAL(3,2),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- case_chunks 表：与现有设计基本一致
CREATE TABLE case_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    embedding vector(1024),  -- pgvector
    chunk_type VARCHAR(50),
    metadata JSONB
);

-- reviews 表：简化审核记录
CREATE TABLE reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
    action VARCHAR(20) NOT NULL,  -- approve / reject
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

> 注：上述 Schema 由 Alembic 迁移脚本生成，开发时以 `packages/py-db/py_db/models/` 中的 ORM 模型为准。

---

## 五、API 端点清单（MVP 裁剪后）

| 方法 | 路径 | 功能 | 对应模块 |
|:---|:---|:---|:---|
| GET | `/health` | 健康检查 | OBS-04 |
| GET | `/api/v1/health` | 健康检查（版本化） | OBS-04 |
| POST | `/api/v1/consult` | 提交应急咨询，返回 session_id | CSLT-02/03 |
| GET | `/api/v1/consult/stream/{session_id}` | SSE 流式获取应急方案 | CSLT-04 |
| GET | `/api/v1/consultations` | 查询当前 device_id 的咨询历史 | CSLT-06 |
| GET | `/api/v1/consultations/{id}` | 查询单次咨询详情 | CSLT-06 |
| POST | `/api/v1/profiles` | 创建/更新档案（upsert） | PROF-01 |
| GET | `/api/v1/profiles/me` | 查询当前 device_id 的档案 | PROF-01 |
| POST | `/api/v1/cases` | 提交案例（进入 pending_review） | CASE-01 |
| GET | `/api/v1/cases` | 案例列表（支持 status/behavior_type 筛选） | CASE-01 |
| GET | `/api/v1/cases/{id}` | 案例详情 | CASE-01 |
| POST | `/api/v1/cases/{id}/review` | 专家审核（approve/reject） | CASE-03 |

**总端点数：12 个**（标准设计中约 30+ 个）。

---

## 六、风险与规避措施

| 风险 | 概率 | 影响 | 规避措施 |
|:---|:---|:---|:---|
| **DeepSeek API 不稳定或成本超预期** | 中 | 咨询功能不可用或运营成本过高 | ①配置超时降级（已有 `RetrievalTimeoutError` 机制，需扩展至 LLM 层）② Prompt 压缩，减少 Token 消耗 ③ MVP 阶段限制单设备每日咨询次数（如 10 次/天，前端硬编码提示） |
| **前端 SSE 在微信小程序中不稳定** | 中 | 流式输出中断或无法续传 | ①实现前端自动重连（最多 3 次）②后端 SSE 端点支持 `Last-Event-Id` 续传（已有实现）③备选方案：若 SSE 实在不稳定，降级为普通 POST 返回完整文本（牺牲流式体验） |
| **案例库冷启动无内容，RAG 检索为空** | 高 | 首次用户体验极差 | ①Phase 3 强制导入 20-30 条种子案例 ② RAG 降级策略已有（`degradation_levels` 逐层放宽标签过滤），空库时返回预设安全提示模板 ③前端提示「案例库持续完善中」 |
| **Worker 索引失败导致案例不可用** | 中 | 审核通过的案例无法被检索 | ① Worker 重试 3 次机制 ②状态标记 `indexing_failed`，后台可监控 ③提供手动重试接口（MVP 后延，可先通过脚本手动重跑） |
| **匿名设备 ID 被清除导致数据丢失** | 低 | 用户卸载小程序后档案/历史丢失 | ①明确告知用户这是 MVP 限制 ②用户可导出历史记录（截图或复制文本）③后续迭代接入微信登录后通过 unionId 关联恢复 |
| **2 人团队并行时前后端接口不同步** | 中 | 联调阶段阻塞 | ① Phase 0 即约定统一错误响应格式和枚举值 ②使用 `py-schemas` 作为后端契约权威来源，前端 TypeScript 类型手工对齐 ③每日 15 分钟站会对齐接口变更 |

---

## 七、交付物清单

| # | 交付物 | 位置 | 说明 |
|:---|:---|:---|:---|
| 1 | 可启动的后端服务 | `apps/api-server/` | `uvicorn app.main:app` 可运行 |
| 2 | 可消费任务的 Worker | `apps/worker/` | 能完成案例切片+向量化+入库 |
| 3 | 可编译预览的 Taro 小程序 | `apps/mini-program/` | `pnpm dev:weapp` 成功 |
| 4 | 完整 Alembic 迁移脚本 | `packages/py-db/migrations/versions/` | 覆盖 MVP 全部表 |
| 5 | 种子数据脚本 | `scripts/seed.sh` | 20-30 条初始案例 |
| 6 | 核心路径集成测试 | `tests/integration/` | ≥3 个 pytest 用例通过 |
| 7 | 开发环境一键启动脚本 | `scripts/dev.sh` | 单命令启动全栈 |
| 8 | 更新后的 README | `README.md` | 含快速启动、功能说明、已知限制 |
| 9 | MVP 差距分析报告 | `docs/MVP差距分析报告.md` | 已存在，本计划完成后可归档对比 |
| 10 | MVP 落地计划 | `docs/MVP落地计划（裁剪版）.md` | 本文档 |

---

## 八、成功标准：什么算「MVP 跑通」

以下场景必须全部可复现：

1. **匿名咨询场景**：新用户打开小程序 → 输入行为描述（如「孩子在商场突然尖叫并用手击打头部」）→ 选择行为类型「自伤」→ 提交 → 3 秒内开始流式输出 → 看到四段式应急方案（含免责声明和来源案例引用）
2. **档案增强场景**：用户填写档案（年龄 5 岁、诊断 ASD、主要行为「刻板行为」）→ 再次咨询同样问题 → RAG 检索结果优先匹配「5 岁 + 刻板行为」相关案例
3. **历史回溯场景**：用户可在历史页面看到刚才的咨询记录，点击进入详情页查看完整方案
4. **案例入库场景**：专家提交一个完整案例 → 在列表中看到状态为「待审核」→ 执行审核通过 → 5 分钟后（Worker 处理完成）用案例中的关键词做咨询，RAG 能命中该案例
5. **开发环境可复现**：任意开发者在全新机器上 `git clone` → 按 README 执行 3 条命令 → 5 分钟内看到上述 1-4 场景可运行

---

*本计划基于「忽略认证层」的硬约束制定，牺牲了安全性和多角色管理，以换取核心功能的最快闭环。后续迭代应优先补回：①微信登录 ②RBAC 鉴权 ③工单兜底通道 ④案例 AI 预审 ⑤生产部署（HTTPS/SSL）。*
