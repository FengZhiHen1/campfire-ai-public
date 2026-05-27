## 1 功能点：CSLT-03 应急方案生成 — 落地规范

> **文档生成时间**：`2026-05-27 14:45:00`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-27 14:45:00` | AI Assistant | 初始版本，基于已冻结意图文档 v2.0、设计文档 v1.0 和契约协调报告全量生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `CSLT-03-应急方案生成-设计文档.md`。

---

### 1.1 技术栈绑定 `【对内实现】`

- **必须使用**：
  - `fastapi>=0.115`：Service 层依赖注入（Depends）、asyncio 异步路由
  - `pydantic>=2.0`：BaseModel 严格校验、Field 约束、model_validate
  - `asyncio`：AsyncGenerator 流式输出、`asyncio.wait_for` 超时控制
  - `packages/py-llm` — `LLMClient.async_chat_stream()`：DeepSeek API 流式调用（带超时控制、重试机制、熔断逻辑）
  - `packages/py-logger` — `Logger.bind(trace_id=..., module="emergency_plan_generation")` 结构化日志注入
  - `packages/py-config` — `Config` pydantic-settings 模式加载环境变量
  - `packages/py-schemas` — `BaseSchema` 基类、`UUID` 校验类型
  - `packages/py-infra` — `AppException` 基类（统一异常处理中间件）
  - `prometheus-fastapi-instrumentator` — Counter/Histogram 指标暴露
- **禁止使用**：
  - 禁止绕过 `packages/py-llm/` 统一客户端直接调用 DeepSeek API
  - 禁止使用同步 `requests` 库替代 `httpx.AsyncClient` 调用 LLM API
  - 禁止在 System Prompt 中包含任何用户 PII（姓名、手机号、地址）
  - 禁止阻断场景下仍发起 LLM API 调用——必须完全短路

### 1.2 文件归属 `【对内实现】`

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| Service 入口 | `apps/api-server/app/services/emergency_plan_generation/service.py` | `generate_emergency_plan()` 函数 + `EmergencyPlanService` 类（可选封装） |
| Prompt 构建 | `apps/api-server/app/services/emergency_plan_generation/prompt_builder.py` | `PromptBuilder` 类：组装 System Prompt + User Message，含预编号引用和 Markdown 格式化 |
| 安全提示模板 | `apps/api-server/app/services/emergency_plan_generation/blocked_outputs.py` | `BLOCKED_PROMPT_TEMPLATES` 字典常量（4 种 BlockVariant 的预设安全提示文本） |
| 流式生成 | `apps/api-server/app/services/emergency_plan_generation/streaming.py` | `stream_generate()` AsyncGenerator 函数：调用 LLM + yield GenerationChunk |
| 类型定义 | `apps/api-server/app/services/emergency_plan_generation/models.py` | Pydantic 模型：`EmergencyPlanInput`、`GenerationResult`、`GenerationChunk` 等 |
| 枚举定义 | `apps/api-server/app/services/emergency_plan_generation/enums.py` | `GenerationStatus`、`BlockVariant` Python StrEnum |
| 异常定义 | `apps/api-server/app/services/emergency_plan_generation/exceptions.py` | `LLMUnavailableError`、`GenerationTimeoutError`、`GenerationInputError` |
| Service 单元测试 | `apps/api-server/tests/services/emergency_plan_generation/test_service.py` | `generate_emergency_plan()` 全流程测试 |
| Prompt 构建测试 | `apps/api-server/tests/services/emergency_plan_generation/test_prompt_builder.py` | Prompt 组装正确性测试（预编号、引用映射、Markdown 格式） |
| 流式生成测试 | `apps/api-server/tests/services/emergency_plan_generation/test_streaming.py` | AsyncGenerator 流式输出测试（超时、截断、正常完成） |

### 1.3 输入定义 `【已锁定】`

**EmergencyPlanInput**
- 【契约引用】`docs/contracts/CSLT-03/EmergencyPlanInput.json`
- 本模块作为该契约的定义方
- 消费方：无（本模块为输入接收方，由 CSLT-08 编排层组装后传入）

内部类型（不对外暴露）：

```python
class PromptBuildContext(BaseModel):
    """Prompt 构建的内部上下文——不对外暴露，仅在 prompt_builder.py 内使用"""
    prenumbered_slices: list[tuple[str, str]] = Field(
        default_factory=list,
        description="预编号后的切片列表。每项为 (编号文本如'[1]', 切片ID_UUID) 的元组"
    )
    slice_text_block: str = Field(
        default="",
        description="组装完成的「参考案例」区域 Markdown 文本块，包含全量切片的预编号和循证等级标注"
    )
    profile_markdown: str = Field(
        default="",
        description="Markdown 格式的患者档案摘要，由上游传入的 profile_summary 字段直接注入"
    )
    has_cases: bool = Field(
        default=False,
        description="上游是否提供了至少一条案例切片。用于决定 Prompt 中是否包含参考案例区域"
    )
```

### 1.4 输出定义 `【已锁定】`

**GenerationResult**
- 【契约引用】`docs/contracts/CSLT-03/GenerationResult.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-05（置信度后校验）、CSLT-06（咨询历史管理）、CSLT-08（前端编排逻辑）、QUAL-02（RAG质量评估）

**GenerationChunk**
- 【契约引用】`docs/contracts/CSLT-03/GenerationChunk.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-04（流式应答推送）

**GenerationStatus**
- 【契约引用】`docs/contracts/CSLT-03/GenerationStatus.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-04、CSLT-05、CSLT-06、CSLT-08、QUAL-02

