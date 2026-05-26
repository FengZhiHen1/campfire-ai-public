## 1 功能点：DEPLOY-01 容器编排 — 设计文档（瘦身版）

> **文档生成时间**：2026-05-26 20:48:17
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-26 20:48:17 | AI Assistant | 初始版本：基于技术决策预研报告（.tmp/reports/tech-decision-report-DEPLOY-01.md）和已冻结的意图文档生成 |

> **配套文档**：
> - 本模块的业务意图和验收标准见 `DEPLOY-01-容器编排-意图文档.md`（已冻结于 2026-05-26 20:41:57）
> - 本模块的精确编码规格见 `DEPLOY-01-容器编排-落地规范.md`

### 1.1 技术实现思路

本模块的核心任务是将 6 个异构服务容器（api-server、worker、postgres、redis、minio、nginx）通过 Docker Compose v2 编排为可一键启动、自愈恢复、环境隔离的完整运行集群。

**为什么选择 Docker Compose 而非 Kubernetes**：项目部署目标为单台 4C8G 云服务器，无需多节点调度和自动伸缩，Docker Compose 在此场景下是零额外复杂度的最优解。Kubernetes（即使是 k3s 轻量版）会引入 etcd 集群管理、Ingress Controller、CNI 插件等额外运维负担，与意图文档 §1.4.1 "执行一条命令即可启动"的简化运维目标背道而驰。

**两文件的环境隔离策略**：`docker-compose.yml`（dev）和 `docker-compose.prod.yml`（prod）共享约 80% 的服务定义骨架（容器名、内部网络、依赖关系），差异集中在端口暴露（dev 暴露全部数据端口供调试，prod 仅暴露 Nginx 80/443）、资源限制（prod 设置 `deploy.resources.limits`，dev 不设限制）、镜像标签（dev 允许 `latest`，prod 强制语义版本号）和健康检查（prod 启用 `condition: service_healthy` 严格等待）。这种差异化方式确保环境切换只需更换命令参数（`-f docker-compose.prod.yml`），应用代码零感知。

**启动时序作为编排的核心挑战**：6 个容器之间存在严格的就绪依赖——PostgreSQL 必须先于业务容器就绪，迁移脚本必须先于 api-server 启动。仅用 Docker Compose 的 `depends_on`（无 `condition`）只能保证启动顺序而无法保证服务就绪，会导致 api-server 在 PostgreSQL 端口未监听时就尝试连接池初始化。因此 prod 环境必须采用 `condition: service_healthy` 模式：

```
postgres ──(healthy)──▶ migration ──(completed)──▶ api-server/worker
redis    ──(healthy)───┤                                │
minio    ──(healthy)───┘                                │
                                                         ▼
                                                      nginx
```

dev 环境为了开发体验（无需等待健康检查通过即可进入调试），使用简单顺序启动模式。这一差异是本模块在"运维严谨性"和"开发便利性"之间的核心权衡。

**日志与监控的被动输出角色**：本模块不主动收集或分析日志，而是作为日志管道的起点。所有业务容器的 stdout/stderr 由 Docker 日志驱动（默认 `json-file`）统一收集，结构化日志模块（OBS-01）从 Docker 日志中提取。这种"被动终端输出 + Docker 驱动收集"的设计避免在每个容器中引入日志采集 Agent，遵循"最小侵入"原则。

**自愈能力的 Docker 原生实现**：业务容器（api-server、worker、nginx）配置 `restart: unless-stopped` 策略——Docker 引擎在容器异常退出后自动拉起新容器。数据容器（postgres、redis、minio）特意不配置自动重启——意图文档 §1.11.1 明确要求防止自动重启引发的数据损坏风险（如 PostgreSQL 因磁盘损坏连续重启可能导致 WAL 日志损坏）。这种"业务容器自愈、数据容器人工恢复"的差异化策略是本模块安全性设计的核心。

**数据持久化的绑定挂载策略**：三个有状态服务（postgres、redis、minio）的数据目录通过 Compose `volumes:` 顶层声明统一管理。dev 环境使用相对路径（`./data/dev/`）并加入 `.gitignore`；prod 环境使用绝对路径（`/data/campfire/`），与意图文档 §1.6.1 示例值完全一致。绑定挂载而非命名卷的选择原因是：绑定挂载路径明确可控，便于备份恢复模块（QUAL-05）通过宿主机路径直接访问数据文件。

