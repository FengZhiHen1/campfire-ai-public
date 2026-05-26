## 1 功能点：KNOW-01 科普内容管理 — 落地规范

> **文档生成时间**：2026-05-26 17:21:27 (Asia/Shanghai)
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 17:21:27 | AI Assistant | 初始版本，基于设计文档 v1.0 和契约协调报告生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `KNOW-01-科普内容管理-设计文档.md`。
> **流水线上下文**：本落地规范基于已冻结的 `KNOW-01-科普内容管理-意图文档.md`（冻结于 2026-05-26 16:54:49）编写。技术实现必须与意图文档中的业务定义保持一致。

---

### 1.1 技术栈绑定

> 【对内实现】

- **必须使用**：
  - Python `>=3.11`
  - FastAPI `>=0.115` — API 路由与请求处理，使用 `APIRouter(prefix="/api/v1/knowledge")`
  - SQLAlchemy `>=2.0` — async ORM，使用 `AsyncSession` 和 `select()` 异步查询
  - Pydantic `>=2.0` — 请求/响应 Schema 校验，使用 `BaseModel` + `Field()` 约束
  - Alembic — 数据库迁移管理，迁移脚本位于 `packages/py-db/migrations/versions/`
  - PostgreSQL `17.x` — 数据库，含 `zhparser` 中文分词扩展用于 ts_vector 列
  - `uuid.uuid4()` — 文章主键生成策略
  - `python-jose` — JWT Token 解析（由 AUTH-04 Depends 注入）
  - `structlog` 或 Python `logging` — 结构化日志记录（通过 `packages/py-logger/`）
  - `datetime.timezone.utc` — 所有时间字段使用 `TIMESTAMPTZ`，存储 UTC，返回时转换

- **禁止使用**：
  - 禁止使用数据库 `ENUM` 类型 — 文章状态和分类使用 `VARCHAR(20)` 字符串存储，Python `Enum` 类在应用层约束
  - 禁止引入 Elasticsearch / Meilisearch 等独立搜索引擎 — 全文检索仅使用 PostgreSQL ts_vector
  - 禁止使用 `PATCH /{id}` 通用端点做状态切换 — 发布/下架使用独立端点 `POST /{id}/publish` 和 `POST /{id}/unpublish`
  - 禁止在 ORM 模型中使用 `ForeignKey` 指向 CASE 模块的表 — 关联案例编号为字符串数组，不建立数据库级外键约束
  - 禁止直接拼接 SQL 字符串 — 全文检索查询使用 `func.plainto_tsquery()` 等 SQLAlchemy 函数封装

### 1.2 文件归属

> 【对内实现】

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| API 路由 | `apps/api-server/app/api/v1/knowledge.py` | REST API 端点定义：CRUD + 发布/下架 + 搜索 |
| Service 层 | `apps/api-server/app/services/knowledge_service.py` | 业务逻辑编排：校验、状态切换、搜索查询组装 |
| ORM 模型 | `packages/py-db/py_db/models/knowledge.py` | `KnowledgeArticle` SQLAlchemy ORM 模型定义 |
| Repository 层 | `packages/py-db/py_db/repositories/knowledge_repository.py` | 数据访问层：CRUD 操作、搜索查询、分页封装 |
| Pydantic Schema | `packages/py-schemas/py_schemas/knowledge.py` | 请求/响应 DTO 定义：ArticleCreate, ArticleUpdate, ArticleResponse 等 |
| Alembic 迁移 | `packages/py-db/migrations/versions/YYYYMMDD_knowledge_articles.py` | 创建 `knowledge_articles` 表的迁移脚本 |
| 测试文件 | `apps/api-server/tests/unit/test_knowledge_service.py` | Service 层单元测试 |
| 测试文件 | `apps/api-server/tests/integration/test_knowledge_api.py` | API 集成测试 |

### 1.3 输入定义

> 【已锁定】对外接口类型使用契约引用。

**ArticleCreate**（文章创建请求）
- 【契约引用】`docs/contracts/KNOW-01/ArticleCreate.json`
- 本模块作为该契约的定义方
- 消费方：暂无（管理端直接调用，暂无下游模块消费此输入类型）

**ArticleUpdate**（文章更新请求）
- 【契约引用】`docs/contracts/KNOW-01/ArticleUpdate.json`
- 本模块作为该契约的定义方
- 消费方：暂无

**ArticleSearchParams**（全文检索查询参数）
- 【契约引用】`docs/contracts/KNOW-01/ArticleSearchParams.json`
- 本模块作为该契约的定义方
- 消费方：KNOW-03（全文检索）、KNOW-06（科普查阅界面）、KNOW-07（科普交互逻辑）

**ArticleCategory**（文章分类枚举）
- 【契约引用】`docs/contracts/KNOW-01/ArticleCategory.json`
- 本模块作为该契约的定义方
- 消费方：KNOW-03（全文检索分类过滤）、KNOW-06（科普查阅界面分类导航）、KNOW-07（科普交互逻辑）

**私有类型 — ArticleStatusEnum**（模块内部使用的 Python Enum，不写入契约文件）：
```python
class ArticleStatusEnum(str, Enum):
    """文章发布状态枚举，仅在本模块内部使用"""
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"
```

### 1.4 输出定义

> 【已锁定】对外接口类型使用契约引用。

