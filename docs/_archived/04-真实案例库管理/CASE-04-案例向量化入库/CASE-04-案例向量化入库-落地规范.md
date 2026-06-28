## 1 功能点：CASE-04 案例向量化入库 — 落地规范

> **文档生成时间**：2026-05-27 09:32:11
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-27 09:32:11 | AI Assistant | 初始版本，基于已冻结意图文档 v2.0 和设计文档 v1.0 生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `CASE-04-案例向量化入库-设计文档.md`。

---

### 1.1 技术栈绑定 【对内实现】

- **必须使用**：
  - `fastapi>=0.115` — lifespan 事件管理（Worker 协程启停）、APIRouter
  - `pydantic>=2.0` — BaseModel、Field()、model_validator、field_validator
  - `sqlalchemy>=2.0` — async engine、async session、declarative Base、sa.Enum
  - `httpx>=0.27` — AsyncClient with connection pool，调用阿里 text-embedding-v4 API
  - `redis>=5.0` — asyncio Redis 客户端，LPUSH/BRPOP 操作 List 队列
  - `asyncio`（Python 标准库） — Task 创建（`asyncio.create_task`）、Semaphore 并发控制、Queue 内部缓冲
  - `re`（Python 标准库） — PII 最终防线正则扫描
- **禁止使用**：
  - 禁止在路由处理函数中直接调用 `process_index_task()`（必须通过 Redis List 异步投递）
  - 禁止使用 Celery、RabbitMQ 或其他独立消息队列（违反零运维负担约束）
  - 禁止绕过 Redis List 直接写入 pgvector（索引写入必须通过 Worker 协程串行化）
  - 禁止在嵌入 API 调用中使用同步 `requests` 库（必须使用 httpx AsyncClient）
  - 禁止在 `enqueue()` 函数中等待嵌入或索引操作的完成（enqueue 必须 < 50ms 同步返回）
  - 禁止在 `build_chunk_text()` 中拆分四要素（四要素必须在同一 chunk_text 字段中完整保留）

### 1.2 文件归属 【对内实现】

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 索引服务入口 | `packages/py-rag/py_rag/indexing/service.py` | `enqueue()`、`process_index_task()`、`manual_retry()` |
| 文本组装模块 | `packages/py-rag/py_rag/indexing/chunk_builder.py` | `build_chunk_text()` — 四要素拼接 + PII 最终防线校验 |
| 嵌入服务客户端 | `packages/py-rag/py_rag/indexing/embedding_client.py` | `generate_embedding()` — 阿里 text-embedding-v4 HTTP 调用 + 熔断器 |
| 索引写入模块 | `packages/py-rag/py_rag/indexing/index_writer.py` | `write_index_to_pgvector()` — pgvector INSERT |
| Worker 协程 | `packages/py-rag/py_rag/indexing/worker.py` | `start_worker()` — lifespan 启动的单例 Worker 协程 |
| Pydantic 模型 | `packages/py-rag/py_rag/indexing/models.py` | `IndexTaskEnvelope`、`ChunkMetadata`、内部模型 |
| ORM 扩展 | `packages/py-db/py_db/models/case_chunks.py` | `CaseChunk` ORM 模型（case_chunks 表） |
| 数据库迁移 | `packages/py-db/migrations/versions/xxx_create_case_chunks.py` | Alembic 迁移脚本：创建 case_chunks 表 + HNSW 索引 |
| 测试文件 | `apps/api-server/tests/api/v1/test_case_indexing.py` | enqueue/process/manual_retry 单元及集成测试 |
| 生命周期注册 | `apps/api-server/app/main.py` | 在 lifespan 中注册 `start_worker()` 和 `stop_worker()` |

---

### 1.3 输入定义 【已锁定】

**IndexTaskEnvelope**（CASE-03 向 Redis List 投递的任务载荷）
- 【契约引用】`docs/contracts/CASE-04/IndexTaskEnvelope.json`
- 本模块作为该契约的定义方
- 消费方：CASE-03（案例审核工作流）
- 说明：此结构是 CASE-03 调用 `enqueue()` 后，由本模块内部生成的 Redis List 载荷。CASE-03 不直接构造此对象，只传入 `case_id`

**enqueue 函数参数**
- 【契约引用】`docs/contracts/CASE-04/enqueue.json`
- 本模块作为该契约的定义方
- 消费方：CASE-03（案例审核工作流）
- 参数：`case_id: UUID` — 审核通过的案例唯一标识

**内部类型**（不对外暴露）：

```python
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime

class InternalIndexContext(BaseModel):
    """Worker 内部处理上下文，不对外暴露"""
    case_id: UUID = Field(description="正在处理的案例标识")
    trace_id: str = Field(pattern=r"^[a-f0-9]{32}$", description="全链路追踪标识")
    retry_count: int = Field(default=0, ge=0, le=2, description="当前重试次数 (0=首次尝试, 1=重试1, 2=重试2)")
    phase: str = Field(description="当前处理阶段: build_chunk_text | generate_embedding | write_index")

class EmbeddingResponse(BaseModel):
    """阿里 text-embedding-v4 API 返回的嵌入向量（内部模型）"""
    embedding: list[float] = Field(min_length=1024, max_length=1024, description="1024 维 float32 向量")
    model: str = Field(default="text-embedding-v4", description="嵌入模型名称")
```

