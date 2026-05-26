# SEC-01 待确认事项

> 生成时间：2026-05-26
> 来源：adversarial-implementation-executor Phase 2 实现

## 1. SecurityConfig 契约外补充字段

### 1.1 JWT_KEY_VERSION

- **契约现状**：`SecurityConfig.json` 契约未包含 `JWT_KEY_VERSION` 字段。
- **实现需要**：`create_access_token()` 需要在 JWT header 中嵌入 `kid` 字段，值来自 `JWT_KEY_VERSION`。
- **当前处理**：已在 `SecurityConfig` 中添加 `JWT_KEY_VERSION: str = Field(default="v1")`。
- **影响范围**：`packages/py-auth/py_auth/jwt_utils.py` 的 `create_access_token()` 和 `verify_token()`。
- **建议**：将 `JWT_KEY_VERSION` 加入 `SecurityConfig.json` 契约。

### 1.2 JWT_PREVIOUS_KEY_VERSION

- **契约现状**：`SecurityConfig.json` 契约未包含 `JWT_PREVIOUS_KEY_VERSION` 字段。
- **实现需要**：`verify_token()` 需要比对 token header 中的 `kid` 与上一个密钥版本标识以支持共栖期校验。
- **当前处理**：已在 `SecurityConfig` 中添加 `JWT_PREVIOUS_KEY_VERSION: str = Field(default="")`。
- **影响范围**：`packages/py-auth/py_auth/jwt_utils.py` 的 `verify_token()`。
- **建议**：将 `JWT_PREVIOUS_KEY_VERSION` 加入 `SecurityConfig.json` 契约。

## 2. REDIS_URL 配置来源

- **契约现状**：`SecurityConfig.json` 契约未包含 `REDIS_URL` 字段。
- **实现需要**：`check_rate_limit()` 需要 Redis 连接 URL。
- **当前处理**：`rate_limit.py` 通过 `py_config.get_settings()` 获取 `AppSettings.REDIS_URL`（DEPLOY-05 模块提供的全局配置），而非从 `SecurityConfig` 读取。这避免了将基础设施级配置混入安全配置。
- **影响范围**：`packages/py-cache/py_cache/rate_limit.py`。
- **建议**：确认 `REDIS_URL` 应归属 `AppSettings`（通用基础设施配置）还是 `SecurityConfig`（安全配置）。

## 3. env_prefix 差异

- **现状**：`AppSettings`（DEPLOY-05）从环境变量直接读取（无前缀），而 `SecurityConfig`（SEC-01）使用 `env_prefix="SECURITY_"`。
- **影响**：同一配置项（如 `JWT_SECRET_KEY`）需要在 `.env` 中同时设置 `JWT_SECRET_KEY`（供 AppSettings）和 `SECURITY_JWT_SECRET_KEY`（供 SecurityConfig）。
- **建议**：统一环境变量命名策略，避免配置冗余和潜在不一致。

## 4. JWT_ALGORITHM 约束收紧

- **契约现状**：`SecurityConfig.json` 契约限定 `JWT_ALGORITHM` 为 `enum: ["HS256"]`。
- **AppSettings 现状**：`AppSettings` 允许 `Literal["HS256", "HS384", "HS512"]`。
- **实现处理**：`SecurityConfig` 使用 `Literal["HS256"]` 严格匹配契约。
- **建议**：确认是否需要统一两个配置模型的 JWT 算法约束。
