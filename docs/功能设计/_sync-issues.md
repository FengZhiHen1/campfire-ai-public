# 同步问题记录

---

## 2026-05-27 15:26:30 — CSLT-04 流式应答推送 — 一致性检查

**检查范围**：模块 CSLT-04 首次进入设计流程（s05-spec-prepare），全量扫描已有规格文档和契约文件。

**扫描检查项**：
- 模块编号冲突：无。CSLT-04 编号唯一，与已有模块无冲突。
- SSE 事件类型冲突：无。已有模块未定义 SSE 事件/流式推送相关类型。CSLT-04 将定义的 StreamEvent、StreamEventType、StreamIdentifier 等类型与已有契约无命名交集。
- 接口命名冲突：无。CSLT-04 的 SSE 端点路由（如 /api/v1/consult/stream/{session_id}）与已有模块的路由前缀（/api/v1/auth/、/api/v1/profiles/、/api/v1/cases/、/api/v1/knowledge/、/api/v1/health/ 等）不冲突，无重叠。
- 同名异构类型：无。CSLT-04 的业务领域（SSE 流式事件传输）是项目内首个涉及该领域的模块，无同名异构风险。
- 循环依赖迹象：无。CSLT-04 依赖链为 CSLT-03（上游数据来源）→ CSLT-04（流式推送）→ CSLT-08（下游消费方），全部为单向数据管道。模块依赖关系分析确认零循环依赖。
- 上游合约对齐：CSLT-03/GenerationChunk 的 x-consumers 已包含 ["CSLT-04"]，CSLT-03/GenerationStatus 的 x-consumers 同样包含 ["CSLT-04"]，两方契约对齐。✅
- 依赖关系对齐：
  - CSLT-04 → CSLT-03：GenerationChunk（AsyncGenerator 产出）、GenerationStatus（finish_reason/GenerationStatus 枚举）— 上游已定义，CSLT-04 作为消费者直接消费。✅ 已对齐
  - CSLT-04 → DEPLOY-02：SSE 长连接需 Nginx 代理配置就绪（依赖关系分析标记为 ⚠️ 推断），将在设计文档阶段确认。不影响本阶段。
  - CSLT-08 → CSLT-04：下游消费方尚未设计，不存在反向依赖冲突。

**审查的相关文档**：
- CSLT-03 应急方案生成-落地规范.md（已冻结）
- CSLT-01/02 危机分级判定/RAG语义检索-落地规范.md（已冻结）
- KNOW-01 科普内容管理-落地规范.md（已冻结）
- AUTH-01～06 用户注册/登录/Token续期/RBAC鉴权/UI/会话管理-落地规范.md（已冻结）
- PROF-01/05 个人档案管理/档案隐私控制-落地规范.md（已冻结）
- OBS-01/04 结构化日志/健康检查-落地规范.md（已冻结）
- SEC-01/04/05 传输存储安全/防刷限流/输入校验防护-落地规范.md（已冻结）
- DEPLOY-01～05 容器编排/反向代理/CI_CD/数据库迁移/环境配置-落地规范.md（已冻结）
- CASE-01/04 案例录入管理/案例向量化入库-落地规范.md（已冻结）
- docs/contracts/CSLT-03/GenerationChunk.json（maturity: draft）
- docs/contracts/CSLT-03/GenerationStatus.json（maturity: draft）
- docs/功能设计/_contracts.md
- docs/功能设计/功能模块全拆解.md
- docs/功能设计/模块依赖关系分析.md
- docs/篝火智答-技术栈设计.md

**结论**：✅ 无冲突。CSLT-04 是纯数据推送通道模块，不定义持久化状态、不引入新数据源、不修改上游 CSLT-03 产出内容。与已有模块的接口边界清晰（仅消费 CSLT-03 的 GenerationChunk 和 GenerationStatus），无反向依赖冲突。CSLT-08 尚未设计，不存在反向依赖冲突。与 DEPLOY-02 的 Nginx SSE 配置依赖将在设计文档阶段确认（非阻塞性）。

---

## 2026-05-26 16:56 — KNOW-01 科普内容管理 — 一致性检查

**检查范围**：模块 KNOW-01 首次进入设计流程，项目内尚无已落地的规格文档（*-落地规范.md）。

**扫描检查项**：
- 模块编号冲突：无已有规格文档，无冲突
- 状态定义冲突：无已有规格文档，无冲突
- 接口命名冲突：无已有规格文档，无冲突
- 同名异构类型：无已有规格文档，无冲突
- 循环依赖迹象：依赖关系分析报告确认零循环依赖

**结论**：✅ 无冲突。KNOW-01 为项目首个进入设计流程的模块，无存量规格文档需要对比。

---

## 2026-05-26 21:08:30 — AUTH-04 五级RBAC鉴权 — 一致性检查

**检查范围**：模块 AUTH-04 设计文档生成阶段（s07），全量扫描已有规格文档和设计文档。

**扫描检查项**：
- 模块编号冲突：无。AUTH-04 编号唯一。
- 状态定义冲突：无。AUTH-04 无状态流转，其他模块的状态定义（ArticleStatus、MigrationState 等）与权限校验无关。
- 接口命名冲突：无。本模块对外接口 `require_role()`、`UserContext`、`get_masked_phone()` 与已有模块无命名冲突。
- 同名异构类型：无。本模块定义的类型（`UserRole`、`UserContext`）在已有规格中未出现同名异构。
- 循环依赖迹象：无。AUTH-04 入度 8（最大安全枢纽），所有依赖方向为其他模块 → AUTH-04，AUTH-04 仅上游依赖 AUTH-02（JWT payload），无循环依赖。
- 角色命名兼容性：已通过双命名体系解决（英文枚举值 + `display_name` 中文映射），兼容 KNOW-01 已使用的 `require_role(["admin", "maintainer"])`。
- Depends 链兼容性：AUTH-04 的 `get_current_user` Depends 为 `request.state.user` 注入 `user_id` + `roles` 字段，兼容 SEC-05 的 `Depends(get_current_user)` 调用和 SEC-01 的 `request.state.user.roles` 读取。

