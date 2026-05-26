# 模块接口契约索引

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