### 1.2 已有设计兼容性分析

- **已审查的相关文档**：`docs/篝火智答-技术栈设计.md` §3.1 架构分层图、§6 部署与运维；`docs/篝火智答-项目结构.md` §5.3 层间依赖规则、§6.1 目录骨架；`docs/功能设计/09-部署与运维/DEPLOY-04-数据库迁移/DEPLOY-04-数据库迁移-意图文档.md`；`docs/功能设计/09-部署与运维/DEPLOY-05-环境配置管理/DEPLOY-05-环境配置管理-意图文档.md`；`docs/功能设计/09-部署与运维/DEPLOY-04-数据库迁移/DEPLOY-04-数据库迁移-设计文档.md`（v1.0）；`docs/功能设计/09-部署与运维/DEPLOY-05-环境配置管理/DEPLOY-05-环境配置管理-设计文档.md`（v1.0）；`docs/功能设计/_contracts.md`；`docs/功能设计/_sync-issues.md`。

- **兼容性结论**：
  - **无冲突**：本模块定义的服务容器集合（FastAPI、Worker、PostgreSQL+pgvector、Redis、MinIO、Nginx）与技术栈设计 §3.1 架构分层图中的 5 层服务划分完全对齐。DEPLOY-05 已明确 DEPLOY-01 为其下游消费方——18 项环境变量通过 `env_file` 注入；DEPLOY-04 已明确与 DEPLOY-01 的启动时序依赖——PostgreSQL 就绪后执行迁移，迁移完成后启动应用容器。DEPLOY-04 设计文档中描述的 `migration` 一次性服务的概念与本模块的启动时序设计不冲突——本模块仅负责在 Compose 文件中为 migration 服务提供声明性定义，具体迁移逻辑由 DEPLOY-04 模块的 `alembic upgrade head` 命令实现。
  - **已知预存现象**：SEC-01 与 SEC-05 之间存在 `FileValidationResult.json` 和 `validate_file.json` 的同名异构类型，此现象先于本模块存在，不阻塞本模块的设计。

- **复用的已有设计**：
  - 技术栈设计 §2：Docker Compose v2 选型约束、Python 3.12 运行时版本
  - 技术栈设计 §3.1：架构分层图中的 5 层服务划分（客户端层、网关层、应用层、数据层、外部服务）作为容器分类依据
  - 项目结构 §6.1 目录骨架：`docker-compose.yml`、`docker-compose.prod.yml`、`infrastructure/` 的目录位置约定
  - 项目结构 §6.1：各应用独立 Dockerfile 的存放位置（`apps/api-server/Dockerfile.api`、`apps/worker/Dockerfile.worker`）
  - 项目结构 §5.3 第 5 条：L3 工程支撑层的向下依赖规则
  - DEPLOY-05：AppSettings 18 项环境变量类型契约（已通过契约协调确认）
  - DEPLOY-04：MigrationTarget/MigrationScript/MigrationState 的迁移契约接口

### 1.3 依赖关系概述（技术层面）

