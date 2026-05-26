# 同步问题记录

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
- OBS-01 结构化日志-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）
- 循环依赖迹象：无。SEC-04 → SEC-01（共享 Redis 基础设施）、SEC-04 → AUTH-02（用户身份标识获取）、SEC-04 → DEPLOY-02（Nginx X-Forwarded-For 协同），均为合理单向依赖。
- OBS-01 结构化日志-落地规范.md（已冻结）
- DEPLOY-04 数据库迁移-落地规范.md（已冻结）
- DEPLOY-05 环境配置管理-落地规范.md（已冻结）