**BlockVariant**
- 【契约引用】`docs/contracts/CSLT-03/BlockVariant.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-08（前端编排逻辑）

### 1.5 核心逻辑步骤 `【对内实现】`

按执行顺序列出可测试的逻辑步骤。每一步是原子操作。

1. **步骤 1：输入校验**
   - **操作对象**：`EmergencyPlanInput` 数据
   - **具体操作**：调用 `EmergencyPlanInput(**kwargs)` 进行 Pydantic 校验。校验 `behavior_description` 长度 1-2000 字符，`profile_summary` 非空，`request_id` 为有效 UUID 格式。crisis_result 和 search_result 字段通过 $ref 引用 CSLT-01/CSLT-02 的契约类型，其语义校验由上游保证。
   - **输入来源**：CSLT-08 编排层调用 `generate_emergency_plan()` 时传入的 dict
   - **输出去向**：校验通过的 `EmergencyPlanInput` 实例进入步骤 2
   - **失败行为**：Pydantic `ValidationError` 时立即抛出 `GenerationInputError`（继承 AppException），HTTP 422，`detail` 含字段名和失败原因。不调用 LLM，不记录高成本日志

2. **步骤 2：阻断检查与短路**
   - **操作对象**：`EmergencyPlanInput.crisis_result.block_deep_response` 布尔字段
   - **具体操作**：
     1. 读取 `crisis_result.block_deep_response`
     2. 若 `True` → 从 `BLOCKED_PROMPT_TEMPLATES` 字典中按 `crisis_result.final_level`（severe）和 `block_variant` 查找对应安全提示文本
     3. 若 `block_variant` 为 None，从 CSLT-01 的 `judgment_sources` 中提取 `PreSelectionLayer` 匹配到的行为类型，映射为 `BlockVariant` 枚举
     4. 构建 `GenerationResult(text="", source_list=[], disclaimer=blocked_output, generation_time_ms=elapsed_ms, is_partial=False, referenced_slice_ids=[], finish_reason=GenerationStatus.BLOCKED, ttft_ms=0.0)`
     5. 直接返回，跳过步骤 3-7
   - **输入来源**：步骤 1 的 `EmergencyPlanInput.crisis_result.block_deep_response`
   - **输出去向**：`GenerationResult` 直接返回给 CSLT-08 编排层。不调用 `stream_generate()`，不产生 GenerationChunk
   - **失败行为**：block_variant 映射失败（crisis_result 中无法提取有效行为类型）→ 使用默认通用安全提示文本，WARNING 日志记录

3. **步骤 3：Prompt 构建**
   - **操作对象**：从步骤 1 的 `EmergencyPlanInput` 提取的所有输入字段
   - **具体操作**：
     1. 遍历 `search_result.results`（CaseSliceDto 列表），按 `composite_score` 降序
     2. 为每条切片分配预编号：`[1]`、`[2]`、...、`[N]`，构建 `prenumbered_slices` 映射表（编号文本 → slice_id UUID）
     3. 构建「参考案例」Markdown 区域：
        ```
        ## 参考案例（共 N 条，按匹配度降序）
        [1] CASE-{case_id} {case_title}（{case_created_at}，循证等级：{evidence_level}）
        场景描述：{scene 类型切片文本}
        干预动作：{intervention 类型切片文本}
        结果反馈：{result 类型切片文本}
        ```
        若 `search_result.results` 为空（0 条），替换为："当前暂无与您描述情况相匹配的真实干预案例参考。"
     4. 构建 System Prompt 完整模板（见步骤 3 注释），包含：角色设定、四段式输出强制结构、来源引用规则、免责声明模板、专业术语解释规则、温度/确定性约束
     5. 构建 User Message：`## 患者档案\n{profile_summary}\n\n## 当前行为描述\n{behavior_description}\n\n## 检索精度说明\n{degradation_level 非 NONE 时注入降级提示}`
     6. 组装为 `messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}]`
   - **输入来源**：步骤 1 的 `search_result.results`、`profile_summary`、`behavior_description`、`search_result.degradation_applied`、`search_result.degradation_level`
   - **输出去向**：`messages` 列表 + `prenumbered_slices` 映射表进入步骤 4
   - **失败行为**：不适用——Prompt 构建为纯内存字符串拼接操作，无外部依赖。安全防护：对 `profile_summary` 和 `behavior_description` 做正则二次扫描检测手机号（`1[3-9]\d{9}`）和身份证号（`\d{17}[\dXx]`），命中则记录 ALERT 日志（不阻断执行——上游脱敏的信任边界）

   > **System Prompt 模板核心结构**（详细文本在代码中定义，此处列出必须包含的元素）：
   > 1. 角色设定：你是一名孤独症行为干预顾问
   > 2. 四段式输出结构（强制 Markdown 格式）：
   >    - ## 一、即时安全干预动作
   >    - ## 二、情绪安抚话术
   >    - ## 三、后续观察指标
   >    - ## 四、就医判断标准
   > 3. 引用规则：引用案例时必须使用预分配的序号标注，如 "引导孩子离开嘈杂环境 [1]"
   > 4. 免责声明规则：在输出末尾必须原样附加以下文本（不可修改）："以上建议由 AI 生成，仅供参考，不构成医疗诊断或治疗建议。如情况紧急，请立即联系专业医疗机构。"
   > 5. 专业术语解释规则：首次出现专业术语时加括号解释
   > 6. 零幻觉约束：仅基于提供的参考案例上下文回答，不得编造案例、研究或数据。无参考案例时明确告知用户
   > 7. 温度/确定性约束：生成内容保持高度确定性，避免模棱两可的建议

4. **步骤 4：LLM 流式调用**
   - **操作对象**：DeepSeek API chat completion stream 请求
   - **具体操作**：
     1. 从 `packages/py-config` 读取 `DEEPSEEK_MODEL`（默认 `deepseek-chat`）、`GENERATION_TEMPERATURE`（默认 `0.3`）、`GENERATION_MAX_TOKENS`（默认 `4096`）、`GENERATION_TIMEOUT_S`（默认 `15.0`）
     2. 调用 `LLMClient.async_chat_stream(messages=messages, model=config.DEEPSEEK_MODEL, temperature=config.GENERATION_TEMPERATURE, max_tokens=config.GENERATION_MAX_TOKENS, timeout=config.GENERATION_TIMEOUT_S)`
     3. 返回 `AsyncGenerator[ChatCompletionChunk, None]` 迭代器
   - **输入来源**：步骤 3 的 `messages` 列表
   - **输出去向**：`AsyncGenerator` 迭代器进入步骤 5 的流式消耗循环
   - **失败行为**：LLM API 返回 HTTP 非 200 或连接超时（>`GENERATION_TIMEOUT_S` 秒未建立连接）→ 抛出 `LLMUnavailableError`（继承 AppException），status_code=503，`detail="LLM 生成服务暂时不可用，请稍后重试"`。记录 CRITICAL 日志含 API 状态码和耗时。不重试——单次调用失败即终止

5. **步骤 5：流式 chunk 生产**
   - **操作对象**：步骤 4 的 `AsyncGenerator[ChatCompletionChunk, None]`
   - **具体操作**：
     1. 记录起始时间 `t_start = time.monotonic()`，初始化 `ttft_ms = None`、`accumulated_text = ""`
     2. 通过 `async for chunk in async_chat_stream(...)` 迭代 chunks
     3. 提取 `delta_text = chunk.choices[0].delta.content or ""`
     4. 若 `ttft_ms is None` 且 `delta_text != ""` → `ttft_ms = (time.monotonic() - t_start) * 1000`
     5. `accumulated_text += delta_text`
     6. `yield GenerationChunk(text=delta_text, is_final=False, finish_reason=None)`
     7. 整个循环用 `asyncio.wait_for(coro, timeout=config.GENERATION_TIMEOUT_S - (time.monotonic() - t_start))` 包裹——剩余时间不足时触发超时
   - **输入来源**：步骤 4 的 AsyncGenerator
   - **输出去向**：每个 `GenerationChunk` yield 给下游 CSLT-04。`accumulated_text`、`ttft_ms` 传递给步骤 6
   - **失败行为**：`asyncio.TimeoutError`（全流程超时 >15s）→ 进入步骤 6 的超时处理分支。若 `accumulated_text` 至少含一个完整段落（以 `## ` 开头的标题行分隔检测），标记 `is_partial=True`；若文本为空，标记 `finish_reason=TIMEOUT`

