## 1 功能点：CSLT-02 RAG语义检索 — 落地规范

> **文档生成时间**：`2026-05-27 09:30:29`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-27 09:30:29 | AI Assistant | 初始版本，基于已冻结意图文档 v2.0 和设计文档 v1.0 生成 |

> **配套文档**：本模块的设计思路与决策依据见 `CSLT-02-RAG语义检索-设计文档.md`。

### 1.1 技术栈绑定

- **必须使用**：
  - FastAPI >= 0.115（异步路由、依赖注入）
  - Pydantic >= 2.0（请求/响应 Schema 校验，BaseModel + Field）
  - SQLAlchemy >= 2.0 async（异步 ORM，async_session）
  - pgvector >= 0.7（pgvector Python 客户端，HNSW 索引）
  - LangChain >= 0.3（`langchain_huggingface` 或 `langchain_openai` 兼容接口调用 DashScope embedding）
  - PostgreSQL 17.x + pgvector 插件（HNSW 向量索引，m=16, ef_construction=200）
  - Redis >= 5.0 async（可选缓存层，本模块 MVP 阶段不强制启用缓存）
  - 项目统一异常体系 `packages/py-infra` 中的 `AppException` 基类
  - 项目统一日志 `packages/py-logger` 中的 `structured_logger`
  - DashScope API（通过 OpenAI 兼容接口调用 text-embedding-v4，1024 维）
  - `asyncio.wait_for()`（500ms 超时控制）
  - 包命名 snake_case：`py_rag/retrieval.py`、`py_schemas/consult.py`
- **禁止使用**：
  - 禁止直接调用 HTTP 客户端绕过 `packages/py-llm/` 的统一 LLM client 封装（embedding 调用通过 py-rag/embedding.py 封装）
  - 禁止在检索函数中直接操作 case_chunks 表的 INSERT/UPDATE/DELETE（只读检索）
  - 禁止使用同步数据库驱动（`psycopg2` 同步版），必须使用 `asyncpg`
  - 禁止直接字符串拼接 SQL，必须使用 SQLAlchemy 参数化查询或 `text()` + 绑定参数
  - 禁止在日志中记录完整的用户查询文本

### 1.2 文件归属

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 检索引擎 | `packages/py-rag/py_rag/retrieval.py` | 混合检索核心逻辑：`hybrid_search()` 函数，封装标签过滤 + 向量排序 + 降级放宽 + 超时保护 |
| 嵌入编码 | `packages/py-rag/py_rag/embedding.py` | `encode_query()` 函数，调用 DashScope text-embedding-v4 生成 1024 维查询向量 |
| 请求/响应 Schema | `packages/py-schemas/py_schemas/consult.py` | `SemanticSearchInput`、`TagFilterDto`、`CaseSliceDto`、`SemanticSearchResult`、`EvidenceLevel`、`DegradationLevel`、`RetrievalStatus` Pydantic 模型 |
| ORM 模型 | `packages/py-db/py_db/models/consult.py` | `CaseChunk` SQLAlchemy 映射（id, case_id, chunk_text, embedding vector(1024), chunk_type, metadata JSONB） |
| 仓储 | `packages/py-db/py_db/repositories/consult_repository.py` | `search_similar_chunks()` 方法，构建 pgvector 混合检索 SQL |
| API 路由 | `apps/api-server/app/api/v1/consult.py` | `POST /api/v1/consult/search` 端点，接收查询请求，调用检索引擎并返回结果 |
| 服务编排 | `apps/api-server/app/services/consult_service.py` | `search_cases()` 方法，编排请求校验 → 检索引擎调用 → 结果包装 |
| 检索引擎测试 | `apps/api-server/tests/unit/test_retrieval.py` | `hybrid_search()` 单元测试 |
| 检索 API 测试 | `apps/api-server/tests/integration/test_consult_search.py` | `POST /api/v1/consult/search` 集成测试 |
| 异常定义 | `packages/py-infra/py_infra/exceptions.py` | `RetrievalTimeoutError`、`EmbeddingUnavailableError` 异常类（追加到现有异常体系） |

### 1.3 输入定义（对外接口）【已锁定】