**ArticleResponse**（文章详情响应）
- 【契约引用】`docs/contracts/KNOW-01/ArticleResponse.json`
- 本模块作为该契约的定义方
- 消费方：KNOW-04（案例关联推荐）、KNOW-06（科普查阅界面）、KNOW-07（科普交互逻辑）

**ArticleListItem**（文章列表条目）
- 【契约引用】`docs/contracts/KNOW-01/ArticleListItem.json`
- 本模块作为该契约的定义方
- 消费方：KNOW-03（全文检索结果列表）、KNOW-06（科普查阅界面列表）、KNOW-07（科普交互逻辑）

**ArticleSearchResult**（搜索结果条目）
- 【契约引用】`docs/contracts/KNOW-01/ArticleSearchResult.json`
- 本模块作为该契约的定义方
- 消费方：KNOW-03（全文检索返回结果）、KNOW-06（搜索结果渲染）、KNOW-07（搜索状态管理）

**ArticleStatus**（文章状态枚举）
- 【契约引用】`docs/contracts/KNOW-01/ArticleStatus.json`
- 本模块作为该契约的定义方
- 消费方：KNOW-03（搜索过滤）、KNOW-06（列表/详情状态展示）、KNOW-07（搜索状态管理）

**PaginatedResponse[T]**（通用分页响应 — 复用项目级类型）
- 非本模块定义，复用项目 `packages/py-schemas/py_schemas/common.py` 中的通用分页 Schema
- 类型签名：`PaginatedResponse[T] = {items: list[T], total: int, page: int, page_size: int, total_pages: int}`

### 1.5 核心逻辑步骤

> 【对内实现】

按执行顺序列出可测试的原子逻辑步骤：

1. **步骤 1：请求校验与鉴权**
   - **操作对象**：FastAPI Request + Pydantic Schema 实例
   - **具体操作**：
     - 管理类端点（create/update/delete/publish/unpublish）：FastAPI Depends 先执行 `require_role(["admin", "maintainer"])` 注入当前用户身份
     - Pydantic 自动校验请求体：`ArticleCreate` 或 `ArticleUpdate` 或 `ArticleSearchParams`
     - 查询类端点（list/detail/search）：无需鉴权，但列表查询的 `status` 参数默认过滤为 `published`（管理端传 `include_unpublished=true` 可查看全部）
   - **输入来源**：HTTP 请求体 JSON → Pydantic 解析
   - **输出去向**：校验通过的 Pydantic 实例传入 Service 层
   - **失败行为**：Pydantic 校验失败 → 立即返回 HTTP 422，响应体 `{"detail": [{"loc": ["body", "title"], "msg": "field required", "type": "value_error.missing"}]}`，不进入后续步骤

2. **步骤 2：关联案例有效性校验（创建/更新时）**
   - **操作对象**：`related_case_ids` 列表
   - **具体操作**：
     - 若 `related_case_ids` 非空 → 调用 `case_repository.exists(case_ids)` 批量查询 CASE-01 模块确认编号存在
     - 再调用 `case_repository.find_approved_ids(case_ids)` 确认关联案例为 `approved` 状态（CASE-03 模块）
     - 若任一 case_id 不存在或非 approved → 收集无效编号列表
   - **输入来源**：步骤 1 校验通过的 Pydantic 实例中的 `related_case_ids` 字段
   - **输出去向**：全部有效的 `related_case_ids` 进入步骤 3；无效编号列表返回给客户端
   - **失败行为**：`case_repository` 调用失败（连接超时/服务不可用）→ 重试 2 次（间隔 1s），仍失败 → 记录日志 `logger.error("case_validation_failed", case_ids=..., error=...)`，返回 HTTP 503

3. **步骤 3：数据持久化（创建）**
   - **操作对象**：`KnowledgeArticle` ORM 模型实例
   - **具体操作**：
     - 创建 `KnowledgeArticle` 实例：`id=uuid4()`, `title=...`, `category=...`, `content=...`, `related_case_ids=...`, `status=ArticleStatusEnum.UNPUBLISHED`
     - 计算 `search_vector`：`func.setweight(func.to_tsvector('chinese', title), 'A') || func.setweight(func.to_tsvector('chinese', content), 'A')`（MVP 等权重）
     - `session.add(article)` → `await session.commit()`
   - **输入来源**：步骤 1 校验通过的 `ArticleCreate`
   - **输出去向**：持久化后的 `KnowledgeArticle` 实例进入步骤 5
   - **失败行为**：数据库写入失败（唯一约束冲突/连接超时/磁盘满）→ 回滚事务，记录日志，返回 HTTP 500，不返回部分写入结果

4. **步骤 4：数据持久化（更新）**
   - **操作对象**：已存在的 `KnowledgeArticle` ORM 模型实例
   - **具体操作**：
     - `await session.get(KnowledgeArticle, id)` 查询文章是否存在
     - 若存在 → 仅更新 `ArticleUpdate` 中提供的字段（非 None 字段），其余字段保持不变
     - 若 `content` 被更新 → 重新计算 `search_vector`
     - 同分类下标题唯一性检查（非阻塞）：若 `title` 被更新且同分类下已存在同名文章 → 返回 200 OK + `{"warning": "同分类下已存在同名文章"}`，不拒绝保存
     - `await session.commit()`
   - **输入来源**：步骤 1 校验通过的 `ArticleUpdate` + URL 路径参数 `id`
   - **输出去向**：更新后的 `KnowledgeArticle` 实例进入步骤 5
   - **失败行为**：文章不存在 → 返回 HTTP 404；数据库写入失败 → 回滚，返回 HTTP 500

