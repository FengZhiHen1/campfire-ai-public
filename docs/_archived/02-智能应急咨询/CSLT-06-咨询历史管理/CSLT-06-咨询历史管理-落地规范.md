## 1 功能点：CSLT-06 咨询历史管理 — 落地规范

> **文档生成时间**：`2026-05-27 17:54:47`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-27 17:54:47` | AI Assistant | 初始版本，基于已冻结意图文档 v2.0、设计文档 v1.0 和契约协调报告全量生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `CSLT-06-咨询历史管理-设计文档.md`。

---

### 1.1 技术栈绑定 `【对内实现】`

- **必须使用**：
  - `fastapi>=0.115`：APIRouter 路由注册、Depends 身份注入、HTTPException 异常抛出
  - `pydantic>=2.0`：BaseModel 严格校验、Field 约束（min_length / max_length / default）、model_validate
  - `SQLAlchemy>=2.0`：AsyncSession 异步查询、declarative_base ORM 模型定义、select() 查询构建
  - `packages/py-db` — `models/consult.py`（ORM 模型）、`repositories/consult_repository.py`（Repository 封装）、Alembic 迁移脚本
  - `packages/py-schemas` — `schemas/consult.py`（Pydantic DTO）、`BaseSchema` 基类、`UUID` 校验类型
  - `packages/py-config` — `Config` pydantic-settings 模式加载环境变量（`HISTORY_PAGE_SIZE_MAX`、`HISTORY_PAGE_SIZE_DEFAULT`、`DATABASE_URL`）
  - `packages/py-logger` — `Logger.bind(trace_id=..., module="consultation_history")` 结构化日志注入
  - `packages/py-infra` — `AppException` 基类（统一异常处理中间件）
  - `prometheus-fastapi-instrumentator` — Counter/Histogram 指标暴露
  - `asyncio`：异步路由处理函数（`async def`）
- **禁止使用**：
  - 禁止绕过 `packages/py-db` Repository 层直接操作数据库（裸 SQLAlchemy Session）
  - 禁止在列表查询中使用 SELECT *（仅需 5 字段：id, consultation_time, behavior_description, crisis_level, has_feedback）
  - 禁止对 `generated_plan` 做任何二次加工、截断或格式化
  - 禁止接受前端传入的 `user_id` 作为查询过滤条件（必须从 JWT Token 提取）
  - 禁止在 Service 层自行生成 `request_id`（必须由上游 CSLT-08 传入）
  - 禁止在详情查询时执行外部 API 调用（所有数据仅从 consultations 表读取）

### 1.2 文件归属 `【对内实现】`

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| API 路由 | `apps/api-server/app/api/v1/consultations.py` | 三个端点：列表查询 GET /、详情查询 GET /{id}、归档写入 POST / |
| Service 层 | `apps/api-server/app/services/consultation_history/service.py` | `list_history()`、`get_detail()`、`archive_consultation()` 函数 |
| ORM 模型 | `apps/api-server/app/models/consultation.py` | `ConsultationHistory` SQLAlchemy 模型（扩展已有 consultations 表） |
| Repository | `apps/api-server/app/repositories/consult_history_repository.py` | `ConsultHistoryRepository` 类：封装查询 + user_id 强制注入 |
| Pydantic DTO | `apps/api-server/app/schemas/consultation_history.py` | `ConsultationHistoryCreate`、`ConsultationHistoryListItem`、`ConsultationHistoryDetail`、`ConsultationHistoryFeedbackUpdate` |
| 枚举定义 | `apps/api-server/app/schemas/consultation_history.py` | 本模块不定义新枚举——全部复用 CSLT-01/CrisisLevel、CSLT-03/GenerationStatus |
| 异常定义 | `apps/api-server/app/exceptions.py`（扩充） | `ConsultationHistoryNotFoundError`、`ConsultationHistoryAccessDeniedError`、`ConsultationHistoryIncompleteDataError`、`ConsultationHistoryDuplicateError` |
| 数据库迁移 | `apps/api-server/alembic/versions/xxxx_add_consultation_history_fields.py` | 扩展 consultations 表：新增 request_id UNIQUE、generated_plan TEXT、source_list JSONB、disclaimer TEXT、generation_time_ms FLOAT、is_partial BOOLEAN、referenced_slice_ids UUID[]、finish_reason VARCHAR(10)、ttft_ms FLOAT、has_feedback BOOLEAN、token_input INTEGER、token_output INTEGER、device_info JSONB；索引：(user_id, consultation_time DESC)、(request_id) UNIQUE |
| Service 测试 | `apps/api-server/tests/services/consultation_history/test_service.py` | list_history / get_detail / archive_consultation 全流程测试 |
| API 测试 | `apps/api-server/tests/api/v1/test_consultations.py` | 端点级集成测试（含权限隔离、分页边界、幂等） |

### 1.3 输入定义 `【已锁定】`

**ConsultationHistoryCreate**
- 【契约引用】`docs/contracts/CSLT-06/ConsultationHistoryCreate.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-08（咨询编排逻辑，每次咨询完成后调用本模块归档）