**审查的相关文档**：
- KNOW-01 科普内容管理-落地规范.md（已冻结）
- SEC-01 传输存储安全-设计文档.md + 落地规范.md（已冻结）
- SEC-05 输入校验防护-设计文档.md + 落地规范.md（已冻结）
- OBS-01 结构化日志-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）

**结论**：✅ 无冲突。AUTH-04 的技术实现方案与全部已有规格文档兼容。双命名体系、Depends 链、脱敏职责分工均已与 KNOW-01/SEC-01/SEC-05 保持一致。

---

## 2026-05-26 21:35:00 — SEC-04 防刷限流 — 一致性检查

**检查范围**：模块 SEC-04 设计文档生成阶段（s07），全量扫描已有规格文档和设计文档。

**扫描检查项**：
- 模块编号冲突：无。SEC-04 编号唯一。
- 状态定义冲突：无。SEC-04 无状态流转（§1.7 明确声明无状态机），其他模块状态定义与限流无关。
- 接口命名冲突：无。SEC-04 不定义新的对外 API 端点，作为全局中间件在请求入口执行，与 SEC-01 预定义契约（`check_rate_limit`、`RateLimitConfig`、`RateLimitExceededResponse`）命名一致。
- 同名异构类型：无。SEC-04 复用的 3 份 SEC-01 契约（`check_rate_limit.json`、`RateLimitConfig.json`、`RateLimitExceededResponse.json`）在已有规格中无同名异构冲突。
- 循环依赖迹象：无。SEC-04 → SEC-01（共享 Redis 基础设施）、SEC-04 → AUTH-02（用户身份标识获取）、SEC-04 → DEPLOY-02（Nginx X-Forwarded-For 协同），均为合理单向依赖。

**审查的相关文档**：
- KNOW-01 科普内容管理-落地规范.md（已冻结）
- SEC-01 传输存储安全-落地规范.md（已冻结）
- SEC-05 输入校验防护-落地规范.md（已冻结）
- OBS-01 结构化日志-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）
- docs/contracts/SEC-01/check_rate_limit.json（maturity: draft）
- docs/contracts/SEC-01/RateLimitConfig.json（maturity: draft）
- docs/contracts/SEC-01/RateLimitExceededResponse.json（maturity: draft）

**结论**：✅ 无冲突。SEC-04 作为 SEC-01 限流契约的纯消费者，不定义新接口类型，不存在与已有模块的类型冲突。依赖方向均为单向，无循环依赖迹象。

---

## 2026-05-26 22:45:00 — AUTH-05 登录注册界面 — 一致性检查

**检查范围**：模块 AUTH-05 规格准备阶段（s05），全量扫描已有规格文档和设计文档，核对接口对齐。

**扫描检查项**：
- 模块编号冲突：无。AUTH-05 编号唯一。
- 状态定义冲突：无。AUTH-05 定义的 5 个 UI 状态（空闲/输入中/提交中/成功/失败）为前端组件内部状态，与其他模块（CASE-03 审核状态机、DEPLOY-04 迁移状态等）无交集。
- 接口命名冲突：无。AUTH-05 为纯 UI 表现层（L1a），不定义后端 API 端点或 Service 接口，所有数据收发通过 `useAuth()` Hook 桥接，与已有模块无接口命名冲突。
- 角色命名兼容性：AUTH-05 意图文档使用中文角色标签（家属/老师/专家）作为 UI 展示文本，AUTH-04 落地规范使用英文枚举值（family/teacher/expert）。两者为显示层与数据层的标准映射关系，不构成冲突。需在规范阶段明确 UI 标签 → 枚举值的转换映射。
- 注册字段对齐：AUTH-05 注册表单字段（用户名、密码、角色类型、手机号码、真实姓名）与 AUTH-01 RegisterRequest 契约完全对齐，无新增字段或冲突。
- 依赖方向验证：AUTH-05 → AUTH-01（注册调用）、AUTH-05 → AUTH-02（登录调用）、AUTH-05 → AUTH-06（状态感知）。均为单向强调用依赖，与模块依赖关系分析一致，无循环依赖。

**审查的相关文档**：
- AUTH-01 用户注册-意图文档.md（已冻结）
- AUTH-01 用户注册-落地规范.md（已冻结）
- AUTH-04 五级RBAC鉴权-落地规范.md（已冻结）
- docs/contracts/AUTH-01/RegisterRequest.json（maturity: draft）
- docs/contracts/AUTH-01/RegisterResponse.json（maturity: draft）
- docs/contracts/AUTH-01/UserRole.json（maturity: draft）
- 功能模块全拆解.md
- 模块依赖关系分析.md

**结论**：✅ 无冲突。AUTH-05 作为纯前端 UI 表现层模块，与已有后端规格无业务或类型冲突。字段定义对齐、依赖方向合理、角色兼容需在规范阶段确认映射即可。

---

## 2026-05-26 22:50:31 — OBS-04 健康检查 — 规格准备一致性检查

**检查范围**：模块 OBS-04 规格准备阶段（s05），扫描已有规格文档和契约文件，核对依赖接口对齐。

