# 1 功能点：DEPLOY-04 数据库迁移 — 落地规范

> **文档生成时间**：`2026-05-26 17:20:00`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 17:20:00 | AI Assistant | 初始版本，基于意图文档 v2.0、设计文档 v1.0、契约协调报告生成 |
>
> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `DEPLOY-04-数据库迁移-设计文档.md`。

---

## 【已锁定】对外接口章节

### 1.3 输入定义（精确类型 / 或契约引用）

**DATABASE_URL**
- 【契约引用】`docs/contracts/DEPLOY-04/DATABASE_URL.json`
- 本模块作为该契约的定义方
- 消费方：DEPLOY-01（容器编排）、DEPLOY-03（CI/CD 流水线）、DEPLOY-05（环境配置）

**MigrationTarget**
- 【契约引用】`docs/contracts/DEPLOY-04/MigrationTarget.json`
- 本模块作为该契约的定义方
- 消费方：DEPLOY-01（容器编排）

### 1.4 输出定义（精确类型 / 或契约引用）

**MigrationScript**
- 【契约引用】`docs/contracts/DEPLOY-04/MigrationScript.json`
- 本模块作为该契约的定义方
- 消费方：DEPLOY-01（容器编排）、DEPLOY-03（CI/CD 流水线）

**MigrationErrorCode**
- 【契约引用】`docs/contracts/DEPLOY-04/MigrationErrorCode.json`
- 本模块作为该契约的定义方
- 消费方：DEPLOY-01（容器编排）、DEPLOY-03（CI/CD 流水线）

**MigrationState**
- 【契约引用】`docs/contracts/DEPLOY-04/MigrationState.json`
- 本模块作为该契约的定义方
- 消费方：DEPLOY-01（容器编排）

### 1.6 接口契约（对外暴露的公共接口）

#### 1.6.1 接口 1：migrate_up

```python
def migrate_up(
    target: str = "head",
    database_url: str | None = None,
) -> int:
    """
    执行数据库正向迁移，将数据库版本从当前状态升级到目标版本。

    Args:
        target: 目标迁移版本标识，默认 "head"（最新版本）。
                可指定具体 revision hash 用于精确版本控制。
        database_url: 目标数据库连接串。若为 None，从环境变量 DATABASE_URL 读取。
                      格式: postgresql+asyncpg://user:pass@host:5432/dbname

    Returns:
        int: 退出码。0 = 无待执行迁移或全部执行成功；非 0 = 迁移失败。

    Raises:
        MigrationExecutionError: 任一迁移脚本的 upgrade() 执行失败。
        MigrationConnectionError: 数据库连接不可用。
        MigrationScriptNotFoundError: 指定 target revision 不存在。

    Side Effects:
        - 对目标数据库执行 DDL 操作（CREATE TABLE、ALTER TABLE、CREATE INDEX 等）
        - 更新 alembic_version 表记录当前版本号
        - 将迁移执行日志以结构化 JSON 格式写入 stdout

    Idempotency:
        重复调用 upgrade head 幂等安全。Alembic 通过 alembic_version 表
        追踪已执行版本，自动跳过已完成的迁移脚本。

    Thread Safety:
        本函数通过 alembic_version 表的行级锁和唯一约束防止并发执行。
        单副本部署下线程安全；多副本场景需额外引入 pg_advisory_lock。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `migrate_up` —— 语义化，描述"正向升级迁移"的业务动作 |
| **输入类型** | `target: str`（目标版本标识）、`database_url: str | None`（连接串） |
| **输出类型** | `int`（退出码，0=成功） |
| **异常类型** | `MigrationExecutionError`、`MigrationConnectionError`、`MigrationScriptNotFoundError` |
| **副作用** | DDL 操作持久化到数据库；alembic_version 表更新；结构化日志写入 stdout |
| **幂等性** | 基于 alembic_version 表的幂等，重复调用自动跳过已执行脚本 |
| **并发安全** | 单副本部署下通过 alembic_version 表行级锁保证安全 |

#### 1.6.2 接口 2：migrate_down

```python
def migrate_down(
    target: str = "-1",
    database_url: str | None = None,
) -> int:
    """
    执行数据库回滚迁移，将数据库版本回退到指定历史版本。

    Args:
        target: 目标回滚版本标识。默认 "-1"（回滚一个版本）。
                可指定具体 revision hash 用于精确回滚。
                接受 Alembic 相对标记：-1（上一个）、-2（上两个）。
        database_url: 目标数据库连接串。若为 None，从环境变量 DATABASE_URL 读取。

    Returns:
        int: 退出码。0 = 回滚成功；非 0 = 回滚失败。

    Raises:
        MigrationRollbackError: 回滚操作失败，原因可能是 downgrade() 不存在或执行错误。
        MigrationConnectionError: 数据库连接不可用。
        MigrationScriptNotFoundError: 指定 target revision 不存在。

    Side Effects:
        - 对目标数据库执行 DDL 逆向操作（DROP TABLE、DROP COLUMN、DROP INDEX 等）
        - 更新 alembic_version 表记录当前版本号
        - 将回滚执行日志以结构化 JSON 格式写入 stdout

    Idempotency:
        回滚到已处于该版本号的数据库为幂等操作（Alembic 检测到当前版本等于目标版本时跳过）。

    Thread Safety:
        同 migrate_up()，单副本部署下线程安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `migrate_down` —— 语义化，描述"回滚降级迁移"的业务动作 |
| **输入类型** | `target: str`（目标版本）、`database_url: str | None`（连接串） |
| **输出类型** | `int`（退出码，0=成功） |
| **异常类型** | `MigrationRollbackError`、`MigrationConnectionError`、`MigrationScriptNotFoundError` |
| **副作用** | DDL 逆向操作持久化到数据库；alembic_version 表更新；结构化日志写入 stdout |

#### 1.6.3 接口 3：generate_migration

```python
def generate_migration(
    message: str,
    autogenerate: bool = True,
) -> str:
    """
    自动生成新的迁移脚本。

    Args:
        message: 迁移脚本的语义化描述信息，将作为文件名的一部分。
                 例如 "add_user_nickname"。
        autogenerate: 是否启用自动检测模式。True 时比对 target_metadata 与数据库
                      实际结构差异自动生成迁移内容；False 时生成空模板供手工填写。

    Returns:
        str: 新生成的迁移脚本文件路径。格式：
             packages/py-db/migrations/versions/YYYYMMDD_HHMMSS_message.py

    Raises:
        MigrationGenerationError: 迁移脚本生成失败（如项目结构不完整、Alembic 配置错误）。

    Side Effects:
        - 在 packages/py-db/migrations/versions/ 目录下创建新的 .py 文件
        - 生成的文件包含 upgrade() 和 downgrade() 两个函数框架

    Note:
        autogenerate=True 时：生成的脚本必须由开发人员审阅后方可提交。特别注意
        列重命名检测——Alembic autogenerate 无法检测列重命名，会生成
        drop_column + add_column 组合，这将导致数据丢失。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `generate_migration` —— 语义化，描述"生成迁移脚本"的业务动作 |