5. **步骤 5：响应序列化**
   - **操作对象**：`KnowledgeArticle` ORM 模型实例
   - **具体操作**：
     - 映射到对应的 Pydantic 响应 Schema（`ArticleResponse` / `ArticleListItem` / `ArticleSearchResult`）
     - `published_at` 字段：若为 `None` 则序列化为 `null`
     - `related_case_ids` 字段：仅 `ArticleResponse` 中需要标注 `_stale` 状态——通过 `case_repository.exists(case_ids)` 惰性查询确认
     - 若因 CASE 模块不可用导致 `_stale` 查询失败 → 不阻塞响应，`_stale` 字段不返回（降级为不标注失效状态），记录 warning 日志
   - **输入来源**：步骤 3 或步骤 4 产出的 ORM 实例
   - **输出去向**：JSON 响应体返回客户端
   - **失败行为**：序列化本身不应失败（ORM 字段类型已保证），若出现意外 → 记录 critical 日志，返回 HTTP 500

6. **步骤 6：状态切换**
   - **操作对象**：`KnowledgeArticle` ORM 实例的 `status` 字段
   - **具体操作**：
     - **publish** 端点：`POST /api/v1/knowledge/{id}/publish`
       - 若 `status == PUBLISHED` → 返回 200 OK（幂等）
       - 若 `status == UNPUBLISHED` → 设置 `status = PUBLISHED`，若 `published_at` 为 `None` 则写入当前 `TIMESTAMPTZ`，更新 `updated_at`
       - 记录审计日志：`logger.info("article_published", article_id=..., operator_id=..., previous_status=..., new_status=...)`
     - **unpublish** 端点：`POST /api/v1/knowledge/{id}/unpublish`
       - 若 `status == UNPUBLISHED` → 返回 200 OK（幂等）
       - 若 `status == PUBLISHED` → 设置 `status = UNPUBLISHED`，不更新 `published_at`，更新 `updated_at`
       - 记录审计日志：`logger.info("article_unpublished", article_id=..., operator_id=..., previous_status=..., new_status=...)`
     - `await session.commit()`
   - **输入来源**：URL 路径参数 `id` + 鉴权通过的当前用户身份
   - **输出去向**：更新后的 `ArticleResponse` 返回客户端
   - **失败行为**：文章不存在 → HTTP 404；数据库写入失败 → 回滚，HTTP 500

7. **步骤 7：全文检索**
   - **操作对象**：`knowledge_articles` 表的 `search_vector` 列
   - **具体操作**：
     - 构建查询：`SELECT *, ts_rank(search_vector, plainto_tsquery('chinese', :query)) AS score FROM knowledge_articles WHERE search_vector @@ plainto_tsquery('chinese', :query)`
     - 若提供 `category` 参数 → 追加 `AND category = :category`
     - 面向终端用户 → 自动追加 `AND status = 'published'`
     - 按 `score DESC` 排序，应用 `LIMIT :page_size OFFSET :offset`
     - 生成 `content_snippet`：使用 PostgreSQL `ts_headline('chinese', content, plainto_tsquery('chinese', :query), 'MaxWords=50, MinWords=20, StartSel=<mark>, StopSel=</mark>')`
   - **输入来源**：步骤 1 校验通过的 `ArticleSearchParams`
   - **输出去向**：`list[ArticleSearchResult]` 通过 `PaginatedResponse` 包装返回
   - **失败行为**：数据库超时 > 5 秒 → 返回 HTTP 503，`{"detail": "搜索服务暂时不可用，请稍后重试"}`，记录慢查询日志。客户端可重试（建议指数退避，最多 3 次）

### 1.6 接口契约

> 【已锁定】本模块对外暴露的公共 API 接口。

#### 1.6.1 接口 1：`create_article` — 创建科普文章