**扫描检查项**：
- 模块编号冲突：无。OBS-04 编号唯一（07-系统可观测性分组）。
- 状态定义冲突：无。OBS-04 定义的业务健康状态（健康/降级/不健康）为实时计算出的瞬时观测状态，不持久化，与 DEPLOY-01 DeploymentState（STARTING/RUNNING/ERROR/STOPPED 容器生命周期）、KNOW-01 ArticleStatus（published/unpublished）等已有持久状态定义无交集。
- 接口命名冲突：无。OBS-04 对外暴露 `GET /health` 端点，路径项目中唯一，与其他模块 API 端点无冲突。
- 同名异构类型：无。OBS-04 尚无已注册的契约类型，在规范阶段定义响应数据模型时需注意不与现有契约（ContainerServiceName、DeploymentState、HealthCheckProbe 等）命名冲突。
- 循环依赖迹象：无。OBS-04 → DEPLOY-01（消费 HealthCheckProbe/DeploymentState/ContainerServiceName 契约，同时反向提供 /health 端点供 HEALTHCHECK 调用，为合理的时序依赖双向关系，非循环依赖）；OBS-04 → DEPLOY-05（消费 AppSettings）；OBS-04 → OBS-01（下游，健康变更记录日志）；OBS-04 → OBS-03（下游，健康变更触发告警）。全部为单向依赖或合理的双向协作关系。
- 依赖接口对齐：OBS-04 已作为消费者登记在 DEPLOY-01 的 4 项契约中（ContainerServiceName、HealthCheckProbe、DeploymentState、ServiceRestartPolicy）；已登记为 DEPLOY-05 AppSettings 的消费者。意图文档提及 3 项 DEPLOY-01 契约，缺少 ServiceRestartPolicy，为意图文档的微小遗漏，不影响技术可行性，将在规范阶段补充。

**审查的相关文档**：
- AUTH-01 用户注册-落地规范.md（已冻结）
- AUTH-04 五级RBAC鉴权-落地规范.md（已冻结）
- KNOW-01 科普内容管理-落地规范.md（已冻结）
- OBS-01 结构化日志-落地规范.md（已冻结）
- SEC-01 传输存储安全-落地规范.md（已冻结）
- SEC-04 防刷限流-落地规范.md（已冻结）
- SEC-05 输入校验防护-落地规范.md（已冻结）
- DEPLOY-01 容器编排-落地规范.md（已冻结）
- DEPLOY-02 反向代理路由-落地规范.md（已冻结）
- DEPLOY-03 CI_CD流水线-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）
- docs/contracts/DEPLOY-01/ContainerServiceName.json（maturity: draft）
- docs/contracts/DEPLOY-01/HealthCheckProbe.json（maturity: draft）
- docs/contracts/DEPLOY-01/DeploymentState.json（maturity: draft）
- docs/contracts/DEPLOY-01/ServiceRestartPolicy.json（maturity: draft）
- docs/contracts/DEPLOY-05/AppSettings.json（maturity: draft）
- 功能模块全拆解.md
- 模块依赖关系分析.md

**结论**：✅ 无冲突。OBS-04 的健康检查端点设计定位与全部已有规格文档兼容。依赖接口已在 DEPLOY-01 和 DEPLOY-05 契约中预先登记，消费关系清晰。意图文档遗漏 ServiceRestartPolicy 契约的消费关系，将在规格阶段补充更新。

---

## 2026-05-26 22:55:00 — DEPLOY-03 CI/CD流水线 — 规格准备一致性检查

**检查范围**：模块 DEPLOY-03 规格准备阶段（s05），全量扫描已有规格文档和契约文件。

**扫描检查项**：
- 模块编号冲突：无。DEPLOY-03 编号唯一（09-部署与运维分组）。
- 状态定义冲突：无。DEPLOY-03 不涉及自定义状态机，CI/CD 运行状态由 GitHub Actions 原生管理（queued/in_progress/completed），与已有模块的状态定义（ArticleStatus、DeploymentState、MigrationState 等）无交集。
- 接口命名冲突：无。DEPLOY-03 不定义后端 API 端点或服务接口。其"接口"为 GitHub Actions 工作流触发事件（push/pull_request/workflow_run/workflow_dispatch），与已有模块无接口命名冲突。
- 同名异构类型：无。DEPLOY-03 不定义结构化类型（type/model/schema），与已有模块无类型冲突。
- 循环依赖迹象：无。DEPLOY-03 出度依赖 DEPLOY-01（docker-compose.prod.yml 镜像构建）和 DEPLOY-04（迁移脚本），入度 0（无其他模块依赖 CI/CD 流水线），模块依赖关系分析确认零循环依赖。
- 依赖接口对齐：DEPLOY-03 CI Job 的服务容器配置（pgvector/pgvector:pg17、redis:7-alpine）与 DEPLOY-01 的容器定义一致；deply.yml 引用 `docker-compose.prod.yml` 与 DEPLOY-01 的编排定义一致；ci.yml 中 pytest 测试阶段与 QUAL-01 的测试命令约定一致。

**审查的相关文档**：
- DEPLOY-01 容器编排-落地规范.md（已冻结）
- DEPLOY-02 反向代理路由-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）
- KNOW-01 科普内容管理-落地规范.md（已冻结）
- 功能模块全拆解.md
- 模块依赖关系分析.md

**结论**：✅ 无冲突。DEPLOY-03 作为 CI/CD 基础设施模块，不定义与传统模块冲突的类型或 API。其依赖关系清晰单向，与已有 DEPLOY 分组模块（01/02/04/05）的接口对齐。当前落地规范 v1.0 为 AI 逆向推导版本，设计文档尚不存在，需在后续阶段补充。

---

## 2026-05-26 22:53:43 — PROF-05 档案隐私控制 — 设计文档生成阶段一致性检查

**检查范围**：模块 PROF-05 设计文档生成阶段（s07），全量扫描已有规格文档和设计文档。