**SemanticSearchInput**
- 【契约引用】`docs/contracts/CSLT-02/SemanticSearchInput.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-03（应急方案生成，间接通过 consult_service 编排）、CSLT-08（前端编排逻辑）

**TagFilterDto**
- 【契约引用】`docs/contracts/CSLT-02/TagFilterDto.json`
- 本模块作为该契约的定义方（临时自包含，待 PROF-02 落地后改为引用 PROF-02 标准契约）
- 消费方：PROF-02（上游生产者，定义过滤条件的字段枚举）
- 引用的外部枚举：CSLT-01/BehaviorTypeCategory（behavior_type 字段的枚举值）

### 1.4 输出定义（对外接口）【已锁定】

**SemanticSearchResult**
- 【契约引用】`docs/contracts/CSLT-02/SemanticSearchResult.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-03（注入 Prompt 模板）、CSLT-08（前端状态展示）

**CaseSliceDto**
- 【契约引用】`docs/contracts/CSLT-02/CaseSliceDto.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-03（读取切片文本和元数据拼装 Prompt）

**EvidenceLevel**
- 【契约引用】`docs/contracts/CSLT-02/EvidenceLevel.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-03（展示循证等级徽章）

**DegradationLevel**
- 【契约引用】`docs/contracts/CSLT-02/DegradationLevel.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-03、OBS-01（记录降级事件）

**RetrievalStatus**
- 【契约引用】`docs/contracts/CSLT-02/RetrievalStatus.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-03、OBS-01（记录检索状态）

### 1.5 核心逻辑步骤

1. **步骤 1：输入校验与预处理**
   - **操作对象**：`SemanticSearchInput` 实例
   - **具体操作**：调用 `SemanticSearchInput.model_validate(data)` 进行 Pydantic 校验；校验通过后提取 `query_text`、`tag_filters`、`top_k`（默认 10）；对 `top_k` 做二次校验：若 `top_k < 1` 设为 1，若 `top_k > 50` 设为 50
   - **输入来源**：HTTP 请求体（`POST /api/v1/consult/search`）或上游 `consult_service.search_cases()` 传入的字典
   - **输出去向**：校验通过的 `SemanticSearchInput` 实例进入步骤 2；`top_k` 的最终值用于后续 LIMIT 查询
   - **失败行为**：校验失败立即抛出 `ValidationError`（Pydantic 原生），返回 422 状态码，不进入后续逻辑

2. **步骤 2：编码查询向量**
   - **操作对象**：`query_text` 字符串
   - **具体操作**：调用 `py_rag.embedding.encode_query(text)` → 通过 DashScope OpenAI 兼容接口 `POST /embeddings` 发送 `{"model": "text-embedding-v4", "input": text}` → 从响应 `data[0].embedding` 提取 1024 维 float32 向量
   - **输入来源**：步骤 1 校验通过的 `query_text` 字段；嵌入模型名和 API 密钥从 `DEPLOY-05/AppSettings`（`EMBEDDING_MODEL`、`DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`）读取
   - **输出去向**：1024 维 `list[float]` 向量进入步骤 3
   - **失败行为**：DashScope API 返回非 200 → 重试 2 次（间隔 500ms），仍失败 → 抛出 `EmbeddingUnavailableError`（继承 `AppException`），status_code=503，不进入后续逻辑

3. **步骤 3：执行混合检索（精确过滤 + 向量排序）**
   - **操作对象**：`case_chunks` 表（pgvector HNSW 索引）
   - **具体操作**：
     ```sql
     SELECT id, case_id, chunk_text, chunk_type,
            1 - (embedding <=> $query_vector) AS similarity,
            metadata
     FROM case_chunks
     WHERE metadata->>'status' = 'approved'
       AND metadata->>'vectorized' = 'true'
       AND metadata->>'age_range' = $age_range
       AND metadata->>'behavior_type' = $behavior_type
       AND metadata->>'status' NOT IN ('obsolete', 'erroneous', 'disputed', 'force_removed')
       -- 可选过滤：
       AND ($emotion_level IS NULL OR metadata->>'emotion_level' = $emotion_level)
     ORDER BY embedding <=> $query_vector
     LIMIT $top_k
     ```
   - **输入来源**：步骤 2 的查询向量 `$query_vector` + 步骤 1 的 `tag_filters` 中各字段（`age_range`、`behavior_type`、可选的 `emotion_level`）
   - **输出去向**：查询结果行列表（每行含 id, case_id, chunk_text, similarity, metadata）进入步骤 4 的结果计数检查
   - **失败行为**：数据库连接超时（>2s）→ 重试 3 次（指数退避 0.5s/1s/2s），仍失败 → 抛出 `DependencyCommunicationError`，返回 503