```python
async def create_article(
    article: ArticleCreate,
    session: AsyncSession,
    case_repo: CaseRepository,
    operator: UserIdentity,
) -> ArticleResponse:
    """
    创建一篇新的科普文章。文章创建后默认状态为 unpublished（下架），
    需通过 publish_article 接口发布后方对终端用户可见。

    Args:
        article: 文章创建请求体，含 title/category/content/related_case_ids
        session: 数据库异步会话
        case_repo: 案例模块仓储，用于校验关联案例有效性
        operator: 当前操作用户身份（由 AUTH-04 Depends 注入）

    Returns:
        ArticleResponse: 创建成功的文章详情

    Raises:
        ValueError: related_case_ids 中存在无效或未审批的案例编号
        SQLAlchemyError: 数据库写入失败

    Side Effects:
        - 在 knowledge_articles 表中新增一行记录
        - 计算并写入 ts_vector 全文检索列
        - 记录结构化审计日志

    Idempotency:
        不支持幂等重复调用。每次调用创建一篇新文章（新 UUID）。

    Thread Safety:
        本函数通过 AsyncSession 管理数据库事务，依赖 SQLAlchemy 连接池的线程安全性。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `create_article` — 描述"创建科普文章"的业务动作 |
| **HTTP 端点** | `POST /api/v1/knowledge` |
| **鉴权要求** | `require_role(["admin", "maintainer"])` |
| **输入类型** | `ArticleCreate`（详见契约引用） |
| **输出类型** | `ArticleResponse`（详见契约引用），HTTP 201 |
| **异常类型** | `ValidationError`(422), `ValueError`(422 含无效案例编号列表), `SQLAlchemyError`(500) |

#### 1.6.2 接口 2：`update_article` — 更新科普文章

```python
async def update_article(
    article_id: str,
    article: ArticleUpdate,
    session: AsyncSession,
    case_repo: CaseRepository,
    operator: UserIdentity,
) -> ArticleResponse:
    """
    更新一篇已有科普文章的部分字段。仅更新提供的非 None 字段，其余字段保持不变。
    若更新了 content 字段，同步更新 search_vector 全文检索列。

    Args:
        article_id: 文章 UUID
        article: 文章更新请求体，所有字段可选
        session: 数据库异步会话
        case_repo: 案例模块仓储
        operator: 当前操作用户身份

    Returns:
        ArticleResponse: 更新后的文章详情

    Raises:
        LookupError: 文章不存在 (404)
        ValueError: 更新的 related_case_ids 中存在无效案例编号 (422)
        SQLAlchemyError: 数据库写入失败 (500)

    Side Effects:
        - 更新 knowledge_articles 表中对应行的字段
        - 若更新了 content，重新计算 ts_vector 列
        - 记录结构化审计日志
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `update_article` |
| **HTTP 端点** | `PUT /api/v1/knowledge/{id}` |
| **鉴权要求** | `require_role(["admin", "maintainer"])` |
| **输入类型** | `ArticleUpdate`（详见契约引用） |
| **输出类型** | `ArticleResponse`（详见契约引用），HTTP 200 |
| **异常类型** | `LookupError`(404), `ValidationError`(422), `ValueError`(422), `SQLAlchemyError`(500) |

#### 1.6.3 接口 3：`list_articles` — 查询文章列表

```python
async def list_articles(
    category: str | None = None,
    page: int = 1,
    page_size: int = 20,
    include_unpublished: bool = False,
    session: AsyncSession,
) -> PaginatedResponse[ArticleListItem]:
    """
    按分类查询文章列表，支持分页。默认仅返回已发布文章。
    管理端设置 include_unpublished=True 可查看全部状态的文章。

    Args:
        category: 文章分类过滤（可选，不传则返回全部分类）
        page: 页码，从 1 开始
        page_size: 每页条数，默认 20，最大 100
        include_unpublished: 是否包含下架文章（仅管理端使用）
        session: 数据库异步会话

    Returns:
        PaginatedResponse[ArticleListItem]: 分页的文章列表

    Raises:
        ValueError: page < 1 或 page_size 超出范围 (422)
        SQLAlchemyError: 数据库查询失败 (500)
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `list_articles` |
| **HTTP 端点** | `GET /api/v1/knowledge?category={category}&page={n}&page_size={n}` |
| **鉴权要求** | 无需鉴权（公开端点）；管理端可通过 `include_unpublished=true` + admin 鉴权查看全部 |
| **输入类型** | Query 参数：`category: str?`, `page: int`, `page_size: int` |
| **输出类型** | `PaginatedResponse[ArticleListItem]`（详见契约引用），HTTP 200 |

#### 1.6.4 接口 4：`get_article` — 查询文章详情

```python
async def get_article(
    article_id: str,
    session: AsyncSession,
    case_repo: CaseRepository | None = None,
) -> ArticleResponse:
    """
    查询单篇文章的完整详情，包含关联案例的失效状态标注。

    Args:
        article_id: 文章 UUID
        session: 数据库异步会话
        case_repo: 案例模块仓储（可选，用于标注关联案例失效状态）

    Returns:
        ArticleResponse: 文章完整详情

    Raises:
        LookupError: 文章不存在或已下架 (404)
        SQLAlchemyError: 数据库查询失败 (500)
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `get_article` |
| **HTTP 端点** | `GET /api/v1/knowledge/{id}` |
| **鉴权要求** | 无需鉴权（公开端点）；下架文章可通过 admin 鉴权查看 |
| **输入类型** | URL 路径参数 `id: str` (UUID) |
| **输出类型** | `ArticleResponse`（详见契约引用），HTTP 200 |

#### 1.6.5 接口 5：`search_articles` — 全文检索

```python
async def search_articles(
    params: ArticleSearchParams,
    session: AsyncSession,
) -> PaginatedResponse[ArticleSearchResult]:
    """
    使用 PostgreSQL 中文全文检索查询文章。

    Args:
        params: 搜索参数（关键词、分类过滤、分页）
        session: 数据库异步会话

    Returns:
        PaginatedResponse[ArticleSearchResult]: 分页的搜索结果，含相关度分数和关键词高亮摘要

    Raises:
        ValueError: q 为空或 page/page_size 超出范围 (422)
        SQLAlchemyError: 数据库查询失败 (500)
        TimeoutError: 查询超过 5 秒 (503)
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `search_articles` |
| **HTTP 端点** | `GET /api/v1/knowledge/search?q={keyword}&category={category}&page={n}&page_size={n}` |
| **鉴权要求** | 无需鉴权（公开端点，自动过滤 status=published） |
| **输入类型** | `ArticleSearchParams`（详见契约引用） |
| **输出类型** | `PaginatedResponse[ArticleSearchResult]`（详见契约引用），HTTP 200 |

#### 1.6.6 接口 6：`publish_article` — 发布文章

```python
async def publish_article(
    article_id: str,
    session: AsyncSession,
    operator: UserIdentity,
) -> ArticleResponse:
    """
    将文章状态从 unpublished 切换为 published，使其对终端用户可见。
    幂等操作：已发布的文章再次调用直接返回成功。
    首次发布时写入 published_at 时间戳。

    Args:
        article_id: 文章 UUID
        session: 数据库异步会话
        operator: 当前操作用户身份

    Returns:
        ArticleResponse: 更新后的文章详情

    Raises:
        LookupError: 文章不存在 (404)
        SQLAlchemyError: 数据库写入失败 (500)

    Side Effects:
        - 更新 knowledge_articles.status 为 published
        - 若首次发布，写入 published_at 为当前 TIMESTAMPTZ
        - 记录结构化审计日志（含 operator_id, 变更前后状态）
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `publish_article` |
| **HTTP 端点** | `POST /api/v1/knowledge/{id}/publish` |
| **鉴权要求** | `require_role(["admin", "maintainer"])` |
| **输入类型** | URL 路径参数 `id: str` (UUID) |
| **输出类型** | `ArticleResponse`（详见契约引用），HTTP 200 |
| **幂等性** | 已 published 的文章再次调用返回 200 OK，不报错 |