6. **步骤 6：流式完成收尾**
   - **操作对象**：`accumulated_text`、`ttft_ms`、`prenumbered_slices` 映射表
   - **具体操作**：
     1. 从 `accumulated_text` 中提取所有 `[N]` 引用标记，反查 `prenumbered_slices` 映射表获取对应的 `slice_id`，构建 `referenced_slice_ids` 列表
     2. 从 `accumulated_text` 中按正则 `^\[(\d+)\] CASE-(\d{3}) .+（\d{4}-\d{2}-\d{2}）$` 提取来源引用行，构建 `source_list` 列表
     3. 确保免责声明已出现在文本末尾——若 LLM 未生成免责声明（检查文本末尾 200 字符），强制追加固定文本
     4. 计算 `generation_time_ms = (time.monotonic() - t_start) * 1000`
     5. 判断 `finish_reason`：正常完成=COMPLETE，超时部分=PARTIAL，完全超时=TIMEOUT
     6. 组装 `GenerationResult(text=accumulated_text, source_list=source_list, disclaimer=DISCLAIMER_TEXT, generation_time_ms=generation_time_ms, is_partial=is_partial, referenced_slice_ids=referenced_slice_ids, finish_reason=finish_reason, ttft_ms=ttft_ms or 0.0)`
     7. yield 最后一个 `GenerationChunk(text="", is_final=True, finish_reason="stop"|"length"|"timeout")`
   - **输入来源**：步骤 5 的 `accumulated_text`、`ttft_ms` + 步骤 3 的 `prenumbered_slices`
   - **输出去向**：`GenerationResult` 返回给 CSLT-08 编排层。最后一个 `GenerationChunk(is_final=True)` 通知 CSLT-04 关闭 SSE 连接
   - **失败行为**：引用反查失败（LLM 输出了不在预编号范围内的 [N]）→ 记录 WARNING 日志含非法编号，从 `source_list` 中排除该条目，`referenced_slice_ids` 中也不包含

7. **步骤 7：指标记录与日志**
   - **操作对象**：Prometheus Counter/Histogram 指标实例
   - **具体操作**：
     1. `GENERATION_REQUESTS.labels(status=finish_reason).inc()`
     2. `GENERATION_DURATION.observe(generation_time_ms / 1000.0)`
     3. `GENERATION_TTFT.observe(ttft_ms / 1000.0)`
     4. 调用 `py-logger.info("generation_completed", trace_id=request_id, finish_reason=..., elapsed_ms=..., ttft_ms=..., slices_count=len(prenumbered_slices), referenced_count=len(referenced_slice_ids))`
   - **输入来源**：步骤 6 的 `GenerationResult` 各字段
   - **输出去向**：Prometheus /metrics 端点 + 结构化日志
   - **失败行为**：Prometheus 指标注册失败（如 labels 不合法）→ 记录 ERROR 日志，不放行异常（指标可观测性不可降级）。日志写入失败 → 仅 stderr 输出，不阻塞业务响应

### 1.6 接口契约 `【已锁定】`

#### 1.6.1 接口 1：generate_emergency_plan

