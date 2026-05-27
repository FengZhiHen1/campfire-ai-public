## 功能模块落地完成：PROF-03 事件记录管理（对抗性验证模式）

### 涉及技术栈
Python 3.12 + FastAPI>=0.115 + Pydantic>=2.0 + SQLAlchemy>=2.0 + asyncpg + pytest

### 代码组织依据
严格遵循 `docs/篝火智答-项目结构.md` 中的 Monorepo 目录规范

### 修改文件范围
- **新增**：
  - `packages/py-db/py_db/repositories/event_repository.py` — EventRepository（7 个方法）
  - `apps/api-server/.tmp/adversarial-tests/PROF-03/` — 对抗性测试代码与中间产物
- **修改**：
  - `packages/py-schemas/py_schemas/profiles.py` — 新增 SeverityLevel、EventSetting 枚举 + EventCreate/EventUpdate/EventResponse/EventListItem DTO
  - `packages/py-config/py_config/exceptions.py` — 新增 EventLimitExceededError（HTTP 409）
  - `packages/py-db/py_db/models/profiles.py` — 新增 EventLog ORM 模型（16 列）
  - `packages/py-db/py_db/repositories/profile_repository.py` — 新增 exists() 方法
  - `apps/api-server/app/services/profile_service.py` — 新增 6 个事件方法（create/update/delete/get/list/cascade_delete）
  - `apps/api-server/app/api/v1/profiles.py` — 新增 4 个事件端点
- **未改动（可复用）**：其余所有已有文件

### 对抗性验证记录

| 轮次 | 总用例 | 通过 | 跳过 | 失败 | 收敛状态 |
|:---|:---|:---|:---|:---|:---|
| 1 | 145 | 123 | 20 | 2 (xfailed) | 初始盲测 |
| 1 (修复后) | 145 | 67 | 20 | 58 | regressed（Round 1 修复引入回归） |
| 2 | 145 | 123 | 20 | 2 (XPASS) | improving（回归修复 + 测试缺陷修正） |
| 2 (修正后) | 145 | 125 | 20 | 0 | converged |

### 流程执行证据索引

| 阶段 | 证据文件 | 状态 | 说明 |
|:---|:---|:---|:---|
| Phase 1.1 契约提取 | `contract-expectations.md` | ✅ | 55 条契约期望（A01-A19 + B01-B36） |
| Phase 1.1 验证 | `validate_contract_expectations.py` 输出 | ✅ | 验证通过，全部 13 个函数已覆盖 |
| Phase 2 函数签名 | `function-signatures.json` | ✅ | 13 个公开函数签名 |
| Phase 2 验证 | `validate_function_signatures.py` 输出 | ✅ | 验证通过 |
| Phase 3 测试生成 | `test_PROF_03_adversarial.py` + `PROF-03.adversarial.test.list.md` | ✅ | 145 个测试用例，12 个测试类 |
| Phase 4.2 Round 1 | `failure-summary-round-1.md` | ✅ | 2 个漏洞（timezone-aware datetime 崩溃） |
| Phase 4.2 Round 2 | `failure-summary-round-2.md` | ✅ | 2 个漏洞（Round 1 修复引入 naive datetime 回归） |
| Phase 4.5.1 测试缺陷 | `test-defects-round-2.md` | ✅ | 2 个 XPASS(strict) 缺陷 |
| Phase 4.5.2 SubAgent 修正 | SubAgent 调用记录 | ✅ | 测试缺陷通过 SubAgent 修正 |
| Phase 5 Round 1 | `pending-confirmations-round-1.md` | ✅ | `datetime.utcnow()` → `datetime.now(timezone.utc)` |
| Phase 5 Round 2 | `pending-confirmations-round-2.md` | ✅ | 添加 tzinfo=None 规范化逻辑 |
| Phase 4.4 回归检查 | 回归检查记录 | ✅ | Round 2 检测到退化并修复 |

### 发现的漏洞与修复

#### 实现漏洞（经 Phase 5 SubAgent 修复）

1. **[datetime 时区不一致]** EventCreate.event_time_not_future validator 使用 `datetime.utcnow()`（offset-naive），与 Pydantic 解析的 timezone-aware datetime 比较时触发 TypeError
   - 修复 Round 1：将 `datetime.utcnow()` 替换为 `datetime.now(timezone.utc)`
   - 修复 Round 2：在比较前统一规范化——若 `v.tzinfo is None` 则 `v.replace(tzinfo=timezone.utc)`
   - 涉及契约：§1.3
   - 修复轮次：Round 1 → Round 2
   - 影响范围：`packages/py-schemas/py_schemas/profiles.py` 第 641 行和第 720 行

2. **[datetime 时区不一致 — EventUpdate]** EventUpdate 的 event_time validator 同根因
   - 修复：同漏洞 1
   - 涉及契约：§1.3
   - 修复轮次：Round 1 → Round 2

#### 测试缺陷（经 Phase 3 SubAgent 修正）

1. `test_adversarial_timezone_aware_crashes_validator` — `@pytest.mark.xfail(strict=True)` 在 bug 修复后导致 XPASS
   - 修正：移除 xfail 标记，改为验证 validator 正确处理 timezone-aware datetime
2. `test_adversarial_event_time_with_timezone_offset` — 同根因 XPASS
   - 修正：移除 xfail 标记，改为正常断言

### 验收检查清单

- [x] 每个公开函数都有对抗性测试覆盖（13/13 函数已覆盖）
- [x] 每轮失败用例经过"失败原因正确性"验证
- [x] 最后一轮全部通过（125 passed, 0 failed）
- [x] 无退化发生（Round 2 检测到退化后已修复）
- [x] 实现代码符合落地规范和项目结构文档
- [⚠️] 外部接口类型通过 `validate_contract_consistency.py` 验证 — 脚本本身有 bug（TypeError crash），已通过 SubAgent 契约自检清单手动验证
- [x] 实现代码未对契约文件产生编译依赖
- [x] 所有测试误报已由 Phase 3 SubAgent 修正
- [x] 漏洞发现记录完整，每条对应契约条款编号
- [x] **角色合规**：orchestrator 未直接修改测试代码文件（`check_isolation.py` 审计通过）
- [x] **角色合规**：所有测试缺陷有对应 `test-defects-round-2.md` 和 SubAgent 修正记录
- [x] **角色合规**：失败摘要未泄露测试代码或具体输入值
- [x] **流程合规**：每轮修复有对应的 `pending-confirmations-round-{N}.md`（Round 1 + Round 2）
- [x] **流程合规**：判定为测试缺陷的轮次存在 `test-defects-round-2.md`

### 诚实声明

-   Round 1 修复引入回归：`datetime.now(timezone.utc)` 与 naive datetime 输入不兼容，导致 58 个测试失败。Round 2 通过在比较前统一规范化为 timezone-aware 解决。⚠️

-   `validate_contract_consistency.py` 脚本本身存在 TypeError bug（`argument of type 'bool' is not iterable` 在 compare_model_to_contract 中），无法完成自动化契约一致性验证。替代措施：Phase 2 SubAgent 在实现输出中提供了完整的契约自检清单（8/8 通过），且 125 个对抗性测试全部通过为契约一致性提供了实证验证。⚠️

-   `validate_contract_consistency.py` 脚本执行失败。⚠️
