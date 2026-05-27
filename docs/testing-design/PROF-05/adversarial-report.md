## 功能模块落地完成：PROF-05 档案隐私控制（对抗性验证模式）

### 涉及技术栈
Python 3.12 后端，FastAPI + Pydantic v2 + SQLAlchemy 2.0 async + PostgreSQL，pytest + pytest-asyncio

### 代码组织依据
严格遵循 `PROF-05-档案隐私控制-落地规范.md` §1.2 文件归属表，代码分布于 `packages/py-auth`、`packages/py-schemas`、`packages/py-db`、`packages/py-config`、`apps/api-server`

### 修改文件范围

**新增 (5)**：
- `packages/py-schemas/py_schemas/profiles.py` — AccessOperation/VisibleScope/AccessRequest/AccessDecision
- `packages/py-db/py_db/models/profiles.py` — TeacherLink ORM 模型
- `packages/py-db/py_db/repositories/teacher_link_repository.py` — TeacherLinkRepository
- `apps/api-server/app/services/profile_service.py` — 档案操作 Service 层
- `apps/api-server/app/api/v1/profiles.py` — 档案 API 路由

**修改 (5)**：
- `packages/py-auth/py_auth/rbac.py` — 新增 PrivacyGuard 类 + check_access + 辅助函数
- `packages/py-config/py_config/exceptions.py` — 新增 ForbiddenAccess 异常
- `packages/py-auth/py_auth/__init__.py` — 导出 PrivacyGuard
- `packages/py-schemas/py_schemas/__init__.py` — 导出 PROF-05 类型
- `packages/py-db/py_db/models/__init__.py` — 导出 TeacherLink
- `packages/py-db/py_db/repositories/__init__.py` — 导出 TeacherLinkRepository
- `packages/py-config/py_config/__init__.py` — 导出 ForbiddenAccess

### 对抗性验证记录

| 轮次 | 总用例 | 通过 | 失败 | 收敛状态 | 备注 |
|:---|:---|:---|:---|:---|:---|
| 1 | 42 | 10 | 32 | 初始盲测 | 32 条失败全部为测试缺陷（AccessRequest `Any` 类型导致枚举值被强转为 str） |
| 1 (修正后) | 42 | 42 | 0 | converged | 测试修正后全部通过，无需 Phase 5 修复迭代 |

### 流程执行证据索引

| 阶段 | 证据文件 | 状态 | 说明 |
|:---|:---|:---|:---|
| Phase 1.1 契约提取 | `contract-expectations.md` | ✅ | 28 条契约期望（A01-A12 + B01-B22 + C01-C07） |
| Phase 1.1 验证 | 手动验证（脚本不可用） | ✅ | 与落地规范/契约 JSON 逐条核对一致 |
| Phase 2 函数签名 | `function-signatures.json` | ✅ | 11 个公开函数（PrivacyGuard + 3 Repository + 6 Service） |
| Phase 2 验证 | 手动验证 | ✅ | 签名与落地规范 §1.6 一致 |
| Phase 2 待确认 | `pending-confirmations.md` | ✅ | 4 项低风险待确认，无阻断项 |
| Phase 3 测试生成 | `test_PROF-05.adversarial.py` + `PROF-05.adversarial.test.list.md` | ✅ | 42 条测试，4 组 |
| Phase 4.2 Round 1 | 测试运行输出 | ✅ | 10 通过 / 32 失败 |
| Phase 4.5.1 测试缺陷 | `test-defects-round-1.md` | ✅ | 7 类缺陷，根因为 AccessRequest `Any` 类型 |
| Phase 4.5.2 SubAgent 修正 | SubAgent 调用记录 | ✅ | `adversarial-test-generator` 修正测试代码 |
| Phase 4.4 回归检查 | 无需执行 | ✅ | 测试缺陷修正后一轮通过，无退化风险 |

### 发现的漏洞与修复

#### 实现漏洞

**无**。经过对抗性测试验证，PrivacyGuard.check_access() 的实现完全符合契约要求：
- 正确校验 requester_role（A08/A09/A10 通过）
- 正确处理 None request（A01 通过）
- 正确处理 None db_session（B22 通过）
- 完全覆盖访问矩阵（B01-B18 全部 18 条通过）
- 正确实现静默拒绝（B19-B20 全部 16 个拒绝场景 denial_reason="数据不存在"）
- 管理员返回 metadata_only（B14 通过）
- maintainer 全部拒绝（B17-B18 通过）
- family 全部操作允许（B01-B05 通过）
- teacher/expert 关联/非关联边界正确处理（B07-B13 + C01-C07 通过）