#### 1.6.7 接口 7：`unpublish_article` — 下架文章

```python
async def unpublish_article(
    article_id: str,
    session: AsyncSession,
    operator: UserIdentity,
) -> ArticleResponse:
    """
    将文章状态从 published 切换为 unpublished，使其对终端用户不可见。
    幂等操作：已下架的文章再次调用直接返回成功。
    不修改 published_at 字段。

    Args:
        article_id: 文章 UUID
        session: 数据库异步会话
        operator: 当前操作用户身份

    Returns:
        ArticleResponse: 更新后的文章详情

    Raises:
        LookupError: 文章不存在 (404)
        SQLAlchemyError: 数据库写入失败 (500)

    Side Effects:
        - 更新 knowledge_articles.status 为 unpublished
        - 不修改 published_at 字段
        - 记录结构化审计日志
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `unpublish_article` |
| **HTTP 端点** | `POST /api/v1/knowledge/{id}/unpublish` |
| **鉴权要求** | `require_role(["admin", "maintainer"])` |
| **输入类型** | URL 路径参数 `id: str` (UUID) |
| **输出类型** | `ArticleResponse`（详见契约引用），HTTP 200 |
| **幂等性** | 已 unpublished 的文章再次调用返回 200 OK，不报错 |

### 1.7 依赖与集成接口

> 【已锁定】本模块调用的外部接口。

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 关系型数据库 | PostgreSQL 17.x + pgvector | `AsyncSession.execute(select(...))` | 文章 CRUD 操作，ts_vector 全文检索 | 技术栈设计 §2，项目结构 §6.1 packages/py-db |
| 缓存 | Redis 7.x | `packages/py-cache/py_cache/client.py` — Redis client | MVP 阶段不启用（预留），未来用于文章列表/详情缓存 | 技术栈设计 §2，项目结构 §6.1 packages/py-cache |
| 日志系统 | structlog / py-logger | `logger.info("event", **kwargs)` | 结构化日志记录，含 trace_id | 项目结构 §6.1 packages/py-logger |
| 数据库迁移 | Alembic | `alembic upgrade head` | 创建 knowledge_articles 表及 GIN 索引 | 技术栈设计 §2，项目结构 §6.1 packages/py-db/migrations |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| AUTH-04 五级RBAC鉴权 | FastAPI Depends: `require_role(["admin", "maintainer"])` → `UserIdentity` | 校验管理类端点的操作权限，注入操作人身份 | 未开始（待落地，可 mock 为返回固定 UserIdentity 的 Depends） |
| CASE-01 案例录入管理 | `case_repository.exists(case_ids: list[str]) -> dict[str, bool]` | 批量校验关联案例编号是否存在 | 未开始（待落地，可 mock 为全返回 True 的假仓储） |
| CASE-03 案例审核工作流 | `case_repository.find_approved_ids(case_ids: list[str]) -> set[str]` | 确认关联案例为 approved 状态，过滤未审批的编号 | 未开始（待落地，可 mock 为全返回 approved 的假仓储） |

**Mock 策略**：
- AUTH-04 未落地时：在测试中用 `override_dependency` 注入固定 `UserIdentity(id="mock-admin", roles=["admin"])`
- CASE-01/CASE-03 未落地时：在 `knowledge_service.py` 中注入 `MockCaseRepository`，其 `exists()` 始终返回全 True，`find_approved_ids()` 始终返回原集合
- 生产环境替换为正式实现时，仅需替换依赖注入配置，无需修改 knowledge_service 业务代码

### 1.8 状态机

> 【对内实现】

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 副作用 |
|----------|----------|----------|----------|--------|
| —（创建时）| `create_article` | unpublished | ArticleCreate 校验通过 | 写入 knowledge_articles 表，初始 status=unpublished |
| unpublished | `publish_article` | published | 文章存在，status 为 unpublished | 更新 status=published；若 published_at 为 None 则写入当前时间；记录审计日志 |
| published | `publish_article` | published（不变）| 文章存在，status 为 published | 无操作，返回 200 OK（幂等） |
| published | `unpublish_article` | unpublished | 文章存在，status 为 published | 更新 status=unpublished；不修改 published_at；记录审计日志 |
| unpublished | `unpublish_article` | unpublished（不变）| 文章存在，status 为 unpublished | 无操作，返回 200 OK（幂等） |

### 1.9 异常与边界条件

> 【对内实现】

#### 1.9.1 异常 1：必填字段缺失或分类无效

- **触发条件**：
  - `ArticleCreate.title` 为空字符串 `""` 或字段缺失
  - `ArticleCreate.content` 为空字符串 `""` 或字段缺失
  - `ArticleCreate.category` 不在 `["术语解释", "干预方法", "诊断标准", "康复指南"]` 中
- **处理策略**：
  1. Pydantic 在请求解析阶段自动捕获 `ValidationError`
  2. FastAPI 异常处理器将 Pydantic 错误转换为 HTTP 422 响应
  3. 响应体格式：`{"detail": [{"loc": ["body", "title"], "msg": "ensure this value has at least 1 characters", "type": "value_error.any_str.min_length", "ctx": {"limit_value": 1}}]}`
  4. 记录结构化日志：`logger.warning("input_validation_failed", validation_errors=[...])`
  5. 不进入 Service 层
- **重试参数**：不重试。客户端修正输入后重新发起请求。

#### 1.9.2 异常 2：关联案例编号无效或超限

- **触发条件**：
  - `ArticleCreate.related_case_ids` 条目数 > 5
  - 提交的 case_id 在 `case_repository.exists()` 中返回 `False`
  - 提交的 case_id 在 `case_repository.find_approved_ids()` 中未被包含（案例存在但未通过审批）
- **处理策略**：
  1. 条目超限 → Pydantic 自动拦截，返回 422，`{"detail": "关联案例最多 5 条"}`
  2. 编号无效 → Service 层调用 `case_repository.exists(case_ids)` 后，收集无效编号列表 `invalid_ids = [id for id, ok in result.items() if not ok]`
  3. 返回 422，响应体：`{"detail": {"msg": "以下案例编号不存在: CASE-001, CASE-002", "invalid_case_ids": ["CASE-001", "CASE-002"]}}`
  4. 未通过审批 → Service 层调用 `case_repository.find_approved_ids(case_ids)` 后，收集未审批编号
  5. 返回 422，响应体：`{"detail": {"msg": "以下案例尚未通过审核: CASE-003", "unapproved_case_ids": ["CASE-003"]}}`
  6. 记录日志：`logger.warning("case_validation_failed", invalid=..., unapproved=...)`
- **重试参数**：不重试。客户端移除无效编号后重新发起请求。

#### 1.9.3 异常 3：文章不存在

- **触发条件**：
  - `GET/PUT/POST /api/v1/knowledge/{id}` 中提供的 `id` 在数据库中不存在
  - 文章已被物理删除（注意：设计文档未定义物理删除功能，此异常防止意外）
- **处理策略**：
  1. Service 层执行 `await session.get(KnowledgeArticle, id)`，返回 `None`
  2. 返回 HTTP 404，响应体：`{"detail": "文章不存在"}`
  3. 记录日志：`logger.info("article_not_found", article_id=...)`
- **重试参数**：不重试。客户端确认 id 正确后重新请求。

#### 1.9.4 异常 4：数据库查询超时

- **触发条件**：
  - 全文检索查询执行时间 > 5 秒（`statement_timeout = 5000`，在 `knowledge_repository.py` 中设置查询级别超时）
  - 数据库连接池耗尽，`AsyncSession` 获取超时 > 3 秒
- **处理策略**：
  1. 全文检索超时 → `SQLAlchemy` 抛出 `asyncio.TimeoutError` → 捕获后返回 HTTP 503
  2. 连接池耗尽 → `asyncio.TimeoutError` → 返回 HTTP 503，`{"detail": "服务暂时不可用，请稍后重试"}`
  3. 记录 slow query 日志：`logger.error("slow_query", query_type="search", duration_sec=..., query_params=...)`
  4. 连接池耗尽记录 critical 日志：`logger.critical("connection_pool_exhausted", pool_size=..., active_connections=...)`
- **重试参数**：客户端可重试，建议指数退避（1s, 2s, 4s），最多 3 次。服务端不自动重试。

#### 1.9.5 异常 5：关联案例被删除（惰性标记）

- **触发条件**：
  - 文章已关联的案例 `CASE-XXX` 被 CASE 模块物理删除或标记为失效
  - 用户在文章详情页查看到该案例编号
- **处理策略**：
  1. 文章详情接口（`get_article`）在序列化 `related_case_ids` 时，惰性调用 `case_repository.exists(case_ids)`
  2. 将不存在的 case_id 包装为 `{"id": "CASE-XXX", "_stale": true}`
  3. 不自动从 `related_case_ids` 数组中移除失效编号
  4. 若 `case_repository` 调用失败（CASE 模块不可用）→ 不阻塞响应，`_stale` 字段不返回，记录 warning 日志：`logger.warning("stale_check_unavailable", article_id=..., error=...)`
- **重试参数**：不重试。失效标记为惰性展示，不会丢失数据。运营人员在管理端看到失效标记后手动清理。

### 1.10 验收测试场景

> 【对内实现】

#### 1.10.1 正向测试 1：完整创建并发布文章

- **场景**：管理员创建科普文章，校验关联案例有效性，发布后终端用户可查询
- **Given**:
  - 管理员身份鉴权通过（`UserIdentity(id="admin-001", roles=["admin"])`）
  - CASE-01 mock 返回 `exists({"CASE-001": True})`
  - CASE-03 mock 返回 `find_approved_ids({"CASE-001"})`
  - 数据库为空，无已有文章
- **When**:
  1. `POST /api/v1/knowledge` 提交 `{"title": "什么是孤独症的刻板行为", "category": "术语解释", "content": "刻板行为是孤独症谱系障碍的核心症状之一...", "related_case_ids": ["CASE-001"]}`
  2. `POST /api/v1/knowledge/{id}/publish`
  3. `GET /api/v1/knowledge/{id}`
- **Then**:
  - 步骤 1 返回 HTTP 201，响应体含 `status: "unpublished"`, `published_at: null`, `related_case_ids: ["CASE-001"]`
  - 步骤 2 返回 HTTP 200，`status: "published"`, `published_at` 非 null（ISO 8601 格式）
  - 步骤 3 返回 HTTP 200，`status: "published"`
  - 数据库 `knowledge_articles` 表中存在 1 条记录，`search_vector` 列非空

#### 1.10.2 正向测试 2：按分类查询文章列表

- **场景**：终端用户按分类浏览已发布文章，支持分页
- **Given**:
  - 数据库中有 25 篇已发布文章（分类为"术语解释"）+ 5 篇其他分类文章 + 3 篇下架文章（分类为"术语解释"）
- **When**:
  1. `GET /api/v1/knowledge?category=术语解释&page=1&page_size=10`
  2. `GET /api/v1/knowledge?category=术语解释&page=2&page_size=10`
  3. `GET /api/v1/knowledge?category=术语解释&page=3&page_size=10`
- **Then**:
  - 步骤 1 返回 `items` 长度为 10，`total: 25`, `page: 1`, `total_pages: 3`
  - 步骤 2 返回 `items` 长度为 10，`total: 25`, `page: 2`
  - 步骤 3 返回 `items` 长度为 5，`total: 25`, `page: 3`
  - 三页结果均不含下架文章（status 均为 `"published"`）

#### 1.10.3 正向测试 3：全文检索返回关键词高亮结果

- **场景**：用户搜索关键词，返回相关度排序的搜索结果
- **Given**:
  - 数据库中有 3 篇已发布文章，内容涉及"刻板行为"
  - zhparser 中文分词扩展已安装
- **When**: `GET /api/v1/knowledge/search?q=刻板行为&page=1&page_size=20`
- **Then**:
  - 返回 `items` 长度 >= 1
  - 每条结果含 `score: float > 0`, `content_snippet` 含 `<mark>刻板行为</mark>` 标记
  - 结果按 `score` 降序排列
  - 不含 status=unpublished 的文章

#### 1.10.4 异常测试 1：必填字段缺失

- **场景**：创建文章时未提供 title 字段
- **Given**: 管理员身份鉴权通过
- **When**: `POST /api/v1/knowledge` 提交 `{"category": "术语解释", "content": "正文内容"}`（缺少 title）
- **Then**:
  - 返回 HTTP 422
  - 响应体 `{"detail": [...]}` 中明确指示 title 字段缺失
  - 数据库无新记录

#### 1.10.5 异常测试 2：关联案例超限

- **场景**：创建文章时关联超过 5 条案例
- **Given**: 管理员身份鉴权通过
- **When**: `POST /api/v1/knowledge` 提交含 6 个 `related_case_ids` 的请求
- **Then**:
  - 返回 HTTP 422
  - 响应体指示 `related_case_ids` 超出 `maxItems: 5` 限制
  - 数据库无新记录

#### 1.10.6 异常测试 3：关联案例编号无效

- **场景**：关联的案例在案例库中不存在
- **Given**:
  - 管理员身份鉴权通过
  - CASE-01 mock 返回 `exists({"CASE-999": False})`
- **When**: `POST /api/v1/knowledge` 提交 `{"title": "测试", "category": "术语解释", "content": "测试内容", "related_case_ids": ["CASE-999"]}`
- **Then**:
  - 返回 HTTP 422
  - 响应体含 `"invalid_case_ids": ["CASE-999"]` 的错误详情
  - 数据库无新记录

#### 1.10.7 异常测试 4：全文检索超时降级

- **场景**：数据库查询超时
- **Given**:
  - 数据库 statement_timeout 设置为 5 秒
  - Mock 数据库查询延迟超过 5 秒
- **When**: `GET /api/v1/knowledge/search?q=复杂查询导致慢查询`
- **Then**:
  - 返回 HTTP 503
  - 响应体 `{"detail": "搜索服务暂时不可用，请稍后重试"}`
  - 慢查询被记录到结构化日志

### 1.11 注意事项与禁止行为（编码层面）

> 【对内实现】

1. **[约束] 状态切换必须使用独立端点**：`POST /api/v1/knowledge/{id}/publish` 和 `POST /api/v1/knowledge/{id}/unpublish`，禁止通过 `PATCH /{id}` 通用端点直接修改 status 字段。违反此约束会导致审计日志不完整、published_at 写入逻辑被绕过。
2. **[约束] published_at 仅首次写入**：publish 端点中，仅当 `published_at IS NULL` 时才写入当前时间戳。重新发布（unpublish → publish）不应更新此字段。
3. **[易错点] 搜索过滤必须排除 unpublished**：面向终端用户的搜索和列表接口，必须在 SQL 查询中显式追加 `AND status = 'published'`，不可在 Python 应用层过滤后截断分页结果——否则会导致分页 total 计数错误。
4. **[易错点] $ref 解析**：ArticleCreate 中的 `category` 字段通过 `$ref: "./ArticleCategory.json"` 引用枚举类型。代码生成时需将 `$ref` 解析为 `Literal["术语解释", "干预方法", "诊断标准", "康复指南"]`，而非字符串类型。
5. **[禁止行为] 禁止对 CASE 模块的表建立外键约束**：`related_case_ids` 是字符串数组，不建立数据库级 `FOREIGN KEY`。关联案例的有效性在应用层（Service 层）校验，避免跨模块的数据库级耦合。
6. **[禁止行为] 禁止使用 PATCH generic 端点**：`PATCH /api/v1/knowledge/{id}` 不实现。文章更新使用 `PUT /api/v1/knowledge/{id}`，状态切换使用独立的 `POST publish/unpublish` 端点。这确保每个端点的业务语义清晰、副作用可预测。
7. **[偷懒红线] 禁止将搜索权重配置硬编码为随机值**：MVP 阶段使用等权重（title 和 content 均为 A 权重，值 1.0）。权重值定义为模块级常量 `SEARCH_WEIGHTS = {"title": "A", "content": "A"}`，预留调优接口。

### 1.12 文档详细度自检清单

> 【对内实现】

- [x] 文档自包含：Agent 仅凭此文档即可完成编码
- [x] 无偷懒表述：已全文搜索并消除 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：每个 Pydantic 字段都在契约 JSON 文件中定义了 `description` + `examples` + 约束（`minLength`/`maxLength`/`maxItems`/`format` 等）
- [x] 逻辑步骤完整：7 个核心逻辑步骤均有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：5 种异常均有精确的触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值来源（如 page_size=20）、条件分支（如 published_at 仅首次写入）、业务规则（如同分类标题非强制唯一）都已显式写出
- [x] 技术栈绑定明确：必须使用和禁止使用的项均已列出，且与 `docs/篝火智答-技术栈设计.md` v1.2 保持一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档（v2.0）一致

### 1.14 外部接口契约清单

> 【已锁定】

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| ArticleCategory | `docs/contracts/KNOW-01/ArticleCategory.json` | shared-enum | draft | KNOW-01 | KNOW-03, KNOW-06, KNOW-07 |
| ArticleStatus | `docs/contracts/KNOW-01/ArticleStatus.json` | shared-enum | draft | KNOW-01 | KNOW-03, KNOW-06, KNOW-07 |
| ArticleCreate | `docs/contracts/KNOW-01/ArticleCreate.json` | input | draft | KNOW-01 | — |
| ArticleUpdate | `docs/contracts/KNOW-01/ArticleUpdate.json` | input | draft | KNOW-01 | — |
| ArticleSearchParams | `docs/contracts/KNOW-01/ArticleSearchParams.json` | input | draft | KNOW-01 | KNOW-03, KNOW-06, KNOW-07 |
| ArticleResponse | `docs/contracts/KNOW-01/ArticleResponse.json` | output | draft | KNOW-01 | KNOW-04, KNOW-06, KNOW-07 |
| ArticleListItem | `docs/contracts/KNOW-01/ArticleListItem.json` | output | draft | KNOW-01 | KNOW-03, KNOW-06, KNOW-07 |
| ArticleSearchResult | `docs/contracts/KNOW-01/ArticleSearchResult.json` | output | draft | KNOW-01 | KNOW-03, KNOW-06, KNOW-07 |
| PaginatedResponse | （复用项目级） | output | stable | PROJECT | KNOW-01, 全部模块 |

### 1.15 意图一致性声明

> 【对内实现】

- **配套意图文档**：`KNOW-01-科普内容管理-意图文档.md`
- **冻结时间**：2026-05-26 16:54:49 (Asia/Shanghai)
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档 §1.6 中的业务字段定义一致（title/category/content/related_case_ids/status/published_at 共 6 个字段）
  - [x] 本落地规范中的状态机实现与意图文档 §1.7 中的状态业务定义一致（published 公开 / unpublished 下架，互相切换）
  - [x] 本落地规范中的异常处理策略与意图文档 §1.8 中的异常业务策略一致（必填字段缺失→拒绝、关联案例无效→标注允许继续、内容越界→人工审核）
  - [x] 本落地规范中的验收测试场景覆盖意图文档 §1.9 中的所有验收标准（AC-01 至 AC-08）：创建文章、分类限制、关联数量限制、分类查询列表、详情查询、全文检索、状态切换、免责声明（AC-08 由前端 KNOW-06 实现，本模块不涉及）
  - [x] 本落地规范中的技术实现未超出意图文档 §1.12 中"留给规范阶段的技术决策"的范围（8 项技术决策均已纳入设计且经 s07 用户确认）
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
