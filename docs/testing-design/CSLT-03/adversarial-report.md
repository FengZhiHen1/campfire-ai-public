# CSLT-03 应急方案生成 — 对抗性验证报告

> 生成时间：2026-05-27
> 编排器：module-implementation-orchestrator
> 模块：CSLT-03 应急方案生成

## 执行摘要

| 指标 | 值 |
|------|-----|
| 实现轮次 | 1 (Phase 2) |
| 修复轮次 | 1 (Phase 5 Round 1) |
| 测试总用例数 | 67 |
| 最终通过 | 67 (100%) |
| 契约期望覆盖 | 45 条 (A01-A20 + B01-B25) |
| 发现实现漏洞 | 4 个（全部在 Round 1 修复） |
| 发现测试缺陷 | 4 个（Round 0，已在 Phase 4.5 修正） |
| 退化 | 无 |
| 收敛停滞 | 无 |

## 流水线执行摘要

| 阶段 | 内容 | 结果 |
|------|------|------|
| Phase 1 | 设计解析与环境同步 | 45 条契约期望 + 函数签名清单冻结 |
| Phase 2 | 实现落地 | 11 个 Python 文件创建（7 模块 + 1 py-llm 补充 + 辅助文件） |
| Phase 3 | 对抗性测试生成 | 67 个测试用例生成 (conftest.py + test_cslt03_adversarial.py) |
| Phase 4 (初测) | 盲测执行 | 4/67 失败 — 测试缺陷（断言被弱化以匹配实现错误行为） |
| Phase 4.5 | 测试缺陷修正 | 4 个测试函数修正为严格契约断言 |
| Phase 4 (修正后) | 盲测执行 | 4 个实现漏洞暴露 |
| Phase 5 Round 1 | 修复迭代 | 修复 `service.py` + `streaming.py` 异常传播路径 |
| Phase 4 (最终) | 盲测执行 | **67/67 通过** |

## 漏洞发现与修复记录

### Round 0 — 测试缺陷（4 个）

测试生成器在初版中将 4 个测试断言修改为匹配实现的实际（错误）行为，而非严格按契约断言。详见 `test-defects-round-1.md`。

| 编号 | 测试函数 | 缺陷类型 | 修正方式 |
|------|---------|---------|---------|
| 缺陷-001 | test_B12_timeout_no_heading | 断言逻辑矛盾 | 改为 `pytest.raises(GenerationTimeoutError)` |
| 缺陷-002 | test_B13_timeout_completely_empty | 断言逻辑矛盾 | 改为 `pytest.raises(GenerationTimeoutError)` |
| 缺陷-003 | test_B14_llm_unavailable_raises | 断言逻辑矛盾 | 改为 `pytest.raises(LLMUnavailableError)` |
| 缺陷-004 | test_X15_stream_generate_llm_unavailable | 断言逻辑矛盾 | 改为 `pytest.raises(LLMUnavailableError)` |

### Round 1 — 实现漏洞修复（4 个）

根因：`stream_generate()` 的 `finally` 块先 yield 最终 chunk，然后异常才传播。`service.py` 的 `async for` 循环在收到 `is_final=True` 后执行 `break`，触发 async generator 的 `aclose()`，将待传播的异常吞没。

| 编号 | 测试用例 | 违反契约 | 修复文件 | 修复内容 |
|------|---------|---------|---------|---------|
| FAIL-001 | test_B12_timeout_no_heading | §1.9.3 — 超时无标题应抛出 GenerationTimeoutError | service.py | 移除 `break`，让迭代自然结束使异常传播 |
| FAIL-002 | test_B13_timeout_completely_empty | §1.9.3 — 超时空文本应抛出 GenerationTimeoutError | service.py | 同上 |
| FAIL-003 | test_B14_llm_unavailable_raises | §1.9.2 — LLM 不可用应抛出 LLMUnavailableError | service.py + streaming.py | 同上 + streaming.py 包装异常为 LLMUnavailableError |
| FAIL-004 | test_X15_stream_generate_llm_unavailable | §1.6.2 — stream_generate 应抛出 LLMUnavailableError | streaming.py | `except Exception: raise` → `raise LLMUnavailableError(...)` |

## 实现文件清单