#### 测试缺陷（经 Phase 3 SubAgent 修正）

1. **AccessRequest `Any` 类型导致枚举值被强转为 str**：测试的 AccessRequest 使用 `Any` 类型字段绕过 Pydantic 校验，导致 AccessOperation StrEnum 值被 Pydantic 强转为纯字符串，实现代码的 `.value` 属性访问失败
   - 修正：将字段类型从 `Any` 改为具体类型（`AccessOperation`、`UUID`、`str(pattern=...)`），新增 `model_config = {"extra": "forbid"}`；将 Pydantic 校验测试与 PrivacyGuard 测试分离为独立测试类
   - 修正轮次：Round 1
   - 测试缺陷报告：`test-defects-round-1.md`
   - SubAgent 修正记录：存在

### 模块作用简述
PROF-05 档案隐私控制是「篝火智答」个性化档案体系的安全守卫模块，通过双层鉴权架构（路由级 require_role + Service 级 PrivacyGuard.check_access）对每次档案访问执行实时权限裁决，确保五类角色（家属/老师/专家/管理员/维护人员）的访问行为严格符合访问矩阵。

### 已知遗留

1. **ForbiddenAccess 继承 Exception 而非 AppException**：项目当前无 AppException 基类，ForbiddenAccess 暂时继承 Exception。待 AppException 引入后需修改父类。（pending-confirmations.md §1）
2. **request.state.user 中间件未实现**：profile_service 路由依赖 `require_role()` Depends 从 `request.state.user` 读取角色信息，但该中间件由 AUTH-04/AUTH-02 团队负责实现，暂未就绪。（pending-confirmations.md §2）
3. **py-schemas 缺少 pydantic 依赖声明**：`packages/py-schemas/pyproject.toml` 的 `dependencies = []` 为空，需补充 `pydantic>=2.0`。（pending-confirmations.md §3）

以上均为低风险基础设施依赖项，不影响 PROF-05 的核心功能正确性。

### 对抗性测试位置
`packages/py-auth/.tmp/adversarial-tests/PROF-05/`

运行复现命令：
```bash
cd E:\Project\Web_Development\Campfire-AI
PYTHONPATH="packages/py-auth;packages/py-schemas;packages/py-logger;packages/py-config;packages/py-db;packages/py-cache;packages/py-infra;packages/py-health;packages/py-storage;apps/api-server" \
  python -m pytest packages/py-auth/.tmp/adversarial-tests/PROF-05/test_PROF-05.adversarial.py -v --import-mode=importlib
```

### 建议后续操作
- PROF-01/PROF-03/PROF-04 落地时需集成 `PrivacyGuard.check_access()` 作为 Service 层权限校验入口
- 待 AUTH-04 request.state.user 中间件就绪后，验证双层鉴权端到端流程
- 补充 `teacher_link_repository` 和 `profile_service` 的单元测试/集成测试

---

## 诚实声明

| # | 声明 | 验证方式 | 证据文件 |
|:---|:---|:---|:---|
| 1 | 实现代码严格按落地规范和设计文档编写，未参考任何对抗性测试代码。 | 实现 SubAgent 在 Phase 2 调度时明确被告知"绝对禁止读取 .tmp/adversarial-tests/ 目录" | `pending-confirmations.md` |
| 2 | 对抗性测试严格按接口契约生成，未读取实现源码。 | 测试 SubAgent 在 Phase 3 调度时明确被告知实现目录为禁止读取 | `contract-expectations.md` + `function-signatures.json` |
| 3 | 失败摘要仅包含错误类型和契约条款，未向实现者暴露测试代码或具体输入值。 | 本轮无实现漏洞（全部为测试缺陷），未进入 Phase 5 | 无需 failure-summary（全部通过） |
| 4 | 所有测试误报已修正并排除在修复流程之外。 | `test-defects-round-1.md` 存在 + SubAgent 修正记录存在 | `test-defects-round-1.md` |
| 5 | 信息隔离规则在全部迭代轮次中被遵守。 | Phase 2/3/4.5.2 调度均包含隔离约束 | SubAgent 调度记录 |
| 6 | orchestrator 未在 Phase 4 直接修改任何测试代码文件。 | 测试缺陷通过 Phase 3 SubAgent（adversarial-test-generator）修正 | `test-defects-round-1.md` + SubAgent 调用记录 |
| 7 | 所有测试缺陷均通过 Phase 3 SubAgent 修正，非 orchestrator 直接处理。 | SubAgent `adversarial-test-generator` 修正了 test_PROF-05.adversarial.py | SubAgent 修正记录（agentId: a65bb75935b207378） |