| **输入类型** | `message: str`（语义描述）、`autogenerate: bool`（是否自动检测） |
| **输出类型** | `str`（新生成的迁移脚本文件路径） |
| **异常类型** | `MigrationGenerationError` |
| **副作用** | 创建新的 Python 文件；不修改数据库 |

#### 1.6.4 接口 4：verify_migration

```python
def verify_migration(
    database_url: str,
) -> tuple[int, str]:
    """
    在目标数据库上执行全面迁移验证。

    执行以下检查：
    1. alembic check：检测数据库状态与迁移脚本是否一致（Alembic 1.9+ 内置）
    2. alembic upgrade head：在空数据库上执行全部迁移脚本测试可执行性
    3. 检查每份迁移脚本是否同时包含 upgrade() 和 downgrade() 函数

    此接口主要用于 CI 流水线中的自动化验证。

    Args:
        database_url: 目标空数据库连接串。此数据库必须为空数据库。

    Returns:
        tuple[int, str]: (退出码, 验证结果摘要)。
                         退出码 0 = 全部验证通过；
                         退出码 1 = 迁移脚本不可执行；
                         退出码 2 = 缺少 downgrade() 函数；
                         退出码 3 = alembic check 检测到未记录的 Schema 变更。

    Raises:
        MigrationConnectionError: 数据库连接失败。
        MigrationVerificationError: 验证过程中发生非预期错误。

    Side Effects:
        - 对空数据库执行全部 DDL 操作后不清理（CI 容器用后销毁）
        - 将验证结果以结构化 JSON 格式写入 stdout

    Thread Safety:
        线程安全。验证在独立数据库连接上执行，不影响生产环境。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `verify_migration` —— 语义化，描述"验证迁移脚本可执行性"的业务动作 |
| **输入类型** | `database_url: str`（空数据库连接串） |
| **输出类型** | `tuple[int, str]`（退出码 + 验证摘要） |
| **异常类型** | `MigrationConnectionError`、`MigrationVerificationError` |
| **副作用** | 对空数据库执行全部 DDL；不清理（依赖 CI 容器销毁）；结构化日志写入 stdout |

### 1.7 依赖与集成接口（本模块调用的外部接口）

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 关系型数据库 | PostgreSQL 17.x + pgvector 0.7+ | `psycopg2.connect(dsn)` / `engine_from_config()` | Alembic 迁移脚本通过 psycopg2 同步驱动执行 DDL 操作 | `docs/篝火智答-项目结构.md` §3、§6.3 |
| 迁移框架 | Alembic | `alembic.command.upgrade()`、`alembic.command.downgrade()`、`alembic.command.revision()`、`alembic.command.check()` | 迁移脚本执行、生成、验证的核心引擎 | `docs/篝火智答-技术栈设计.md` §2 |
| ORM 元数据 | SQLAlchemy 2.x | `Base.metadata`（`packages/py-db/models/` 下的声明式映射） | autogenerate 时比对 ORM 模型定义与实际数据库结构差异 | `docs/篝火智答-项目结构.md` §6.3 `packages/py-db/models/` |
| 环境变量 | 操作系统环境 | `os.environ["DATABASE_URL"]` | 获取目标数据库连接串 | `docs/篝火智答-技术栈设计.md` §6.2 |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| DEPLOY-01（容器编排） | `docker-compose.yml` 中的 `depends_on` + `healthcheck` 配置；`migrate.sh` 脚本的调用时序 | 确保 PostgreSQL 容器就绪后执行迁移；迁移成功后启动应用容器；迁移失败时阻断应用容器启动 | ⏭️ 待落地（在 DEPLOY-01 的 docker-compose.yml 和 migrate.sh 中引用） |
| DEPLOY-03（CI/CD 流水线） | `.github/workflows/` 中 `services.postgres` 临时容器创建；`alembic upgrade head` 调用 | CI 流水线中在空数据库上执行全部迁移脚本，验证可执行性 | ⏭️ 待落地（在 DEPLOY-03 的 GitHub Actions workflow 中引用） |
| DEPLOY-05（环境配置） | 环境变量 `DATABASE_URL` | 提供目标数据库的连接串 | ⏭️ 待落地（在 DEPLOY-05 的 .env.example 和 pydantic-settings 中定义） |

---

## 【对内实现】内部实现章节

### 1.1 技术栈绑定

- **必须使用**：
  - Alembic >= 1.13.0（`alembic check` 命令在 1.9+ 可用，1.13+ 为当前稳定版）
  - SQLAlchemy >= 2.0（声明式映射，ORM 模型通过 `Base.metadata` 暴露元数据）
  - psycopg2 >= 2.9（同步 PostgreSQL 驱动，Alembic DDL 操作依赖同步连接）
  - asyncpg >= 0.29（异步 PostgreSQL 驱动，应用运行时使用；迁移脚本本身与之无关）
  - Python >= 3.12（项目统一版本约束）
  - 迁移脚本必须放置在 `packages/py-db/migrations/versions/` 目录下
  - 每份迁移脚本必须同时包含 `upgrade()` 和 `downgrade()` 两个函数

- **禁止使用**：
  - 禁止在迁移脚本中直接使用 `asyncpg` 或任何异步驱动（Alembic DDL 操作必须通过同步连接）
  - 禁止在迁移脚本中硬编码数据库连接串（必须从环境变量或 `alembic.ini` 配置读取）
  - 禁止在迁移脚本中执行业务数据的 DML 操作（INSERT/UPDATE/DELETE），除非属于数据迁移脚本
  - 禁止使用 `alembic.op.execute()` 拼接用户输入的 SQL 字符串（必须使用参数化方式）

### 1.2 文件归属

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| Alembic 配置 | `packages/py-db/alembic.ini` | Alembic 主配置文件，包含数据库连接配置、脚本目录路径、日志配置 |
| 环境配置 | `packages/py-db/migrations/env.py` | Alembic 运行时环境，配置 target_metadata、连接引擎、事务模式 |
| 迁移脚本目录 | `packages/py-db/migrations/versions/` | 存放全部迁移脚本文件，命名格式 `YYYYMMDD_HHMMSS_description.py` |
| 脚本模板 | `packages/py-db/migrations/script.py.mako` | Alembic 生成迁移脚本使用的 Mako 模板 |
| 迁移执行脚本 | `scripts/migrate.sh` | 部署时自动调用 alembic upgrade head 的 Shell 脚本 |
| 迁移接口模块 | `packages/py-db/py_db/migration.py` | 封装 migrate_up()、migrate_down()、generate_migration()、verify_migration() |
| 测试文件 | `packages/py-db/tests/test_migration.py` | migrate_up()、migrate_down()、verify_migration() 的单元/集成测试 |

### 1.5 核心逻辑步骤

1. **步骤 1：解析数据库连接**
   - **操作对象**：目标数据库连接串
   - **具体操作**：从环境变量 `DATABASE_URL` 读取连接串；若为 None 则回退到 `alembic.ini` 中 `[alembic]` 节的 `sqlalchemy.url` 配置项
   - **输入来源**：`os.environ["DATABASE_URL"]` 或 `alembic.ini`
   - **输出去向**：解析后的连接串注入 Alembic 配置上下文 `config.set_main_option("sqlalchemy.url", database_url)`
   - **失败行为**：DATABASE_URL 不存在且 alembic.ini 中无配置 → 抛出 `MigrationConnectionError("DATABASE_URL not configured")`，退出码 3，不进入后续步骤

2. **步骤 2：验证数据库连接可用**
   - **操作对象**：步骤 1 解析的目标数据库
   - **具体操作**：通过 `psycopg2.connect(database_url)` 创建测试连接，执行 `SELECT 1` 并立即关闭；连接超时设为 5 秒
   - **输入来源**：步骤 1 的 database_url
   - **输出去向**：连接验证通过 → 进入步骤 3；连接验证失败 → 进入重试逻辑
   - **失败行为**：连接失败 → 重试最多 3 次，间隔 5 秒（固定间隔）。3 次失败后抛出 `MigrationConnectionError(f"Database unreachable after 3 retries: {err}")`，退出码 3，部署流程中止

3. **步骤 3：获取当前数据库版本状态**
   - **操作对象**：目标数据库的 `alembic_version` 表
   - **具体操作**：执行 `alembic.command.current(alembic_cfg)` 获取当前数据库的版本号；执行 `alembic.command.heads(alembic_cfg)` 获取最新可用版本号列表；比对两者判定是否需要迁移
   - **输入来源**：步骤 1 的 database_url，Alembic 配置上下文
   - **输出去向**：版本差值为空 → 数据库已就绪，退出码 0，不执行任何迁移；版本差值非空 → 进入步骤 4
   - **失败行为**：`alembic_version` 表不存在 → 说明数据库从未执行过迁移，视为全部脚本待执行，进入步骤 4。alembic 命令本身抛出异常 → 抛出 `MigrationExecutionError`

4. **步骤 4：执行正向迁移**
   - **操作对象**：目标数据库中所有待执行的迁移脚本
   - **具体操作**：调用 `alembic.command.upgrade(alembic_cfg, target)` 按时间戳顺序逐个执行迁移脚本的 `upgrade()` 函数；每份脚本在独立事务中执行（`transaction_per_migration=True`）；单脚本执行超时 300 秒；脚本执行失败立即中止，不执行后续脚本
   - **输入来源**：步骤 3 的待执行脚本列表，所有 `packages/py-db/migrations/versions/` 中的脚本文件
   - **输出去向**：执行成功的版本号写入 `alembic_version` 表；执行日志以 JSON 格式写入 stdout
   - **失败行为**：任一脚本的 `upgrade()` 抛出异常 → 当前脚本的事务自动回滚（PostgreSQL 事务保证），数据库停留在失败脚本之前一个版本；输出结构化错误 `{"script_name": "...", "revision_id": "...", "error_type": "MIG-ERR-001", "error_message": "...", "current_version": "..."}` 到 stderr；退出码 1；部署流程中止

5. **步骤 5（可选）：执行回滚迁移**
   - **操作对象**：目标数据库中需要回退的迁移脚本
   - **具体操作**：调用 `alembic.command.downgrade(alembic_cfg, target)` 按时间戳逆序逐个执行迁移脚本的 `downgrade()` 函数；仅当目标版本的 `downgrade()` 存在且数据库当前版本高于目标版本时执行；回滚前打印确认信息 "Downgrading from <current> to <target>"
   - **输入来源**：步骤 1 的 database_url，用户指定的 target 版本标识
   - **输出去向**：回滚成功的版本号写入 `alembic_version` 表；执行日志以 JSON 格式写入 stdout
   - **失败行为**：目标版本的 `downgrade()` 不存在 → 抛出 `MigrationRollbackError("Downgrade not available for revision X")`，退出码 2；`downgrade()` 执行失败 → 抛出 `MigrationRollbackError("Rollback failed: ...")`，退出码 2；阻止继续降级，要求开发人员通过正向迁移修正问题

6. **步骤 6：生成迁移脚本（开发辅助，非运行时操作）**
   - **操作对象**：`packages/py-db/migrations/versions/` 目录
   - **具体操作**：调用 `alembic.command.revision(alembic_cfg, message=message, autogenerate=True)` 生成迁移脚本；生成的文件以当前时间戳 + 描述信息命名；若 `autogenerate=False`，生成空模板
   - **输入来源**：开发人员提供的 `message`（如 "add_user_nickname"），ORM 模型的 `target_metadata`
   - **输出去向**：新创建的 `.py` 文件路径返回给调用方
   - **失败行为**：Alembic 配置不正确或项目结构不完整 → 抛出 `MigrationGenerationError`；不修改数据库

7. **步骤 7：迁移验证（CI 专用）**
   - **操作对象**：CI 提供的空数据库
   - **具体操作**：执行 `alembic.command.check(alembic_cfg)` 检测手动修改痕迹；执行 `alembic.command.upgrade(alembic_cfg, "head")` 验证全部脚本可执行性；扫描 `versions/` 下所有 `.py` 文件，通过 AST 解析检查每个文件是否同时定义了 `upgrade` 和 `downgrade` 函数
   - **输入来源**：步骤 1 的 database_url（指向 CI empty DB），`versions/` 目录下所有脚本文件
   - **输出去向**：验证结果 `(exit_code, summary)` 返回给 CI 流水线
   - **失败行为**：`alembic check` 检测到手动修改 → 退出码 3；迁移脚本执行失败 → 退出码 1；缺少 `downgrade()` → 退出码 2

### 1.8 状态机（如适用）

| 当前状态 | 触发事件 | 下一状态 | 前置条件 | 副作用 |
|----------|----------|----------|----------|--------|
| 待迁移 (Pending) | `migrate_up("head")` 调用 | 迁移执行中 (Migrating) | 数据库连接可用且 `alembic current` != `alembic heads` | 开始执行第一部分迁移脚本的 `upgrade()` |
| 迁移执行中 (Migrating) | 全部脚本执行成功 | 已就绪 (Ready) | 所有待执行迁移脚本的 `upgrade()` 均返回且无异常 | 更新 `alembic_version` 表为最新 revision hash |
| 迁移执行中 (Migrating) | 单个脚本执行失败 | 待迁移 (Pending) | 任一脚本的 `upgrade()` 抛出异常 | 当前失败脚本的事务回滚；数据库停留在失败前的版本；向部署流程报告错误 |
| 已就绪 (Ready) | `migrate_up("head")` 再次调用 | 已就绪 (Ready) | `alembic current` == `alembic heads`（幂等） | 无操作，返回退出码 0 |
| 迁移执行中 (Migrating) | 数据库连接中断 | 待迁移 (Pending) | 连接检测失败且重试 3 次后仍不可用 | 中止迁移；数据库停留在中断前版本；报告连接错误 |
| 已就绪 (Ready) | `migrate_down(target)` 调用 | 迁移执行中 (Migrating) | `target` 版本低于当前版本且对应 `downgrade()` 存在 | 开始执行逆向迁移 |

上述状态机完全依赖 Alembic 内置的 `alembic_version` 表持久化，不引入额外的状态管理组件。

### 1.9 异常与边界条件

#### 1.9.1 异常 1：迁移脚本执行失败 (MIG-ERR-001)

- **触发条件**：
  - 任一迁移脚本的 `upgrade()` 函数在执行时抛出异常
  - 常见具体原因：目标表已存在（`CREATE TABLE` 重复）、列名冲突、约束冲突（如 `UNIQUE` 约束冲突）、数据类型不兼容、DDL 语法错误
  - 单个脚本执行时间超过 300 秒但尚未完成（超时场景下进程被终止）
- **处理策略**：
  1. 捕获异常，立即调用 `transaction.rollback()` 回滚当前迁移脚本的事务（PostgreSQL 保证原子性）
  2. 不执行任何后续待执行的迁移脚本（migrate_up 返回 None 信号中断循环）
  3. 构造结构化错误 JSON 写入 stderr：
     ```json
     {"script_name": "20260526_001_add_nickname.py", "revision_id": "20260526_001", "error_type": "MIG-ERR-001", "error_message": "column 'nickname' already exists", "current_version": "20260520_003"}
     ```
  4. 日志记录错误详情：`logger.error("migration_execution_failed", script_name=..., revision_id=..., error_message=..., current_version=...)`
  5. 返回退出码 1
- **重试参数**：不重试。DDL 操作重试无法解决结构冲突——失败原因通常是永久的（如表已存在），只有人工修复迁移脚本后才能重试。连接中断导致的失败场景由 §1.9.3 覆盖。

#### 1.9.2 异常 2：迁移脚本无法回滚 (MIG-ERR-002)

- **触发条件**：
  - 执行 `migrate_down(target)` 时，目标版本的迁移脚本不存在 `downgrade()` 函数
  - 对应版本的 `downgrade()` 函数存在但执行时抛出异常（原因包括：DROP 不存在的表/列、数据类型变更无法逆向、约束依赖未解除）
  - 指定的 target revision hash 在 `alembic_version` 历史记录中不存在
- **处理策略**：
  1. `downgrade()` 不存在 → 立即中止，抛出 `MigrationRollbackError`
  2. `downgrade()` 执行异常 → 当前脚本的事务回滚，中止后续回滚操作
  3. 输出结构化错误到 stderr：
     ```json
     {"script_name": "20260526_001_add_nickname.py", "revision_id": "20260526_001", "error_type": "MIG-ERR-002", "error_message": "Downgrade failed: column 'nickname' referenced by index 'idx_nickname'", "current_version": "20260526_001"}
     ```
  4. 阻止继续降级——数据库停留在执行失败前的版本，不进入不可预测的中间状态
  5. 返回退出码 2
- **重试参数**：不重试。要求开发人员编写正向修复迁移脚本（而非尝试回滚）来解决问题。

#### 1.9.3 异常 3：数据库连接不可用 (MIG-ERR-003)

- **触发条件**：
  - 迁移开始前连接测试（步骤 2）失败：PostgreSQL 容器未启动、网络不可达、DATABASE_URL 格式错误
  - 迁移执行过程中连接中断：PostgreSQL 容器崩溃、网络闪断、连接池耗尽
  - 连接成功但认证失败：用户名/密码错误、数据库不存在
- **处理策略**：
  1. **迁移开始前检测到连接失败**：
     - 重试连接最多 3 次，固定间隔 5 秒
     - 3 次重试后仍失败 → 输出错误到 stderr：`{"error_type": "MIG-ERR-003", "error_message": "Database unreachable after 3 retries: Connection refused at postgres:5432", "current_version": "unknown"}`
     - 中止部署流程，返回退出码 3，应用容器不启动
  2. **执行过程中连接中断**：
     - 当前迁移脚本的事务应已通过 PostgreSQL 自动回滚
     - 尝试恢复连接并执行 `alembic current` 确认中断时的版本号
     - 若连接恢复：重新执行 migrate_up 继续后续脚本
     - 若无法恢复：记录当前已确认的版本号，输出错误，中止部署
  3. **认证失败**：不重试，直接输出错误中止
- **重试参数**：连接重试最多 3 次，固定间隔 5 秒。每次重试前必须创建新的连接（禁止在失效连接上重试）。认证失败不重试。

### 1.10 验收测试场景

#### 1.10.1 正向测试 1：空数据库完整迁移

- **场景**：全新空数据库上执行全部迁移脚本
- **Given**：
  - 空 PostgreSQL 17.x 数据库，`DATABASE_URL=postgresql+psycopg2://test:test@localhost:5432/test_empty`
  - `versions/` 目录下有 3 份迁移脚本：`20260520_001_create_users.py`、`20260522_001_add_profiles.py`、`20260526_001_add_cases.py`
  - 每份脚本均包含 `upgrade()` 和 `downgrade()` 函数
  - `alembic_version` 表为空（从未执行过迁移）
