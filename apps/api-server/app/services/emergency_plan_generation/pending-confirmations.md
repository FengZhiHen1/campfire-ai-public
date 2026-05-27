# CSLT-03 应急方案生成 — 实现待确认项

> 生成时间：2026-05-27
> 状态：待上游确认后处理

---

## 一、重大风险项（需上游确认后方可继续）

### 1. [CONFIRM-01] ~~py-config/AppSettings 缺少生成专用配置字段~~ ✅ 已修复

已在 `AppSettings` 中添加 4 个可选字段（均含默认值）：
- `DEEPSEEK_MODEL` = `"deepseek-chat"`
- `GENERATION_TEMPERATURE` = `0.3` (ge=0.0, le=2.0)
- `GENERATION_MAX_TOKENS` = `4096` (ge=1, le=32768)
- `GENERATION_TIMEOUT_S` = `15.0` (ge=1.0, le=120.0)

`streaming.py` 已改为直接属性访问（`config.DEEPSEEK_MODEL`），移除了 `getattr` 回退和硬编码默认常量。

### 2. [CONFIRM-02] ~~py-llm/client.py 的 async_chat_stream() 为 Stub 实现~~ ✅ 已修复

已重写 `py_llm/client.py`：
- 底层使用 `openai.AsyncOpenAI`（DeepSeek 兼容 OpenAI SDK）
- 模型默认值更新为 `deepseek-v4-pro`，max_tokens 默认 8192
- 内置指数退避重试：RateLimitError/APITimeoutError/APIStatusError → 最多 3 次，延迟 3s→120s jitter
- 新增 `LLMClientError` 异常类，重试耗尽后抛出
- `openai>=1.0` 已声明为 `packages/py-llm` 依赖
- `streaming.py` 区分捕获 `LLMClientError`（已知）和 `Exception`（兜底）

### 3. [CONFIRM-03] ~~prometheus_client 未声明为项目依赖~~ ✅ 已修复

已在 `apps/api-server/pyproject.toml` 声明 `prometheus-client>=0.20` 为硬依赖。
同步移除 `_metrics.py` 中的 `try/except ImportError` 降级逻辑，改为直接 import。

---

## 二、风险可控项（实施时已做防御处理，可按当前实现继续）

### 4. [CONFIRM-04] ~~GenerationInputError 包装格式~~ ✅ 已修复

`service.py` 现在捕获 `ValidationError` 并提取 `error.errors()[0]` 的 `loc`（字段路径）、`msg`（失败原因）、`input`（实际值），组装为契约要求的 `detail={"field": "behavior_description", "msg": "...", "received": ""}` 格式。非 `ValidationError` 的异常用通用格式兜底。

### 5. [CONFIRM-05] ~~PII 二次扫描的日志方法~~ ✅ 已修复

`py-logger` 不支持 `logger.alert()`（仅有 debug/info/warning/error/critical）。已将 `prompt_builder.py` 中的 `logger.alert()` 改为 `logger.critical()`，语义一致——PII 检测是需立即关注的安全事件。

### 6. [CONFIRM-06] `py_logger` 的 import 路径和 API 确认

**描述**：`prompt_builder.py` 和 `streaming.py` 中使用 `from py_logger import logger`，与 `crisis_judgment` 模块的导入模式一致。但 `py-logger` 包的 `__init__.py` 导出内容需确认是否包含全局 `logger` 实例。

**当前处理**：沿用 `crisis_judgment` 模块的导入模式。若 `py_logger` 的 API 不同，需调整导入方式。

**风险等级**：低 — 与已落地的 CSLT-01 模块使用相同的导入方式，已验证可行。

### 7. [CONFIRM-07] `GenerationChunk` 的 `finish_reason` 枚举值范围

**描述**：`GenerationChunk.finish_reason` 字段在契约中定义为 `"stop" | "length" | "timeout"` 字符串枚举，而在 `streaming.py` 的 `build_generation_result()` 返回的 `GenerationResult.finish_reason` 使用的是 `GenerationStatus` 枚举（`COMPLETE`/`PARTIAL`/`BLOCKED`/`TIMEOUT`/`ERROR`）。

**当前处理**：`GenerationChunk.finish_reason` 使用字符串 `"stop"`/`"timeout"`/`"length"`（与 OpenAI 兼容格式），`GenerationResult.finish_reason` 使用 `GenerationStatus` 枚举。两者语义不同，当前实现已区分。

**风险等级**：低 — 设计文档和契约明确了两种 finish_reason 的语义域不同。

### 8. [CONFIRM-08] `_SECTION_HEADER_PATTERN` 匹配四段式标题的完整性

**描述**：流式超时检测中使用 `##\s[一二三四]、` 正则检测是否包含完整段落标题。若 LLM 输出格式与预期偏离（如使用 `## 1.` 代替 `## 一、`），则部分生成结果可能被误判为完全超时。

**当前处理**：在 System Prompt 中明确要求四段式使用 `## 一、` — `## 四、` 格式。若 LLM 违反格式约束，降级为完全超时处理。

**风险等级**：低 — 格式约束在 System Prompt 中清晰写明，且全流程超时场景本身应属于少数异常情况。
