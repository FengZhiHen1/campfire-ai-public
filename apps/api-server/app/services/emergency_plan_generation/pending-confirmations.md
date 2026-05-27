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

### 6. [CONFIRM-06] ~~py_logger 的 import 路径和 API 确认~~ ✅ 已确认（无需修改）

`py_logger.__init__.py` 明确导出 `logger` 全局单例（`from .core import logger`），文档注释写明 `from py_logger import logger`。与 CSLT-01 和本模块的导入方式完全一致，无问题。

### 7. [CONFIRM-07] ~~GenerationChunk.finish_reason 枚举值范围~~ ✅ 已确认（无需修改）

设计如此——`GenerationChunk.finish_reason` 使用 OpenAI 兼容字符串 (`stop`/`length`/`timeout`)，`GenerationResult.finish_reason` 使用模块业务枚举 (`COMPLETE`/`PARTIAL`/`BLOCKED`/`TIMEOUT`/`ERROR`)。落地规范 §1.4 和两份契约文件已明确区分。

### 8. [CONFIRM-08] ~~_SECTION_HEADER_PATTERN 匹配四段式标题的完整性~~ ✅ 已确认（无需修改）

设计合理——System Prompt 强制要求 `## 一、` 至 `## 四、` 格式，正则严格匹配此约束。LLM 偏离格式时保守降级为完全超时，在应急响应场景中是安全的兜底策略。
