# 同步问题报告 — AUTH-01 用户注册

---

## [2026-05-26T21:25:20] MODULE: AUTH-01 用户注册

### 处理摘要
- **场景**: full_design
- **执行阶段**: s01, s03, s04, s05, s06, s07, s08, s09, s10
- **状态**: completed
- **产物**:
  - docs/功能设计/01-用户认证与授权/AUTH-01-用户注册/AUTH-01-用户注册-意图文档.md
  - docs/功能设计/01-用户认证与授权/AUTH-01-用户注册/AUTH-01-用户注册-设计文档.md
  - docs/功能设计/01-用户认证与授权/AUTH-01-用户注册/AUTH-01-用户注册-落地规范.md
  - docs/contracts/AUTH-01/RegisterRequest.json
  - docs/contracts/AUTH-01/RegisterResponse.json
  - docs/contracts/AUTH-01/UserRole.json
  - docs/contracts/AUTH-01/_module-index.json

### 同步矛盾

#### [medium] contract-conflict: SEC-01 hash_password 契约消费者列表遗漏 AUTH-01
- **描述**: SEC-01 的 `hash_password.json` 契约中 `x-consumers` 当前仅列出 `["AUTH-02"]`，但 AUTH-01 注册流程也调用 `hash_password()` 对用户密码执行 bcrypt 哈希。消费者追踪不完整，影响 SEC-01 契约的消费者影响面分析准确性。
- **来源阶段**: s10-contract-harmonize
- **影响模块**: SEC-01
- **建议方案**: 通知 SEC-01 更新 `docs/contracts/SEC-01/hash_password.json`，在 `x-consumers` 数组中追加 `"AUTH-01"`。同时更新 `docs/contracts/SEC-01/_module-index.json` 中 `hash_password` 条目的 `consumers` 列表。

#### [medium] contract-conflict: DEPLOY-05 AppSettings 未定义 BCRYPT_ROUNDS 配置字段
- **描述**: DEPLOY-05 的 `AppSettings.json` 契约定义了 18 项配置字段（涵盖数据库、缓存、LLM、嵌入模型、对象存储、JWT、限流七个维度），但未包含 `BCRYPT_ROUNDS` 字段。AUTH-01 的 `hashing.py` 通过 `settings.get("BCRYPT_ROUNDS", 12)` 降级逻辑工作，当前无功能阻塞（默认值 12 符合安全/性能平衡）。但生产环境中运维无法通过环境变量调节 bcrypt rounds 参数。
- **来源阶段**: s09-spec-design-doc
- **影响模块**: DEPLOY-05
- **建议方案**: DEPLOY-05 在后续迭代中向 `AppSettings.json` 追加 `BCRYPT_ROUNDS` 字段（类型 `integer`，最小值 4，默认值 12，可选非必填），并同步更新 `docs/contracts/DEPLOY-05/_module-index.json`。同时将 AUTH-01 加入 `AppSettings` 的 `x-consumers` 列表。

---

### 遗留问题（从上周期延续）

无。AUTH-01 为本模块首次进入完整设计流程，无上周期遗留问题。