**扫描检查项**：
- 模块编号冲突：无。PROF-05 编号唯一（03-个性化档案分组）。
- 状态定义冲突：无。PROF-05 不涉及持久化状态机（意图文档 §1.7 明确声明无状态流转），其他模块的状态定义（ArticleStatus、UserRole、DeploymentState 等）与隐私控制无关。
- 接口命名冲突：无。PROF-05 新增的类型（`PrivacyGuard`、`AccessRequest`、`AccessDecision`、`AccessOperation`、`AccessResult`、`VisibleScope`、`ForbiddenAccess` 异常）与已有模块定义的类型无命名冲突。
- 同名异构类型：无。PROF-05 定义的 `AccessOperation` 枚举六值（view/create/update/delete/professional_assess/unlink_teacher）与 KNOW-01 的 `ArticleStatus`（published/unpublished）、AUTH-04 的 `UserRole`（parent/teacher/expert/admin/maintainer）无交集，无同名异构风险。
- 循环依赖迹象：无。PROF-05 仅依赖 AUTH-04（上游 RBAC），被 PROF-01/03/04 依赖（下游消费方）。依赖方向全部单向：AUTH-04 → PROF-05 → PROF-01/03/04，无循环。
- 角色命名兼容性：PROF-05 直接复用 AUTH-04 的 `UserRole` 枚举（parent/teacher/expert/admin/maintainer）和双命名体系（英文枚举值 + display_name），访问矩阵五类角色（家属/老师/专家/管理员/维护人员）与 AUTH-04 层级完全一致。
- 依存接口对齐：PROF-05 的 `require_role()` Depends 消费方身份和 `get_current_user` Depends 请求人身份获取方式，与 AUTH-04 已有接口签名完全兼容。`ForbiddenAccess` 异常类继承 `AppException`，与项目统一异常体系兼容。

**审查的相关文档**：
- AUTH-01 用户注册-落地规范.md（已冻结）
- AUTH-04 五级RBAC鉴权-设计文档.md + 落地规范.md（已冻结）
- KNOW-01 科普内容管理-落地规范.md（已冻结）
- OBS-01 结构化日志-落地规范.md（已冻结）
- SEC-01 传输存储安全-落地规范.md（已冻结）
- SEC-04 防刷限流-落地规范.md（已冻结）
- SEC-05 输入校验防护-落地规范.md（已冻结）
- DEPLOY-01 容器编排-落地规范.md（已冻结）
- DEPLOY-02 反向代理路由-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）
- 功能模块全拆解.md
- 模块依赖关系分析.md
- docs/功能设计/_contracts.md

**业务矛盾裁决**：技术决策报告标记 4 项业务矛盾，已通过用户 4 项澄清解决：
1. Q1（隐藏删除）：解除关联后历史评估为软删除，不物理删除。
2. Q2（仅元数据）：管理员仅可查看聚合统计数据，不可查看任何业务内容字段。
3. Q3（全部可见）：关联老师和专家可见档案全部内容。
4. Q4（权限一致）：同一家庭多位家属权限完全一致。

**结论**：✅ 无冲突。PROF-05 的技术实现方案（双层鉴权架构、实时关系表查询、乐观锁并发控制）与全部已有规格文档兼容。依赖 AUTH-04 的接口已对齐，新增类型无冲突，4 项业务矛盾已通过用户裁决解决。

- OBS-01 结构化日志-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）
- 循环依赖迹象：无。SEC-04 → SEC-01（共享 Redis 基础设施）、SEC-04 → AUTH-02（用户身份标识获取）、SEC-04 → DEPLOY-02（Nginx X-Forwarded-For 协同），均为合理单向依赖。
- OBS-01 结构化日志-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）
## 2026-05-26 22:55:58 — AUTH-03 Token续期 — 一致性检查
**检查范围**：模块 AUTH-03 设计文档生成阶段（s07），全量扫描已有规格文档和设计文档。
- 模块编号冲突：无。AUTH-03 编号唯一。
- 状态定义冲突：无。AUTH-03 定义 Refresh Token 二态（valid/invalid），与 AUTH-01（用户状态）、AUTH-04（无状态）、KNOW-01（ArticleStatus）无重叠或冲突。
- 循环依赖迹象：无。AUTH-03 上游依赖 AUTH-02（Refresh Token 签发）和 SEC-04（限流保护），下游被 AUTH-04 和 AUTH-06 消费。依赖方向均为单向，无循环依赖。
- JWT payload 兼容性：SEC-01 定义的 `TokenPayload`（含 `sub`、`roles`、`kid`、`exp`、`iat`）为最小必需结构。AUTH-03 在此基础上增加 `jti`（JWT 标准声明）和 `type`（区分 access/refresh）字段，通过 JWT 现有声明扩展实现，不违反 SEC-01 契约的接口定义。
- Redis 黑名单 Key 前缀协调：AUTH-04 当前设计使用 `token_blacklist:{jti}` 作为角色变更失效 key。AUTH-03 的轮换黑名单使用 `token_blacklist:rotated:{jti}`，吊销黑名单使用 `token_blacklist:revoked:{jti}`，通过不同前缀实现同一 Redis 实例下的命名空间隔离。建议 AUTH-04 后续将其 key 前缀也调整为 `token_blacklist:revoked:{jti}` 以保持一致性。
- 降级策略一致性：AUTH-03 采用与 AUTH-04 一致的 fail-open 策略——Redis 不可用时跳过黑名单查询，仅依赖 JWT 签名验证。两模块降级行为对齐。
- 错误响应格式兼容：AUTH-03 使用 `{"detail": "..."}` 格式，与 KNOW-01、AUTH-04、SEC-01、SEC-05 的统一错误格式一致。
- AUTH-01 用户注册-设计文档.md + 落地规范.md（已冻结）
- OBS-01 结构化日志-落地规范.md（已冻结）
- DEPLOY-01～05 系列设计文档（已冻结）
**结论**：✅ 无冲突。AUTH-03 的技术实现方案与全部已有规格文档兼容。JWT payload 扩展通过现有声明字段实现，不违反 SEC-01 契约。Redis key 前缀建议已记录，留待 AUTH-04 后续迭代调整。依赖方向单向，无循环依赖迹象。
- OBS-01 结构化日志-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）
- 循环依赖迹象：无。SEC-04 → SEC-01（共享 Redis 基础设施）、SEC-04 → AUTH-02（用户身份标识获取）、SEC-04 → DEPLOY-02（Nginx X-Forwarded-For 协同），均为合理单向依赖。
- OBS-01 结构化日志-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）

---

## 2026-05-27 09:35 — CSLT-01 危机分级判定 — 材料准备一致性检查

**检查范围**：模块 CSLT-01 规格准备阶段（s05），全量扫描已有规格文档和设计文档，核对接口对齐与类型冲突。

