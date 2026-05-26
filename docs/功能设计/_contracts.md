# 模块接口契约索引

## DEPLOY-04 - 数据库迁移
- **输入**: `DATABASE_URL (str, 环境变量)`, `MigrationTarget (str, "head"/revision_hash/"-N")`
- **输出**: `MigrationScript (interface, 含 upgrade/downgrade)`
- **状态机**: pending → migrating → ready (线性三态, 依赖 alembic_version 表)
- **模块依赖**: DEPLOY-01 (容器编排，运行时时序依赖), DEPLOY-03 (CI/CD，验证调用方), DEPLOY-05 (环境配置，DATABASE_URL 来源)
- **外部依赖**: PostgreSQL 17.x + pgvector 0.7+ (psycopg2), Alembic >= 1.13.0, SQLAlchemy >= 2.0 (target_metadata)
- **技术栈**: psycopg2 >= 2.9, asyncpg >= 0.29 (应用运行，不用于迁移)
- **契约文件**: `docs/contracts/DEPLOY-04/DATABASE_URL.json`, `docs/contracts/DEPLOY-04/MigrationState.json`, `docs/contracts/DEPLOY-04/MigrationErrorCode.json`, `docs/contracts/DEPLOY-04/MigrationScript.json`, `docs/contracts/DEPLOY-04/MigrationTarget.json`
- **更新时间**: `2026-05-26 17:20:00`