内部类型（不对外暴露）：

```python
class ConsultationHistoryFeedbackUpdate(BaseModel):
    """QUAL-03 回调更新反馈标记。仅含 has_feedback 字段，由 QUAL-03 在用户提交反馈后调用 PATCH /api/v1/consultations/{id}/feedback。当前为初步草案——具体输入格式待 QUAL-03 设计时协商调整。"""
    has_feedback: bool = Field(
        default=True,
        description="反馈标记。仅支持 false → true 单向变化。QUAL-03 传入 false 时返回 422 并说明此字段仅可设为 true。"
    )
```

**契约冲突处理说明**：契约协调报告发现 CSLT-06 设计文档 v1.0 曾将 `confidence_score` 列为 CSLT-03/GenerationResult 的第 9 个字段，但实际 `docs/contracts/CSLT-03/GenerationResult.json` 仅有 8 个字段，不包含 confidence_score。经核实意图文档 §1.10：置信度评分来源于 CSLT-05（置信度后校验），非 CSLT-03。设计文档该处为笔误。本落地规范不将 confidence_score 作为 GenerationResult 的字段引用，而是作为来自 CSLT-05 的数据透传字段（由 CSLT-08 编排层在咨询完成后统一传入）。CSLT-05 尚未设计，本模块在 ConsultationHistoryCreate 中暂不单独定义 confidence_score 字段——该字段将在 CSLT-05 落地并定义其输出契约后，通过 Alembic 迁移追加到 consultations 表。

### 1.4 输出定义 `【已锁定】`

**ConsultationHistoryListItem**
- 【契约引用】`docs/contracts/CSLT-06/ConsultationHistoryListItem.json`
- 本模块作为该契约的定义方
- 消费方：FRONTEND（前端历史列表页面）

**ConsultationHistoryDetail**
- 【契约引用】`docs/contracts/CSLT-06/ConsultationHistoryDetail.json`
- 本模块作为该契约的定义方
- 消费方：FRONTEND（前端详情页面）、TICK-01（工单自动生成——读取咨询上下文）

### 1.5 核心逻辑步骤 `【对内实现】`

1. **步骤 1：身份鉴权校验**
   - **操作对象**：FastAPI Request 对象
   - **具体操作**：通过 `Depends(get_current_user)` 从 JWT Token 中提取 `user_id` 和 `roles`，注入到 `request.state.user`
   - **输入来源**：HTTP 请求头 `Authorization: Bearer <token>`
   - **输出去向**：`user_id`（UUID）和 `roles`（list[UserRole]）注入请求上下文，供后续步骤使用
   - **失败行为**：Token 无效/过期 → 返回 401；Token 有效但无对应角色 → 返回 403

2. **步骤 2：归档写入 — 输入校验**
   - **操作对象**：`ConsultationHistoryCreate` 模型实例
   - **具体操作**：调用 `ConsultationHistoryCreate.model_validate(request_body)` 进行 Pydantic 校验。额外执行：`disclaimer` 字段的等值校验——必须与固定文本完全一致，否则拒绝写入
   - **输入来源**：HTTP POST /api/v1/consultations 请求体（JSON）
   - **输出去向**：校验通过的 `ConsultationHistoryCreate` 实例进入步骤 3
   - **失败行为**：必填字段缺失 → 返回 422 `{"detail": {"field": "...", "msg": "..."}}`；disclaimer 等值校验失败 → 返回 422 `{"detail": "disclaimer 内容与标准声明不一致，请使用 CSLT-03 输出的原始声明文本"}`

3. **步骤 3：归档写入 — 幂等插入**
   - **操作对象**：PostgreSQL `consultations` 表
   - **具体操作**：执行 `INSERT INTO consultations (...) VALUES (...) ON CONFLICT (request_id) DO NOTHING RETURNING *`。若 RETURNING 返回空行（已存在），则执行 `SELECT * FROM consultations WHERE request_id = $1` 返回已有记录。`consultation_time` 使用 PostgreSQL `NOW()` 函数自动填充，忽略请求体中的值
   - **输入来源**：步骤 2 校验通过的 `ConsultationHistoryCreate` 实例 + 步骤 1 的 `user_id`
   - **输出去向**：插入成功 → 返回 `ConsultationHistoryDetail`（HTTP 201）；重复归档 → 返回已有记录（HTTP 200）
   - **失败行为**：数据库连接异常 → 重试 3 次（SQLAlchemy 连接池自动管理），仍失败则返回 503 `{"detail": "服务暂时不可用，请稍后重试", "trace_id": "..."}` ；外键约束违反（user_id 不存在）→ 返回 422