**扫描检查项**：
- 模块编号冲突：无。CSLT-01 编号唯一（02-智能应急咨询分组首个进行意图编写的模块）。
- 状态定义冲突：无。CSLT-01 意图文档 §1.7 明确声明"本功能点不涉及持久化状态流转，故无需状态机"，与已有模块状态定义（OBS-04 HealthStatus、KNOW-01 ArticleStatus、DEPLOY-01 DeploymentState 等）无交集。
- 接口命名冲突：无。CSLT-01 输出类型（最终危机等级 轻度/中度/重度、判定来源列表、复核置信度、人工复核标记、阻断深度回答标记）为危机分级领域专有，与已有模块类型无命名冲突。
- 同名异构类型：无。CSLT-01 的业务类型与已有契约（LoginRequest、HealthCheckResponse、ArticleCategory、AccessOperation、UserRole 等）领域隔离，无同名异构风险。
- 循环依赖迹象：无。CSLT-01 入度 2（CSLT-07、PROF-02 数据输入）、出度 4（CSLT-03、CSLT-05、TICK-01、TICK-02 数据消费），另有 2 项共享资源依赖（SEC-02、KNOW-05 高危关键词库）。依赖方向均为单向，模块依赖关系分析确认为零循环依赖。
- 共享关键词库风险感知：CSLT-01 ↔ SEC-02 ↔ KNOW-05 三方共享高危关键词库的依赖关系已在模块依赖关系分析.md 记录为风险项 #1（CRITICAL关键词库三向共享），推荐方案为提取至 `packages/py-config/` 公共常量 `CRISIS_KEYWORDS` 单点维护。不构成规格阶段的阻塞性冲突。

**审查的相关文档**：
- AUTH-01～06 用户注册/登录/Token续期/RBAC鉴权/UI/会话管理-落地规范.md（已冻结）
- PROF-05 档案隐私控制-落地规范.md（已冻结）
- KNOW-01 科普内容管理-落地规范.md（已冻结）
- OBS-01/04 结构化日志/健康检查-落地规范.md（已冻结）
- SEC-01/04/05 传输存储安全/防刷限流/输入校验防护-落地规范.md（已冻结）
- DEPLOY-01～05 容器编排/反向代理/CI_CD/数据库迁移/环境配置-落地规范.md（已冻结）
- 功能模块全拆解.md
- 模块依赖关系分析.md
- docs/功能设计/_contracts.md

**结论**：✅ 无冲突。CSLT-01 作为 02-智能应急咨询分组首个模块，其业务类型与已有 18 份规格文档的接口契约领域隔离，无任何命名或类型冲突。关键词库共享风险已由依赖关系分析记录并给出推荐方案，不阻塞规格阶段。
- OBS-01 结构化日志-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）
- 循环依赖迹象：无。SEC-04 → SEC-01（共享 Redis 基础设施）、SEC-04 → AUTH-02（用户身份标识获取）、SEC-04 → DEPLOY-02（Nginx X-Forwarded-For 协同），均为合理单向依赖。
- OBS-01 结构化日志-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）
- OBS-01 结构化日志-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）
- 循环依赖迹象：无。SEC-04 → SEC-01（共享 Redis 基础设施）、SEC-04 → AUTH-02（用户身份标识获取）、SEC-04 → DEPLOY-02（Nginx X-Forwarded-For 协同），均为合理单向依赖。
- OBS-01 结构化日志-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）
---

## 2026-05-27 09:30 — CSLT-02 RAG语义检索 — 材料准备一致性检查

**检查范围**：模块 CSLT-02 规格准备阶段（s05），全量扫描已有规格文档和契约文件，核对依赖接口对齐。

**扫描检查项**：
- 模块编号冲突：无。CSLT-02 编号唯一（02-智能应急咨询分组）。
- 状态定义冲突：无。CSLT-02 意图文档 §1.7 明确声明无状态流转，每次检索为独立同步请求-响应操作。其他模块的状态定义（ArticleStatus、DeploymentState、MigrationState、UserRole 等）与本模块无交集。
- 接口命名冲突：无。CSLT-02 尚未定义对外接口类型。已有模块的接口类型（ArticleSearchParams、ArticleSearchResult 等 KNOW-01 全文检索类型、PROF-05 隐私控制类型、AUTH/OBS/DEPLOY/SEC 系列接口）均与向量语义检索领域无命名交集。
- 同名异构类型：无。KNOW-01 的 ArticleSearchParams/ArticleSearchResult（PostgreSQL ts_vector 全文检索）与 CSLT-02 将定义的向量检索类型分属不同领域（全文检索 vs 语义检索），不存在同名异构风险。
- 循环依赖迹象：无。CSLT-02 出度 4（PROF-02 接收过滤条件、CASE-04 依赖向量索引、CASE-06 感知淘汰状态、向下游 CSLT-03 输出结果），入度 5（CSLT-03/CSLT-05/CSLT-08/PROF-02/QUAL-02 依赖本模块）。全部为单向依赖或合理的数据供应链关系，模块依赖关系分析确认零循环依赖。
- 嵌入模型配置对齐：DEPLOY-05/AppSettings.json 已定义 EMBEDDING_MODEL（默认 text-embedding-v4）和 EMBEDDING_DIMENSION（默认 1024），CSLT-02 应消费该配置而非硬编码。与项目技术栈设计（ADR-003 pgvector 方案）完全一致。
- 技术栈对齐：CSLT-02 使用 pgvector HNSW 索引、text-embedding-v4（1024 维）、LangChain 0.3+、FastAPI 0.115+，与 docs/篝火智答-技术栈设计.md 声明的技术栈一致。无技术栈根本性冲突。
- CSLT-02 位于分层架构 L5（业务能力层），依赖方（CASE-04、CASE-06、PROF-02）尚未进入设计流程，被依赖方（CSLT-03、CSLT-08 等）同样未启动。CSLT-02 需在自身规范阶段首先锁定对外接口契约，为上下游提供稳定的消费接口。

