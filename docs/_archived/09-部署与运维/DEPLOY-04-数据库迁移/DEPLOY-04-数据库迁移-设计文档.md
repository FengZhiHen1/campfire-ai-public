# 1 功能点：DEPLOY-04 数据库迁移 — 设计文档（瘦身版）

> **文档生成时间**：`2026-05-26 17:12:13`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 17:12:13 | AI Assistant | 初始版本，基于意图文档 v2.0 和技术决策报告生成 |
>
> **配套文档**：
> - 本模块的业务意图和验收标准见 `DEPLOY-04-数据库迁移-意图文档.md`（已冻结于 2026-05-26 16:54:46）
> - 本模块的精确编码规格见 `DEPLOY-04-数据库迁移-落地规范.md`

### 1.1 技术实现思路

数据库迁移模块基于 Alembic 对 PostgreSQL 17.x 数据库 Schema 实施版本化增量管理。设计上的核心考量是：Alembic 内置的版本追踪机制和事务控制已覆盖本模块绝大多数需求，因此**设计策略是最大程度复用 Alembic 原生能力，仅在部署流水线集成和错误报告格式上做薄层封装**。

**为什么选择"薄封装"而非"重框架"**：Alembic 本身已提供版本追踪表 (`alembic_version`)、事务级原子执行、自动生成迁移脚本、历史查询等核心机制。重新封装这些能力不仅增加维护负担，还会引入与 Alembic 版本升级的兼容性风险。本模块的增值点在于：将 Alembic 命令嵌入 CI/CD 流水线和 Docker Compose 容器启动顺序中，提供结构化的错误输出格式，以及在开发流程层面强制双向操作检查。

**数据流**：ORM 模型变更 (packages/py-db/models/) → `alembic revision --autogenerate` 生成迁移脚本草稿 → 开发人员审阅修正 → 提交至 Git → CI 空库验证 → 部署时 `alembic upgrade head` 执行迁移 → Alembic 自动更新 `alembic_version` 表记录当前版本。整个链路中，迁移脚本是**单一真相来源**——生产数据库的结构变更必须且只能通过 `packages/py-db/migrations/versions/` 中的脚本执行，这一约束通过 CI 流水线和 Docker 启动脚本在技术层面强制执行。

**事务原子性**：每份迁移脚本作为一个独立 PostgreSQL 事务执行（`transaction_per_migration=True`），与意图文档 §1.11 第 4 条"原子执行"约束一致。若单脚本中任一 DDL 语句失败，整个事务回滚，数据库停留在失败脚本之前的状态。不跨脚本合并事务的原因：Alembic 的版本追踪依赖每个迁移脚本独立提交后更新 `alembic_version`，跨脚本事务会破坏版本追踪的准确性。

**幂等策略**：Alembic 通过 `alembic_version` 表记录每个已执行的 revision hash，重复执行 `upgrade head` 时自动跳过已执行版本，天然幂等。这一机制同时满足意图文档 AC-07（变更历史可追溯）的要求。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：`docs/功能设计/功能模块全拆解.md`、`docs/篝火智答-技术栈设计.md`、`docs/篝火智答-项目结构.md`、`docs/功能设计/模块依赖关系分析.md`
- **兼容性结论**：
  - **无冲突**：本项目尚无已冻结的规格文档（DEPLOY-04 为首个进入设计阶段的模块）。本模块遵循技术栈设计 §2 确立的 Alembic + PostgreSQL 17.x 技术选型，使用项目结构 §6.1 中 `packages/py-db/migrations/` 的目录约定，与模块依赖关系分析中 DEPLOY-04 的 L1 基础层定位一致——无上游业务模块依赖，与 DEPLOY-01/03/05 的时序与调用依赖关系清晰。