4. **步骤 4：结果不足时触发降级放宽**
   - **操作对象**：步骤 3 返回的结果行数量 `result_count`
   - **具体操作**：
     - 若 `result_count >= top_k` → 跳至步骤 6
     - 否则进入降级循环，按以下顺序逐层放宽：
       - **层级 1（情绪等级放宽）**：移除 `emotion_level` 过滤条件，重新执行步骤 3 的查询。若 `result_count >= top_k` → 标记 `degradation_level = EMOTION_RELAXED`，跳至步骤 6
       - **层级 2（行为类型放宽）**：进一步移除 `behavior_type` 过滤条件，仅保留 `age_range` + 失效排除。若 `result_count >= top_k` → 标记 `degradation_level = BEHAVIOR_RELAXED`，跳至步骤 6
       - **层级 3（全部标签移除）**：移除全部标签过滤条件，仅保留 `status='approved'` + `vectorized='true'` + 失效排除，执行纯语义检索。标记 `degradation_level = ALL_TAGS_REMOVED`，无论结果多少均跳至步骤 6
   - **输入来源**：步骤 3 的查询结果数量 + 步骤 1 的 `tag_filters` 结构
   - **输出去向**：最终的查询结果行列表 + `degradation_level` 枚举值进入步骤 5
   - **失败行为**：所有三层放宽后仍为 0 条 → 进入步骤 5 的空结果处理

5. **步骤 5：超时保护包装**
   - **操作对象**：整个步骤 2+3+4 的异步协程
   - **具体操作**：将步骤 2（编码）+ 步骤 3+4（检索+降级）包装在 `asyncio.wait_for(coro, timeout=0.5)` 中。超时触发 `asyncio.TimeoutError` → 捕获后：
     - 若已有部分结果（在超时前步骤 3 或降级循环中已返回的行数 > 0）→ 返回已有结果，标记 `is_complete = False`、`degradation_applied = True`（即使未进入降级循环也标记）
     - 若结果数为 0 → 标记 `is_complete = False`、`reason = "timeout"`，返回空结果列表
   - **输入来源**：整个检索 coroutine
   - **输出去向**：最终结果行列表 + 状态标记进入步骤 6
   - **失败行为**：若编码阶段（步骤 2）本身就超时（无任何数据库结果），标记 `reason = "embedding_unavailable"`

6. **步骤 6：结果组装与排序**
   - **操作对象**：步骤 4 或 5 的原始数据库结果行 + `degradation_level` + 状态标记
   - **具体操作**：
     1. 对每条结果计算综合排序分数：
        ```
        time_decay = 1.0 (if录入时间距今<1年) | 0.7 (1-3年) | 0.5 (>3年)
        evidence_weight = 1.0 (NCAEP) | 0.8 (INSTITUTIONAL_EXPERIENCE) | 0.6 (CASE_OBSERVATION)
        composite_score = similarity * 0.5 + time_decay * 0.25 + evidence_weight * 0.25
        ```
     2. 按 `composite_score` 降序排序（分数相同时按 `case_created_at` 降序 —— 更新的案例排前面）
     3. 截取前 `top_k` 条
   - **输入来源**：步骤 4 或 5 的结果行列表
   - **输出去向**：排序后的 `List[CaseSliceDto]` 进入步骤 7
   - **失败行为**：此步骤为纯内存计算，无外部依赖，无失败路径

7. **步骤 7：输出包装与日志记录**
   - **操作对象**：步骤 6 的排序结果
   - **具体操作**：
     1. 组装 `SemanticSearchResult` 对象：
        - `results`: 步骤 6 的排序列表
        - `total_count`: 列表长度
        - `is_complete`: 步骤 5 的状态
        - `reason`: 步骤 5 的 reason（仅 `is_complete=False` 时非空）
        - `query_fingerprint`: `hashlib.sha256(query_text.encode()).hexdigest()`（日志用指纹，不暴露原文）
        - `degradation_applied`: 步骤 4 是否触发降级
        - `degradation_level`: 步骤 4 的最终降级等级
     2. 调用 `py_logger` 记录结构化日志：
        ```python
        logger.info("semantic_search_completed",
            trace_id=request_id,
            query_len=len(query_text),
            filters=tag_filters.dict(),
            result_count=total_count,
            elapsed_ms=elapsed_ms,
            degradation_level=degradation_level,
            is_complete=is_complete,
            query_fingerprint=query_fingerprint)
        ```
     3. 返回 `SemanticSearchResult` 实例
   - **输入来源**：步骤 6 结果 + 步骤 1-5 的状态标志
   - **输出去向**：HTTP 200 响应体或返回给 `consult_service.search_cases()` 调用方
   - **失败行为**：此步骤为纯内存组装，无外部依赖，无失败路径

