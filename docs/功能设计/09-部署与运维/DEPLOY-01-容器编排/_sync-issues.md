# 同步问题报告 — DEPLOY-01 容器编排

---

## 2026-05-26T21:32:00 MODULE: DEPLOY-01 容器编排

### 处理摘要
- **场景**: full_design
- **执行阶段**: s03-detect-existing-artifacts, s04-intent-writing, s05-spec-prepare, s06-spec-research, s07-spec-design-doc, s08-spec-implementation, s09-contract-harmonize, s10-module-sync-report
- **状态**: completed
- **产物**:
  - docs/功能设计/09-部署与运维/DEPLOY-01-容器编排/DEPLOY-01-容器编排-意图文档.md
  - docs/功能设计/09-部署与运维/DEPLOY-01-容器编排/DEPLOY-01-容器编排-设计文档.md (v2.0)
  - docs/功能设计/09-部署与运维/DEPLOY-01-容器编排/DEPLOY-01-容器编排-落地规范.md (v1.0, 50KB)
  - docs/contracts/DEPLOY-01/ContainerServiceName.json
  - docs/contracts/DEPLOY-01/InternalDnsName.json
  - docs/contracts/DEPLOY-01/NamedVolume.json
  - docs/contracts/DEPLOY-01/ContainerNetwork.json
  - docs/contracts/DEPLOY-01/HealthCheckProbe.json
  - docs/contracts/DEPLOY-01/LogDriverConfig.json
  - docs/contracts/DEPLOY-01/PortMappingRule.json
  - docs/contracts/DEPLOY-01/DeploymentState.json
  - docs/contracts/DEPLOY-01/ServiceRestartPolicy.json
  - docs/contracts/DEPLOY-01/ComposeFileReference.json
  - docs/contracts/DEPLOY-01/_module-index.json

### 同步矛盾

#### [medium] intent-defect: 数据容器重启策略偏差（B9/D15）
- **描述**: 意图文档 §1.11.1 明确要求数据容器（PostgreSQL、Redis、MinIO）"不宜配置自动重启，防止数据损坏风险"。设计文档 v2.0 经代码审查后采用 D15 折中方案——为全部容器（含数据容器）配置 `restart: unless-stopped`，同时附加严格 HEALTHCHECK 指令，确保基础数据损坏时容器标记为 `unhealthy` 而非循环重启。此方案在落地规范 §1.15 中声明为显式偏差。
  - 意图要求：数据容器不自动重启
  - 实际实现：全部容器 `restart: unless-stopped` + HEALTHCHECK + 运维告警
- **来源阶段**: s06-spec-research, s07-spec-design-doc
- **影响模块**: DEPLOY-01（自约束）, OBS-03（下游消费 unhealthy 状态做运维告警——待落地）
- **建议方案**: 已采纳 D15 折中方案并在设计文档 v2.0 中经用户确认。后续若 OBS-03 告警模块落地后，应建立数据容器 unhealthy→运维告警的完整闭环。

#### [medium] intent-defect: 数据持久化方式偏差（B10/D14）
- **描述**: 意图文档 §1.4 目标 5 和 §1.11.4 明确要求数据持久化采用"宿主机绑定挂载（bind mount）"。设计文档 v2.0 经代码审查后采用 D14 方案——保留现有 Docker 命名卷（named volume），不强制切换为绑定挂载。理由：跨平台路径一致（回避 Windows/Linux 路径差异）；Docker 自动处理权限；QUAL-05 可通过 `docker volume inspect` 或 `docker cp` 访问数据。此方案在落地规范 §1.15 中声明为显式偏差。
  - 意图要求：绑定挂载（bind mount）
  - 实际实现：Docker 命名卷（named volume: pgdata, redis_data, minio_data）
- **来源阶段**: s06-spec-research, s07-spec-design-doc
- **影响模块**: DEPLOY-01, QUAL-05（通过 docker volume inspect 或 docker cp 访问数据）
- **建议方案**: 已采纳 D14 命名卷方案并在设计文档 v2.0 中经用户确认。后续 QUAL-05 备份恢复模块设计时应确认其通过 Docker API（`docker volume inspect`/`docker cp`）访问命名卷数据的可行性，若不支持则需回退到绑定挂载方案。

#### [low] dependency-drift: 功能模块全拆解表未同步更新（B11）
- **描述**: `docs/功能设计/功能模块全拆解.md` 中 DEPLOY-01 的设计状态仍标注为"未开始"，核心功能描述记载"编排服务含 FastAPI、PostgreSQL+pgvector、Redis、MinIO 与 Nginx 共 5 个容器"。实际设计已完成全部流程并产出意图/设计/规范三大制品，且服务集合已确认为 6+1 个（新增 Worker 和 migration 一次性服务）。此外，`tmp/wfctl_report.txt` 中的模块状态表也仍显示 DEPLOY-01 为"未开始"。
  - 全拆解表记载：5 个容器 | 设计状态=未开始
  - 实际：6+1 个服务（含 Worker + migration）| 设计状态=已完成
- **来源阶段**: s07-spec-design-doc（设计文档 v2.0 §v2.0新增 B11）
- **影响模块**: DEPLOY-01（文档一致性），全项目模块调度视图
- **建议方案**: 在项目同步阶段（project-sync-aggregator）统一更新功能模块全拆解表：将 DEPLOY-01 设计状态改为"规格已完成"，容器数量更新为 6+1。同步更新 `tmp/wfctl_report.txt` 或此类调度清单的模块状态。

### 遗留问题（从上周期延续）

无。本模块为首次进入设计流程，全局 `_sync-issues.md` 中此前两次 DEPLOY-01 一致性检查（2026-05-26 21:06 和 2026-05-26 21:10）均结论为"无冲突"。

### 预存现象（本模块未引入，仅记录）

- SEC-01 与 SEC-05 之间存在 `FileValidationResult.json` 和 `validate_file.json` 的同名异构类型。此现象在先前的 KNOW-01/OBS-01 设计阶段已记录，先于本模块存在，不阻塞 DEPLOY-01 的设计。设计文档 v2.0 §1.2 "兼容性分析"已注明此预存现象。