- **When**：调用 `migrate_up(target="head")`
- **Then**：
  - 退出码为 0
  - 数据库包含 migrations 中定义的全部表（users、profiles、cases）
  - `alembic_version` 表中记录 latest revision hash 等于 head
  - 日志输出包含 3 条成功记录：`Running upgrade  → 20260520_001`，`Running upgrade 20260520_001 → 20260522_001`，`Running upgrade 20260522_001 → 20260526_001`
- **验证数据**：
  ```json
  {"expected": {"exit_code": 0, "tables": ["users", "profiles", "cases", "alembic_version"], "alembic_current": "20260526_001"}}
  ```

#### 1.10.2 正向测试 2：幂等重复迁移

- **场景**：在已处于最新版本的数据库上重复执行迁移
- **Given**：
  - 数据库已处于最新版本（正向测试 1 的完成状态）
  - `alembic current` 输出 head revision hash = `20260526_001`
- **When**：再次调用 `migrate_up(target="head")`
- **Then**：
  - 退出码为 0
  - 不执行任何新的迁移操作
  - 数据库表结构无变化
  - 日志输出：`INFO: No migrations to apply. Database is up to date.`
- **验证数据**：
  ```json
  {"expected": {"exit_code": 0, "alembic_current": "20260526_001", "unchanged": true}}
  ```

