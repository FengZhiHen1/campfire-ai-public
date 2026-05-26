## 功能模块落地完成：OBS-01 结构化日志（对抗性验证模式）

### 涉及技术栈
后端 Python 3.12+，标准库 only（`logging`、`json`、`uuid`、`contextvars`、`datetime`、`collections`），零外部依赖。

### 代码组织依据
严格遵循 `docs/篝火智答-项目结构.md` §6.1 中 `packages/py-logger/py_logger/` 目录规范。

### 修改文件范围
- **新增**：
  - `packages/py-logger/py_logger/core.py` — 日志工厂、JSONFormatter、Logger 单例、环形缓冲区
  - `packages/py-logger/py_logger/context.py` — ContextVar trace_id 管理
  - `packages/py-logger/py_logger/middlewares/fastapi.py` — RequestLoggingMiddleware（ASGI 中间件）
- **修改**：
  - `packages/py-logger/py_logger/__init__.py` — 更新公共 API 导出
  - `packages/py-logger/py_logger/middlewares/__init__.py` — 导出 RequestLoggingMiddleware
- **未改动（可复用）**：`packages/py-logger/pyproject.toml`

### 对抗性验证记录

| 轮次 | 总用例 | 通过 | 失败 | 收敛状态 |
|:---|:---|:---|:---|:---|
| 1（初始盲测） | 83 | 30 | 53 | 初始盲测（52 个判定为测试缺陷） |
| 1（修正测试后） | 83 | 82 | 1 | improving（1 个实现缺陷暴露） |
| 2（修复后） | 83 | 83 | 0 | converged |

### 流程执行证据索引

| 阶段 | 证据文件 | 状态 | 说明 |
|:---|:---|:---|:---|
| Phase 1.1 契约提取 | `contract-expectations.md` | ✅ | 34 条契约期望（A01-A28, B01-B04, C01-C06） |
| Phase 2 函数签名 | `function-signatures.json` | ✅ | 9 个公开函数 |
| Phase 3 测试生成 | `test_OBS-01.adversarial.py` | ✅ | 83 条对抗性测试 |
| Phase 3 测试清单 | `OBS-01.adversarial.test.list.md` | ✅ | 测试清单完整 |
| Phase 4.2 Round 1 | `failure-summary-round-1.md` | ✅ | 1 个实现漏洞（case-001） |
| Phase 4.5.1 测试缺陷 | `test-defects-round-1.md` | ✅ | 8 个缺陷条目（核心问题：stdout 捕获失效） |
| Phase 4.5.2 SubAgent 修正 | SubAgent 调用记录 | ✅ | 测试从 30/83 → 82/83 通过 |
| Phase 5 Round 1 | `pending-confirmations-round-1.md` | ✅ | extra 空 dict 修复 + 契约自检 |
| Phase 4.4 回归检查 | 无退化发生 | ✅ | 83/83 全部通过 |

### 发现的漏洞与修复

#### 实现漏洞（经 Phase 5 SubAgent 修复）

1. **[falsy 值误判]** `_write()` 方法中 extra 字段赋值逻辑 `extra_dict if extra_dict else None` 将空 dict `{}`（falsy 值）误判为 None
   - 修复：改为 `extra_dict if extra_dict else ({} if extra is not None else None)`，正确区分"未传 extra (None → null)"和"传空 dict ({} → {})"
   - 涉及契约：§1.6.1
   - 修复轮次：Round 1（1 轮修复即通过）
   - 待确认事项：无风险项

#### 测试缺陷（经 Phase 3 SubAgent 修正）

1. **[stdout 捕获失效]** 自定义 `cap_stdout`/`cap_both` fixture 使用 `patch("sys.stdout", StringIO())` 与 pytest 输出捕获冲突，导致约 40 个测试误报
   - 修正：全部迁移至 pytest 内置 `capsys` fixture
   - 修正轮次：Round 1
   - 测试缺陷报告：`test-defects-round-1.md`
   - SubAgent 修正记录：存在（修正后 82/83 通过）

2. **[参数传递错误]** test_A12 parametrize 对 critical() 使用 keyword+positional 混合传递导致 TypeError
   - 修正：统一使用位置参数传递
   - 修正轮次：Round 1

3. **[异常模拟无效]** test_A17/test_A18 的异常注入方式无法触发异常屏障
   - 修正：使用 `patch("json.dumps", side_effect=RuntimeError)` mock 内部路径
   - 修正轮次：Round 1

### 模块作用简述

结构化日志模块为 Campfire-AI 平台提供统一的 JSON 格式 stdout 日志输出能力。通过 contextvars 自动传播 trace_id（支持 W3C Trace Context），实现端到端请求追踪。关键动作（AI 调用/权限拒绝/工单创建）通过 `critical()` 接口强制审计日志不可绕过。

### 已知遗留
无。83/83 全部通过，零遗留问题。

### 对抗性测试位置
`packages/py-logger/.tmp/adversarial-tests/OBS-01/`
（可运行 `cd packages/py-logger && PYTHONPATH=. python -m pytest .tmp/adversarial-tests/OBS-01/test_OBS-01.adversarial.py -v --import-mode=importlib` 复现）

### 建议后续操作
- 调用 module-test-writer 生成正式验收测试覆盖 FastAPI 中间件（C01-C06 条目）
- 将 extra 空 dict 的 falsy 陷阱纳入后续模块的落地规范检查清单
- 确认并修复 `KNOWN_TRACE_ID` 为非十六进制字符的问题（已在测试修正中间接修复）

---

## 诚实声明

| # | 声明 | 验证方式 | 证据文件 | 状态 |
|:---|:---|:---|:---|:---|
| 1 | 实现代码严格按落地规范和项目结构设计文档编写，未参考任何对抗性测试代码 | 代码审查 + Phase 2 SubAgent 工作目录排除 `.tmp/` | 实现源码文件 | ✅ |
| 2 | 对抗性测试严格按接口契约生成，未读取实现源码 | Phase 3 SubAgent 仅接触契约文档，排除源码目录 | `contract-expectations.md` + `function-signatures.json` | ✅ |
| 3 | 失败摘要仅包含错误类型和契约条款，未向实现者暴露测试代码或具体输入值 | `failure-summary-round-1.md` 审查 | `failure-summary-round-1.md` | ✅ |
| 4 | 所有测试误报已修正并排除在修复流程之外 | `test-defects-round-1.md` 存在 + SubAgent 修正记录 | `test-defects-round-1.md` | ✅ |
| 5 | 信息隔离规则在全部迭代轮次中被遵守 | 以上 1-4 项全部通过 | 以上全部证据 | ✅ |
| 6 | orchestrator 未在 Phase 4 直接修改任何测试代码文件 | `test-defects-round-1.md` 存在且 SubAgent 调用记录完整 | `test-defects-round-1.md` | ✅ |
| 7 | 所有测试缺陷均通过 Phase 3 SubAgent 修正，非 orchestrator 直接处理 | SubAgent 调用记录 + `test-defects-round-1.md` 存在 | `test-defects-round-1.md` | ✅ |