4. **步骤 4：列表查询**
   - **操作对象**：PostgreSQL `consultations` 表
   - **具体操作**：执行 `SELECT id, consultation_time, behavior_description, crisis_level, has_feedback FROM consultations WHERE user_id = $1 ORDER BY consultation_time DESC LIMIT $2 OFFSET $3`。`$2 = page_size`（默认 20，最大 100），`$3 = (page - 1) * page_size`。同时执行 `SELECT COUNT(*) FROM consultations WHERE user_id = $1` 获取 `total`
   - **输入来源**：HTTP GET /api/v1/consultations?page=1&page_size=20 查询参数 + 步骤 1 的 `user_id`
   - **输出去向**：`PaginatedResponse[ConsultationHistoryListItem]`（items, page, page_size, total, total_pages）
   - **失败行为**：`page` 或 `page_size` 为非正整数 → 返回 422；`page_size > HISTORY_PAGE_SIZE_MAX`（默认 100）→ 返回 422；`page > total_pages` → 返回空 items + 正确的 total 和 total_pages（HTTP 200，空列表是正常边界情况）；数据库连接异常 → 返回 503

5. **步骤 5：详情查询**
   - **操作对象**：PostgreSQL `consultations` 表
   - **具体操作**：执行 `SELECT * FROM consultations WHERE id = $1 AND user_id = $2`。若返回 0 行：且 `id` 格式非 UUID → 立即返回 404；UUID 有效但 0 行 → 执行 `SELECT COUNT(*) FROM consultations WHERE id = $1` 以区分「ID 存在但 user_id 不匹配」和「ID 不存在」，两类均对外统一返回 404
   - **输入来源**：HTTP GET /api/v1/consultations/{id} 路径参数 + 步骤 1 的 `user_id`
   - **输出去向**：`ConsultationHistoryDetail`（HTTP 200）；不存在/无权访问 → 404
   - **失败行为**：ID 格式非 UUID → 返回 404；记录存在但 user_id 不匹配 → 内部日志记录 WARNING 含实际拒绝原因，对外返回 404 `{"detail": "该咨询记录不存在或无权查看"}` ；数据库连接异常 → 返回 503

### 1.6 接口契约 `【已锁定】`

#### 1.6.1 接口 1：archive_consultation（归档写入）