#### 1.10.3 正向测试 3：回滚迁移

- **场景**：从最新版本回滚到上一个版本
- **Given**：
  - 数据库处于最新版本（3 份迁移脚本均已执行）
  - `alembic current` = `20260526_001`
- **When**：调用 `migrate_down(target="-1")`
- **Then**：
  - 退出码为 0
  - `cases` 表被删除（20260526_001 的回滚操作执行）
  - `alembic_version` 表记录当前版本 = `20260522_001`
- **验证数据**：
  ```json
  {"expected": {"exit_code": 0, "tables": ["users", "profiles", "alembic_version"], "dropped_tables": ["cases"], "alembic_current": "20260522_001"}}
  ```

#### 1.10.4 异常测试 1：脚本执行失败中止

- **场景**：某份迁移脚本执行失败，验证后续脚本不被执行
- **Given**：
  - 空数据库，DATABASE_URL 有效
  - `versions/` 目录下有 2 份迁移脚本：`20260520_001_create_users.py`（正常），`20260526_001_broken.py`（包含执行 `CREATE TABLE users` 的操作——表已存在导致失败）
- **When**：调用 `migrate_up(target="head")`
- **Then**：
  - 第一份脚本 `20260520_001` 执行成功（users 表已创建）
  - 第二份脚本 `20260526_001` 执行失败，抛出 `MigrationExecutionError`
  - 退出码为 1
  - `alembic_version` 表记录当前版本 = `20260520_001`（停留在失败脚本之前）
  - 错误输出包含 `{"error_type": "MIG-ERR-001", "script_name": "20260526_001_broken.py"}`