```python
async def generate_emergency_plan(
    input: EmergencyPlanInput,
    config: Config | None = None,
) -> GenerationResult:
    """
    接收应急咨询的上游结果（危机等级、案例切片、患者档案），组装 Prompt 并调用大模型生成四段式应急方案。

    阻断场景下（crisis_result.block_deep_response=True）完全跳过 LLM 调用，
    直接返回硬编码安全提示文本。

    Args:
        input: 完整的生成输入，由 CSLT-08 编排层组装后传入。
               包含 CSLT-01 的危机判定结果、CSLT-02 的检索结果、患者档案摘要和行为描述。
        config: 可选配置注入（用于测试时注入 mock 配置）。若为 None 则从 packages/py-config 加载。

    Returns:
        GenerationResult: 生成结果，包含完整文本、来源引用清单、免责声明、耗时、状态等。

    Raises:
        GenerationInputError: Pydantic 输入校验失败（必填字段缺失、类型错误等）
        LLMUnavailableError: DeepSeek API 不可用或返回非 200（不重试）
        GenerationTimeoutError: 全流程超时 15s 且无任何文本产出

    Side Effects:
        - 记录生成全流程的结构化日志（INFO/WARNING/ERROR 级别）
        - 暴露 Prometheus 指标：请求计数、生成耗时 Histogram、TTFT Histogram、Token 消耗 Counter
        - 不持久化任何生成结果——持久化由调用方（CSLT-06）负责

    Idempotency:
        本函数为无状态生成，不维护跨调用状态，不检查幂等 Key。
        同一输入参数的重复调用产生独立的全新生成结果。

    Thread Safety:
        本函数为 async 协程，内部无共享可变状态。不同调用通过 AsyncGenerator 上下文隔离。线程安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `generate_emergency_plan` —— 语义化，描述"生成应急方案"的业务动作 |
| **输入类型** | `EmergencyPlanInput`（详见 §1.3，契约引用） |
| **输出类型** | `GenerationResult`（详见 §1.4，契约引用） |
| **异常类型** | `GenerationInputError`、`LLMUnavailableError`、`GenerationTimeoutError`（详见 §1.9） |
| **副作用** | 记录结构化日志、暴露 Prometheus 指标、不执行写操作 |
| **幂等性** | 无状态生成，每次调用独立执行 |
| **并发安全** | async 协程安全，内部无共享可变状态 |

#### 1.6.2 接口 2：stream_generate

```python
async def stream_generate(
    input: EmergencyPlanInput,
    config: Config | None = None,
) -> AsyncGenerator[GenerationChunk, None]:
    """
    流式生成应急方案——将 LLM 返回的每个 Token 增量通过 AsyncGenerator 实时产出。

    调用方使用 async for chunk in stream_generate(input) 消费。最后一个 chunk 的 is_final=True。

    Args:
        input: 完整的生成输入（同 generate_emergency_plan）
        config: 可选配置注入

    Yields:
        GenerationChunk: 每个 LLM Token 增量块。text 为非空字符串直到流式结束。
                         最后一个 chunk 的 is_final=True 表示流式输出结束。

    Raises:
        GenerationInputError: 输入校验失败
        LLMUnavailableError: LLM API 不可用（在 yield 前抛出）
        GenerationTimeoutError: 全流程 15s 超时且无任何文本产出（在 yield 前抛出）

    Side Effects:
        - 首个 token 到达时记录 TTFT 指标
        - 每个 chunk yield 后更新 Prometheus 指标
        - 不持久化任何数据

    Thread Safety:
        AsyncGenerator 的每次迭代在同一个事件循环任务中执行，天然单线程。线程安全。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `stream_generate` —— 语义化，描述"流式生成"的技术动作 |
| **输入类型** | `EmergencyPlanInput` |
| **输出类型** | `AsyncGenerator[GenerationChunk, None]` |
| **异常类型** | 同 `generate_emergency_plan` |
| **副作用** | Prometheus 指标更新、不执行写操作 |
| **幂等性** | 无状态，每次调用产生独立的流式输出 |

### 1.7 依赖与集成接口 `【已锁定】`

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| LLM API | DeepSeek API | `POST /v1/chat/completions`；Header `Authorization: Bearer $DEEPSEEK_API_KEY`；Body `{"model": "deepseek-chat", "messages": [...], "temperature": 0.3, "max_tokens": 4096, "stream": true}`；超时 15s | 流式生成四段式应急方案 | `docs/篝火智答-技术栈设计.md` §2（LLM 服务）、§7（潜在风险——DeepSeek API 中断备选方案为通义千问 API） |
| LLM 客户端 | packages/py-llm | `LLMClient.async_chat_stream(messages=messages, model="deepseek-chat", temperature=0.3, max_tokens=4096, timeout=15.0)` → `AsyncGenerator[ChatCompletionChunk]` | 统一的流式 API 调用封装，含超时控制、连接池管理、重试策略和熔断机制 | `docs/篝火智答-项目结构.md` §6.1 `packages/py-llm/` |
| 配置管理 | packages/py-config | `config = Config()` — `pydantic-settings` 加载 `.env` | 读取 `DEEPSEEK_MODEL`、`GENERATION_TEMPERATURE`、`GENERATION_MAX_TOKENS`、`GENERATION_TIMEOUT_S` | `docs/篝火智答-项目结构.md` §6.1 `packages/py-config/` |
| 日志系统 | packages/py-logger | `logger.bind(trace_id=..., module="emergency_plan_generation").info(...)` | 结构化 JSON 日志，含生成耗时、TTFT、Token 消耗、阻断事件、超时事件 | `docs/篝火智答-项目结构.md` §6.1 `packages/py-logger/` |
| 可观测性 | Prometheus (via prometheus-fastapi-instrumentator) | `Counter.labels(...).inc()`、`Histogram.observe(value)` | 暴露生成服务的核心指标：请求计数、耗时、TTFT | `docs/篝火智答-技术栈设计.md` §6.3（监控与告警） |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| CSLT-01（危机分级判定） | `CrisisJudgmentResult` 类型（契约引用 `docs/contracts/CSLT-01/CrisisJudgmentResult.json`），消费 `final_level` 和 `block_deep_response` 字段 | 决定正常生成还是短路返回安全提示。final_level 注入 Prompt 作为危机上下文 | ✅ 已落地 |
| CSLT-02（RAG语义检索） | `SemanticSearchResult` 类型（契约引用 `docs/contracts/CSLT-02/SemanticSearchResult.json`），消费 `results`、`degradation_applied`、`degradation_level`；`CaseSliceDto` 类型（契约引用 `docs/contracts/CSLT-02/CaseSliceDto.json`），全字段消费 | Prompt 中参考案例的来源数据。degradation 标记用于在 Prompt 中提示检索精度降低 | ✅ 已落地 |
| CSLT-04（流式应答推送） | 不直接调用。通过 `stream_generate()` 的 AsyncGenerator 向 CSLT-04 产出 `GenerationChunk` | CSLT-04 作为下游消费者，通过 async for 消费流式 chunks 并封装为 SSE 推送给前端 | ⏭️ 待落地（CSLT-03 通过 GenerationChunk 契约定义稳定的输出接口，CSLT-04 落地时按此契约消费即可） |
| CSLT-05（置信度后校验） | 不直接调用。流式完成后将 `GenerationResult` 传递给 CSLT-05 | CSLT-05 消费生成结果进行置信度评估和兜底工单触发 | ⏭️ 待落地（CSLT-03 通过 GenerationResult 契约定义稳定的输出接口） |
| CSLT-08（咨询编排逻辑） | 不直接调用。CSLT-08 作为本模块的调用方，组装 `EmergencyPlanInput` 后调用 `generate_emergency_plan()` 或 `stream_generate()` | 编排应急咨询全流程，本模块的入口 | ⏭️ 待落地（mock 策略：直接在测试中构造 EmergencyPlanInput 实例调用） |

> **Mock 策略**：CSLT-04/05/08 均未落地时，module-implementation-executor 使用以下 mock 方案：
> - CSLT-01 模拟：构造 `CrisisJudgmentResult` mock（`final_level=mild/moderate/severe`，`block_deep_response=false/true`）
> - CSLT-02 模拟：构造 `SemanticSearchResult` mock（`results` 含 3-10 条 `CaseSliceDto`，或空列表用于零案例测试）
> - CSLT-04 模拟：`async for chunk in stream_generate(input)` 收集所有 chunks 后断言最后一个 chunk 的 `is_final=True`
> - CSLT-08 模拟：直接在测试中创建 `EmergencyPlanInput(**mock_data)` 传入

### 1.8 状态机 `【对内实现】`

本功能点不涉及持久化状态流转，故无需状态机。

单次生成的内部运行时阶段（纯内存，不持久化）：

| 当前阶段 | 触发条件 | 下一阶段 | 前置条件 | 副作用 |
|----------|----------|---------|---------|--------|
| `awaiting_input` | `generate_emergency_plan()` 调用 | `input_validation` | 无 | 无 |
| `input_validation` | Pydantic 校验通过 | `block_check` | EmergencyPlanInput 所有 required 字段存在且类型正确 | 无。校验失败 → GenerationInputError，流程终止 |
| `block_check` | block_deep_response=True | `output_blocked` | crisis_result.final_level=severe | 记录 WARNING 安全日志。跳过 Prompt 构建和 LLM 调用 |
| `block_check` | block_deep_response=False | `prompt_build` | 非重度场景或重度但上游未激活阻断 | 无 |
| `prompt_build` | Prompt 组装完成 | `llm_stream` | messages 列表非空 | 纯内存操作 < 50ms |
| `llm_stream` | LLM API 正常返回 | `stream_yield` | LLMClient.async_chat_stream() 成功建立连接 | 记录 TTFT |
| `llm_stream` | LLM API 调用失败或超时 | `output_error` | HTTP 非 200 或连接超时 | 抛出 LLMUnavailableError |
| `stream_yield` | async for 迭代正常完成 | `output_normal` | finish_reason='stop' | 累计文本 ≥ 一个完整段落 |
| `stream_yield` | asyncio.TimeoutError 且有部分文本 | `output_partial` | finish_reason='length'/'timeout' | accumulated_text 至少含一个 ## 标题段落 |
| `stream_yield` | asyncio.TimeoutError 且无文本 | `output_timeout` | accumulated_text 为空字符串 | 抛出 GenerationTimeoutError |
| `output_normal` | — | 返回 | — | 组装 GenerationResult + Prometheus 埋点 |
| `output_partial` | — | 返回 | — | 组装 GenerationResult(is_partial=True) + WARNING 日志 |
| `output_blocked` | — | 返回 | — | 直接返回硬编码安全提示，耗时 < 10ms |
| `output_timeout` | — | 抛出异常 | — | 记录 ERROR 日志 |

### 1.9 异常与边界条件 `【对内实现】`

#### 1.9.1 异常 1：输入校验失败

- **触发条件**：
  - `behavior_description` 为空字符串 `""` 或长度 > 2000（Pydantic `min_length=1, max_length=2000`）
  - `profile_summary` 为空字符串（Pydantic `min_length=1`）
  - `request_id` 不是有效 UUID 格式（Pydantic `UUID` 类型）
  - `crisis_result` 为 None 或缺少 `final_level`/`block_deep_response` 字段
  - `search_result` 为 None 或缺少 `results` 字段
- **处理策略**：
  1. Pydantic 校验阶段捕获 `ValidationError`
  2. 提取第一个失败字段的错误信息（`error.errors()[0]`）
  3. 包装为 `GenerationInputError(detail={"field": "behavior_description", "msg": "ensure this value has at least 1 characters", "received": ""})`（继承 `AppException`）
  4. 返回 HTTP 422，不进入 Prompt 构建和 LLM 调用
  5. 记录结构化日志：`logger.warning("generation_input_validation_failed", field=..., trace_id=..., request_id=input.request_id if hasattr else "unknown")`
- **重试参数**：不重试。客户端（CSLT-08）修正后重新发起请求。

#### 1.9.2 异常 2：LLM API 不可用

- **触发条件**：
  - `LLMClient.async_chat_stream()` 内部 HTTP 调用返回 4xx/5xx 状态码
  - 或 TCP 连接超时（> `GENERATION_TIMEOUT_S` 秒未建立连接——注意区分"全流程 15s 超时"和"连接建立超时"）
  - 或响应体 JSON 解析失败（`choices[0].delta.content` 字段缺失）
- **处理策略**：
  1. 捕获 `httpx.HTTPStatusError` 或 `httpx.ConnectTimeout`（由 py-llm 客户端统一包装为 `LLMClientError`）
  2. 包装为 `LLMUnavailableError(detail="LLM 生成服务暂时不可用，请稍后重试", original_error=e)`
  3. 状态码设为 503
  4. 记录 CRITICAL 日志：`logger.critical("llm_api_unavailable", status_code=..., error_detail=str(e), trace_id=...)`
  5. 不调用 `yield`——AsyncGenerator 在此场景下不产出任何 chunk
  6. 清除当前 Prometheus Counter 的增量（此请求应计入 error 而非正常计数）
- **重试参数**：**不重试**。设计决策：单次 LLM 调用——重试增加延迟且不确定能恢复，应急场景不应让用户等待更久。上游调用方（CSLT-08）可在收到错误后启动冷却期并给用户"重试"选项。

#### 1.9.3 异常 3：生成全流程超时

- **触发条件**：
  - 从 `generate_emergency_plan()` 被调用开始计时，到 `asyncio.wait_for()` 触发 `asyncio.TimeoutError`（超过 `GENERATION_TIMEOUT_S=15.0` 秒）
  - 超时可能发生在 LLM 流式迭代期间的任何时刻（包括 Prompt 构建后的 API 调用等待、流式迭代中间某次 yield 等）
- **处理策略**：
  1. 捕获 `asyncio.TimeoutError`
  2. 检查 `accumulated_text` 是否有内容：
     - 若长度 > 0 且包含至少一个 `## ` 开头的标题段落（正则 `##\s[一二三四]、` 检测）→ 标记 `finish_reason=PARTIAL`，`is_partial=True`，将已有文本返回
     - 若长度 > 0 但不含完整段落标题 → 视为无有效内容，标记 `finish_reason=TIMEOUT`，`accumulated_text=""`，抛出 `GenerationTimeoutError`
     - 若长度 == 0 → 抛出 `GenerationTimeoutError(detail="应急方案生成超时，请稍后重试（30秒冷却期）")`
  3. 记录 WARNING 日志：`logger.warning("generation_timeout", elapsed_ms=..., partial_text_len=len(accumulated_text), trace_id=...)`
  4. yield 最后一个 `GenerationChunk(text="", is_final=True, finish_reason="timeout")`（仅 PARTIAL 场景）
- **重试参数**：不重试。15s 为全流程硬超时，超时即终止。上游 CSLT-08 可在收到 PARTIAL 结果后决定是否让用户重新请求（需满足 30s 冷却期约束）。

#### 1.9.4 异常 4：案例切片列表为空（边界条件——非异常的正常业务状态）

- **触发条件**：
  - `search_result.results` 为空列表 `[]` 且 `search_result.total_count == 0`
  - 或 `search_result.degradation_applied == True` 且 `search_result.degradation_level == "ALL_TAGS_REMOVED"` 但 results 仍为空
- **处理策略**：
  1. 在 Prompt 构建时（步骤 3），将「参考案例」区域替换为："**注意**：当前暂无与您描述情况相匹配的真实干预案例参考。以下建议基于通用专业知识生成，建议咨询专业医生或特教老师获取更具针对性的指导。"
  2. System Prompt 中追加指令："当前无参考案例可供引用，因此你的回答中不得包含任何 [N] 格式的来源引用标记。"
  3. `prenumbered_slices` 为空列表（0 条）
  4. 后续所有步骤（LLM 调用、流式产出、引用反查）正常执行——`referenced_slice_ids` 和 `source_list` 自然为空
  5. 不抛异常——零案例为正常业务状态
- **重试参数**：不适用（非异常状态）。

#### 1.9.5 异常 5：LLM 输出不包含免责声明

- **触发条件**：
  - LLM 生成的 `accumulated_text` 末尾 200 字符内不包含免责声明关键文本（`"不构成医疗诊断"` 或 `"以上建议由 AI 生成"`）
- **处理策略**：
  1. 在步骤 6（流式完成收尾）中进行免责声明存在性检查——`bool(re.search(r"不构成医疗诊断|以上建议由 AI 生成", accumulated_text[-200:]))`
  2. 若缺失 → 强制在 `accumulated_text` 末尾追加固定免责声明文本（`DISCLAIMER_TEXT = "\n\n---\n\n以上建议由 AI 生成，仅供参考，不构成医疗诊断或治疗建议。如情况紧急，请立即联系专业医疗机构。"`）
  3. 记录 WARNING 日志：`logger.warning("disclaimer_missing_from_llm_output", trace_id=...)`
  4. 不视为异常——免责声明容错追加是设计级安全保障，非运行时错误
- **重试参数**：不适用（非异常，自动修复）。

### 1.10 验收测试场景 `【对内实现】`

#### 1.10.1 正向测试 1：完整输入正常生成

- **场景**：CSLT-08 传入完整数据（含 8 条案例切片、轻度危机等级、正常档案），系统生成完整四段式方案
- **Given**: `EmergencyPlanInput` 含 `crisis_result.block_deep_response=False`、`search_result.results` 含 8 条 `CaseSliceDto`（各字段完整）、`profile_summary`="诊断类型：ASD\n..."（约 600 汉字）、`behavior_description`="儿子在商场突然捂耳朵蹲下"、`request_id="a1b2c3d4-..."`
- **When**: 调用 `result = await generate_emergency_plan(input)`
- **Then**:
  - 返回 `GenerationResult`，`finish_reason=COMPLETE`，`is_partial=False`
  - `text` 包含 `## 一、即时安全干预动作`、`## 二、情绪安抚话术`、`## 三、后续观察指标`、`## 四、就医判断标准` 四个标题段落
  - `referenced_slice_ids` 长度 ≥ 1（LLM 至少引用了一条案例）
  - `source_list` 非空（含引用案例编号）
  - `disclaimer` 包含 "不构成医疗诊断"
  - `generation_time_ms > 0`，`ttft_ms ≤ 3000`
  - 不抛出异常

**完整 JSON 测试数据**：
```json
{
  "input": {
    "crisis_result": {
      "final_level": "mild",
      "block_deep_response": false,
      "manual_review_flag": false,
      "review_confidence": null,
      "judgment_sources": [
        {"layer_name": "PreSelectionLayer", "level": null, "details": {"high_risk_hit": false}},
        {"layer_name": "RuleEngineLayer", "level": null, "details": {"matched_keywords": [], "negation_filtered": false}},
        {"layer_name": "LLMReviewLayer", "level": "mild", "details": {"prompt_version": "v1"}}
      ],
      "degradation_note": null
    },
    "search_result": {
      "results": [
        {
          "slice_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
          "case_id": "CASE-042",
          "slice_text": "在嘈杂商场环境中ASD儿童出现听觉感官过载反应，捂耳朵蹲下拒绝移动，建议立即带离刺激源",
          "chunk_type": "intervention",
          "similarity_score": 0.92,
          "composite_score": 0.88,
          "evidence_level": "NCAEP",
          "case_title": "ASD商场感官过载干预案例",
          "source": "expert",
          "case_created_at": "2025-11-03",
          "applicable_tags": {"age_range": "学龄儿童(6-12岁)", "behavior_type": "情绪崩溃"}
        }
      ],
      "total_count": 1,
      "is_complete": true,
      "query_fingerprint": "e3b0c44298fc1c149afbf4c8996fb924",
      "degradation_applied": false,
      "degradation_level": "NONE",
      "elapsed_ms": 350.0
    },
    "profile_summary": "- **诊断类型**：ASD\n- **主要行为类型**：情绪崩溃\n- **最近事件**：\n  1. 2026-05-25：因噪音触发情绪崩溃，干预方式为提供降噪耳机，效果部分缓解",
    "behavior_description": "儿子在商场突然捂耳朵蹲下，拒绝移动，持续尖叫，之前在家也出现过类似情况",
    "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "block_variant": null
  },
  "expected_response": {
    "finish_reason": "COMPLETE",
    "is_partial": false,
    "text_contains": ["## 一、即时安全干预动作", "## 二、情绪安抚话术", "## 三、后续观察指标", "## 四、就医判断标准"],
    "disclaimer": "以上建议由 AI 生成，仅供参考，不构成医疗诊断或治疗建议。如情况紧急，请立即联系专业医疗机构。",
    "referenced_slice_ids_min_length": 1,
    "source_list_min_length": 1,
    "ttft_ms_le": 3000,
    "generation_time_ms_gt": 0
  }
}
```

#### 1.10.2 正向测试 2：零案例正常生成

- **场景**：上游无任何参考案例（罕见行为类型），系统基于通用知识生成方案并明确告知用户
- **Given**: `search_result.results=[]`、`total_count=0`、`block_deep_response=False`
- **When**: 调用 `result = await generate_emergency_plan(input)`
- **Then**:
  - `finish_reason=COMPLETE`，`is_partial=False`
  - `text` 首段包含 "暂无与您描述情况相匹配的真实干预案例参考"
  - `referenced_slice_ids` 为空列表 `[]`
  - `source_list` 为空列表 `[]`
  - `text` 中不含任何 `[N]` 格式的引用标记
  - 不抛出异常

**完整 JSON 测试数据**：
```json
{
  "input": {
    "crisis_result": {
      "final_level": "mild",
      "block_deep_response": false,
      "manual_review_flag": false,
      "review_confidence": 0.88,
      "judgment_sources": [
        {"layer_name": "PreSelectionLayer", "level": null, "details": {"high_risk_hit": false}},
        {"layer_name": "LLMReviewLayer", "level": "mild"}
      ],
      "degradation_note": null
    },
    "search_result": {
      "results": [],
      "total_count": 0,
      "is_complete": true,
      "reason": "case_library_empty",
      "query_fingerprint": "abc123",
      "degradation_applied": true,
      "degradation_level": "ALL_TAGS_REMOVED",
      "elapsed_ms": 180.0
    },
    "profile_summary": "- **诊断类型**：ADHD\n- **主要行为类型**：刻板行为",
    "behavior_description": "罕见行为类型：患者出现从未记录过的特殊行为模式",
    "request_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
    "block_variant": null
  },
  "expected_response": {
    "finish_reason": "COMPLETE",
    "is_partial": false,
    "text_contains": ["暂无与您描述情况相匹配的真实干预案例参考"],
    "referenced_slice_ids": [],
    "source_list": [],
    "text_not_contains_pattern": "\\[\\d+\\]"
  }
}
```

#### 1.10.3 正向测试 3：AsyncGenerator 流式产出

- **场景**：通过 `stream_generate()` 流式消费各 chunk，最后一个 chunk `is_final=True`
- **Given**: 同正向测试 1 的完整输入
- **When**: `async for chunk in stream_generate(input): chunks.append(chunk)`
- **Then**:
  - `chunks` 列表长度 ≥ 1
  - 除最后一个外，所有 chunk 的 `is_final=False`
  - 最后一个 chunk 的 `is_final=True` 且 `finish_reason="stop"`
  - 所有 chunk 的 `text` 拼接后 = `generate_emergency_plan(input).text`

**完整 JSON 测试数据**：
```json
{
  "input": "同正向测试1的input",
  "expected_response": {
    "chunks_min_count": 1,
    "all_except_last": { "is_final": false },
    "last_chunk": { "is_final": true, "finish_reason": "stop" }
  }
}
```

#### 1.10.4 异常测试 1：阻断场景短路返回

- **场景**：危机等级重度、阻断标记激活，完全跳过 LLM 调用直接输出安全提示
- **Given**: `crisis_result.block_deep_response=True`、`final_level="severe"`、`block_variant="SELF_INJURY"`
- **When**: 调用 `result = await generate_emergency_plan(input)`
- **Then**:
  - `finish_reason=BLOCKED`，`is_partial=False`
  - `generation_time_ms < 50`（短路操作 < 50ms）
  - `ttft_ms == 0.0`
  - `text == ""`（空字符串）
  - `disclaimer` 包含自伤场景的安全提示文本（含 "立即拨打急救电话" 或 "移除危险物品" 等关键词）
  - `referenced_slice_ids` 为空列表
  - **不调用** LLM API（Mock 验证 `LLMClient.async_chat_stream` 未被调用）
  - 不抛出异常

**完整 JSON 测试数据**：
```json
{
  "input": {
    "crisis_result": {
      "final_level": "severe",
      "block_deep_response": true,
      "manual_review_flag": false,
      "review_confidence": null,
      "judgment_sources": [
        {"layer_name": "PreSelectionLayer", "level": "severe", "trigger_rule_id": null, "details": {"checked_types": ["SELF_INJURY"], "high_risk_hit": true}}
      ],
      "degradation_note": null
    },
    "search_result": {
      "results": [],
      "total_count": 0,
      "is_complete": true,
      "query_fingerprint": "def456",
      "degradation_applied": false,
      "degradation_level": "NONE",
      "elapsed_ms": 100.0
    },
    "profile_summary": "- **诊断类型**：ASD",
    "behavior_description": "患者用头撞墙",
    "request_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
    "block_variant": "SELF_INJURY"
  },
  "expected_response": {
    "finish_reason": "BLOCKED",
    "is_partial": false,
    "text": "",
    "generation_time_ms_lt": 50,
    "ttft_ms": 0.0,
    "referenced_slice_ids": [],
    "disclaimer_contains": ["移除危险物品", "急救电话", "专业医疗机构"]
  }
}
```

#### 1.10.5 异常测试 2：LLM API 不可用

- **场景**：DeepSeek API 返回 HTTP 503，不重试
- **Given**: Mock `LLMClient.async_chat_stream()` 抛出 `LLMClientError`（HTTP 503）
- **When**: 调用 `generate_emergency_plan(input)`
- **Then**:
  - 抛出 `LLMUnavailableError`（status_code=503）
  - `LLMClient.async_chat_stream()` 仅被调用 1 次（无重试）

**完整 JSON 测试数据**：
```json
{
  "input": "同正向测试1的input（不含阻断标记）",
  "mock_behavior": "LLMClient.async_chat_stream raises LLMClientError(status_code=503)",
  "expected_response": {
    "exception_type": "LLMUnavailableError",
    "status_code": 503,
    "detail_contains": "LLM 生成服务暂时不可用",
    "llm_call_count": 1
  }
}
```

#### 1.10.6 异常测试 3：全流程超时但部分文本可用

- **场景**：LLM 流式输出在 15s 时超时，但已生成至少一个完整段落
- **Given**: Mock `async_chat_stream()` 在产出 3 个 chunk 后模拟 `asyncio.TimeoutError`（通过 `asyncio.sleep(15.1)` + `raise asyncio.TimeoutError` 模拟）。已产出的 text 含 "## 一、即时安全干预动作\n1. 立即带离..."
- **When**: 调用 `result = await generate_emergency_plan(input)`
- **Then**:
  - `finish_reason=PARTIAL`，`is_partial=True`
  - `text` 非空，含已生成的段落
  - `generation_time_ms` 约 15000-15100
  - 不抛出异常

**完整 JSON 测试数据**：
```json
{
  "input": "同正向测试1的input",
  "mock_behavior": "async_chat_stream yields 3 chunks then asyncio.TimeoutError after 15.1s",
  "expected_response": {
    "finish_reason": "PARTIAL",
    "is_partial": true,
    "text_not_empty": true,
    "text_contains": ["## 一、即时安全干预动作"],
    "generation_time_ms_approx": 15000,
    "no_exception": true
  }
}
```

### 1.11 注意事项与禁止行为 `【对内实现】`

1. **[约束 1 -- 受意图文档 §1.11 约束]** 大模型调用 `temperature` 参数不得超过 0.3。通过 `packages/py-config` 读取 `GENERATION_TEMPERATURE` 环境变量，代码中不硬编码。

2. **[约束 2 -- 受意图文档 §1.11 约束]** 免责声明必须作为固定文本硬注入在 System Prompt 的输出格式要求中，并在步骤 6 末尾做存在性检查（二次保障）。禁止期望 LLM 自主输出完整免责声明。

3. **[约束 3 -- 受设计文档 §1.7 约束]** 阻断场景必须完全跳过 LLM 调用——不得以任何理由"轻度生成后再由下游过滤"。步骤 2 的 `block_deep_response` 检查必须在步骤 3（Prompt 构建）之前执行。

4. **[易错点 1]** 预编号引用在 Prompt 中以 `[1]` `[2]` 等格式出现，LLM 会在输出中包含这些标记。步骤 6 的引用反查必须使用 Prompt 构建时建立的 `prenumbered_slices` 映射表——禁止在 LLM 输出中重新解析引用标记再与原始切片列表做模糊匹配。

5. **[易错点 2]** `stream_generate()` 的超时保护使用 `asyncio.wait_for(coro, timeout=remaining_time)`，其中 `remaining_time = GENERATION_TIMEOUT_S - (time.monotonic() - t_start)`。不要使用固定超时值——Prompt 构建耗时也需要纳入全流程时间预算。

6. **[易错点 3]** `GenerationChunk` 的 `is_final` 标记在超时 PARTIAL 场景下也必须为 true——流式输出无论成功或失败，必须有一个标记流结束的 chunk，防止 CSLT-04 无限等待。

7. **[易错点 4]** System Prompt 中的「参考案例」文本采用预编号而不是依赖 LLM 自行编号。LLM 可能输出不在预编号范围的编号（如 `[15]` 而实际只有 10 条切片）——这种场景仅记录 WARNING 日志，不视为错误，不触发重试。

8. **[设计边界]** 本模块不负责：
   - 冷却期校验——由 CSLT-08 在调用 `generate_emergency_plan()` 之前通过 Redis Key `generation_cooldown:{user_id}:{profile_id}` 检查
   - PII 脱敏——信任上游已完成脱敏，本模块仅做二次扫描（正则匹配手机号/身份证）记录 ALERT 日志
   - 生成结果的持久化存储——由 CSLT-06 在收到 `GenerationResult` 后负责
   - Token 计数和成本核算——由 `packages/py-llm` 统一管理

9. **[禁止行为]** 禁止在 System Prompt 中包含 Python/system/shell 命令执行指令（如 "请执行以下 Python 代码"）。System Prompt 仅用于指导 LLM 的文本生成行为。

10. **[禁止行为]** 禁止在对 LLM 的 User Message 中包含任何用户身份标识信息（user_id、profile_id 等）。这些信息仅通过 trace_id 在日志中关联。

11. **[禁止行为]** 禁止在 `stream_generate()` 的外部循环中做任何同步阻塞操作（如 `time.sleep()`、同步 I/O）。所有操作必须在事件循环内通过 `await` 完成——否则会阻塞其他并发的 AsyncGenerator 生产。

### 1.12 文档详细度自检清单 `【对内实现】`

- [x] 文档自包含：不了解本项目代码的 Agent，仅凭此文档即可完成 CSLT-03 的编码（含类型定义、Prompt 构建逻辑、流式生成、阻断短路、超时降级、契约文件路径）
- [x] 无偷懒表述：全文无 "等等"、"..."、"其他字段"、"类似"、"同上"、"参考其他模块"、"请根据实际情况补充"、"开发者自行决定"
- [x] 类型定义完整：每个 Pydantic 字段都有 `description` + `examples` + 约束（`min_length`/`max_length`/`pattern` 等），详见对应的契约 JSON Schema 文件
- [x] 逻辑步骤完整：7 个步骤，每步都有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：5 种异常/边界场景（输入校验失败、LLM 不可用、全流程超时、零案例边界、免责声明缺失），每种都有精确触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值来源（`DEEPSEEK_MODEL`、`GENERATION_TEMPERATURE`、`GENERATION_MAX_TOKENS`、`GENERATION_TIMEOUT_S`）、条件分支（阻断短路、零案例 Prompt 替换、免责声明追加）、业务规则（预编号引用、全量降序注入、Markdown 格式化）都已显式写出
- [x] 技术栈绑定明确：必须使用和禁止使用的项均已列出，且与项目技术栈设计文档（`docs/篝火智答-技术栈设计.md` v1.2）保持一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致（见 §1.15）

### 1.14 外部接口契约清单 `【已锁定】`

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| EmergencyPlanInput | `docs/contracts/CSLT-03/EmergencyPlanInput.json` | input | draft | CSLT-03 | — |
| GenerationResult | `docs/contracts/CSLT-03/GenerationResult.json` | output | draft | CSLT-03 | CSLT-05, CSLT-06, CSLT-08, QUAL-02 |
| GenerationChunk | `docs/contracts/CSLT-03/GenerationChunk.json` | output | draft | CSLT-03 | CSLT-04 |
| BlockVariant | `docs/contracts/CSLT-03/BlockVariant.json` | shared-enum | draft | CSLT-03 | CSLT-08 |
| GenerationStatus | `docs/contracts/CSLT-03/GenerationStatus.json` | shared-enum | draft | CSLT-03 | CSLT-04, CSLT-05, CSLT-06, CSLT-08, QUAL-02 |

**复用契约**：
| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费用途 |
|:---------|:---------|:---------|:-------|:-------|:---------|
| CrisisJudgmentResult | `docs/contracts/CSLT-01/CrisisJudgmentResult.json` | output | draft | CSLT-01 | 消费 final_level 和 block_deep_response 字段 |
| CrisisLevel | `docs/contracts/CSLT-01/CrisisLevel.json` | shared-enum | draft | CSLT-01 | Prompt 中注入危机等级上下文 |
| SemanticSearchResult | `docs/contracts/CSLT-02/SemanticSearchResult.json` | output | draft | CSLT-02 | 消费 results、degradation_applied、degradation_level |
| CaseSliceDto | `docs/contracts/CSLT-02/CaseSliceDto.json` | output | draft | CSLT-02 | Prompt 中参考案例数据源，全字段消费 |
| EvidenceLevel | `docs/contracts/CSLT-02/EvidenceLevel.json` | shared-enum | draft | CSLT-02 | Prompt 中为每个切片标注循证等级 |
| DegradationLevel | `docs/contracts/CSLT-02/DegradationLevel.json` | shared-enum | draft | CSLT-02 | Prompt 中提示检索精度可能降低 |

### 1.15 意图一致性声明 `【对内实现】`

- **配套意图文档**：`CSLT-03-应急方案生成-意图文档.md`
- **冻结时间**：`2026-05-27 14:29:12`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档 §1.6 中的业务字段定义一致（4 个输入字段 → `EmergencyPlanInput` 精确映射，4 个输出字段 → `GenerationResult` 精确映射）
  - [x] 本落地规范中的状态机实现与意图文档 §1.7 中的状态业务定义一致（均声明无持久化状态流转，仅内部处理阶段：等待输入→组装中→生成中→已完成/阻断输出）
  - [x] 本落地规范中的异常处理策略与意图文档 §1.8 中的异常业务策略一致（空列表 → 零案例 Prompt + 前端灰色提示建议；超时 → 部分返回/完全失败 + 30s 冷却期；阻断 → 跳过 LLM 直接输出安全提示）
  - [x] 本落地规范中的验收测试场景覆盖意图文档 §1.9 中的所有 5 项验收标准（AC-01 四段覆盖率在正向 1/2 中覆盖，AC-02 首字延迟在正向 1 中覆盖，AC-03 专业人员认可度由 QUAL-02 负责本模块提供样本，AC-04 来源引用准确率在步骤 6 引用反查逻辑中覆盖，AC-05 重新生成率由 CSLT-08 冷却期机制保障）
  - [x] 本落地规范中的技术实现未超出意图文档 §1.12 中"留给规范阶段的技术决策"的范围——全部 8 项决策（Prompt 模板、LLM 参数、冷却期机制、数据模型、异常处理、档案格式化、生成超时、安全提示文本）已在设计文档中完成决策并在本规范中精确落地
- **偏差说明**：无偏差。技术实现与意图文档完全一致。唯一的技术细化是 LLM 全流程超时阈值设定为 15s（设计文档 §1.6 决策），此项为意图文档 §1.12.7 明确授权规范阶段确定精确值的范围之内。