| 依赖方 | 关系类型 | 技术交互说明 |
|--------|----------|-------------|
| Docker 引擎 24+ | 硬性运行时依赖 | 提供容器生命周期管理、镜像构建、内部 DNS 解析、卷挂载、网络隔离。`docker compose` v2 子命令（非旧版 `docker-compose` Python 脚本）作为编排入口 |
| Docker Hub（MVP） | 镜像仓库 | 拉取基础镜像（postgres:17、redis:7-alpine、minio/minio、nginx:1.26-alpine）；自构建镜像（api-server、worker）在 CI 流水线中构建并推送 |
| 宿主机文件系统 | 数据持久化来源 | 通过 `volumes:` 绑定挂载，将 PostgreSQL 数据目录、Redis RDB/AOF 文件、MinIO 存储桶映射至宿主机固定路径。dev 使用相对路径 `./data/dev/`，prod 使用绝对路径 `/data/campfire/` |
| 宿主机网络栈 | 端口通道 | dev 环境暴露全部服务端口：8000（API）、8080/8443（Nginx）、5432（PG）、6379（Redis）、9000/9001（MinIO）；prod 仅暴露 80/443（Nginx） |
| DEPLOY-05 环境配置管理 | 上游数据消费 | 通过 `env_file: .env` 指令将 18 项环境变量注入 api-server 和 worker 容器。postgres/redis/minio 仅接收各自所需配置（POSTGRES_USER/POSTGRES_PASSWORD 等）。nginx 不注入业务环境变量 |
| DEPLOY-04 数据库迁移 | 同层时序协作 | 通过 `depends_on` + `condition: service_healthy` 确保 postgres 就绪后触发 migration 一次性服务执行 `alembic upgrade head`；migration 完成后 (`service_completed_successfully`) 才启动 api-server 和 worker |
| DEPLOY-02 反向代理路由 | 下游供给 | Nginx 容器的 upstream 地址指向 Compose 内部 DNS 名 `api-server:8000`，无需手动配置 IP 地址 |
| OBS-01 结构化日志 | 下游消费 | 所有业务容器的 stdout/stderr 通过 Docker `json-file` 日志驱动收集，OBS-01 从 Docker 日志中提取并结构化 |
| OBS-04 健康检查 | 同层协作 | Docker HEALTHCHECK 指令调用各服务的 `/health` 端点或状态命令（`pg_isready`、`redis-cli ping`），检查结果用于 `depends_on` 的 `condition: service_healthy` 判定 |
| QUAL-05 数据备份恢复 | 同层协作 | PostgreSQL 和 MinIO 的数据目录通过绑定挂载暴露宿主机路径，QUAL-05 备份脚本直接读取挂载路径的数据文件 |

> 精确的 Compose YAML 字段结构、Dockerfile 各层定义、HEALTHCHECK 命令语法见落地规范。

### 1.4 状态机设计（技术实现策略）

本模块为基础设施编排模块，不涉及需要持久化到业务数据库的应用级状态机。但其"业务状态"（意图 §1.7 定义的 4 个状态）直接映射为 Docker Compose 的容器生命周期管理：

**启动中** → **运行中** → **异常** → **已停止**

状态转换逻辑：

- 执行 `docker compose up -d` 命令后进入"启动中"。此时 Docker 引擎拉取镜像、创建容器、启动进程。此阶段通过 `docker compose logs -f` 或 `docker compose ps` 的 `STATUS` 列（显示 `starting` 或 `health: starting`）观察。
- 全部 6 个容器的 HEALTHCHECK 返回 healthy 后进入"运行中"。Docker Compose 的 `docker compose ps` 可输出各容器的 `STATUS` 列（此时全部显示 `Up (healthy)`）。
- 任一容器健康检查连续失败达到重试次数（默认 3 次）或容器异常退出时，进入"异常"。Docker 引擎对 `restart: unless-stopped` 容器自动触发恢复——这对应了意图文档中"自动恢复机制已触发"的业务语义。恢复成功后重新进入"运行中"。
- 执行 `docker compose down` 后进入"已停止"。所有容器停止并移除（数据卷保留）。再次执行 `docker compose up -d` 回到"启动中"。

**技术实现策略**：不引入额外的状态存储或状态管理组件。状态通过 Docker Engine API（`docker compose ps` 输出）实时反映。容器退出事件和健康检查状态变更由 OBS-01 的结构化日志捕获，供告警和审计使用。

**幂等策略**：`docker compose up -d` 天然幂等——若容器已存在且配置未变更，跳过创建；若 Compose 文件有变更，仅重建受影响的容器（Docker Compose 通过对比哈希值精确识别变更范围）。此机制确保意图文档 §1.8.3 "恢复至关机前运行状态"的业务语义。

**非状态：持久化**：Docker Compose 本身不持久化集群运行状态——这由 Docker Engine 守护进程管理（daemon.json 中的 `live-restore` 配置，本模块不在 Compose 层面干预）。容器数据通过绑定挂载独立于容器生命周期存在。

### 1.5 设计原则兑现清单（技术视角）