- **验证数据**：
  ```json
  {"expected": {"exit_code": 1, "alembic_current": "20260520_001", "error_type": "MIG-ERR-001", "reason": "relation 'users' already exists"}}
  ```

#### 1.10.5 异常测试 2：数据库连接不可用

- **场景**：数据库服务完全不可达
- **Given**：
  - DATABASE_URL 指向不存在的数据库（如 `postgresql+psycopg2://test:test@localhost:59999/nonexistent`）
  - 重试次数设为 3，间隔 5 秒
- **When**：调用 `migrate_up(target="head")`
- **Then**：
  - 第 1 次连接尝试失败 → 等待 5 秒 → 第 2 次失败 → 等待 5 秒 → 第 3 次失败
  - 抛出 `MigrationConnectionError`
  - 退出码为 3
  - 错误输出包含 `{"error_type": "MIG-ERR-003", "error_message": "Database unreachable after 3 retries"}`
  - 不再继续执行任何迁移操作
- **验证数据**：
  ```json
  {"expected": {"exit_code": 3, "error_type": "MIG-ERR-003", "retries_attempted": 3, "retry_interval_sec": 5}}
  ```

#### 1.10.6 异常测试 3：回滚失败（缺少 downgrade）

- **场景**：尝试回滚但目标脚本缺少 `downgrade()` 函数
- **Given**：
  - 数据库已执行 `20260520_001_create_users.py`（仅有 `upgrade()` 无 `downgrade()`）
  - `alembic current` = `20260520_001`