**审查的相关文档**：
- KNOW-01 科普内容管理-落地规范.md（已冻结）
- AUTH-01 用户注册-落地规范.md（已冻结）
- AUTH-02 用户登录-落地规范.md（已冻结）
- AUTH-03 Token续期-落地规范.md（已冻结）
- AUTH-04 五级RBAC鉴权-落地规范.md（已冻结）
- AUTH-05 登录注册界面-落地规范.md（已冻结）
- AUTH-06 认证会话管理-落地规范.md（已冻结）
- PROF-05 档案隐私控制-落地规范.md（已冻结）
- OBS-01 结构化日志-落地规范.md（已冻结）
- OBS-04 健康检查-落地规范.md（已冻结）
- SEC-01 传输存储安全-落地规范.md（已冻结）
- SEC-04 防刷限流-落地规范.md（已冻结）
- SEC-05 输入校验防护-落地规范.md（已冻结）
- DEPLOY-01 容器编排-落地规范.md（已冻结）
- DEPLOY-02 反向代理路由-落地规范.md（已冻结）
- DEPLOY-03 CI/CD流水线-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）
- docs/contracts/DEPLOY-05/AppSettings.json（maturity: draft）
- docs/contracts/_index.json
- 功能模块全拆解.md
- 模块依赖关系分析.md
- 篝火智答-技术栈设计.md

**结论**：✅ 无冲突。CSLT-02 的技术方案（pgvector HNSW 混合检索、text-embedding-v4 语义嵌入）与全部已有规格文档和技术栈设计兼容。嵌入配置可通过 DEPLOY-05 消费，无需自行定义。当前项目尚无与向量语义检索领域重叠的已有契约类型。CSLT-02 在规范阶段首次定义本模块的向量检索接口类型时，需注意与未来 CASE-04 的向量索引契约对齐。
## 2026-05-27 14:31 — CSLT-03 应急方案生成 — 材料准备一致性检查

**检查范围**：模块 CSLT-03 规格准备阶段（s05），全量扫描已有规格文档和契约文件，核对上游接口对齐与类型冲突。

**扫描检查项**：
- 模块编号冲突：无。CSLT-03 编号唯一（02-智能应急咨询分组）。
- 状态定义冲突：无。CSLT-03 意图文档 §1.7 明确声明本模块为"无状态生成服务——每次应急咨询独立执行 Prompt 组装与 LLM 调用，不维护跨咨询会话的持久状态"；内部处理阶段（等待输入→组装中→生成中→已完成→阻断输出）为运行时内存阶段，不持久化。与已有模块状态定义（ArticleStatus、DeploymentState、MigrationState、CrisisLevel 等无状态枚举）无交集。
- 接口命名冲突：无。CSLT-03 尚无已定义的对外接口（将在规范阶段定义），已有模块的接口命名（judge_crisis、hybrid_search、require_role、ArticleSearchParams、AccessRequest 等）均与本模块待定义的生成接口无命名交集。
- 同名异构类型：无。CSLT-03 的业务类型（Prompt 结构、四段式输出、来源引用清单）为 Prompt 工程领域专有，与已有 40+ 份契约类型的领域隔离，无同名异构风险。
- 循环依赖迹象：无。CSLT-03 依赖链为 CSLT-01→CSLT-02→CSLT-03→CSLT-04/CSLT-05，为单向数据管道。模块依赖关系分析确认 CSLT-03 入度 2（CSLT-01 危机等级 + 阻断标记、CSLT-02 案例切片列表）、出度 2（CSLT-04 流式推送、CSLT-05 置信度校验），全部为单向依赖。

**上游接口兼容性审查**：
- **CSLT-01 → CSLT-03**：CSLT-01 输出 `CrisisJudgmentResult`（含 `final_level: CrisisLevel`、`block_deep_response: bool`、`judgment_sources`、`degradation_note`）→ CSLT-03 意图文档 §1.6.1 输入字段「危机等级与阻断标记」精确接收。字段类型和枚举值完全对齐，无契约间隙。
- **CSLT-02 → CSLT-03**：CSLT-02 输出 `SemanticSearchResult`（含 `results: list[CaseSliceDto]`）→ CSLT-03 意图文档 §1.6.1 输入字段「案例切片列表」精确接收。`CaseSliceDto` 包含的 `slice_text`、`case_id`、`evidence_level`、`similarity_score` 字段与 CSLT-03 意图文档中的业务约束描述完全一致。

**审查的相关文档**：
- CSLT-01 危机分级判定-落地规范.md（已冻结）
- CSLT-02 RAG语义检索-落地规范.md（已冻结）
- AUTH-01~06 用户认证系列-落地规范.md（已冻结）
- PROF-05 档案隐私控制-落地规范.md（已冻结）
- KNOW-01 科普内容管理-落地规范.md（已冻结）
- OBS-01/04 结构化日志/健康检查-落地规范.md（已冻结）
- SEC-01/04/05 安全合规系列-落地规范.md（已冻结）
- DEPLOY-01~05 部署运维系列-落地规范.md（已冻结）
- CASE-01/04 真实案例库管理-落地规范.md（已冻结）
- docs/contracts/CSLT-01/CrisisJudgmentResult.json（maturity: draft）
- docs/contracts/CSLT-01/CrisisLevel.json（maturity: draft）
- docs/contracts/CSLT-02/SemanticSearchResult.json（maturity: draft）
- docs/contracts/CSLT-02/CaseSliceDto.json（maturity: draft）
- docs/contracts/CSLT-01/JudgmentLayerResult.json（maturity: draft）
- docs/功能设计/功能模块全拆解.md
- 模块依赖关系分析.md
- 篝火智答-技术栈设计.md
- docs/功能设计/_contracts.md

**业务矛盾裁决**：未发现业务矛盾。意图文档 §1.12 列出的 8 项技术决策（Prompt 模板设计、LLM 调用参数精确值、冷却期实现机制、数据模型技术类型、异常处理技术实现、档案上下文格式化方式、生成超时精确阈值、安全提示文本预设内容）均在留给规范阶段的合理范围内，无业务矛盾标记。