---

### 1.4 输出定义 【已锁定】

**ChunkMetadata**（写入 case_chunks.metadata JSONB 列的结构）
- 【契约引用】`docs/contracts/CASE-04/ChunkMetadata.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-02（RAG语义检索）
- 说明：CSLT-02 在检索时使用此 metadata 中的 4 个键名作为 WHERE 过滤条件

**IndexStatus**（写入 cases.index_status 列的枚举值）
- 【契约引用】`docs/contracts/CASE-04/IndexStatus.json`
- 本模块作为该契约的定义方
- 消费方：CASE-05（案例版本迭代）、CASE-06（案例淘汰管理）、CSLT-02（RAG语义检索）

**INDEX_METADATA_KEYS**（JSONB 键名常量，供 CSLT-02 引用）
- 【契约引用】`docs/contracts/CASE-04/INDEX_METADATA_KEYS.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-02（RAG语义检索）

**enqueue 函数返回值**

```python
class EnqueueResult(TypedDict):
    """enqueue() 的返回字典结构"""
    status: Literal["enqueued", "already_queued", "already_indexed"]
```

| status 值 | 含义 | 触发条件 |
|-----------|------|----------|
| `enqueued` | 正常入队 | 案例状态为 approved 且 index_status 非 pending/processing/indexed |
| `already_queued` | 已在队列或处理中 | 案例 index_status 为 pending 或 processing（幂等跳过） |
| `already_indexed` | 已索引完成 | 案例 index_status 为 indexed（幂等跳过） |

---

### 1.5 核心逻辑步骤 【对内实现】

本模块包含两套逻辑序列：**同步投递路径**（enqueue）和**异步处理路径**（Worker 消费）。

#### 同步投递路径

1. **步骤 1：输入校验与状态查询**
   - **操作对象**：`case_id` 参数 + cases 数据库行
   - **具体操作**：`SELECT id, status, index_status FROM cases WHERE id = $1`（参数化查询，$1 = str(case_id)）
   - **输入来源**：CASE-03 调用 `enqueue(case_id)` 传入的 UUID
   - **输出去向**：查询结果进入步骤 2 的状态分支判断
   - **失败行为**：case_id 格式无效（非 UUID）→ 直接抛出 `ValueError("无效的 case_id 格式")`，不返回 EnqueueResult；数据库查询异常 → 抛出 `DatabaseError`

2. **步骤 2：状态分支判断**
   - **操作对象**：步骤 1 的查询结果
   - **具体操作**：
     - 若行不存在 → 抛出 `ValueError(f"案例 {case_id} 不存在")`
     - 若 `status != 'approved'` → 抛出 `ValueError(f"案例 {case_id} 未审核通过，当前状态: {status}")`
     - 若 `index_status == 'indexed'` → 返回 `EnqueueResult(status="already_indexed")`
     - 若 `index_status IN ('pending', 'processing')` → 返回 `EnqueueResult(status="already_queued")`
     - 若 `index_status IS NULL OR index_status == 'indexing_failed' OR index_status IS DISTINCT FROM 'pending','processing','indexed'` → 进入步骤 3
   - **输入来源**：步骤 1 的数据库查询结果
   - **输出去向**：允许入队的 case_id → 步骤 3；其他 → 直接返回结果
   - **失败行为**：不适用（纯条件判断，无外部调用）

3. **步骤 3：生成任务载荷并投递到 Redis List**
   - **操作对象**：Redis List `index:queue:case_chunks`
   - **具体操作**：
     1. 生成 `trace_id`：`secrets.token_hex(16)`（32 位十六进制小写，与 OBS-01 格式对齐）
     2. 构造 `IndexTaskEnvelope`：`{"case_id": str(case_id), "trace_id": trace_id, "enqueued_at": datetime.now(timezone.utc).isoformat()}`
     3. 序列化为 JSON：`json.dumps(envelope, ensure_ascii=False)`
     4. LPUSH 到 Redis：`await redis.lpush("index:queue:case_chunks", json_str)`
     5. UPDATE cases：`UPDATE cases SET index_status = 'pending' WHERE id = $1`（原子更新，CAS 校验当前 index_status 非 pending/processing/indexed）
   - **输入来源**：步骤 2 确认允许入队的 case_id
   - **输出去向**：LPUSH 成功 → 返回 `EnqueueResult(status="enqueued")`；LPUSH 成功但 UPDATE 失败（CAS 冲突）→ 仍返回 `EnqueueResult(status="already_queued")`（无实际副作用）
   - **失败行为**：Redis LPUSH 超时（> 2s）→ 重试 1 次，仍失败抛出 `RedisConnectionError`，不修改 cases.index_status

#### 异步处理路径（Worker 协程循环）

4. **步骤 4：Worker 循环从 Redis List 消费任务**
   - **操作对象**：Worker 协程实例 + Redis List
   - **具体操作**：`await redis.brpop("index:queue:case_chunks", timeout=5)` — 阻塞等待最多 5s，超时后重新循环
   - **输入来源**：Redis List `index:queue:case_chunks`
   - **输出去向**：取出的任务 JSON 字符串 → 反序列化为 dict → 进入步骤 5
   - **失败行为**：BRPOP 超时（5s 无任务）→ 静默继续循环（正常空闲状态）；Redis 连接断开 → `asyncio.sleep(1)` 后重连

