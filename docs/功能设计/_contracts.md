# 模块接口契约索引

## DEPLOY-05 - 环境配置管理
- **输入**: 环境变量 / .env 文件（操作系统级，无类型化入参）
- **输出**: `AppSettings {DATABASE_URL, REDIS_URL, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, JWT_SECRET_KEY, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS, RATE_LIMIT_USER_PER_MINUTE, RATE_LIMIT_IP_PER_MINUTE, ENVIRONMENT}`
- **状态机**: 无
- **模块依赖**: 无（L1 基础层无上游业务依赖）
- **外部依赖**: pydantic-settings >= 2.0（环境变量加载与校验），pydantic >= 2.0（类型校验与 SecretStr 脱敏），Python 3.12+ 运行时
- **技术栈**: pydantic-settings>=2.0, pydantic>=2.0, Python 3.12+
- **契约文件**: `docs/contracts/DEPLOY-05/AppSettings.json`, `docs/contracts/DEPLOY-05/ConfigError.json`, `docs/contracts/DEPLOY-05/MissingRequiredFieldError.json`, `docs/contracts/DEPLOY-05/ConfigFormatError.json`, `docs/contracts/DEPLOY-05/ConfigWarning.json`
- **更新时间**: 2026-05-26 17:22:10