**结论**：✅ 无冲突。CSLT-03 作为 CSLT-01 和 CSLT-02 的下游纯消费者，其输入类型与上游已锁定契约完全对齐。本模块不定义新类型与已有契约冲突，依赖方向全部单向。下游模块 CSLT-04、CSLT-05 尚未设计，不存在反向依赖冲突。8 项技术决策归入规范阶段处理，不阻塞 s05 阶段进展。

---


**检查范围**：模块 PROF-01 规格准备阶段（s05），全量扫描已有规格文档和契约文件，核对依赖接口对齐与类型冲突。

**扫描检查项**：
- 模块编号冲突：无。PROF-01 编号唯一（03-个性化档案分组首个进入设计流程的模块）。
- 状态定义冲突：无。PROF-01 意图文档 §1.7 明确声明"本功能点不涉及状态流转，故无需状态机"，与已有模块状态定义（ArticleStatus、HealthStatus、DeploymentState、MigrationState 等）无交集。
- 接口命名冲突：无。PROF-01 尚未定义对外接口（本阶段仅准备材料），已有模块的接口类型（PROF-05/AccessOperation、AUTH-04/UserRole、CSLT-01/CrisisLevel 等）均与个人档案管理领域无命名交集。
- 同名异构类型：无。PROF-01 尚无已注册的契约类型，在规范阶段定义 Profile 相关类型时需注意不与已有契约命名冲突。
- 循环依赖迹象：无。PROF-01 入度 3（PROF-02/PROF-03/PROF-07 消费 — 均为 PROF 域内下游），出度 3（PROF-05 调用访问门控、AUTH-04 调用角色校验、SEC-03 调用 PII 检测 — 不确定性见注），全部为单向合理依赖。模块依赖关系分析确认为零循环依赖。

**依赖接口对齐**：
- PROF-01 → PROF-05：PROF-05 契约中 AccessOperation 枚举的 view/create/update/delete 值与 PROF-01 的 CRUD 操作一一对应。PROF-05 访问矩阵中"家属本人全权"已覆盖 PROF-01 所有操作权限需求。✅ 已对齐
- PROF-01 → AUTH-04：family 角色标识已在 AUTH-04 契约中定义，PROF-01 作为消费者可直接复用。✅ 已对齐
- PROF-01 → SEC-03：PII 检测的调用方式（是否实时调用 SEC-03 的检测接口，还是仅在 UI 层提示用户避免填写敏感信息）为不确定性项（依赖关系分析标记为 ⚠️），需在规范阶段确认。不影响本阶段。

**审查的相关文档**：
- PROF-05 档案隐私控制-落地规范.md（已冻结）
- PROF-05 档案隐私控制-设计文档.md（已冻结）
- KNOW-01 科普内容管理-落地规范.md（已冻结）
- AUTH-01～06 用户注册/登录/Token续期/RBAC鉴权/UI/会话管理-落地规范.md（已冻结）
- CSLT-01/02 危机分级判定/RAG语义检索-落地规范.md（已冻结）
- OBS-01/04 结构化日志/健康检查-落地规范.md（已冻结）
- SEC-01/04/05 传输存储安全/防刷限流/输入校验防护-落地规范.md（已冻结）
- DEPLOY-01～05 容器编排/反向代理/CI_CD/数据库迁移/环境配置-落地规范.md（已冻结）
- CASE-01/04 案例录入管理/案例向量化入库-落地规范.md（已冻结）
- docs/contracts/PROF-05/AccessOperation.json（maturity: draft）
- docs/contracts/PROF-05/AccessRequest.json（maturity: draft）
- docs/contracts/PROF-05/AccessDecision.json（maturity: draft）
- docs/contracts/PROF-05/VisibleScope.json（maturity: draft）
- docs/contracts/AUTH-04/UserRole.json（maturity: draft）
- docs/功能设计/_contracts.md
- docs/功能设计/功能模块全拆解.md
- docs/功能设计/模块依赖关系分析.md
- docs/篝火智答-技术栈设计.md

**结论**：✅ 无冲突。PROF-01 作为 03-个性化档案分组首个进入设计流程的模块，其 CRUD 语义与已有 PROF-05 契约完全对齐。依赖方向均为单向合理依赖，无循环依赖迹象。与 SEC-03 的 PII 检测调用方式将在规范阶段确认（非阻塞性）。建议在规范阶段首先定义 Profile 数据模型契约，为 PROF 域下游模块（PROF-02/PROF-03/PROF-07）提供稳定的消费接口。

---

## 2026-05-27 21:37:16 — CSLT-08 咨询编排逻辑 — 材料准备一致性检查

**检查范围**：模块 CSLT-08 规格准备阶段（s05），全量扫描已有规格文档和契约文件，核对依赖接口对齐与类型冲突。

**扫描检查项**：
- 模块编号冲突：无。CSLT-08 编号唯一（02-智能应急咨询分组），与已有模块无冲突。
- 状态定义冲突：无。CSLT-08 定义的 8 种前端业务状态（空闲、选择行为类型、提交中、流式接收中、已完成、工单引导、提交失败、流传输失败）为前端编排领域专有状态机，与已有模块的状态定义（KNOW-01 ArticleStatus、DEPLOY-01 DeploymentState、OBS-04 HealthStatus、PROF-03 SeverityLevel 等）领域隔离，无交集。
- 接口命名冲突：无。CSLT-08 为前端 L1b 逻辑层模块（位于 `logics/consult/`），不定义新的后端 API 端点或 Service 接口。其消费类型（BehaviorTypeCategory、CrisisLevel、ChunkEvent/DoneEvent/ErrorEvent/HeartbeatEvent、ValidationVerdict 等）全部来自已有 CSLT-01/03/04/05/06 的已发布契约，无新增接口命名冲突。
- 同名异构类型：无。CSLT-08 复用已有契约类型的同名定义（CrisisLevel/BehaviorTypeCategory/ValidationVerdict 等），保持同名同构。已有模块间的同名异构（PROF-03 SeverityLevel vs CASE-01 SeverityLevel）与 CSLT-08 无关。
- 循环依赖迹象：无。CSLT-08 出度 7（CSLT-01~06 + AUTH-06 + PROF-07，全部单向调用），入度 2（CSLT-07 + KNOW-05）。模块依赖关系分析确认零循环依赖。CSLT-07→CSLT-08 为前端 L1a→L1b 标准分层调用，非循环依赖。