| 文件 | 说明 |
|------|------|
| `apps/api-server/app/services/emergency_plan_generation/__init__.py` | 模块导出 |
| `apps/api-server/app/services/emergency_plan_generation/enums.py` | GenerationStatus (5值), BlockVariant (4值) |
| `apps/api-server/app/services/emergency_plan_generation/exceptions.py` | GenerationInputError (422), LLMUnavailableError (503), GenerationTimeoutError (504) |
| `apps/api-server/app/services/emergency_plan_generation/models.py` | EmergencyPlanInput, GenerationResult, GenerationChunk, PromptBuildContext |
| `apps/api-server/app/services/emergency_plan_generation/blocked_outputs.py` | DISCLAIMER_TEXT, 4 种 BLOCKED_PROMPT_TEMPLATES, DEFAULT_BLOCKED_TEXT |
| `apps/api-server/app/services/emergency_plan_generation/prompt_builder.py` | PromptBuilder 类（System Prompt + User Message 组装） |
| `apps/api-server/app/services/emergency_plan_generation/streaming.py` | stream_generate() AsyncGenerator + build_generation_result() |
| `apps/api-server/app/services/emergency_plan_generation/service.py` | generate_emergency_plan() 主入口 |
| `apps/api-server/app/services/emergency_plan_generation/_metrics.py` | Prometheus 指标（含优雅降级） |
| `packages/py-llm/py_llm/client.py` | LLMClient + ChatCompletionChunk 模型 |

## 待确认事项

| 编号 | 等级 | 说明 |
|------|------|------|
| CONFIRM-01 | 重大 | py-config/AppSettings 缺少 DEEPSEEK_MODEL/GENERATION_TEMPERATURE/GENERATION_MAX_TOKENS/GENERATION_TIMEOUT_S 字段 |
| CONFIRM-02 | 重大 | py-llm/client.py 的 async_chat_stream() 为 stub，需完成真实 HTTP 调用实现 |
| CONFIRM-03 | 重大 | prometheus_client 未声明为项目依赖 |
| CONFIRM-04~08 | 可控 | 见 pending-confirmations.md（输入校验包装格式、PII 日志方法、py_logger API、finish_reason 语义域、段落标题正则覆盖） |

## 验收检查清单

- [x] 每个公开函数都有对抗性测试覆盖（`generate_emergency_plan` + `stream_generate` 均有测试）
- [x] 每轮失败用例经过"失败原因正确性"验证
- [x] 最后一轮全部通过（67/67）
- [x] 无退化发生
- [x] 实现代码符合落地规范和项目结构文档
- [x] 外部接口类型与契约 JSON Schema 一致（字段名、类型、必填性已验证）
- [x] 实现代码未对契约文件产生编译依赖（Pydantic 模型自包含定义）
- [x] 所有测试误报已由 Phase 3 SubAgent 修正（4 个测试缺陷 → 已修正 → 暴露真实漏洞 → 已修复）
- [x] 漏洞发现记录完整，每条对应契约条款编号
- [x] **角色合规**：orchestrator 未直接修改测试代码文件（由 Phase 4.5.2 SubAgent 修正）
- [x] **角色合规**：所有测试缺陷有对应 `test-defects-round-1.md` 和 SubAgent 修正记录
- [x] **角色合规**：失败摘要未泄露测试代码或具体输入值
- [x] **流程合规**：每轮修复有对应的 `pending-confirmations-round-1.md`
- [x] **流程合规**：判定为测试缺陷的轮次存在 `test-defects-round-1.md`

## 诚实声明

本报告基于 module-implementation-orchestrator 编排流程生成。以下声明确认流程完整性：

1. **信息隔离维持**：Phase 2/5 的 SubAgent 未读取 `.tmp/adversarial-tests/` 目录；Phase 3/4.5.2 的 SubAgent 仅依据契约文件生成测试（Round 0 中 4 个测试的弱化是 SubAgent 首次生成时未正确遵循对抗性原则造成的，已在 Phase 4.5.2 修正）。
2. **契约权威**：所有实现和测试的共同依据为 `docs/contracts/CSLT-03/` 下的 5 份 JSON Schema 契约文件。
3. **验证脚本缺失说明**：本项目的 `scripts/` 目录中不存在 orchestrator 技能要求的验证脚本（`preflight_check.py`、`validate_function_signatures.py` 等），所有验证通过手动审查完成。
4. **py-llm stub 说明**：`packages/py-llm` 在本次实现中被补充了 `LLMClient` 基础结构，但 `async_chat_stream()` 仍为 stub。对抗性测试通过 mock 绕过了此依赖，测试结果反映的是模块内部逻辑正确性而非端到端集成正确性。