- **复用的已有设计**：
  - 设计原则第 8 条 "Alembic 迁移为单一真相来源" — 本模块是此设计的直接落地载体
  - SQLAlchemy 2.x 声明式映射作为 `target_metadata` 来源 — 与项目结构 §7.2 一致
  - DATABASE_URL 环境变量注入 — 与 DEPLOY-05 的接口约定，格式 `postgresql+asyncpg://`

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| PostgreSQL 17.x + pgvector | 运行时数据存储 | 迁移脚本通过 `op.*` API 对目标数据库执行 DDL 操作。连接串由 DATABASE_URL 环境变量注入，格式 `postgresql+asyncpg://user:pass@host:5432/dbname` |
| Alembic (Python 包) | 框架依赖 | 提供 CLI 命令式和 Python API 式两种调用方式。本模块主要使用 CLI（`alembic upgrade head`、`alembic downgrade -1`、`alembic revision --autogenerate`），部署脚本中通过 subprocess 或直接调用 alembic.config.main() |
| SQLAlchemy ORM 模型 (packages/py-db/models/) | 上游元数据来源 | `target_metadata = Base.metadata` 指向所有 ORM 模型声明，autogenerate 通过比对 metadata 与数据库实际结构差异生成迁移脚本 |
| DEPLOY-01 (容器编排) | 运行时时序依赖 | PostgreSQL 容器就绪后、应用容器启动前，通过 `migrate.sh` 或 docker-compose 中的 `depends_on` + healthcheck 机制执行迁移。迁移失败则应用容器不启动 |
| DEPLOY-03 (CI/CD) | 验证调用方 | CI 流水线中通过 GitHub Actions 的 `services.postgres` 创建临时空数据库，执行全部迁移脚本验证可执行性 |
| DEPLOY-05 (环境配置) | 运行时数据来源 | 提供 DATABASE_URL 环境变量，迁移脚本和 Alembic 配置均通过此变量获取目标数据库连接 |

> 精确的函数签名、CLI 命令参数、migrate.sh 脚本逻辑见落地规范。

### 1.4 状态机设计（技术实现策略）

本模块涉及的数据库迁移是**线性串行**操作，不涉及需要持久化复杂状态的业务状态机。迁移过程通过 Alembic 内置的 `alembic_version` 表追踪当前版本号，状态判定通过比对 `alembic current` 与 `alembic heads` 的输出来实现。

**三种逻辑状态**：

- **待迁移 (Pending)**：`alembic current` 的版本不等于 `alembic heads`，存在未执行的迁移脚本。进入条件：部署流程启动时检测到版本差异。
- **迁移执行中 (Migrating)**：`alembic upgrade head` 正在执行中，数据库表结构处于变更过程。进入条件：部署流程调用迁移命令后。
- **已就绪 (Ready)**：`alembic current` 等于 `alembic heads`，数据库 Schema 与应用代码一致。进入条件：全部待执行迁移脚本成功完成或无可执行迁移脚本。

```
待迁移 ──alembic upgrade head──▶ 迁移执行中 ──全部成功──▶ 已就绪
                                       │
                                       └──单个脚本失败──▶ 待迁移 + 错误报告（人工介入）
```

**技术实现要点**：
- 不引入额外状态持久化组件，完全依赖 Alembic 内置机制
- 部署脚本（migrate.sh）通过 Alembic 命令的退出码（0=成功/无待迁移脚本，非0=失败）判定迁移结果
- "已就绪"状态的判定：当 `alembic current` 与 `alembic heads` 返回相同 revision hash 时
- 单次部署中这是一次性操作——不存在长时间保持"迁移执行中"状态并等待人工干预的场景

### 1.5 设计原则兑现清单（技术视角）

| 原则编号 | 原则名称 | 技术响应 |
|----------|----------|----------|
| 原则 8 | Alembic 迁移为单一真相来源 | 本模块是此原则的直接执行者。所有 Schema 变更必须通过 `packages/py-db/migrations/versions/` 的迁移脚本执行；CI 流水线中通过 `alembic check` 检测手动修改，阻断未通过迁移脚本的数据库变更进入生产环境 |

> 注：当前项目设计文档中仅原则 8 直接与本模块相关。其他原则（如单一职责、零 Any 容忍等）主要在应用层模块兑现，本模块作为 L1 基础设施层模块，仅涉及数据库 Schema 的结构管理。

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 迁移框架 | Alembic（SQLAlchemy 生态） | Flyway（Java 原生）/ 手写 SQL 脚本 | 技术栈设计已确立 Alembic；与 SQLAlchemy ORM 深度集成，支持 autogenerate 自动检测 ORM 模型变更；Python 生态一致性——小团队无需引入 Java 运行时依赖 |
| 迁移脚本管理策略 | 线性历史优先（rebase 后合并主分支） | 分支合并标记（alembic merge） | 1-3 人小团队最适合线性模式：rebase 冲突少，历史清晰，无需处理 merge point 的分叉。受意图文档约束（§1.12 第 5 项）—用户确认采纳推荐方案 A |
| 迁移锁机制（MVP 适用） | 单副本部署，不引入分布式锁 | 基于 pg_advisory_lock 的分布式迁移锁 | 项目采用 Docker Compose 单机生产架构（技术栈设计 §6.1），单副本部署下并发迁移风险极低。Alembic 本身通过 `alembic_version` 表唯一约束防并发。受意图文档约束（§1.12 第 4 项）—用户确认单副本架构 |
| 自动生成策略 | autogenerate + 人工审核，数据敏感变更手工编写 | 全部手工编写 / 全量 autogenerate | autogenerate 无法检测列重命名（会生成 drop+add 导致数据丢失），因此涉及列重命名、列类型变更等数据敏感操作必须手工编写迁移脚本。一般字段变更（新增列、可空性修改）使用 autogenerate 加速开发。受意图文档约束（§1.12 第 2 项）—用户确认采纳混合模式 |
| 执行失败处理 | 脚本执行失败不重试，仅连接中断重试 3 次 | 自动回滚 + 重试 / 全量重试 | DDL 操作重试的风险高于收益——失败原因通常是结构冲突（表已存在、列名冲突），重试无法解决。连接中断场景下重试是合理的，因为中断是临时的且重试不会产生副作用。受意图文档约束（§1.12 第 3 项）—用户确认采纳推荐方案 |
| 数据迁移模式 | 预估执行时间 <30s 使用标准 DDL，超过则分批迁移 | 全部标准 DDL / 全量零停机方案 | 初期数据量预估 <10 万切片 + 用户档案，标准 ALTER TABLE 在 30s 内可完成绝大多数操作。仅对大规模存量数据的表（如案例表、档案表）的破坏性变更保留分批迁移选项。零停机迁移暂不纳入 MVP——团队运维能力不支持。受意图文档约束（§1.12 第 7 项） |