| 原则 | 原则名称（来源） | 技术响应 |
|------|-----------------|----------|
| 单向依赖 | 项目结构 §5.3 层间依赖规则：应用层(L1) → 共享能力层(L2) → 工程支撑层(L3)，禁止反向依赖 | 本模块作为 L3 工程支撑层，其编排的 6 个容器之间的依赖关系严格遵循：数据层(postgres/redis/minio) → 应用层(api-server/worker) → 网关层(nginx)。不存在反向依赖——nginx 不启动 API，API 不管理数据库 |
| 最小化可工作 | 项目结构 §3 设计原则第 5 条：不为未规划的功能预留代码实现 | 本模块仅在 Compose 文件中定义当前明确规划的 6 个服务。不为远期规划的 celery 任务队列、gRPC 服务、Elasticsearch 搜索服务等预置镜像声明或端口映射 |
| 厚 package、薄 app | 项目结构 §3 设计原则第 1 条：领域逻辑集中 packages，app 仅含运行时入口 | 本模块位于 L3 层，不直接参与应用层与共享能力层的分离。但其编排方式遵循同样思想：应用镜像仅包含运行时入口（uvicorn/gunicorn 启动命令），业务逻辑在 packages 中，编排层不感知业务细节 |
| 前后端契约先行 | 项目结构 §3 设计原则第 3 条：Pydantic Schema 与 TypeScript 类型作为前后端数据契约 | 不直接适用（本模块为基础设施层，无前后端数据交互）。但其编排的 api-server 容器通过内部 DNS 名 `api-server:8000` 暴露 API，Nginx 通过配置 upstream 转发，这种 DNS 名契约是网络层的前后端接口 |

### 1.6 架构权衡与备选方案

| 决策点 | 最终方案 | 备选方案 | 选择理由 |
|--------|---------|---------|---------|
| 编排工具 | Docker Compose v2 | Kubernetes（k3s） | 部署目标为单台 4C8G 云服务器，无多节点调度需求。k3s 需额外维护 etcd、CNI、Ingress Controller，运维复杂度与意图文档 §1.4.1"一键启动"目标矛盾 |
| 环境隔离 | 双文件策略（`docker-compose.yml` + `docker-compose.prod.yml`） | Compose profiles 或单一文件 + 环境变量分支 | 双文件策略优势：(1) 差异一目了然（端口暴露、资源限制），profile 方案需阅读所有 YAML 才能理解；(2) 生产文件可直接用于 CI 验证；(3) 与环境变量注入解耦（环境变量由 `.env` 管理，不与 Compose 结构混淆） |
| 数据持久化 | 绑定挂载（bind mount） | 命名卷（named volume） | 绑定挂载路径明确可审计，QUAL-05 备份脚本可直接按路径读取。命名卷路径为 `/var/lib/docker/volumes/`，对运维不透明 |
| 启动依赖 | `depends_on` + `condition: service_healthy`（prod） | 应用内部重试连接池 + 简单顺序启动 | prod 环境使用严格等待——避免 api-server 在 postgres 端口监听但数据库尚未接受连接时失败。dev 环境使用简单顺序启动——无需等待健康检查，开发更快 |
| 健康检查实现 | HEALTHCHECK 指令（Docker 原生） | 独立监控 Agent 周期性探测 | Docker HEALTHCHECK 零额外组件，与 Compose 的 `condition: service_healthy` 原生集成。独立 Agent 需额外容器和配置同步 |
| 重启策略 | 差异化策略：业务容器 `unless-stopped`，数据容器 `no` | 全部 `unless-stopped` 或全部不自动重启 | 受意图文档 §1.11.1 明确约束："数据容器不宜配置自动重启，防止数据损坏风险"。业务容器必须自愈恢复 |
| 镜像标签 | dev: `latest`；prod: 语义版本号 | 统一使用 `latest` 或统一使用 hash tag | 意图 §1.11.6 强制 prod 使用明确版本号。dev 用 `latest` 简化开发工作流，每次 `docker compose up --build` 后自动使用最新本地构建 |
| env_file 注入方式 | `env_file: .env` 从项目根目录注入 | `environment:` 逐字段声明 | `env_file` 统一管理 18 项配置，与 DEPLOY-05 的 `.env` 文件格式对齐。`environment` 仅用于 Compose 文件中的非敏感默认值（如 `POSTGRES_USER=campfire`），避免密钥明文写入 Compose 文件 |
| 容器名 | 统一前缀 `campfire-{service}` | Docker Compose 默认命名（项目名 + 服务名 + 序号） | 统一前缀避免宿主机多项目命名冲突。Docker Compose 默认命名含随机序号，不易识别 |
| 资源限制策略 | prod 文件设置 `deploy.resources.limits`，dev 不设 | 统一不设限制或统一设置相同值 | dev 环境不设限制便于开发调试（4C8G 本地足够）；prod 设限制防止单一容器内存泄漏影响全集群。（详见 B2 矛盾处理） |