5. **步骤 5：更新状态为 processing + 读取案例数据**
   - **操作对象**：cases 数据库行
   - **具体操作**：
     1. `UPDATE cases SET index_status = 'processing' WHERE id = $1 AND index_status = 'pending'`
     2. `SELECT title, scene_description, behavior_manifestation, intervention_action, result_feedback, behavior_type, emotion_level, applicable_population, evidence_level, disclaimer FROM cases WHERE id = $1`
   - **输入来源**：步骤 4 反序列化的任务 dict 中的 `case_id`
   - **输出去向**：UPDATE 成功 → 案例字段 dict 进入步骤 6；UPDATE 返回 0 rows（CAS 失败，状态已非 pending）→ 跳过本次任务（幂等保护，任务可能已被另一 Worker 或手动操作处理）
   - **失败行为**：数据库连接异常 → 重试 2 次（间隔 1s），仍失败则 LRANGE 将此任务重新放回队列头部（`redis.lpush("index:queue:case_chunks", original_json)`）并由本协程 continue 进入下一次 BRPOP

6. **步骤 6：文本组装与 PII 最终防线校验**
   - **操作对象**：`build_chunk_text()` 函数 + 案例字段 dict
   - **具体操作**：
     1. 检查四段式字段非空：任一字段为 `None` 或空字符串 `""` → 抛出 `ChunkBuildError("四段式字段不完整", missing_fields=[...])`
     2. 模板拼接：`f"场景：{scene_description}\n行为：{behavior_manifestation}\n干预：{intervention_action}\n结果：{result_feedback}"`
     3. 免责声明完整性检查：拼接后的文本中必须包含 `disclaimer` 字段的内容，若缺失 → 抛出 `ChunkBuildError("免责声明在文本组装过程中丢失")`
     4. PII 最终防线校验：对 chunk_text 执行正则扫描：
        - 中国手机号：`r'1[3-9]\d{9}'`
        - 身份证号：`r'[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]'`
        - 家庭住址：`r'([一-龥]{2,}(市|区|县|镇|路|街|号|弄|小区|栋|单元|室)){2,}'`
        - 若命中任一正则 → 抛出 `PIIRejectionError("PII 最终防线检测到未脱敏的个人信息", patterns_matched=[...], sample_offset=n)`并写入告警日志
     5. 校验通过后，构造 `ChunkMetadata` 对象：`behavior_type`、`age_range`（从 `applicable_population` JSONB 中提取）、`severity`（映射 `emotion_level`：mild→轻度, moderate→中度, severe→重度）、`evidence_level`
   - **输入来源**：步骤 5 查询的案例字段 dict
   - **输出去向**：`(chunk_text: str, metadata: ChunkMetadata)` 元组 → 步骤 7
   - **失败行为**：任一校验失败 → 标记 `index_status = 'indexing_failed'`，写入结构化错误日志（包含 case_id、失败原因、缺失字段名），不进入后续步骤

7. **步骤 7：调用嵌入服务生成向量**
   - **操作对象**：`generate_embedding()` 函数 + httpx AsyncClient
   - **具体操作**：`POST https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding`，请求体：
     ```json
     {"model": "text-embedding-v4", "input": {"texts": [chunk_text]}, "parameters": {"text_type": "document"}}
     ```
     从响应 `data[0].embedding` 提取 1024 维 float32 列表
   - **输入来源**：步骤 6 产出的 `chunk_text`
   - **输出去向**：1024 维 `list[float]` → 步骤 8
   - **失败行为**：API 超时（> 5s）→ 重试最多 2 次（间隔 1s, 3s）；所有重试耗尽 → 标记 `index_status = 'indexing_failed'`，记录 `retry_exhausted` 事件；若连续 5 次失败（全局计数器），触发熔断器：暂停 Worker BRPOP 消费 30 秒

8. **步骤 8：写入 pgvector 索引**
   - **操作对象**：case_chunks 数据库表 + pgvector HNSW 索引
   - **具体操作**：
     ```sql
     INSERT INTO case_chunks (id, case_id, chunk_text, embedding, metadata, created_at)
     VALUES ($1, $2, $3, $4::vector(1024), $5::jsonb, $6)
     ```
     参数：`$1 = gen_random_uuid()`, `$2 = str(case_id)`, `$3 = chunk_text`, `$4 = embedding_list`, `$5 = json.dumps(metadata_dict)`, `$6 = now()`
   - **输入来源**：步骤 6 的 `(chunk_text, metadata)` + 步骤 7 的 `embedding` list
   - **输出去向**：INSERT 成功 → 进入步骤 9
   - **失败行为**：INSERT 失败（唯一约束冲突、连接中断等）→ 重试最多 2 次（间隔 1s）；所有重试耗尽 → 标记 `index_status = 'indexing_failed'`

9. **步骤 9：更新索引状态为 indexed**
   - **操作对象**：cases 数据库行
   - **具体操作**：`UPDATE cases SET index_status = 'indexed', indexed_at = now() WHERE id = $1 AND index_status = 'processing'`
   - **输入来源**：步骤 8 INSERT 成功确认
   - **输出去向**：状态更新完成，本次索引入库流程结束
   - **失败行为**：UPDATE 失败 → 重试 2 次（间隔 1s）；仍失败 → 标记 `index_status = 'indexing_failed'`（但向量已写入，后续手动重试时需在步骤 8 中检查 case_chunks 是否已存在对应记录以去重）

