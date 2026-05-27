# CSLT-03 应急方案生成 — 实现待确认项

> 生成时间：2026-05-27
> 状态：待上游确认后处理

---

## 一、重大风险项（需上游确认后方可继续）

### 1. [CONFIRM-01] py-config/AppSettings 缺少生成专用配置字段

**描述**：`packages/py-config/py_config/config.py` 中的 `AppSettings` 类当前不包含以下字段：

| 字段名 | 默认值 | 用途 |
|--------|--------|------|
| `DEEPSEEK_MODEL` | `"deepseek-chat"` | LLM 模型名称 |
| `GENERATION_MAX_TOKENS` | `4096` | 最大生成 Token 数 |
| `GENERATION_TEMPERATURE` | `0.3` | 采样温度（意图文档约束 ≤ 0.3） |
| `GENERATION_TIMEOUT_S` | `15.0` | 全流程超时秒数 |

**影响**：当前 `service.py` 和 `streaming.py` 通过 `getattr(config, field, default)` 在运行时动态读取这些字段。若 `py-config` 后续添加了这些字段但未在 `.env` 中配置，Pydantic BaseSettings 会因缺少必填字段而抛出 `ValidationError`。

**建议处理方式**：
- 在 `AppSettings` 中添加上述四个字段（均为可选，含默认值）
- 或在 `.env.example` 中添加对应注释

### 2. [CONFIRM-02] py-llm/client.py 的 async_chat_stream() 为 Stub 实现

**描述**：`packages/py-llm/py_llm/client.py` 中的 `LLMClient.async_chat_stream()` 当前仅是一个代码骨架（返回空 chunk），未包含真实的 `httpx.AsyncClient` HTTP 调用逻辑和 DeepSeek API 请求格式。

**影响**：在真实运行环境下，`stream_generate()` 将无法从 LLM API 获取实际内容。

**建议处理方式**：
- 使用 `httpx.AsyncClient` 实现 `POST /v1/chat/completions` 请求（stream=True）
- 注入 `DEEPSEEK_API_KEY` 和 `DEEPSEEK_BASE_URL` 配置
- 实现 `response.raise_for_status()` 错误处理
- 实现重试和熔断机制

### 3. [CONFIRM-03] prometheus_client 未声明为项目依赖

**描述**：`_metrics.py` 使用 `try/except ImportError` 优雅降级处理 `prometheus_client` 缺失的情况，No-op 桩会导致指标静默丢失。

**影响**：若 `prometheus_client` 未安装，所有 Prometheus 指标均不会被记录，但业务逻辑正常运行（不会报错）。运维时可能难以发现指标缺失原因。

**建议处理方式**：
- 在 `apps/api-server/pyproject.toml` 中添加 `prometheus-client` 依赖
- 或统一在根 `pyproject.toml` 的 workspace 级依赖中声明

---

## 二、风险可控项（实施时已做防御处理，可按当前实现继续）

### 4. [CONFIRM-04] `GenerationInputError` 在 Pydantic 校验失败时的包装格式

**描述**：`service.py` 中当直接传入 dict 时的 Pydantic 校验失败使用了 `GenerationInputError(detail={"field": "input_data", "msg": str(exc)})`，未精确提取 Pydantic 的逐字段错误信息（如 `error.errors()[0]`）。

**当前处理**：捕获所有 `Exception` 并包装为 `GenerationInputError`。上层调用方（CSLT-08）通常会在调用本模块前自行完成 Pydantic 校验，因此此处的校验兜底很少触发。

**风险等级**：低 — 兜底路径非主流程，错误信息已包含原始异常文本。

### 5. [CONFIRM-05] PII 二次扫描的日志方法

**描述**：`prompt_builder.py` 中调用了 `logger.alert()` 方法记录 PII 检测事件。`py-logger` 的 `logger` 实例是否支持 `.alert()` 级别需确认。

**当前处理**：`py-logger/core.py` 的 structlog 配置未在本次实现范围内确认。若不存在 `.alert()` 方法，可使用 `.critical()` 替代或自定义级别。

**风险等级**：低 — 编译时不会报错（Python 动态属性），运行时若方法不存在会抛出 `AttributeError`，但 PII 扫描为二次保障，不会阻断核心流程。

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