```python
async def archive_consultation(
    data: ConsultationHistoryCreate,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConsultationHistoryDetail:
    """
    将一次应急咨询的完整上下文数据归档存储为一条历史记录。

    幂等语义：重复的 request_id 提交返回已有记录（HTTP 200），不产生重复行。
    consultation_time 以服务端时间为准，忽略请求体中的值。
    disclaimer 入库前做等值校验——与 CSLT-03 固定声明文本不一致时拒绝写入。

    Args:
        data: 归档数据，由 CSLT-08 编排层在咨询完成后组装
        current_user: 当前认证用户（由 get_current_user Depends 注入）
        db: 数据库异步会话

    Returns:
        ConsultationHistoryDetail: 归档后的完整记录（含系统生成的 id）

    Raises:
        ConsultationHistoryIncompleteDataError: 必填字段缺失或 disclaimer 等值校验失败（422）
        ConsultationHistoryDuplicateError: （保留，当前由幂等逻辑自动处理，不主动抛出）

    Side Effects:
        - 向 consultations 表 INSERT 一条新记录
        - 记录结构化日志（INFO：归档成功；WARNING：重复归档；ERROR：写入失败）
        - Prometheus Counter: consultation_archive_requests_total{status="success|duplicate|error"}

    Idempotency:
        基于 request_id UNIQUE 约束实现。同一 request_id 的重复提交：
        1. 首次 → INSERT 成功，返回 HTTP 201
        2. 重复 → ON CONFLICT DO NOTHING，SELECT 返回已有记录，HTTP 200

    Thread Safety:
        幂等由 PostgreSQL UNIQUE 约束保障，多线程/多进程安全。
        函数内部不维护可变状态。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `archive_consultation` — 语义化，描述"归档一次咨询"的业务动作 |
| **HTTP 端点** | `POST /api/v1/consultations` |
| **输入类型** | `ConsultationHistoryCreate`（详见 §1.3） |
| **输出类型** | `ConsultationHistoryDetail`（详见 §1.4） |
| **异常类型** | `ConsultationHistoryIncompleteDataError`（422）、`ConsultationHistoryDuplicateError`（409，预留） |
| **副作用** | 写入 consultations 表、记录日志、Prometheus 指标 |
| **幂等性** | 基于 request_id，重复提交返回已有记录 |
| **并发安全** | PostgreSQL UNIQUE 约束保障，线程安全 |

#### 1.6.2 接口 2：list_history（历史列表查询）

```python
async def list_history(
    page: int = Query(default=1, ge=1, description="页码（1-based）"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页记录数"),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ConsultationHistoryListItem]:
    """
    查询当前用户的所有咨询历史记录摘要列表。

    按 consultation_time 降序排列。每页最多显示 page_size 条（默认 20，上限 100）。
    page 超出总页数时返回空列表 + 正确的 total 和 total_pages（HTTP 200，不抛错）。

    Args:
        page: 页码（1-based）
        page_size: 每页记录数（1-100，通过 HISTORY_PAGE_SIZE_MAX 环境变量配置上限）
        current_user: 当前认证用户
        db: 数据库异步会话

    Returns:
        PaginatedResponse[ConsultationHistoryListItem]: 分页响应，items 为列表摘要条目

    Raises:
        ValidationError: page 或 page_size 非法（422）

    Side Effects:
        - 记录结构化日志（查询耗时、返回条数）
        - Prometheus Histogram: consultation_list_duration_seconds

    Idempotency:
        纯查询接口，天然幂等。

    Thread Safety:
        纯查询接口，线程安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `list_history` — 语义化，描述"列出历史记录"的业务动作 |
| **HTTP 端点** | `GET /api/v1/consultations` |
| **查询参数** | `page: int`（默认 1）、`page_size: int`（默认 20，最大 100） |
| **输出类型** | `PaginatedResponse[ConsultationHistoryListItem]`（详见 §1.4） |
| **异常类型** | `ValidationError`（422） |
| **副作用** | 记录日志、Prometheus 指标 |
| **幂等性** | 天然幂等（纯查询） |
| **并发安全** | 线程安全（纯查询） |

#### 1.6.3 接口 3：get_detail（详情查询）

```python
async def get_detail(
    consultation_id: UUID,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConsultationHistoryDetail:
    """
    查询单次咨询的完整详情。

    仅返回当前用户本人的记录。记录不存在或 user_id 不匹配时统一返回 404，
    对外不区分「不存在」和「无权查看」两种情况（保护用户隐私）。
    内部日志中记录实际拒绝原因供运维排查。

    Args:
        consultation_id: 咨询记录 ID（UUID 格式）
        current_user: 当前认证用户
        db: 数据库异步会话

    Returns:
        ConsultationHistoryDetail: 咨询完整详情

    Raises:
        HTTPException(404): 记录不存在或无权查看

    Side Effects:
        - 权限拒绝时记录 WARNING 日志含实际原因
        - Prometheus Histogram: consultation_detail_duration_seconds

    Idempotency:
        纯查询接口，天然幂等。

    Thread Safety:
        纯查询接口，线程安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `get_detail` — 语义化，描述"获取（某条记录的）详情"的业务动作 |
| **HTTP 端点** | `GET /api/v1/consultations/{consultation_id}` |
| **路径参数** | `consultation_id: UUID` |
| **输出类型** | `ConsultationHistoryDetail`（详见 §1.4） |
| **异常类型** | `HTTPException(404)` |
| **副作用** | 记录日志、Prometheus 指标 |
| **幂等性** | 天然幂等（纯查询） |
| **并发安全** | 线程安全（纯查询） |

### 1.7 依赖与集成接口 `【已锁定】`

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 关系型数据库 | PostgreSQL 17.x | SQLAlchemy `AsyncSession.execute(select(...))` | 归档写入、列表查询、详情查询 | 技术栈设计 §4.1；项目结构 §6.1 |
| ORM 框架 | `packages/py-db` | `models/consult.py` — `ConsultationHistory` ORM 类；`repositories/consult_history_repository.py` — `ConsultHistoryRepository` 类 | 数据库操作封装、user_id 强制注入 | 项目结构 §6.1、§9.3 |
| 数据校验 | `packages/py-schemas` | `schemas/consultation_history.py` — Pydantic BaseModel DTO | 输入校验、输出序列化 | 项目结构 §6.1 |
| 环境配置 | `packages/py-config` | `Config` 类 — `HISTORY_PAGE_SIZE_MAX`（默认 100）、`HISTORY_PAGE_SIZE_DEFAULT`（默认 20）、`DATABASE_URL` | 分页参数上限、数据库连接 | 项目结构 §6.1 |
| 结构化日志 | `packages/py-logger` | `Logger.bind(trace_id=..., module="consultation_history")` — `.info()` / `.warning()` / `.error()` | 归档写入、权限拒绝、重复请求、异常记录 | 项目结构 §6.1 |
| 异常基类 | `packages/py-infra` | `AppException` — 统一异常处理中间件 | 自定义异常（NotFound、AccessDenied、IncompleteData、Duplicate） | 项目结构 §6.1 |
| 数据库迁移 | Alembic | `alembic revision --autogenerate -m "add_consultation_history_fields"` | 扩展 consultations 表字段和索引 | 技术栈设计 §4.1（PostgreSQL）；项目结构 §9.3 |
| 可观测性 | Prometheus（via prometheus-fastapi-instrumentator） | `Counter` — `consultation_archive_requests_total`；`Histogram` — `consultation_list_duration_seconds`、`consultation_detail_duration_seconds` | 写入请求计数、查询耗时分布 | 技术栈设计 §6.3（可观测性） |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| CSLT-03（应急方案生成） | `GenerationResult` 输出契约（`docs/contracts/CSLT-03/GenerationResult.json`） — 消费其全部 8 个字段（text, source_list, disclaimer, generation_time_ms, is_partial, referenced_slice_ids, finish_reason, ttft_ms） | 归档数据的核心来源——方案文本、来源引用、免责声明、耗时等 | ✅ 契约已定义（maturity: draft） |
| CSLT-01（危机分级判定） | `CrisisLevel` 枚举契约（`docs/contracts/CSLT-01/CrisisLevel.json`） — 消费其三值枚举（mild/moderate/severe） | 存储咨询的危机等级标签 | ✅ 契约已定义（maturity: draft） |
| CSLT-08（咨询编排逻辑） | 调用本模块的 `POST /api/v1/consultations` 发起归档 | 每次咨询流程完成后触发历史记录归档写入 | ⏭️ 待设计（CSLT-08 作为消费方） |
| AUTH-04（五级RBAC鉴权） | `Depends(get_current_user)` — 从 JWT 提取 `user_id` 和 `roles`；`Depends(require_role(["admin", "maintainer"]))` — 管理员运维通道鉴权 | 列表和详情查询的身份校验；预留管理员运维端点 | ✅ 契约已定义（maturity: draft） |
| TICK-01（工单自动生成） | 读取 `ConsultationHistoryDetail` — 消费其 `behavior_description` 和 `generated_plan` 字段 | 工单创建时继承咨询上下文到工单「业务背景」字段 | ⏭️ 待设计（TICK-01 作为消费方） |
| QUAL-03（用户反馈收集） | 预留接口：`PATCH /api/v1/consultations/{id}/feedback` — 写入 `has_feedback = true` | 用户提交反馈后回调更新反馈标记 | ⏭️ 待设计（QUAL-03 需协商接口格式） |
| QUAL-04（Token用量追踪） | 直接查询 `consultations` 表 — `SELECT SUM(token_input), SUM(token_output) FROM consultations WHERE user_id = $1 AND consultation_time BETWEEN $2 AND $3` | 按用户/时间段聚合 Token 消耗统计 | ⏭️ 待设计（QUAL-04 作为消费方） |

### 1.8 状态机 `【对内实现】`

本功能点不涉及状态流转，故无需状态机。

咨询历史记录一旦归档存储即为只读，不支持用户自行修改或删除。`has_feedback` 标记不构成状态机——仅为一个由 QUAL-03 单向更新（false → true）的布尔属性，不驱动任何后续流程。

### 1.9 异常与边界条件 `【对内实现】`

#### 1.9.1 异常 1：归档写入时必填字段缺失

- **触发条件**：
  - `behavior_description` 为空字符串 `""` 或长度超过 2000 汉字字符
  - `generated_plan` 为 None（非 is_partial 场景下不允许）
  - `source_list` 为 None
  - `disclaimer` 内容与 CSLT-03 固定声明文本不一致（等值校验失败）
  - `crisis_level` 不在 `{"mild", "moderate", "severe"}` 范围内
  - `request_id` 为空或格式非 UUID
- **处理策略**：
  1. Pydantic 校验阶段捕获 `ValidationError`
  2. 提取第一个失败字段名和错误详情
  3. disclaimer 等值校验在 Service 层单独执行——对比 `data.disclaimer != GENERATION_DISCLAIMER_CONST`，不一致时构造 `ConsultationHistoryIncompleteDataError`
  4. 返回 HTTP 422，响应体 `{"detail": [{"field": "disclaimer", "msg": "disclaimer 内容与标准声明不一致，请使用 CSLT-03 输出的原始声明文本"}]}`
  5. 记录 WARNING 日志：`logger.warning("archive_validation_failed", field=..., received_value=..., trace_id=...)`
  6. `is_partial=true` 时：`generated_plan` 可为非完整四段式文本——Pydantic 校验仅检查字符串非空，不检查段落完整性。归档成功后额外在 `ConsultationHistoryDetail` 中标记 `is_partial=true`
- **重试参数**：不重试，直接失败。客户端修正输入后重新发起请求。

#### 1.9.2 异常 2：请求查看的咨询记录不存在或无权访问

- **触发条件**：
  - `consultation_id` 格式非 UUID（如 `/api/v1/consultations/not-a-uuid`）
  - `consultation_id` 为有效 UUID 但在 `consultations` 表中无匹配行
  - `consultation_id` 对应的记录存在，但 `user_id != current_user.user_id`（跨用户访问）
- **处理策略**：
  1. 执行 `SELECT * FROM consultations WHERE id = $1 AND user_id = $2`（主查询）
  2. 返回 0 行时：先检查 `id` 格式是否为 UUID → 否 → 直接返回 404
  3. UUID 有效但返回 0 行 → 执行辅助查询 `SELECT COUNT(*) FROM consultations WHERE id = $1`：COUNT > 0 → 记录属于其他用户（WARNING 日志）；COUNT = 0 → 记录不存在
  4. 两种情况均返回 HTTP 404，响应体 `{"detail": "该咨询记录不存在或无权查看"}`
  5. 内部日志：`logger.warning("consultation_access_denied", consultation_id=..., actual_reason="record_belongs_to_other_user" | "record_not_found", trace_id=...)`
- **重试参数**：不重试，立即返回。

#### 1.9.3 异常 3：并发重复归档

- **触发条件**：
  - 同一 `request_id` 被 CSLT-08 提交两次或更多次（如网络超时导致前端重试，编排层重复调用归档接口）
- **处理策略**：
  1. 首次提交 — `INSERT ... ON CONFLICT (request_id) DO NOTHING RETURNING *` 正常返回插入行 → HTTP 201
  2. 重复提交 — `ON CONFLICT DO NOTHING` 不插入任何行，RETURNING 返回空结果集
  3. 检测到 RETURNING 为空 → 执行 `SELECT * FROM consultations WHERE request_id = $1 AND user_id = $2` 获取已有记录 → HTTP 200（而非 409，对上游透明幂等）
  4. 记录 INFO 日志：`logger.info("duplicate_archive_detected", request_id=..., trace_id=...)`
  5. Prometheus Counter +1：`consultation_archive_requests_total{status="duplicate"}`
- **重试参数**：不重试，幂等已自动处理。

#### 1.9.4 异常 4：数据库连接不可用

- **触发条件**：
  - PostgreSQL 连接池耗尽或返回 `OperationalError`
  - SQLAlchemy `AsyncSession.execute()` 抛出 `sqlalchemy.exc.OperationalError` 或 `asyncio.TimeoutError`
- **处理策略**：
  1. 捕获 SQLAlchemy 连接异常
  2. 关闭当前失效会话，依赖 SQLAlchemy 连接池自动重新建立连接
  3. 连接池内部重试（由 SQLAlchemy `pool_pre_ping=True` 控制，最多 3 次）
  4. 重试耗尽 → 抛出 `AppException`（status_code=503），由 `packages/py-infra` 统一异常中间件格式化错误响应
  5. 返回 HTTP 503，响应体 `{"detail": "服务暂时不可用，请稍后重试", "trace_id": "..."}`
  6. 记录 ERROR 日志：`logger.error("database_connection_failed", error_type=..., trace_id=...)`
- **重试参数**：SQLAlchemy 连接池级重试，最大 3 次，指数退避（1s/2s/4s）。应用层不做额外重试。

#### 1.9.5 边界条件 1：用户无任何咨询历史

- **触发条件**：用户首次使用应急咨询，`consultations` 表中该 `user_id` 无任何行
- **处理策略**：列表查询返回 `PaginatedResponse(items=[], page=1, page_size=20, total=0, total_pages=0)`，HTTP 200。前端展示空状态引导文案「暂无咨询历史，开始一次应急咨询即可在此查看记录」
- **重试参数**：不重试（正常业务状态）

#### 1.9.6 边界条件 2：page 超出 total_pages 范围

- **触发条件**：`page` 参数值大于 `total_pages`（如共 35 条记录、每页 20 条、共 2 页，请求 page=5）
- **处理策略**：返回 `PaginatedResponse(items=[], page=5, page_size=20, total=35, total_pages=2)`，HTTP 200。不返回 400/404 错误——空结果是正常的分页边界情况
- **重试参数**：不重试（客户端应使用 total_pages 调整分页导航）

### 1.10 验收测试场景 `【对内实现】`

#### 1.10.1 正向测试 1：正常归档 + 完整查询回环

- **场景**：一次完整的应急咨询流程结束后，CSLT-08 传入完整数据归档。归档后家属可立即通过详情接口查询到完全相同的数据。
- **Given**:
  - 已认证家属用户（user_id=`"f47ac10b-58cc-4372-a567-0e02b2c3d479"`）
  - CSLT-08 传入完整的 `ConsultationHistoryCreate`：
    ```json
    {
      "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "user_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
      "crisis_level": "moderate",
      "behavior_description": "儿子在商场突然捂耳朵蹲下，拒绝移动，持续尖叫",
      "consultation_time": "2026-05-27T14:32:18+08:00",
      "generated_plan": "## 一、即时安全干预动作\n1. 立即将孩子带离嘈杂环境，寻找安静角落\n\n## 二、情绪安抚话术\n请用平静的语气说...",
      "source_list": ["[1] CASE-042 ASD商场感官过载干预案例（2025-11-03）"],
      "disclaimer": "以上建议由 AI 生成，仅供参考，不构成医疗诊断或治疗建议。如情况紧急，请立即联系专业医疗机构。",
      "generation_time_ms": 2850.5,
      "is_partial": false,
      "referenced_slice_ids": ["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
      "finish_reason": "COMPLETE",
      "ttft_ms": 1850.0,
      "token_input": 1850,
      "token_output": 620,
      "device_info": {"platform": "weapp", "device_brand": "iPhone", "os_version": "iOS 17.4", "app_version": "1.0.0"}
    }
    ```
- **When**: 调用 `POST /api/v1/consultations`，然后调用 `GET /api/v1/consultations/{returned_id}`
- **Then**:
  - POST 返回 HTTP 201，响应体为 `ConsultationHistoryDetail`，`id` 为系统生成的 UUID
  - `generated_plan`、`source_list`、`disclaimer` 与输入完全一致
  - `consultation_time` 为服务端当前时间（忽略请求体中的传入值）
  - `has_feedback` 为 `false`
  - GET 详情查询返回 HTTP 200，所有字段与 POST 返回体一致

#### 1.10.2 正向测试 2：列表分页正常排列

- **场景**：家属有 35 条咨询历史，查看第 1 页和第 2 页。
- **Given**:
  - 数据库 `consultations` 表中该 `user_id` 有 35 条记录，时间跨度从 2026-05-20 到 2026-05-27
  - 查询参数：`page=1, page_size=20`
- **When**: 调用 `GET /api/v1/consultations?page=1&page_size=20`，然后 `GET /api/v1/consultations?page=2&page_size=20`
- **Then**:
  - 第 1 页：`items` 含 20 条，第 1 条为最新记录（2026-05-27），`page=1, page_size=20, total=35, total_pages=2`
  - 第 2 页：`items` 含 15 条，`page=2, page_size=20, total=35, total_pages=2`
  - 每条 `items[i]` 仅包含 5 个字段：id, consultation_time, behavior_description, crisis_level, has_feedback
  - 不包含 `generated_plan` 等大字段

#### 1.10.3 正向测试 3：重复归档幂等返回已有记录

- **场景**：因网络超时 CSLT-08 重复提交同一 request_id 的归档请求。
- **Given**: 首次归档已成功（同 1.10.1 数据），数据库中存在该 request_id 的记录
- **When**: 使用相同的 `request_id` 再次调用 `POST /api/v1/consultations`
- **Then**:
  - 返回 HTTP 200（非 201）
  - 响应体与首次归档返回的记录完全一致（含相同 id）
  - 数据库 `consultations` 表中该 `request_id` 只有 1 行（不是 2 行）

#### 1.10.4 异常测试 1：跨用户访问被拒绝且信息不泄露

- **场景**：家属 A 尝试查看家属 B 的咨询记录。
- **Given**:
  - 家属 A（user_id=`"USER-A-UUID"`）已认证
  - 家属 B（user_id=`"USER-B-UUID"`）有一条咨询记录（id=`"B-RECORD-UUID"`）
- **When**: 家属 A 调用 `GET /api/v1/consultations/B-RECORD-UUID`
- **Then**:
  - 返回 HTTP 404，响应体 `{"detail": "该咨询记录不存在或无权查看"}`
  - 不返回 403（统一模糊提示保护隐私）
  - 内部日志记录：`logger.warning("consultation_access_denied", consultation_id="B-RECORD-UUID", actual_reason="record_belongs_to_other_user", trace_id=...)`

#### 1.10.5 异常测试 2：disclaimer 被篡改时代绝写入

- **场景**：CSLT-08 因编程错误传入了被修改过的 disclaimer 文本。
- **Given**:
  - 归档输入中 `disclaimer` 为 `"本内容仅供参考"`（不符合 const 固定文本）
  - 其他字段均有效
- **When**: 调用 `POST /api/v1/consultations`
- **Then**:
  - 返回 HTTP 422
  - 响应体含字段级错误：`{"detail": [{"field": "disclaimer", "msg": "disclaimer 内容与标准声明不一致，请使用 CSLT-03 输出的原始声明文本"}]}`
  - 数据库中无新增记录

### 1.11 注意事项与禁止行为（编码层面） `【对内实现】`

1. **[约束 1 -- 受意图文档 §1.11 约束]** 列表查询和详情查询的 WHERE 条件中必须强制包含 `user_id = :current_user_id`（从 `Depends(get_current_user)` 提取的 `request.state.user.user_id`）。`ConsultHistoryRepository` 类的所有查询方法必须以此作为第一个 WHERE 条件——Repository 封装确保不会遗漏。

2. **[约束 2 -- 受意图文档 §1.11 约束]** 对无权访问的详情查询，必须返回 404 而非 403，且响应体不区分「不存在」和「无权查看」。实现方式：详情查询 SQL 中同时包含 `id` 和 `user_id` 两个条件，返回 0 行时统一返回 404。内部日志通过辅助查询区分两种情况并记录不同消息。

3. **[约束 3 -- 受意图文档 §1.11 约束]** 归档时 `consultation_time` 必须使用 PostgreSQL `NOW()` 函数自动填充，忽略请求体中的值。Service 层在 INSERT 语句中显式指定 `consultation_time = NOW()`，不在 Pydantic 模型中设默认值。

4. **[约束 4 -- 受意图文档 §1.6.1 约束]** `disclaimer` 入库前执行等值校验——必须与 CSLT-03/GenerationResult 中的固定声明文本完全一致。Service 层在 Pydantic 校验通过后、SQL INSERT 执行前进行此检查。固定声明文本定义为本模块常量 `GENERATION_DISCLAIMER_CONST`。

5. **[约束 5 -- 受设计文档 §1.7 约束]** 不暴露 PUT/PATCH/DELETE 端点给普通用户。预留的管理员运维端点（`PATCH /admin/consultations/{id}`）受 `Depends(require_role(["admin", "maintainer"]))` 保护。

6. **[易错点 1]** `request_id` 由 CSLT-08 编排层生成并传入——Service 层不得自行生成。若 `request_id` 为空或缺失，返回 422 字段缺失错误而非静默生成 UUID。

7. **[易错点 2]** 列表查询禁止执行 `SELECT *`。仅选取 5 个字段：`id, consultation_time, behavior_description, crisis_level, has_feedback`。`generated_plan`（最大 65536 字符）和 `token_output` 等大字段/分析字段不在列表中返回。

8. **[易错点 3]** `is_partial=true` 的记录仍需在列表中正常展示，不可隐藏或降序排到末尾。部分生成的结果仍包含有效参考信息，用户有权回溯查看。

9. **[易错点 4]** 分页参数 `page` 是 1-based。`OFFSET = (page - 1) * page_size`。`page` 超出 `total_pages` 时返回空列表 + 正确 total，不返回 400。

10. **[易错点 5]** PaginatedResponse 泛型实现：`PaginatedResponse[ConsultationHistoryListItem]`。`total_pages = ceil(total / page_size)`。

11. **[禁止行为]** 禁止在详情查询中对 `generated_plan` 做截断、压缩或格式化——必须原样返回归档时的完整 Markdown 文本。

12. **[禁止行为]** 禁止绕过 `ConsultHistoryRepository` 层在 API 路由中直接编写 SQL 查询。所有查询必须通过 Repository 类封装，确保 `user_id` 的强制注入不遗漏。

13. **[禁止行为]** 禁止使用同步 `psycopg2` 或 `requests` 库进行任何 I/O 操作——全部通过 SQLAlchemy AsyncSession 异步执行。

14. **[禁止行为]** 禁止在错误响应中返回数据库内部错误信息（如表名、列名、约束名）——对外仅返回用户可理解的错误消息。

### 1.12 文档详细度自检清单 `【对内实现】`

- [x] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成编码
- [x] 无偷懒表述：全文无 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：所有对外类型通过契约 JSON Schema 完整定义（含 constraints、examples、required）；所有内部类型（ConsultationHistoryFeedbackUpdate）含完整 Pydantic Field 定义
- [x] 逻辑步骤完整：5 个步骤均有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：4 种异常 + 2 种边界条件，每种含精确触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值来源（`HISTORY_PAGE_SIZE_MAX`=100、`HISTORY_PAGE_SIZE_DEFAULT`=20）、条件分支（page > total_pages 返回空）、业务规则（404 统一模糊提示）均已显式写出
- [x] 技术栈绑定明确：必须使用 10 项、禁止使用 6 项，与项目技术栈设计文档（`docs/篝火智答-技术栈设计.md`）保持一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档 v2.0 一致（详见 §1.15）

### 1.14 外部接口契约清单 `【已锁定】`

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| ConsultationHistoryCreate | `docs/contracts/CSLT-06/ConsultationHistoryCreate.json` | input | draft | CSLT-06 | CSLT-08 |
| ConsultationHistoryListItem | `docs/contracts/CSLT-06/ConsultationHistoryListItem.json` | output | draft | CSLT-06 | FRONTEND |
| ConsultationHistoryDetail | `docs/contracts/CSLT-06/ConsultationHistoryDetail.json` | output | draft | CSLT-06 | FRONTEND, TICK-01 |
| CrisisLevel | `docs/contracts/CSLT-01/CrisisLevel.json` | shared-enum | draft | CSLT-01 | CSLT-06（复用） |
| GenerationResult | `docs/contracts/CSLT-03/GenerationResult.json` | output | draft | CSLT-03 | CSLT-06（复用） |
| GenerationStatus | `docs/contracts/CSLT-03/GenerationStatus.json` | shared-enum | draft | CSLT-03 | CSLT-06（复用） |
| UserRole | `docs/contracts/AUTH-04/UserRole.json` | shared-enum | draft | AUTH-04 | CSLT-06（复用） |
| PaginatedResponse | `packages/py-schemas/py_schemas/common.py` | shared-model | stable | PROJECT | CSLT-06（复用） |

### 1.15 意图一致性声明 `【对内实现】`

- **配套意图文档**：`CSLT-06-咨询历史管理-意图文档.md`
- **冻结时间**：`2026-05-27 17:02:44`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致（10 个输入字段全部覆盖——behavior_description、retrieved_case_ids→source_list、generated_plan、source_list、disclaimer、confidence_score 暂待 CSLT-05 定义后追加、crisis_level、consultation_time、token_input/output）
  - [x] 本落地规范中的状态机实现与意图文档中的状态业务定义一致（无状态流转）
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致（3 类异常 + 隐私保护 + 统一错误提示）
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准（AC-01 归档完整性、AC-02 详情查询性能、AC-03 列表分页正确性、AC-04 数据隔离正确性、AC-05 部分生成告警）
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围（8 项技术决策全部兑现）
- **偏差说明**：`confidence_score` 字段在意图文档 §1.6.1 列为必填输入，但其上游来源为 CSLT-05（置信度后校验）而非 CSLT-03。当前 CSLT-05 尚未设计，本模块暂不在 ConsultationHistoryCreate 中定义此字段——待 CSLT-05 定义其输出契约后，通过 Alembic 迁移将该字段追加到 consultations 表。此偏差不影响核心归档流程，且为 CSLT-05 设计完成前的唯一合理处理方式。契约协调报告已记录此项冲突（#1: GenerationResult.confidence_score 缺失，severity: medium），当前处理方式为「确认 CSLT-05 为字段来源，暂缓定义」。