> 上述方案中，"受意图文档约束"的条目已标注。

### 1.7 注意事项与禁止行为（设计层面）

1. **[设计边界 1]** 本模块不负责 SSL 证书的申请与续期（归属 DEPLOY-02 反向代理路由）。Nginx 容器的 SSL 配置仅在本模块的 Compose 文件中以卷挂载（`./infrastructure/nginx/ssl/:/etc/nginx/ssl/`）的形式预留路径，证书内容由 DEPLOY-02 管理。

2. **[设计边界 2]** 本模块不负责镜像的构建时机和推送策略（归属 DEPLOY-03 CI/CD 流水线）。Compose 文件中的 `build` 上下文路径仅用于 dev 环境的本地构建，prod 环境使用 `image` 字段引用 CI 流水线推送的版本化镜像。

3. **[设计边界 3]** 本模块不负责数据库的备份恢复操作（归属 QUAL-05 数据备份恢复模块）。Compose 文件中的 `volumes:` 声明仅为 QUAL-05 的备份脚本提供可访问的宿主机路径。

4. **[易错点 1: 端口冲突]** dev 环境 Nginx 使用 8080/8443 而非 80/443——避免与 Windows/Linux 开发机已运行的其他 Web 服务端口冲突。prod 环境使用标准端口 80/443。切换环境时需注意端口变化。

5. **[易错点 2: 数据路径误串]** dev 和 prod 的数据持久化路径必须物理隔离。若错误地将 prod Compose 文件中的 `volumes:` 指向 `./data/dev/`，将导致开发数据覆盖生产数据库。设计层面通过将 prod 路径设为绝对路径 `/data/campfire/` 降低此风险，但运维仍需在部署时验证路径。

6. **[易错点 3: depends_on 误解]** Docker Compose 的 `depends_on` 仅控制启动顺序，不保证服务就绪。prod 环境必须使用 `condition: service_healthy` 确保 postgres 在 api-server 之前不仅已启动，且已完成初始化和 WAL 恢复并接受连接。未添加 `condition` 的 `depends_on` 仅保证容器已创建，不保证进程已监听端口。

7. **[禁止行为 1]** 禁止在 Compose 文件中硬编码密钥（如 `DEEPSEEK_API_KEY=sk-xxx`）。所有密钥类环境变量必须通过 `env_file: .env` 注入，Compose 文件内仅可设置非敏感默认值（如 `POSTGRES_USER=campfire`）。

8. **[禁止行为 2]** 禁止在 Compose 文件中暴露数据容器端口到 `0.0.0.0`（prod 环境）。prod 配置下 postgres/redis/minio 的 `ports:` 字段不可存在或必须为 `127.0.0.1:5432:5432`（仅限运维通过 SSH 隧道访问）。

9. **[禁止行为 3]** 禁止在 Prod Compose 文件中使用 `latest` 标签——意图文档 §1.11.6 明确要求生产环境使用语义版本号或构建日期标签。

10. **[禁止行为 4]** 禁止为未规划的未来服务（如 elasticsearch、celery、gRPC sidecar）预置容器定义。遵循"最小化可工作"设计原则——仅定义当前明确规划的 6 个服务。

### 1.8 引用：配套意图文档