10. **步骤 10：手动重试入口**
    - **操作对象**：`manual_retry(case_id)` 函数
    - **具体操作**：
      1. `SELECT index_status FROM cases WHERE id = $1`
      2. 若 `index_status != 'indexing_failed'` → 返回 `{"error": "案例当前索引状态非异常，不允许手动重试"}`
      3. 若 `index_status == 'indexing_failed'` → 调用 `enqueue(case_id)` 重新投递到队列
      4. 返回 `EnqueueResult(status="enqueued")`
    - **输入来源**：运营人员在管理端点击"重新索引"按钮传入的 case_id
    - **输出去向**：返回 EnqueueResult 给调用方
    - **失败行为**：数据库查询失败 → 抛出 `DatabaseError`

---

### 1.6 接口契约 【已锁定】

本模块不暴露独立 HTTP 端点，通过 Python 函数接口与 CALLER 模块交互。

#### 1.6.1 接口 1：enqueue_index_task

```python
async def enqueue_index_task(
    case_id: UUID,
) -> dict:
    """
    将审核通过的案例卡片投递到索引入库异步队列。

    本函数是 CASE-04 对外暴露的唯一入口，由 CASE-03 在审核通过后调用。
    执行内容仅为状态校验 + Redis LPUSH，不执行实际向量化处理。
    同步返回，耗时 < 50ms。

    Args:
        case_id: 审核通过的案例唯一标识（UUID v4）。

    Returns:
        dict: {"status": "enqueued" | "already_queued" | "already_indexed"}

    Raises:
        ValueError: case_id 格式无效、案例不存在、或案例未审核通过。
        RedisConnectionError: Redis List 连接失败（重试 1 次后仍失败）。

    Side Effects:
        - LPUSH JSON 载荷到 Redis List "index:queue:case_chunks"
        - UPDATE cases.index_status = 'pending'（首次入队时）

    Idempotency:
        同一 case_id 重复调用时的行为：
        - index_status=indexed → 返回 {"status": "already_indexed"}，无副作用
        - index_status=pending/processing → 返回 {"status": "already_queued"}，无副作用
        - index_status=indexing_failed 或 NULL → 重新入队，状态设为 pending

    Thread Safety:
        函数内部通过 PostgreSQL CAS（Compare-And-Swap）保证 status 更新的原子性。
        多个并发调用同一 case_id 时，仅第一个成功入队，其余返回 "already_queued"。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `enqueue_index_task` — 描述"将索引入库任务加入队列"的业务动作 |
| **输入类型** | `case_id: UUID`（详见"输入定义"章节 + `docs/contracts/CASE-04/enqueue.json`） |
| **输出类型** | `EnqueueResult`（详见"输出定义"章节） |
| **异常类型** | `ValueError`、`RedisConnectionError`（详见"异常与边界条件"章节） |
| **副作用** | Redis LPUSH、cases.index_status UPDATE |
| **幂等性** | 基于 case_id + index_status 状态机的幂等，重复调用无额外副作用 |
| **并发安全** | PostgreSQL 行级 CAS 保证原子性 |

#### 1.6.2 接口 2：manual_retry_index

```python
async def manual_retry_index(
    case_id: UUID,
) -> dict:
    """
    对索引入库失败的案例执行手动重新索引。

    仅当案例 index_status = 'indexing_failed' 时允许调用。
    内部调用 enqueue_index_task() 重新投递到队列。

    Args:
        case_id: 索引异常的案例唯一标识（UUID v4）。

    Returns:
        dict: {"status": "enqueued"}

    Raises:
        ValueError: 案例不存在、index_status 非 indexing_failed。
        DatabaseError: 数据库查询异常。

    Side Effects:
        - 调用 enqueue_index_task() 的副作用（Redis LPUSH + status UPDATE）。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `manual_retry_index` — 描述"手动重新索引"的管理操作 |
| **输入类型** | `case_id: UUID` |
| **输出类型** | `EnqueueResult` |
| **异常类型** | `ValueError`、`DatabaseError` |
| **副作用** | 委托给 enqueue_index_task() |
| **幂等性** | 通过 enqueue_index_task() 的幂等机制保证 |
| **并发安全** | 继承 enqueue_index_task() 的 CAS 原子性 |

---

### 1.7 依赖与集成接口 【已锁定】

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 关系型数据库 | PostgreSQL 17.x | `asyncpg` 驱动 → SQLAlchemy async engine；`SELECT/UPDATE/INSERT` 参数化查询 | cases 表读取和 index_status 更新；case_chunks 表向量写入 | `docs/篝火智答-项目结构.md` §6.1 `packages/py-db/` |
| 向量检索插件 | pgvector 0.7+ | `CREATE INDEX ON case_chunks USING hnsw (embedding vector_cosine_ops)`；`INSERT ... VALUES ($4::vector(1024))` | 案例切片向量存储与 HNSW 索引 | `docs/篝火智答-技术栈设计.md` §2 |
| 缓存与队列 | Redis 7.x | `redis.asyncio.Redis.lpush(key, value)` / `brpop(key, timeout=5)` | 异步索引入库任务队列 | `docs/篝火智答-技术栈设计.md` §2；`docs/篝火智答-项目结构.md` §6.1 `infrastructure/redis/` |
| 外部 API | 阿里 text-embedding-v4 | `POST https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding`；Header: `Authorization: Bearer $DASHSCOPE_API_KEY`；超时 5s | 文本向量嵌入生成（1024 维） | `docs/篝火智答-技术栈设计.md` §2、§4.3 |
| 日志系统 | OBS-01 结构化日志 | `packages/py-logger/py_logger/structured_logger.py` → `logger.info()/error()/warning()` | 全链路结构化日志（含 trace_id） | `docs/篝火智答-项目结构.md` §6.1 `packages/py-logger/` |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| CASE-01 案例录入管理 | cases 表的四段式字段（`scene_description`、`behavior_manifestation`、`intervention_action`、`result_feedback`）、`behavior_type` 枚举、`emotion_level` 枚举、`applicable_population` JSONB、`evidence_level` 列 | 读取案例文本用于向量化 | ⏭️ 待落地（生成 mock 案例数据） |
| CASE-03 案例审核工作流 | 调用 `enqueue_index_task(case_id)` — 审核通过后的触发入口 | 索引入库的时序触发 | ⏭️ 待落地（生成 mock 调用方） |
| CSLT-02 RAG语义检索 | 消费 case_chunks 表和 `ChunkMetadata` JSONB 键名；通过 `INDEX_METADATA_KEYS` 常量获取过滤键名 | pgvector HNSW 语义检索 + 标签过滤 | ⏭️ 待落地（索引数据已写入，检索功能由 CSLT-02 提供） |
| SEC-03 PII检测脱敏 | PII 检测正则规则集（手机号、身份证号、家庭住址模式） | PII 最终防线校验的规则来源 | ⏭️ 待落地（当前使用本模块内置的正则规则作为独立防线，后续与 SEC-03 对齐） |
| OBS-01 结构化日志 | `json_logger.info("event_name", case_id=..., trace_id=..., ...)` | 各阶段结构化日志输出 | ✅ 已落地 |

---

### 1.8 状态机 【对内实现】

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 副作用 |
|----------|----------|----------|----------|--------|
| (NULL) | `case.status` 变更为 `approved`（CASE-03 触发）| `pending` | case.status = 'approved' 且 index_status IS NULL | `enqueue_index_task()` LPUSH 到 Redis List |
| `pending` | Worker BRPOP 取出任务 | `processing` | Redis List 中有该 case_id 的任务 | `UPDATE cases SET index_status = 'processing'` |
| `processing` | 文本组装成功 + 嵌入成功 + 索引写入成功 | `indexed` | 四段式字段完整、嵌入 API 返回 1024 维向量、pgvector INSERT 成功 | `UPDATE cases SET index_status = 'indexed', indexed_at = now()`；case_chunks 表新增一行 |
| `processing` | 任一阶段重试耗尽（3 次尝试均失败）| `indexing_failed` | 重试计数达到 2（共 3 次尝试） | `UPDATE cases SET index_status = 'indexing_failed'`；结构化日志写入失败详情（phase、error、retry_count） |
| `indexing_failed` | `manual_retry_index(case_id)` | `pending` | 运营人员通过管理端操作触发 | 调用 `enqueue_index_task(case_id)` 重新 LPUSH |
| `indexing_failed` | 熔断器连续 5 次嵌入服务失败 | (不转换) | Worker 暂停消费 30s | 新任务继续 LPUSH 入队但不被处理；30s 后自动恢复消费 |
| `indexed` | CASE-05 版本更新后案例重新审核通过 | `pending` | 仅 CASE-05 触发，新版本需要重新索引 | 与首次 `approved → pending` 相同流程 |

**幂等性规则**：
- `pending` 或 `processing` 状态下再次收到同一 case_id 的 enqueue 调用 → 跳过，返回 `"already_queued"`
- `indexed` 状态下再次收到 enqueue → 跳过，返回 `"already_indexed"`
- `indexing_failed` 状态下再次收到 enqueue → 允许入队（等同于手动重试）

---

### 1.9 异常与边界条件 【对内实现】

#### 1.9.1 异常 1：案例四段式字段不完整

- **触发条件**：
  - `scene_description` 为 `None` 或空字符串 `""`（`len(stripped) < 10`）
  - `behavior_manifestation` 为 `None` 或空字符串 `""`（`len(stripped) < 10`）
  - `intervention_action` 为 `None` 或空字符串 `""`（`len(stripped) < 10`）
  - `result_feedback` 为 `None` 或空字符串 `""`（`len(stripped) < 10`）
- **处理策略**：
  1. 在步骤 6（文本组装）阶段执行字段非空校验
  2. 按顺序检验四个字段，收集所有缺失/过短的字段名列表
  3. 构造 `ChunkBuildError("四段式字段不完整", missing_fields=["scene_description", "behavior_manifestation"], case_id=...)`
  4. UPDATE `cases SET index_status = 'indexing_failed'`
  5. 记录结构化日志：`logger.error("chunk_build_failed", case_id=..., missing_fields=[...], reason="incomplete_fields")`
  6. 不调用嵌入 API，不写入 pgvector
  7. 管理端异常详情展示缺失的具体字段名，引导运营人员联系专家补充后重新提交审核
- **重试参数**：不重试。此异常属于数据完整性问题，非瞬时故障，重试不会改变结果。运营人员修正数据后通过 `manual_retry_index()` 重新触发。

#### 1.9.2 异常 2：嵌入服务不可用或超时

- **触发条件**：
  - 阿里 text-embedding-v4 API 返回 HTTP 4xx/5xx 状态码
  - httpx 请求超时（超过 `EMBEDDING_TIMEOUT = 5` 秒）
  - 响应 JSON 解析失败或 `data[0].embedding` 字段缺失
  - 返回的 embedding 数组长度不等于 1024
- **处理策略**：
  1. 捕获 `httpx.HTTPStatusError` / `httpx.TimeoutException` / `KeyError` / `ValueError`
  2. 递增内部重试计数：`InternalIndexContext.retry_count += 1`
  3. 若 `retry_count < 2`（即还有重试机会）：
     - 线性退避等待：`await asyncio.sleep(1 if retry_count == 0 else 3)`
     - 重新调用 `generate_embedding(chunk_text)`（使用新的 httpx 请求，不重用失效连接）
  4. 若 `retry_count >= 2`（3 次尝试全部失败）：
     - UPDATE `cases SET index_status = 'indexing_failed'`
     - 全局失败计数器 `embedding_failure_count` 递增；若达到 5，启动熔断器（`asyncio.sleep(30)` 暂停 Worker 消费）
     - 记录结构化日志：`logger.error("embedding_exhausted", case_id=..., retry_count=2, last_error=str(e))`
  5. 不写入 pgvector（无有效向量无法创建索引记录）
- **重试参数**：共 3 次尝试（1 主 + 2 重试），线性退避 1s / 3s。总等待时间上限 4s。

#### 1.9.3 异常 3：pgvector 索引写入失败

- **触发条件**：
  - `INSERT INTO case_chunks` 失败：唯一约束冲突（`id` 碰撞）、外键约束冲突（`case_id` 无效）、PostgreSQL 连接池耗尽、磁盘空间不足
  - HNSW 索引写入触发 PostgreSQL 错误
- **处理策略**：
  1. 捕获 `sqlalchemy.exc.IntegrityError` / `sqlalchemy.exc.OperationalError` / `asyncpg.exceptions.UniqueViolationError`
  2. 递增内部重试计数
  3. 若 `retry_count < 2`：线性退避等待 1s，重新执行 INSERT
  4. 若 `retry_count >= 2`（3 次尝试全部失败）：
     - UPDATE `cases SET index_status = 'indexing_failed'`
     - 记录结构化日志：`logger.error("index_write_exhausted", case_id=..., retry_count=2, error=str(e))`
  5. 不保留已生成的 embedding 向量（丢弃，下次手动重试时从步骤 6 重新生成）
- **重试参数**：共 3 次尝试（1 主 + 2 重试），固定间隔 1s。总等待时间上限 2s。

#### 1.9.4 异常 4：Redis List 连接中断

- **触发条件**：
  - Redis 连接池耗尽或 Redis 服务不可达
  - LPUSH 或 BRPOP 操作超时后连接未恢复
- **处理策略**：
  1. 捕获 `redis.exceptions.ConnectionError` / `redis.exceptions.TimeoutError`
  2. 对于 LPUSH（enqueue 投递路径）：重试 1 次（间隔 500ms），仍失败则抛出 `RedisConnectionError("索引队列不可用，案例索引入库暂时中断")` 给 CASE-03
  3. 对于 BRPOP（Worker 消费路径）：静默等待 1s 后重连，无限重试但每次间隔递增（1s → 2s → 4s → 上限 10s）
  4. 记录结构化日志：`logger.critical("redis_unavailable", operation="lpush|brpop", retry_count=...)`
- **重试参数**：LPUSH 路径 1+1 次，BRPOP 路径无限重试（含间隔递增）。LPUSH 失败时 CASE-03 可稍后重试调用来恢复。

#### 1.9.5 异常 5：PII 最终防线触发

- **触发条件**：
  - 文本拼接后的 chunk_text 中正则匹配到手机号（`r'1[3-9]\d{9}'`）
  - 匹配到身份证号（`r'[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]'`）
  - 匹配到家庭住址模式（`r'([一-龥]{2,}(市|区|县|镇|路|街|号|弄|小区|栋|单元|室)){2,}'`）
- **处理策略**：
  1. 抛出 `PIIRejectionError("PII 最终防线检测到未脱敏的个人信息", patterns_matched=[...], sample_offset=n)`，附带匹配到的模式类型和文本偏移量
  2. UPDATE `cases SET index_status = 'indexing_failed'`
  3. 记录告警日志：`logger.warning("pii_rejection", case_id=..., patterns_matched=[...], sample_text=chunk_text[offset-20:offset+20])`
  4. 不在日志中完整输出 PII 原文（仅输出前后各 20 字符的上下文片段，且对匹配段做掩码替换 `***`）
- **重试参数**：不重试。此异常属于数据问题，需运营人员检查上游脱敏流程是否正常执行。

---

### 1.10 验收测试场景 【对内实现】

#### 1.10.1 正向测试 1：完整案例审核通过后自动索引入库

- **场景**：一条四段式字段完整的案例经专家审核通过后，系统自动完成向量化入库全流程。
- **Given**：
  - 案例 `cases` 表存在记录，status = 'approved'，四段式字段均非空且完整
  - 案例数据：`case_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"`，scene_description = "ASD 人士在大型商场因噪音引发感官过载"，behavior_manifestation = "出现捂耳蹲下拒绝移动"，intervention_action = "先关闭附近声源设备电源，提供降噪耳罩"，result_feedback = "3 分钟后平复并离开"，disclaimer = "AI 建议仅供参考，不构成医疗诊断或治疗建议"
  - Redis List 可用
  - 嵌入 API 返回正常 1024 维向量
  - pgvector 可写入
- **When**：CASE-03 调用 `enqueue_index_task(case_id)` → Worker 消费并执行全流程
- **Then**：
  - `enqueue_index_task()` 返回 `{"status": "enqueued"}`，耗时 < 50ms
  - cases.index_status 最终为 `indexed`
  - case_chunks 表新增一行，chunk_text 包含完整四要素：`"场景：ASD 人士...\n行为：出现捂耳...\n干预：先关闭...\n结果：3 分钟后..."`
  - embedding 列为 1024 维向量（无零向量：`sum(embedding) != 0.0`）
  - metadata JSONB 包含 4 个键：behavior_type、age_range、severity、evidence_level
  - 结构化日志包含 trace_id、case_id、各阶段耗时

#### 1.10.2 正向测试 2：已索引案例幂等跳过

- **场景**：同一案例已被索引后，CASE-03 误操作再次触发索引入库。
- **Given**：案例 index_status = 'indexed'，case_chunks 表已有对应记录
- **When**：再次调用 `enqueue_index_task(case_id)`
- **Then**：
  - 返回 `{"status": "already_indexed"}`
  - 未向 Redis List 投递新任务
  - cases.index_status 保持 `indexed`
  - case_chunks 表无重复记录

#### 1.10.3 正向测试 3：索引异常案例手动重试成功

- **场景**：案例因嵌入 API 瞬时故障被标记为 indexing_failed 后，运营人员手动触发重新索引成功。
- **Given**：
  - 案例 index_status = 'indexing_failed'
  - 嵌入 API 此刻可用（前次失败为瞬时故障）
- **When**：调用 `manual_retry_index(case_id)`
- **Then**：
  - `manual_retry_index()` 返回 `{"status": "enqueued"}`
  - Worker 处理完成后 cases.index_status 更新为 `indexed`
  - case_chunks 表新增一行（若前次失败在文本组装阶段）或仅一行（若前次失败在嵌入阶段后未写入 pgvector）

#### 1.10.4 异常测试 1：四段式字段缺失拒绝入库

- **场景**：案例的四段式字段中 `intervention_action` 为空，系统拒绝向量化入库。
- **Given**：
  - 案例 status = 'approved'，但 `intervention_action = None`
  - 其他三个字段正常
- **When**：`enqueue_index_task(case_id)` → Worker 执行到步骤 6（文本组装）
- **Then**：
  - 抛出 `ChunkBuildError`，错误信息包含 `missing_fields: ["intervention_action"]`
  - cases.index_status 更新为 `indexing_failed`
  - 未调用嵌入 API
  - case_chunks 表无该案例记录
  - 结构化日志中 `phase = "build_chunk_text"`，`reason = "incomplete_fields"`

#### 1.10.5 异常测试 2：嵌入 API 超时后重试并标记异常

- **场景**：嵌入 API 连续 3 次超时，系统标记索引入库失败。
- **Given**：
  - 案例数据正常，四段式字段完整
  - 嵌入 API 配置为模拟超时（Mock httpx 返回 `TimeoutException`）
- **When**：Worker 执行到步骤 7（嵌入生成）
- **Then**：
  - 第 1 次调用超时 → 等待 1s → 重试
  - 第 2 次调用超时 → 等待 3s → 重试
  - 第 3 次调用超时 → 不再重试
  - cases.index_status 更新为 `indexing_failed`
  - 全局计数器 `embedding_failure_count` 递增
  - 结构化日志中 `retry_count = 2`，`phase = "generate_embedding"`
  - case_chunks 表无新增记录

#### 1.10.6 异常测试 3：PII 最终防线触发后拒绝入库

- **场景**：上游 SEC-03 脱敏遗漏，chunk_text 中仍包含手机号模式，被本模块 PII 防线拦截。
- **Given**：
  - 案例数据正常，但 scene_description 中包含文本 "请联系 13812345678"
  - 正则 `r'1[3-9]\d{9}'` 匹配到该手机号
- **When**：Worker 执行到步骤 6 的 PII 最终防线校验
- **Then**：
  - 抛出 `PIIRejectionError`，`patterns_matched` 包含 "phone_number"
  - cases.index_status 更新为 `indexing_failed`
  - 告警日志中 `sample_text` 对手机号部分做了掩码 `***`
  - 未调用嵌入 API，未写入 pgvector

---

### 1.11 注意事项与禁止行为（编码层面） 【对内实现】

1. **（编码约束）Redis List 键名固定为 `index:queue:case_chunks`**：Worker BRPOP 和 enqueue LPUSH 必须使用完全一致的键名字符串。建议定义为模块级常量 `INDEX_QUEUE_KEY = "index:queue:case_chunks"` 全局复用，禁止硬编码分散在多处。

2. **（编码约束）embedding 维度校验不可省略**：每次从阿里 text-embedding-v4 API 获取 embedding 后，必须执行 `assert len(embedding) == 1024, f"期望 1024 维，实际 {len(embedding)} 维"`。pgvector 的 `vector(1024)` 类型会拒绝维度不匹配的写入，但事前断言可以给出更清晰的错误信息。

3. **（编码约束）metadata JSONB 键名使用 `INDEX_METADATA_KEYS` 常量**：`ChunkMetadata` 对象的构造必须引用 `INDEX_METADATA_KEYS` 常量中定义的键名，禁止手写字符串 `"behavior_type"` 等。这保证了与 CSLT-02 RAG 检索模块的键名一致性。常量定义：`INDEX_METADATA_KEYS = {"behavior_type", "age_range", "severity", "evidence_level"}`。

4. **（易错点）Worker 协程异常边界**：Worker 的 BRPOP → 处理 → 状态更新循环中，任何未捕获异常都会导致 Worker 协程终止。必须在外层使用 `try: ... except Exception as e: logger.critical(...); await asyncio.sleep(1)` 兜底，确保 Worker 永不死循环退出。

5. **（易错点）熔断器全局计数器线程安全**：`embedding_failure_count` 作为模块级变量，在 asyncio 单线程协程模型下天然安全。若未来迁移到多线程 Worker，必须使用 `asyncio.Lock` 或 `threading.Lock` 保护计数器的读写。

6. **（禁止行为）禁止在 enqueue 中调用嵌入 API**：`enqueue_index_task()` 必须 < 50ms 同步返回。在其中调用 `generate_embedding()` 或直接 `INSERT INTO case_chunks` 将导致 CASE-03 审核接口超时。

7. **（禁止行为）禁止在索引失败时修改 cases.status**：索引流程失败仅影响 `cases.index_status`，绝不可修改 `cases.status`（审核结果）。违反此条将导致已审核通过的案例退回草稿状态，专家的审核工作成果被抹除。该行为对应意图文档 §1.11 约束 3，是不可触碰的底线。

8. **（偷懒红线）禁止以 "和 AUTH 模块类似" 为由省略异常处理**：本模块涉及异步队列、外部 API、向量数据库三个独立故障面，每个故障面都有独立的异常类型和处理策略。禁止使用泛化的 `except Exception` 统一处理。

---

### 1.12 文档详细度自检清单

- [x] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成编码
- [x] 无偷懒表述：已全文检查，无 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：每个对外类型通过契约引用定义（JSON Schema 文件含完整字段、约束、示例）；内部类型给出完整 Pydantic 定义
- [x] 逻辑步骤完整：同步投递 3 步 + 异步处理 7 步，每步都有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：5 种异常，每种都有精确触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值（EMBEDDING_TIMEOUT=5s、重试间隔 1s/3s、BRPOP timeout=5s 等）均已显式写出
- [x] 技术栈绑定明确：必须使用和禁止使用的项均已列出，且与 `docs/篝火智答-技术栈设计.md` 保持一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致（见 1.15 意图一致性声明）

---

### 1.14 外部接口契约清单 【已锁定】

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| IndexStatus | `docs/contracts/CASE-04/IndexStatus.json` | shared-enum | draft | CASE-04 | CASE-05, CASE-06, CSLT-02 |
| IndexTaskEnvelope | `docs/contracts/CASE-04/IndexTaskEnvelope.json` | input | draft | CASE-04 | CASE-03 |
| ChunkMetadata | `docs/contracts/CASE-04/ChunkMetadata.json` | output | draft | CASE-04 | CSLT-02 |
| INDEX_METADATA_KEYS | `docs/contracts/CASE-04/INDEX_METADATA_KEYS.json` | shared-model | draft | CASE-04 | CSLT-02 |
| enqueue | `docs/contracts/CASE-04/enqueue.json` | input | draft | CASE-04 | CASE-03 |

---

### 1.15 意图一致性声明

- **配套意图文档**：`CASE-04-案例向量化入库-意图文档.md`
- **冻结时间**：2026-05-27 09:13:07
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致（1.3 输入定义映射了业务字段的 14 个字段；1.4 输出定义的 ChunkMetadata 对应意图文档的元数据标签 4 个维度）
  - [x] 本落地规范中的状态机实现与意图文档中的状态业务定义一致（1.8 状态机的 4 个状态队列等待→处理中→已入库|索引异常 与意图文档 §1.7 完全对应）
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致（1.9 的 5 种异常覆盖了意图文档 §1.8 的全部 3 类异常，并补充了 Redis 连接中断和 PII 最终防线两种边界场景）
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准（1.10 的 6 个测试场景对应意图文档 §1.9 的 7 项验收条件，AC-03 向量维度校验嵌入在正向测试 1 的 Then 断言中）
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"的范围（1.5 核心逻辑步骤明确了异步队列选型、重试退避策略、索引写入策略、并发控制的具体取值）
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