**上游接口兼容性审查**：
- CSLT-01 → CSLT-08：`CrisisJudgmentResult`（含 `final_level: CrisisLevel`、`block_deep_response: bool`、`manual_review_flag: bool`）— CSLT-08 意图文档 §1.6.1 输入字段「危机判定结果」精确接收。字段类型和枚举值完全对齐。✅
- CSLT-04 → CSLT-08：SSE 四类事件（ChunkEvent/DoneEvent/ErrorEvent/HeartbeatEvent）— CSLT-08 作为下游消费者直接消费，CSLT-04 契约中 `x-consumers` 已登记含 CSLT-08。✅
- CSLT-05 → CSLT-08：`ConfidenceValidationOutput`（含 `confidence_score: float`、`verdict: ValidationVerdict`、`ticket_triggered: bool`）— CSLT-08 意图文档 §1.6.1 输入字段「置信度校验结论」精确接收。✅
- CSLT-06 → CSLT-08：`ConsultationHistoryListItem`/`ConsultationHistoryDetail` — 历史查询接口完全兼容。✅

**依赖接口对齐**：
- CSLT-08 → CSLT-04：SSE 事件流消费方 — 依赖关系分析标记为 ✅ 确定，CSLT-04 契约已登记 CSLT-08 为消费者。✅ 已对齐
- CSLT-08 → CSLT-01：危机等级消费方 — 依赖关系分析标记为 ✅ 确定，CSLT-01 契约已登记 CSLT-08 为消费者。✅ 已对齐
- CSLT-08 → CSLT-05：置信度校验结论消费方 — 依赖关系分析标记为 ✅ 确定，CSLT-05 契约已登记 CSLT-08 为消费者。✅ 已对齐
- CSLT-08 → CSLT-06：归档触发 + 历史查询 — 依赖关系分析标记为 ✅ 确定。✅ 已对齐
- CSLT-08 → TICK-09：工单跳转 — CSLT-08 通过"联系专家"按钮移交控制权至 TICK-09，依赖方向明确。CSLT-08 不调用 TICK-09 后端 API，仅进行前端路由跳转。✅ 已对齐
- CSLT-08 → AUTH-06：前端 httpClient Token 自动注入 — 前端标准依赖。✅ 已对齐

**技术栈对齐**：CSLT-08 技术栈（Taro 4.x / React 18.x / Zustand 5.x / TypeScript 5.x）与 `docs/篝火智答-项目结构.md` §6.1 声明的 L1b 前端逻辑层技术栈完全一致。无技术栈根本性冲突。

**意图缺陷结论**：无。意图文档完整定义了 8 种业务状态与法定转换路径、5 输入 + 5 输出业务定义、3 种异常策略、7 条验收标准、10 项技术决策留白。无性能指标不可达成、无技术栈冲突、无业务规则自相矛盾。

**审查的相关文档**：
- CSLT-01 危机分级判定-落地规范.md（已冻结）
- CSLT-02 RAG语义检索-落地规范.md（已冻结）
- CSLT-03 应急方案生成-落地规范.md（已冻结）
- CSLT-04 流式应答推送-落地规范.md（已冻结）
- CSLT-05 置信度后校验-落地规范.md（已冻结）
- CSLT-06 咨询历史管理-落地规范.md（已冻结）
- AUTH-01~06 用户认证系列-落地规范.md（已冻结）
- PROF-01/03/05 个人档案/事件记录/隐私控制-落地规范.md（已冻结）
- KNOW-01 科普内容管理-落地规范.md（已冻结）
- CASE-01/04/09 案例录入/向量化入库/管理逻辑-落地规范.md（已冻结）
- OBS-01/04 结构化日志/健康检查-落地规范.md（已冻结）
- SEC-01/04/05 安全合规系列-落地规范.md（已冻结）
- DEPLOY-01~05 部署运维系列-落地规范.md（已冻结）
- docs/contracts/CSLT-01/CrisisJudgmentResult.json（maturity: draft）
- docs/contracts/CSLT-01/CrisisLevel.json（maturity: draft）
- docs/contracts/CSLT-01/BehaviorTypeCategory.json（maturity: draft）
- docs/contracts/CSLT-04/ChunkEvent.json（maturity: draft）
- docs/contracts/CSLT-04/DoneEvent.json（maturity: draft）
- docs/contracts/CSLT-04/ErrorEvent.json（maturity: draft）
- docs/contracts/CSLT-04/HeartbeatEvent.json（maturity: draft）
- docs/contracts/CSLT-05/ConfidenceValidationOutput.json（maturity: draft）
- docs/contracts/CSLT-05/ValidationVerdict.json（maturity: draft）
- docs/contracts/CSLT-06/ConsultationHistoryCreate.json（maturity: draft）
- docs/contracts/CSLT-06/ConsultationHistoryListItem.json（maturity: draft）
- docs/contracts/CSLT-06/ConsultationHistoryDetail.json（maturity: draft）
- docs/功能设计/_contracts.md
- docs/功能设计/功能模块全拆解.md
- docs/功能设计/模块依赖关系分析.md
- docs/篝火智答-技术栈设计.md
- docs/篝火智答-项目结构.md

**结论**：✅ 无冲突。CSLT-08 作为前端 L1b 逻辑层模块，不定义新的后端 API 契约，仅消费已有模块的已锁定接口。其 8 状态机在项目中唯一，依赖方向全部单向，零循环依赖。上游 6 个模块（CSLT-01/03/04/05/06 + AUTH-06）的接口契约均已对齐。10 项技术决策归入规范阶段处理，不阻塞 s05 阶段进展。