- **意图文档**：`DEPLOY-01-容器编排-意图文档.md`
- **冻结时间**：2026-05-26 20:41:57
- **一致性声明**：本设计文档的技术实现与上述意图文档中的业务定义一致。5 项业务目标（一键启动、30 秒自愈、镜像体积 ≤500MB/300MB、双环境切换、数据持久化）均在本设计中找到技术实现路径。8 项验收标准（AC-01~AC-08）在本设计的对应技术方案中均可验证。6 项业务约束（重启策略差异化、多阶段构建、网络隔离、数据持久化红线、环境隔离、镜像标签规范）在本设计的架构权衡小节中逐项落实。8 项"留给规范阶段的技术决策"（意图 §1.12）经技术决策预研后，已在本设计中采纳报告推荐的方案或标注为需用户裁决。如有歧义，以意图文档为准。

---

## 附录：业务矛盾处理声明

以下 8 项矛盾来源于技术决策预研报告的 §5 业务矛盾标记清单（意图文档 §1.12 "留给规范阶段的技术决策"）。本设计文档中采纳了报告推荐的方案。如用户在此轮确认中提供裁决，将以用户裁决为准修订相关章节。

| 编号 | 矛盾点 | 类别 | 采纳方案 | 理由 |
|------|--------|------|---------|------|
| B1 | Docker Compose YAML 精确结构 | 技术实现细节 | services 下 6 服务使用 Compose v2 标准字段；api-server/worker 加 `build` 上下文，数据服务用 `image` | Compose v2 无 `version` 字段，结构简洁。具体 YAML 骨架在落地规范中完整输出 |
| B2 | CPU/内存资源限制 | 性能阈值（需基准测试数据） | 起始分配：postgres(1C/2G)、redis(0.5C/512M)、minio(0.5C/1G)、api-server(1C/2G)、worker(1C/1G)、nginx(0.25C/256M)。合计 4.25C/6.75G | 保守起始值（留约 1G 系统余量），上线后按 Prometheus 指标调整。仅 prod 文件设置 limits |
| B3 | 多阶段 Dockerfile 精确实现 | 技术实现细节 | Stage1: `python:3.12` + `uv sync --no-dev --frozen`；Stage2: `python:3.12-slim` 仅含 `.venv` 和 `src` | 技术栈指定 uv 0.6+ 为包管理器，`-slim` 镜像体积最小化满足 AC-02 体积目标 |
| B4 | 健康检查精确参数 | 技术实现细节 | api-server: `curl -f /health`(start_period 60s)；postgres: `pg_isready`；redis: `redis-cli ping`；minio: `curl /minio/health/live`；nginx: `nginx -t`。间隔/超时/重试=30s/10s/3 | 各服务启动耗时不同，api-server 的 60s start_period 覆盖 uv sync 和连接池初始化 |
| B5 | 镜像仓库与推送策略 | 依赖其他模块决策（DEPLOY-03） | MVP 使用 Docker Hub，镜像格式 `campfire-{service}:{tag}`。具体构建触发器由 DEPLOY-03 确定 | Docker Hub 成本最低、配置最简单。此决策仅影响 Compose 文件中 prod 的 `image` 字段值 |
| B6 | 日志驱动与保留策略 | 技术实现细节 | dev: `json-file`，7 天(max-size 10m, max-file 3)；prod: `json-file`，100MB 总容量(max-size 20m, max-file 5) | json-file 为默认驱动，与 OBS-01 的结构化日志管道兼容。Loki 集成留作后续补充 |
| B7 | 容器启动顺序依赖精确条件 | 技术实现细节 | prod 使用 `condition: service_healthy` + `condition: service_completed_successfully`；dev 使用简单顺序启动 | prod 严格等待确保业务容器不会在数据库就绪前启动。dev 快速启动优化开发体验 |
| B8 | 环境变量注入方式 | 技术实现细节 | 统一使用 `env_file: .env` 注入全部环境变量；非敏感默认值在 Compose 文件的 `environment` 直接声明 | `env_file` 与 DEPLOY-05 的 `.env` 文件格式完全对齐。敏感配置与 Compose 文件物理隔离 |

**说明**：上述 B1-B8 的采纳方案基于技术决策预研报告的推荐方案。在本次 s07 阶段用户确认环节，若有任何裁决与上述采纳方案不同，将以用户裁决为准修订对应章节。
