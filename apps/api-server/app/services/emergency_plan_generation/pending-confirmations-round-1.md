# Round 1 修复确认 — 盲测失败修复记录

## FAIL-01: `streaming.py` — `except Exception` 裸重新抛出，未包装为 `LLMUnavailableError`

**文件**: `apps/api-server/app/services/emergency_plan_generation/streaming.py`

**问题描述**: `stream_generate()` 的 `except Exception: raise` 直接重新抛出了 LLM 底层原始异常，未按契约包装为 `LLMUnavailableError`。这导致下游无法通过异常类型区分"LLM 不可用"与"其他不可预知错误"。

**修复内容**:
- 将 `except Exception:` 改为 `except Exception as exc:`
- 将裸 `raise` 替换为 `raise LLMUnavailableError(detail="LLM 生成服务暂时不可用，请稍后重试", original_error=exc) from exc`
- 在 `streaming.py` 的 import 中添加 `LLMUnavailableError` 导入

**验证场景**:
- 当 LLM API 返回 HTTP 非 200 或网络连接失败时，`stream_generate()` 抛出 `LLMUnavailableError` 而非原始异常

---

## FAIL-02: `service.py` — `break` 导致 async generator 异常被吞没

**文件**: `apps/api-server/app/services/emergency_plan_generation/service.py`

**问题描述**: `generate_emergency_plan()` 的 `async for chunk in stream_generate(...)` 循环在收到 `is_final=True` 的 chunk 后执行 `break`。但 `stream_generate()` 在 `finally` 块中 yield 了最终 chunk，然后异常才传播。`break` 触发 async generator 的 `aclose()`，导致待传播的异常（如 `GenerationTimeoutError`、`LLMUnavailableError`）被吞没。

**修复内容**:
- 移除 `if chunk.is_final: ... break` 的依赖方式
- 改为 `if chunk.is_final: ... else:` 结构：
  - `if chunk.is_final:` 分支：仅记录 finish_reason 状态，**不 break**
  - `else:` 分支：累积文本 + 追踪 TTFT
- 让 `async for` 循环自然结束，确保异常能从 `stream_generate()` 的 `finally` 块中正常传播到 `except` 捕获块

**场景验证**:

| 场景 | 预期行为 | 原理 |
|------|----------|------|
| 1. LLM 正常完成 | `GenerationStatus.COMPLETE` | `finish_reason="stop"`，else 不触发，异常不抛出 |
| 2. LLM 超时但有标题文本 | `GenerationStatus.PARTIAL`（不抛异常）| `finish_reason="timeout"`，streaming 不 raise，正常结束 |
| 3. LLM 超时无标题文本 | 抛出 `GenerationTimeoutError` | `except asyncio.TimeoutError` 中 raise → 不 break → 异常传播 |
| 4. LLM 超时完全无文本 | 抛出 `GenerationTimeoutError` | 同 3 |
| 5. LLM 底层异常 | 抛出 `LLMUnavailableError` | `except Exception` 包装 → 不 break → 异常传播 |

---

## 契约自检

- [x] 修复后的 Pydantic 模型字段名、类型、必填性与 `docs/contracts/CSLT-03/` 下的契约 JSON 一致（本次修复不涉及模型变更）
- [x] 未在修复中引入契约文件未声明的新字段（仅使用了已存在的 `LLMUnavailableError` 异常类）