- **When**：调用 `migrate_down(target="-1")`
- **Then**：
  - 抛出 `MigrationRollbackError`
  - 退出码为 2
  - 数据库停留在当前版本（`20260520_001`），表结构不变
  - 错误输出包含 `{"error_type": "MIG-ERR-002", "reason": "Downgrade not available for revision 20260520_001"}`
- **验证数据**：
  ```json
  {"expected": {"exit_code": 2, "error_type": "MIG-ERR-002", "alembic_current": "20260520_001", "unchanged": true}}
  ```

### 1.11 注意事项与禁止行为（编码层面）

1. **[约束] 同步驱动强制**：`migrate_up()` 和 `migrate_down()` 的实现中，数据库连接必须通过 `alembic.ini` 的 `[alembic]` 配置节或 `engine_from_config()` 创建同步引擎（`psycopg2`）。禁止在此上下文中使用 `create_async_engine()` 或 `asyncpg` 连接。

2. **[约束] 事务模式**：`env.py` 中 `run_migrations_online()` 必须设置 `transaction_per_migration=True`。不可在单个迁移脚本中使用 `op.execute("COMMIT")` 或 `op.execute("ROLLBACK")` 手动控制事务边界。

3. **[易错点] 列重命名陷阱**：开发人员在 ORM 模型中重命名列后，`alembic revision --autogenerate` 会生成 `op.drop_column()` + `op.add_column()` 而非 `op.alter_column()`。这会导致原列数据永久丢失。编码规范必须明确：涉及列重命名的迁移脚本必须手工编写，使用 `op.alter_column(table_name, old_column_name, new_column_name=new_name)`。