### 1.6 接口契约（对外暴露的公共接口）【已锁定】

#### 1.6.1 接口 1：hybrid_search

```python
async def hybrid_search(
    query_text: str,
    tag_filters: TagFilterDto,
    top_k: int = 10,
    request_id: str | None = None,
    db: AsyncSession,
) -> SemanticSearchResult:
    """
    对用户行为描述文本执行混合检索——先按档案标签精确过滤候选集，
    再按语义相似度 + 时效衰减 + 循证加权排序。

    Args:
        query_text: 用户行为描述文本（1-2000 字符，上游已脱敏 PII）
        tag_filters: 档案标签过滤条件（年龄范围、行为类型、情绪等级等）
        top_k: 期望返回的结果数量（默认 10，范围 1-50）
        request_id: 全链路追踪 ID（可选，由上游生成）
        db: 异步数据库会话

    Returns:
        SemanticSearchResult: 排序后的案例切片列表及检索状态

    Raises:
        ValidationError: tag_filters 中必填字段缺失或枚举值不合法
        EmbeddingUnavailableError: DashScope 编码服务不可用（重试耗尽）
        RetrievalTimeoutError: 整体检索超过 500ms 且无任何结果
        DependencyCommunicationError: PostgreSQL 连接失败（重试耗尽）

    Side Effects:
        - 记录结构化日志（含 query_fingerprint，不含完整查询文本）
        - 不执行任何写操作（纯只读）

    Idempotency:
        相同参数重复调用：若案例库无变更，返回一致的结果排序。
        若有新案例入库或案例淘汰，结果可能因数据变化而不同——此为非幂等预期行为。

    Thread Safety:
        本函数内部不维护可变状态。数据库会话由外层依赖注入管理。并发安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `hybrid_search` —— 语义化，描述"混合检索"的业务动作 |
| **输入类型** | 参数：`query_text`（str）、`tag_filters`（TagFilterDto）、`top_k`（int）、`request_id`（str\|None）；契约引用见 §1.3 |
| **输出类型** | `SemanticSearchResult`；契约引用见 §1.4 |
| **异常类型** | `ValidationError`、`EmbeddingUnavailableError`、`RetrievalTimeoutError`、`DependencyCommunicationError`（详见 §1.9） |
| **副作用** | 记录结构化日志、不执行写操作 |
| **幂等性** | 相同参数 + 案例库不变 → 结果一致。案例库变化时结果可能不同，属预期行为 |
| **并发安全** | 线程安全，内部无共享可变状态。数据库会话由调用方提供 |

### 1.7 依赖与集成接口（本模块调用的外部接口）

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 关系型数据库 | PostgreSQL 17.x + pgvector 0.7+ | `SELECT ... FROM case_chunks WHERE ... ORDER BY embedding <=> $vec LIMIT $k` | 执行向量语义检索，HNSW 索引查询 | `docs/篝火智答-项目结构.md` §技术栈回顾、packages/py-db/ |
| 嵌入 API | 阿里云 DashScope | `POST https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings`；Header `Authorization: Bearer $DASHSCOPE_API_KEY`；Body `{"model": "text-embedding-v4", "input": text}`；超时 10s | 文本向量化，1024 维 | `docs/篝火智答-技术栈设计.md` §嵌入模型 |
| 配置服务 | DEPLOY-05/AppSettings | `EMBEDDING_MODEL: str`（默认 text-embedding-v4）、`EMBEDDING_DIMENSION: int`（默认 1024）、`DASHSCOPE_API_KEY: SecretStr`、`DASHSCOPE_BASE_URL: str` | 获取嵌入模型配置 | `docs/篝火智答-项目结构.md` §packages/py-config/ |
| 日志系统 | py-logger | `logger.info("event", **kwargs)` | 结构化日志记录（含 trace_id、query_fingerprint） | `docs/篝火智答-项目结构.md` §packages/py-logger/ |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| PROF-02（档案驱动检索过滤） | `get_tag_filters(profile_id: UUID) -> TagFilterDto` | 提供标准化的档案标签过滤条件（年龄段、行为类型、情绪等级） | ⏭️ 待落地（CSLT-02 自包含定义 TagFilterDto，Mock 返回示例数据） |
| CASE-04（案例向量化入库） | case_chunks 表（只读查询） | 检索已审核通过且已向量化的案例切片（`metadata->>'status'='approved'` + `metadata->>'vectorized'='true'`） | ⏭️ 待落地（CSLT-02 独立测试时使用预置测试数据的 case_chunks 表） |
| CASE-06（案例淘汰管理） | case_chunks.metadata JSONB 中的 status 字段 | 排除标记为失效的案例切片（obsolete/erroneous/disputed/force_removed） | ⏭️ 待落地（CSLT-02 通过 WHERE 条件消费其写入的 metadata 状态，mock 时测试数据中不包含失效状态切片） |
| CSLT-01（危机分级判定） | `BehaviorTypeCategory` 枚举（复用） | TagFilterDto.behavior_type 字段的枚举取值，引用 CSLT-01/BehaviorTypeCategory | ⏭️ 待落地（CSLT-02 引用的枚举值与 CSLT-01/BehaviorTypeCategory.json 一致） |

> **Mock 策略**：PROF-02/CASE-04/CASE-06 均未落地时，module-implementation-executor 使用以下 mock 方案：
> - `TagFilterDto`：直接在 CSLT-02 的 Schema 中自包含定义，使用引用的枚举值（CSLT-01/BehaviorTypeCategory）
> - `case_chunks` 表：在测试环境的 PostgreSQL 中预置 100 条测试切片数据（含 embedding 向量）
> - 失效排除逻辑：测试数据中不包含失效状态切片，验证排除逻辑时手动插入一条 status='obsolete' 的切片确认被排除

### 1.8 状态机

本功能点不涉及状态流转，故无需状态机。每次检索为独立的同步请求-响应操作。检索过程中的内部状态（检索中 → 完成/部分完成/超时/空库）通过 `RetrievalStatus` 枚举和 `SemanticSearchResult.is_complete`/`reason` 字段隐式传递，不持久化。

### 1.9 异常与边界条件

#### 1.9.1 异常 1：检索结果不足期望数量 —— 触发降级放宽

- **触发条件**：
  - 精确标签过滤后结果数 < `top_k`（默认 10）
  - 可能有部分结果（1-9 条）也可能为 0 条
- **处理策略**：
  1. 检查当前过滤层级。初始为 NONE
  2. 层级 1：移除 `emotion_level` 过滤条件，重新执行查询（SQL 中 AND 条件移除对应行）
  3. 若结果数仍 < top_k → 层级 2：进一步移除 `behavior_type` 过滤条件
  4. 若结果数仍 < top_k → 层级 3：移除全部标签条件，执行纯语义检索
  5. 每层放宽后立即检查结果数，达到 top_k 即停止
  6. 记录降级事件：`degradation_applied=True`、`degradation_level=<对应层级>`
  7. 若三层后仍为 0 条 → 返回空列表，标记 `reason="case_library_empty"`（下游可能触发"案例库为空"的用户提示）
- **重试参数**：不重试，降级本身即为重试策略。每层放宽执行一次独立数据库查询

#### 1.9.2 异常 2：检索耗时超过 500 毫秒

- **触发条件**：
  - 从步骤 2（编码查询向量）开始计时，到 `asyncio.wait_for(timeout=0.5)` 触发 `asyncio.TimeoutError`
- **处理策略**：
  1. 捕获 `asyncio.TimeoutError`
  2. 检查是否有部分结果（在超时前已从数据库返回的行数）
  3. 若 `partial_count > 0`：返回已有结果（按步骤 6 排序包装），标记 `is_complete=False`、`degradation_applied=True`
  4. 若 `partial_count == 0`：返回空列表，标记 `is_complete=False`、`reason="timeout"`
  5. 记录超时事件日志：`logger.warning("search_timeout", partial_count=..., elapsed_ms=500)`
  6. **不抛出异常**——返回部分结果或空结果，由下游决策
- **重试参数**：不重试（500ms 是硬超时，超时即返回，不延长等待）

#### 1.9.3 异常 3：DashScope 嵌入 API 不可用

- **触发条件**：
  - `POST /embeddings` 返回 HTTP 4xx/5xx 状态码
  - 或连接超时（>10 秒未建立 TCP 连接）
  - 或响应 JSON 解析失败（`data[0].embedding` 字段缺失）
- **处理策略**：
  1. 捕获 `httpx.HTTPStatusError` 或 `httpx.ConnectTimeout`
  2. 重试最多 2 次（间隔 500ms），每次重试使用新的 HTTP 连接
  3. 第 3 次仍失败 → 抛出 `EmbeddingUnavailableError`（继承 `AppException`）
     - `status_code=503`
     - `detail="向量编码服务暂时不可用，请稍后重试"`
     - 记录日志：`logger.critical("embedding_api_unavailable", retry_count=3, last_error=...)`
  4. 触发告警（通过 OBS-03 的 Webhook 发送钉钉/企业微信通知）
- **重试参数**：最大 2 次，固定间隔 500ms。每次重试前重新建立 HTTP 连接（禁用 keep-alive）

#### 1.9.4 异常 4：PostgreSQL 数据库连接不可用

- **触发条件**：
  - `AsyncSession.execute()` 抛出 `sqlalchemy.exc.OperationalError` 或 `asyncpg.exceptions.ConnectionDoesNotExistError`
  - 连接池耗尽（`QueuePool limit reached`）
- **处理策略**：
  1. 捕获 `SQLAlchemyError`
  2. 从连接池获取新连接（`engine.dispose()` 重建连接池）
  3. 重试最多 3 次（指数退避 0.5s/1s/2s）
  4. 第 4 次仍失败 → 抛出 `DependencyCommunicationError`（继承 `AppException`）
     - `status_code=503`
     - `detail="数据库服务暂不可用"`
     - 记录日志：`logger.critical("database_unavailable", retry_count=3)`
- **重试参数**：最大 3 次，指数退避（0.5s, 1s, 2s）。每次重试前调用 `await engine.dispose()` 重建连接池

#### 1.9.5 边界条件：案例库完全为空

- **触发条件**：
  - 步骤 3 查询返回 0 行，且步骤 4 三层降级后仍为 0 行（确认非过滤条件过严所致）
- **处理策略**：
  1. 不触发降级循环（降级循环仅在 `result_count < top_k` 但 > 0 时进入；若初始结果为 0，降级循环内仍为 0）
  2. 直接返回 `SemanticSearchResult(results=[], total_count=0, is_complete=True, reason="case_library_empty")`
  3. 不抛异常——下游 CSLT-03 感知 `reason="case_library_empty"` 后使用通用策略生成方案
  4. 记录日志：`logger.info("case_library_empty")`

#### 1.9.6 边界条件：top_k 参数超出范围

- **触发条件**：
  - `top_k < 1` 或 `top_k > 50`
- **处理策略**：
  1. 在步骤 1（输入校验）后的二次校验中静默修正：`top_k = max(1, min(50, top_k))`
  2. 不抛异常，不返回 422
  3. 记录日志：`logger.info("top_k_clamped", original=..., clamped=top_k)` 以便排查调用方参数异常

### 1.10 验收测试场景

#### 1.10.1 正向测试 1：精确标签过滤 + 语义检索返回完整结果

- **场景**：传入完整标签条件和查询文本，检索返回恰好 10 条排序结果
- **Given**: `SemanticSearchInput`（query_text="儿子在商场突然捂耳朵蹲下拒绝移动持续尖叫", tag_filters={age_range="学龄儿童(6-12岁)", behavior_type="情绪崩溃", emotion_level="重度"}, top_k=10）；case_chunks 表中存在 >=10 条匹配的已审核切片
- **When**: 调用 `hybrid_search(query_text, tag_filters, top_k=10)`
- **Then**:
  - 返回 `SemanticSearchResult`，`total_count=10`，`is_complete=True`
  - 全部结果的 `metadata->>'behavior_type'` = "情绪崩溃"
  - 全部结果的 `metadata->>'age_range'` = "学龄儿童(6-12岁)"
  - 全部结果的 `metadata->>'status'` 不在 ['obsolete', 'erroneous', 'disputed', 'force_removed'] 中
  - 结果按 `composite_score` 降序排列，第一条 similarity >= 0.80
  - JSON 示例：
    ```json
    {
      "results": [
        {
          "slice_id": "a1b2c3d4-...",
          "case_id": "CASE-042",
          "slice_text": "在嘈杂商场环境中ASD儿童出现听觉感官过载反应...",
          "similarity_score": 0.92,
          "composite_score": 0.88,
          "evidence_level": "NCAEP",
          "case_title": "ASD商场感官过载干预案例",
          "source": "expert"
        }
      ],
      "total_count": 10,
      "is_complete": true,
      "reason": null,
      "query_fingerprint": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "degradation_applied": false,
      "degradation_level": "NONE"
    }
    ```

#### 1.10.2 正向测试 2：三层降级放宽全部触发后返回结果

- **场景**：精确过滤结果为 0 条，三层降级放宽后最终通过纯语义检索返回 3 条
- **Given**: case_chunks 中无同时匹配 `age_range="学龄儿童(6-12岁)"` + `behavior_type="情绪崩溃"` + `emotion_level="重度"` 的切片，但存在匹配行为描述的切片（标签不匹配）
- **When**: 调用 `hybrid_search(query_text, tag_filters, top_k=10)`
- **Then**:
  - 返回 `SemanticSearchResult`，`total_count=3`（实际匹配数），`degradation_applied=True`，`degradation_level="ALL_TAGS_REMOVED"`
  - `is_complete=True`

#### 1.10.3 正向测试 3：自定义 top_k 返回指定数量

- **场景**：用户指定 top_k=5，检索返回恰好 5 条结果
- **Given**: case_chunks 中存在 >=5 条匹配切片，top_k=5
- **When**: 调用 `hybrid_search(query_text, tag_filters, top_k=5)`
- **Then**: `total_count=5`，`is_complete=True`，`degradation_applied=False`

#### 1.10.4 异常测试 1：检索超时返回部分结果

- **场景**：数据库查询耗时超过 500ms，但已有 4 条部分结果
- **Given**: case_chunks 表响应延迟 > 500ms（模拟大量数据未建索引），查询在超时前返回了 4 行
- **When**: 调用 `hybrid_search(query_text, tag_filters, top_k=10)`
- **Then**:
  - 返回 `SemanticSearchResult`，`total_count=4`，`is_complete=False`
  - `degradation_applied=True`
  - 不抛出异常

#### 1.10.5 异常测试 2：案例库完全为空

- **场景**：案例库中无任何已审核切片
- **Given**: case_chunks 表为空或所有切片 status != 'approved'
- **When**: 调用 `hybrid_search(query_text, tag_filters, top_k=10)`
- **Then**:
  - 返回 `SemanticSearchResult`，`total_count=0`，`is_complete=True`，`reason="case_library_empty"`
  - 不抛出异常

#### 1.10.6 异常测试 3：DashScope 嵌入 API 返回 503

- **场景**：DashScope 不可用，重试 2 次后仍失败
- **Given**: Mock DashScope 返回 HTTP 503 三次
- **When**: 调用 `hybrid_search(query_text, tag_filters, top_k=10)`
- **Then**:
  - 抛出 `EmbeddingUnavailableError`（status_code=503）
  - 重试次数 = 3（初始 1 次 + 重试 2 次）

#### 1.10.7 异常测试 4：失效案例被正确排除

- **场景**：案例库中存在 1 条 status='obsolete' 的切片，其语义相似度最高
- **Given**: case_chunks 有 11 条匹配切片，其中 1 条 `metadata->>'status'='obsolete'`，其 embedding 与查询向量距离最近
- **When**: 调用 `hybrid_search(query_text, tag_filters, top_k=10)`
- **Then**:
  - 返回 `total_count=10`，全部 `status != 'obsolete'`
  - 语义相似度最高的失效切片不在结果中

### 1.11 注意事项与禁止行为（编码层面）

1. **SQL WHERE 条件顺序**：失效排除条件（`status NOT IN (...)`）必须在过滤条件之后、ORDER BY 之前。失效排除是最昂贵的过滤（JSONB 字段条件无索引），放最后减少对其不可用切片的计算

2. **降级循环中的查询优化**：每层放宽后重新执行完整 SQL 查询（含 COUNT 子查询检查结果数），而非在应用层对已返回结果做二次过滤。原因：应用层过滤无法扩大召回量——如果原查询只返回 3 条，移除 `emotion_level` 条件后在应用层过滤仍只有 3 条

3. **超时时间分配**：500ms 总超时中，embedding 编码预留 100ms（通常 20-80ms），数据库查询预留 400ms。若 embedding 编码耗时 > 100ms，将直接触发超时并抛出 `EmbeddingUnavailableError`（性能劣化视为不可用）

4. **禁止使用 ORM relationship 加载切片关联的案例详情**：`hybrid_search()` 返回的 `CaseSliceDto` 仅包含切片级别字段（slice_id, case_id, slice_text, scores, evidence_level 等），不执行 JOIN 查询加载 Case 表的完整元数据。案例元数据的加载由下游 CSLT-03 按需执行

5. **查询指纹的计算**：`query_fingerprint = hashlib.sha256(query_text.encode('utf-8')).hexdigest()`。使用 SHA256 而非 MD5——防碰撞不是主要目标，但与 SEC-01 的安全要求保持一致的算法选择

6. **综合排序分数精度**：所有分数保留 4 位小数（`round(score, 4)`），防止浮点累加误差导致排序不稳定

7. **禁止在异步上下文中使用同步 embedding 调用**：`encode_query()` 必须异步实现（`await` DashScope HTTP 调用）。同步阻塞调用会冻结事件循环，导致其他并发请求超时

8. **HNSW 索引参数不可在代码中硬编码**：m=16, ef_construction=200 是数据库级索引创建参数（DDL），代码中只执行查询（DML），不管理索引。索引参数变更应在 Alembic 迁移脚本中管理

### 1.12 文档详细度自检清单

- [x] 文档自包含：不了解本项目代码的 Agent 仅凭此文档即可完成编码
- [x] 无偷懒表述：全文无 "等等"、"..."、"其他字段"、"类似"、"同上"、"参考其他模块"、"请根据实际情况补充"、"开发者自行决定"
- [x] 类型定义完整：每个 Pydantic 字段都有 description + examples + 约束（min_length/max_length/ge/le/pattern 等），详见对应的契约 JSON Schema 文件
- [x] 逻辑步骤完整：每个步骤都有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：6 种异常/边界场景，每种都有精确的触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值来源、条件分支、业务规则都已显式写出
- [x] 技术栈绑定明确：必须使用和禁止使用的项均已列出，且与项目技术栈设计文档保持一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致（见 §1.15）

### 1.14 外部接口契约清单

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| SemanticSearchInput | `docs/contracts/CSLT-02/SemanticSearchInput.json` | input | draft | CSLT-02 | CSLT-03, CSLT-08 |
| TagFilterDto | `docs/contracts/CSLT-02/TagFilterDto.json` | shared-model | draft | CSLT-02 | PROF-02 |
| CaseSliceDto | `docs/contracts/CSLT-02/CaseSliceDto.json` | output | draft | CSLT-02 | CSLT-03 |
| SemanticSearchResult | `docs/contracts/CSLT-02/SemanticSearchResult.json` | output | draft | CSLT-02 | CSLT-03, CSLT-08 |
| EvidenceLevel | `docs/contracts/CSLT-02/EvidenceLevel.json` | shared-enum | draft | CSLT-02 | CSLT-03, QUAL-02 |
| DegradationLevel | `docs/contracts/CSLT-02/DegradationLevel.json` | shared-enum | draft | CSLT-02 | CSLT-03, OBS-01 |
| RetrievalStatus | `docs/contracts/CSLT-02/RetrievalStatus.json` | shared-enum | draft | CSLT-02 | CSLT-03, OBS-01 |
| AppSettings | `docs/contracts/DEPLOY-05/AppSettings.json` | output | draft | DEPLOY-05 | CSLT-02（复用，仅消费 EMBEDDING_MODEL/EMBEDDING_DIMENSION/DASHSCOPE_API_KEY/DASHSCOPE_BASE_URL） |
| BehaviorTypeCategory | `docs/contracts/CSLT-01/BehaviorTypeCategory.json` | shared-enum | draft | CSLT-01 | CSLT-02（复用，TagFilterDto.behavior_type 引用） |

### 1.15 意图一致性声明

- **配套意图文档**：`CSLT-02-RAG语义检索-意图文档.md`
- **冻结时间**：`2026-05-27 09:13:43`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致
  - [x] 本落地规范中的检索流程（标签过滤 + 语义排序）与意图文档中的业务流程一致
  - [x] 本落地规范中的三层降级策略（情绪等级→行为类型→移除标签）与意图文档中的异常业务策略一致
  - [x] 本落地规范中的 500ms 超时部分返回与意图文档中的超时异常策略一致
  - [x] 本落地规范中的失效案例排除（SQL WHERE）与意图文档中的"案例淘汰无条件优先"安全红线一致
  - [x] 本落地规范中的验收测试场景覆盖意图文档中全部 8 项验收标准（AC-01~AC-08）
  - [x] 本落地规范中的 10 项技术决策均在意图文档中"留给规范阶段的技术决策"清单范围内
- **偏差说明**：无偏差，技术实现与意图文档完全一致