> 上表中标注"受意图文档约束"的决策点对应意图文档 §1.12 的 8 项"留给规范阶段的技术决策"，其裁决方向已由用户在 s06 技术预研阶段确认。

### 1.7 注意事项与禁止行为（设计层面）

1. **[设计边界] 不负责数据备份与恢复**：数据备份与恢复属于 QUAL-05（数据备份恢复）模块的职责，本模块仅管理 Schema 结构变更，不涉足数据内容。迁移脚本中禁止写入业务数据的 DML 操作（如 INSERT/UPDATE/DELETE），除非属于数据迁移脚本（如将旧列数据迁至新列）。

2. **[设计边界] 不负责查询性能优化**：索引策略的设计和创建虽然通过迁移脚本实现，但索引的"是否创建、如何创建"由相关业务模块（如 CSLT-02 RAG 检索、CASE-04 向量化入库）在自身设计文档中决定，本模块仅提供执行载体。

3. **[设计边界] 不负责数据内容校验**：数据校验（PII 脱敏、字段格式校验）属于 SEC-03 的职责，迁移脚本不包含输入校验逻辑。

4. **[易错点] 数据库驱动的同步/异步混用**：Alembic 的 DDL 操作使用同步驱动（psycopg2），ORM 模型使用异步驱动（asyncpg）。两个驱动连接的是同一个数据库但使用不同的连接配置。在 `env.py` 中配置 `run_migrations_online()` 时必须使用 `connectable = engine_from_config(config.get_section(...), prefix="sqlalchemy.")`，确保 DDL 通过同步连接执行。

5. **[易错点] autogenerate 的列重命名陷阱**：Alembic autogenerate 通过比对 `target_metadata` 与数据库实际结构来生成迁移脚本。当开发者在 ORM 模型中重命名列时，autogenerate 会生成 `op.drop_column()` + `op.add_column()`，这将导致**原列数据永久丢失**。开发规范必须明确：列重命名时必须手工编写 `op.alter_column(table_name, old_column_name, new_column_name=new_name)`。

6. **[禁止行为] 禁止在迁移脚本中硬编码数据库连接串**：所有迁移脚本和 Alembic 配置必须通过 `DATABASE_URL` 环境变量获取目标数据库地址。违反此规则的迁移脚本将无法在不同环境（开发/测试/生产）中执行。

7. **[禁止行为] 禁止在生产数据库中手动执行 SQL 变更**：所有 Schema 变更必须通过迁移脚本执行。CI 流水线中通过 `alembic check`（Alembic 1.9+ 内置命令）检测未记录的变更并阻断部署流程。

8. **[禁止行为] 禁止提交仅有 upgrade 而无 downgrade 的迁移脚本**：每份迁移脚本必须同时提供 `upgrade()` 和 `downgrade()` 函数。计划在 CI 流水线中增加检查步骤（解析迁移脚本 AST 检测两个函数的存在性），阻断仅含单向操作的脚本进入版本库。

### 1.8 引用：配套意图文档

- **意图文档**：`DEPLOY-04-数据库迁移-意图文档.md`
- **冻结时间**：`2026-05-26 16:54:46`
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。8 项"留给规范阶段的技术决策"（意图文档 §1.12）的裁决方向已由用户在 s06 技术预研阶段确认，并在本设计文档 §1.6 中明确记录。如有歧义，以意图文档为准。