4. **[易错点] pgvector 扩展依赖**：迁移脚本中若有依赖 pgvector 扩展的操作（如创建 `vector` 类型列），必须在迁移脚本的 `upgrade()` 开头显式执行 `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`。同样 `downgrade()` 中禁止 `DROP EXTENSION vector`（除非确认该扩展仅由本迁移使用）。

5. **[禁止行为] 禁止在迁移脚本中使用异步 API**：迁移脚本中禁止使用 `await`、`async def`、`AsyncSession` 或任何异步模式。Alembic 的迁移上下文是同步的。

6. **[禁止行为] 禁止跳过双向检查**：CI 流水线中必须执行 AST 解析检查（每份迁移脚本的 AST 中必须包含 `upgrade` 和 `downgrade` 两个函数定义）。禁止仅靠代码审查的"人工检查"替代自动化检查。

7. **[偷懒红线] 禁止省略 alembic check**：CI 和部署流水线中必须包含 `alembic check` 步骤检测手动修改。禁止以"开发环境不关心"为由跳过此步骤。

### 1.12 文档详细度自检清单

- [x] 文档自包含：不了解本项目代码的 Agent，仅凭此文档 + 设计文档 + 意图文档即可完成 DEPLOY-04 编码
- [x] 无偷懒表述：全文无 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`
- [x] 类型定义完整：对外类型使用契约引用（4 个 JSON Schema 文件），内部接口有完整函数签名和 docstring
- [x] 逻辑步骤完整：7 个步骤均有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：3 种异常均有精确触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有超时阈值（300s/5s）、重试次数（3）、间隔（5s 固定）、错误码（MIG-ERR-001/002/003）均已显式写出
- [x] 技术栈绑定明确：必须使用和禁止使用的项均已列出，与项目技术栈设计文档 §2 一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致（见 §1.15）

### 1.14 外部接口契约清单

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| DATABASE_URL | `docs/contracts/DEPLOY-04/DATABASE_URL.json` | configuration | draft | DEPLOY-04 | DEPLOY-01, DEPLOY-03, DEPLOY-05 |
| MigrationState | `docs/contracts/DEPLOY-04/MigrationState.json` | shared-enum | draft | DEPLOY-04 | DEPLOY-01 |
| MigrationErrorCode | `docs/contracts/DEPLOY-04/MigrationErrorCode.json` | error-code | draft | DEPLOY-04 | DEPLOY-01, DEPLOY-03 |
| MigrationScript | `docs/contracts/DEPLOY-04/MigrationScript.json` | interface | draft | DEPLOY-04 | DEPLOY-01, DEPLOY-03 |
| MigrationTarget | `docs/contracts/DEPLOY-04/MigrationTarget.json` | input | draft | DEPLOY-04 | DEPLOY-01 |

### 1.15 意图一致性声明

- **配套意图文档**：`DEPLOY-04-数据库迁移-意图文档.md`
- **冻结时间**：`2026-05-26 16:54:46`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档 §1.6 中的业务字段定义一致
  - [x] 本落地规范中的状态机实现与意图文档 §1.7 中的状态业务定义一致（待迁移 → 迁移执行中 → 已就绪）
  - [x] 本落地规范中的异常处理策略与意图文档 §1.8 中的异常业务策略一致（3 种异常场景一一对应）
  - [x] 本落地规范中的验收测试场景覆盖意图文档 §1.9 中的全部 7 项验收标准（AC-01 至 AC-07）
  - [x] 本落地规范中的技术实现未超出意图文档 §1.12 中"留给规范阶段的技术决策"的范围（8 项裁决方向已在设计文档 §1.6 中记录）
- **偏差说明**：无偏差，技术实现与意图文档完全一致。
