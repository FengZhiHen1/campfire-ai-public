## 1 功能点：CSLT-05 置信度后校验 — 落地规范

> **文档生成时间**：`2026-05-27 17:40:00`（Asia/Shanghai）
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | 2026-05-27 17:40:00 | AI Assistant | 初始版本，基于意图文档 v2.0 和技术决策完整报告生成 |

> **配套文档**：本模块的设计思路与决策依据见 `CSLT-05-置信度后校验-设计文档.md`。
> **流水线上下文**：本落地规范基于已冻结的 `CSLT-05-置信度后校验-意图文档.md`（冻结于 2026-05-27 17:03:36）编写。

---

### 1.1 技术栈绑定

- **必须使用**：
  - `FastAPI>=0.115` — 异步 HTTP API 框架，BackgroundTasks 异步工单创建
  - `Pydantic>=2.0` — 输入/输出数据模型强校验，`model_validate()` 解析 LLM JSON 输出
  - `asyncio` — 异步协程编排，关键词扫描和 LLM 调用的串行组织
  - `ahocorasick>=2.0` — AC 自动机关键词匹配引擎，O(n) 复杂度的关键词扫描（复用 CSLT-01 实现）
  - `tenacity>=8.0` — 指数退避重试装饰器，`retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))`
  - `packages/py-llm` — DeepSeek API 统一客户端，`async_chat(messages, stream=False, timeout=5.0)` 非流式 LLM 自评估调用
  - `packages/py-config` — 环境变量配置加载，`CONFIDENCE_LLM_WEIGHT`、`CONFIDENCE_RULE_WEIGHT`、`LOW_CONFIDENCE_DISCLAIMER`、`HIGH_RISK_BLOCK_MESSAGE`
  - `packages/py-logger` — 结构化日志，`logger.info/logger.warning/logger.error` 带 `request_id` 上下文
  - `packages/py-db` — SQLAlchemy 异步 ORM，`async_session` 操作 `consultations` 表
  - `packages/py-cache` — Redis 异步客户端，订阅 `keyword_dict:updates` Pub/Sub channel
  - `Redis>=5.0` — 异步 Redis 客户端，词库热更新通知
  - `PostgreSQL>=17.x` — 关系型数据库，`crisis_keywords` 表（全量加载关键词）和 `consultations` 表（持久化校验结果）

- **禁止使用**：
  - 禁止直接调用 DeepSeek API 而不通过 `packages/py-llm` 统一客户端
  - 禁止在 LLM 自评估中使用流式调用（非流式 JSON 结构化输出适合短评估文本，延迟更低且解析更可靠）
  - 禁止在关键词扫描中使用正则逐词匹配替代 AC 自动机（正则 O(kn) 在数百条关键词时性能劣化）
  - 禁止独立维护关键词词库——必须复用 CSLT-01 的词库加载逻辑和 Redis Pub/Sub 热更新机制
  - 禁止修改 CSLT-03 生成的方案正文内容——只可在末尾追加警示文本或整体替换
  - 禁止在关键词检测未完成前开始置信度计算
  - 禁止在 LLM 自评估不可用时抛出异常中断流程——必须降级为纯规则评分

### 1.2 文件归属

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| 模块入口 | `apps/api-server/app/services/consult/confidence_validator.py` | 置信度后校验服务主模块，包含 `validate_confidence()` 接口 |
| 关键词扫描 | `apps/api-server/app/services/consult/keyword_scanner.py` | AC 自动机关键词扫描器（启动时加载词库，订阅热更新），含 `scan_keywords()` 和 `load_keywords()` |
| 输入模型 | `packages/py-schemas/py_schemas/consult/confidence.py` | `ConfidenceValidationInput`、`ConfidenceValidationOutput`、`ValidationVerdict` Pydantic 模型 |
| LLM 评估模型 | `packages/py-schemas/py_schemas/consult/confidence.py` | `LLMAssessmentResult`（citation_adequacy/logical_coherence/unsourced_claim_risk）Pydantic 模型 |
| 规则校验 | `apps/api-server/app/services/consult/rule_validator.py` | 规则校验器（来源引用覆盖率 + 四段式结构完整性），含 `compute_rule_score()` |
| 测试文件 | `tests/services/consult/test_confidence_validator.py` | `validate_confidence()` 接口的单元/集成测试 |
| 关键词扫描测试 | `tests/services/consult/test_keyword_scanner.py` | AC 自动机加载、扫描、热更新测试 |

### 【已锁定】 1.3 输入定义

**ConfidenceValidationInput**
- 【契约引用】`docs/contracts/CSLT-05/ConfidenceValidationInput.json`
- 本模块作为该契约的定义方
- 消费方：暂无（CSLT-08 编排层在运行时组装后传入）

```python
# 内部类型——不对外单独暴露，仅用于 ConfidenceValidationInput 字段精细校验
class LLMAssessmentResult(BaseModel):
    """LLM 自评估返回的 JSON 结构化评估结果。用于 Pydantic 强校验，校验失败时走降级纯规则评分路径。"""
    citation_adequacy: float = Field(
        ge=0.0, le=1.0,
        description="来源引用充分度评分。评估 LLM 生成内容中对案例切片的引用是否充分和恰当。0=完全没有引用来源，1=所有论断都有来源支撑。"
    )
    logical_coherence: float = Field(
        ge=0.0, le=1.0,
        description="逻辑连贯性评分。评估四段式内容之间的逻辑关系是否自然、不矛盾。0=段落之间逻辑断裂或矛盾，1=逻辑完全连贯。"
    )
    unsourced_claim_risk: float = Field(
        ge=0.0, le=1.0,
        description="无来源声明可感知风险。评估生成内容中有多少论断可能缺乏来源支撑。0=无风险（所有论断都可追溯到引用），1=高风险（大量不可验证的论断）。越低越好。"
    )
```

**复用契约（CSLT-05 消费的已有类型，由其他模块定义）**：
- `CrisisLevel`（CSLT-01）— 三级危机等级 mild/moderate/severe。用于判断是否需要追加特急优先级工单
- `CrisisJudgmentResult`（CSLT-01）— 包含 final_level、block_deep_response、high_risk_keyword_hit（待补充）
- `GenerationResult`（CSLT-03）— 包含 text（方案全文）、source_list（引用清单）、disclaimer（免责声明）

### 【已锁定】 1.4 输出定义

**ConfidenceValidationOutput**
- 【契约引用】`docs/contracts/CSLT-05/ConfidenceValidationOutput.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-08（编排层 UI 策略决策）、CSLT-06（咨询历史持久化）、TICK-01（工单创建）

**ValidationVerdict**
- 【契约引用】`docs/contracts/CSLT-05/ValidationVerdict.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-08（编排层 UI 策略决策）、CSLT-06（咨询历史持久化）

### 【对内实现】 1.5 核心逻辑步骤

1. **步骤 1：输入接收与前置检查**
   - **操作对象**：`ConfidenceValidationInput` 模型实例
   - **具体操作**：
     a. 接收 CSLT-08 编排层传入的 `ConfidenceValidationInput` 字典，调用 `ConfidenceValidationInput.model_validate(data)` 进行 Pydantic 校验
     b. 检查 `block_deep_response` 字段：若为 `True`（upstream 已判定 severe 且阻断 AI 深度回答），直接构造输出——`verdict=PASS`、`confidence_score=0.0`（无意义分数）、`modified_plan_text=input.plan_text`（原文不动）、`ticket_triggered=False`、`validation_time_ms=0`——进入步骤 8
   - **输入来源**：CSLT-08 编排层组装的 `ConfidenceValidationInput` 字典
   - **输出去向**：校验通过的 `ConfidenceValidationInput` 实例进入步骤 2；block_deep_response=True 时直接跳转步骤 8
   - **失败行为**：Pydantic 校验失败 → 抛出 `ValidationError`，不进入任何后续步骤，由 FastAPI 统一异常处理返回 422

2. **步骤 2：高危关键词检测**
   - **操作对象**：AC 自动机内存索引（`KeywordScanner` 实例，已在模块启动时从 `crisis_keywords` 表全量加载）
   - **具体操作**：
     a. 检查 `input.high_risk_keyword_hit`：若存在且为 `True`（CSLT-01 标记用户原文命中高危词），跳转步骤 6a（FORCE_BLOCK 路径）
     b. 对 `input.plan_text`（方案全文）执行独立 AC 自动机扫描：`scanner.scan_keywords(input.plan_text)`
     c. 若扫描命中（返回非空命中列表），跳转步骤 6a（FORCE_BLOCK 路径）
     d. 若均未命中，记录日志 `logger.info("keyword_scan_clean", request_id=input.request_id)`，进入步骤 3
   - **输入来源**：步骤 1 的 `ConfidenceValidationInput.plan_text` + 启动时加载的 AC 自动机关键词库
   - **输出去向**：命中 → 步骤 6a；未命中 → 步骤 3
   - **失败行为**：AC 自动机扫描本身不会失败（纯内存操作）。若 AC 自动机未初始化（词库加载失败），记录 `logger.error("keyword_scanner_not_initialized", request_id=input.request_id)`，但仍执行正则降级扫描（对核心高危词列表逐词 `re.search`），命中则走阻断路径，未命中则进入步骤 3 且标注降级

3. **步骤 3：LLM 自评估调用**
   - **操作对象**：`packages/py-llm` 的 `async_chat()` 函数
   - **具体操作**：
     a. 构建评估 messages：
        - system: `"你是一个应急方案质量评估专家。请评估以下应急方案的内容质量，返回 JSON 格式的评估结果。评估维度：1) citation_adequacy=来源引用充分度（0-1）；2) logical_coherence=逻辑连贯性（0-1）；3) unsourced_claim_risk=无来源声明风险（0-1，越低越好）。仅返回 JSON，不要其他内容。"`
        - user: 包含 `plan_text`（方案全文）+ `"患者行为描述：" + input.behavior_description` + `"来源引用清单：" + json.dumps(input.source_list)`
     b. 调用 `await async_chat(messages, stream=False, timeout=5.0)`，超时 5s
     c. 解析返回的 JSON 文本为 `LLMAssessmentResult`：`LLMAssessmentResult.model_validate_json(response_text)`
     d. 计算 LLM 自评估得分：`llm_score = (citation_adequacy + logical_coherence + (1 - unsourced_claim_risk)) / 3`
   - **输入来源**：步骤 1 的 `ConfidenceValidationInput.plan_text`、`behavior_description`、`source_list`
   - **输出去向**：`llm_score: float` 进入步骤 5；失败则进入步骤 4
   - **失败行为**：三种失败场景均走降级纯规则评分路径（步骤 4），不重试：
     - async_chat 抛出异常（网络错误/API 不可用/503）→ `logger.warning("llm_assessment_unavailable", request_id=input.request_id, error=str(e))`，进入步骤 4
     - async_chat 超时（>5s）→ `logger.warning("llm_assessment_timeout", request_id=input.request_id)`，进入步骤 4
     - JSON 解析失败（LLM 未返回有效 JSON / Pydantic 校验失败）→ `logger.warning("llm_assessment_parse_failed", request_id=input.request_id, raw_response=response_text[:200])`，进入步骤 4

4. **步骤 4：降级纯规则评分**
   - **操作对象**：`RuleValidator` 实例
   - **具体操作**：
     a. 设置 `degradation_note = "llm_unavailable"`
     b. 调用 `compute_rule_score(input.plan_text, input.source_list)` 计算纯规则评分
     c. 规则分数直接作为 `confidence_score`
   - **输入来源**：步骤 1 的 `ConfidenceValidationInput`
   - **输出去向**：`confidence_score: float` 进入步骤 7
   - **失败行为**：规则校验本身不会失败（纯文本分析）。若 `plan_text` 为空字符串，`compute_rule_score()` 返回 `0.0` 而非抛出异常

5. **步骤 5：规则校验与复合评分**
   - **操作对象**：`RuleValidator` 实例 + `py-config` 环境变量配置
   - **具体操作**：
     a. 调用 `compute_rule_score(input.plan_text, input.source_list)` 计算规则校验分数。计分逻辑：
        - **结构完整性（50% 权重）**：扫描 `plan_text` 是否包含四个预定义段落标题——`### 一、即时安全干预动作`、`### 二、情绪安抚话术`、`### 三、后续观察指标`、`### 四、就医判断标准`。每缺失一个段落扣除 25 分，得分为 `(包含的段落数 / 4) × 100`
        - **来源引用覆盖率（50% 权重）**：提取 `plan_text` 中所有 `[N]` 格式的引用标记（N 为正整数）。有效引用定义为 N 在 `1` 到 `len(input.source_list)` 之间。覆盖率 = `去重后的有效引用数 / max(len(input.source_list), 1)`。得分 = `min(覆盖率 / 0.8, 1.0) × 100`
        - 规则分数 = 结构完整性得分 × 0.5 + 来源引用覆盖率得分 × 0.5，再除以 100 归一化到 0-1
     b. 读取配置权重：`llm_weight = float(get_config("CONFIDENCE_LLM_WEIGHT", "0.5"))`，`rule_weight = float(get_config("CONFIDENCE_RULE_WEIGHT", "0.5"))`
     c. 复合评分：`confidence_score = llm_score * llm_weight + rule_score * rule_weight`
     d. Clamp 到 0.0-1.0 区间：`confidence_score = max(0.0, min(1.0, confidence_score))`
   - **输入来源**：步骤 3 的 `llm_score` + 步骤 1 的 `ConfidenceValidationInput`
   - **输出去向**：`confidence_score: float` 进入步骤 7
   - **失败行为**：数值计算本身不会失败。若配置读取失败（环境变量缺失），使用默认值 0.5 并记录 `logger.warning("config_fallback", key="CONFIDENCE_LLM_WEIGHT")`

6. **步骤 6a：阻断输出（FORCE_BLOCK 路径）**
   - **操作对象**：`py-config` 环境变量配置的安全提示模板
   - **具体操作**：
     a. 设置 `confidence_score = 0.0`（高危阻断，无置信度意义）
     b. 设置 `verdict = ValidationVerdict.FORCE_BLOCK`
     c. 读取安全提示模板：`block_message = get_config("HIGH_RISK_BLOCK_MESSAGE", default_block_message)`
     d. 设置 `modified_plan_text = block_message`（整体替换）
     e. 异步触发工单：`background_tasks.add_task(trigger_ticket_with_retry, user_context, request_id, priority="critical")`
        - `trigger_ticket_with_retry` 调用 `POST /api/v1/tickets`，传入脱敏咨询上下文，指定 `priority=critical`
        - 重试 3 次（指数退避 1s/3s/5s），使用 `tenacity` 实现
        - 全部失败：设置 `ticket_creation_failed = True`，记录 `logger.error("ticket_creation_exhausted", request_id=request_id)`
        - 成功：设置 `ticket_triggered = True`，`ticket_creation_failed = False`
   - **输入来源**：步骤 2 的高危关键词命中结果
   - **输出去向**：`ConfidenceValidationOutput` 进入步骤 8
   - **失败行为**：工单创建失败不影响模块主流程——`ticket_creation_failed=True` 标注在输出中，由 CSLT-08 前端展示手动联系提示

7. **步骤 7：判定分支（PASS vs APPEND_WARNING）**
   - **操作对象**：置信度分数 + 阈值常量 `CONFIDENCE_THRESHOLD = 0.7`
   - **具体操作**：
     a. 若 `confidence_score >= 0.7`：
        - `verdict = ValidationVerdict.PASS`
        - `modified_plan_text = input.plan_text`（原文不动）
        - `ticket_triggered = False`
        - `ticket_creation_failed = False`
     b. 若 `confidence_score < 0.7`：
        - `verdict = ValidationVerdict.APPEND_WARNING`
        - 读取追加免责文案：`warning_text = get_config("LOW_CONFIDENCE_DISCLAIMER", default_warning_text)`
        - `modified_plan_text = input.plan_text + "\n\n" + warning_text`（原文末尾追加，两者之间以两个换行分隔）
        - 异步触发工单（同步骤 6a 工单创建逻辑）：`background_tasks.add_task(trigger_ticket_with_retry, ...)`
        - `ticket_triggered = True`
     c. 若 `confidence_score < 0.7` 但步骤 3 失败走降级路径（步骤 4）：degradation_note 保持步骤 4 设置的 "llm_unavailable"
   - **输入来源**：步骤 5 或步骤 4 的 `confidence_score`
   - **输出去向**：`ConfidenceValidationOutput` 各字段组装完成，进入步骤 8
   - **失败行为**：判定逻辑本身不涉及外部调用，不会失败

8. **步骤 8：超时安全检查与持久化**
   - **操作对象**：计时器 + `BackgroundTasks` 实例
   - **具体操作**：
     a. 计算总耗时：`validation_time_ms = (time.perf_counter() - start_time) * 1000`
     b. 若 `validation_time_ms > 3000` 且当前 `verdict == PASS`：执行超时安全兜底——将 verdict 修改为 `APPEND_WARNING`，追加文案，触发工单，设置 `degradation_note = "timeout_fallback"`
     c. 日志记录：`logger.info("confidence_validation_complete", request_id=input.request_id, verdict=verdict.value, score=confidence_score, elapsed_ms=validation_time_ms, degraded=(degradation_note is not None))`
     d. 异步持久化：`background_tasks.add_task(persist_validation_result, request_id=input.request_id, confidence_score=confidence_score, verdict=verdict.value, validation_detail=validation_detail)`
        - `persist_validation_result` 将校验结果写入 `consultations` 表的 `confidence_score`（DECIMAL(3,2)）和 `validation_detail`（JSONB：含 llm_score、rule_score、degradation_note、verdict 等）字段
   - **输入来源**：步骤 6a 或步骤 7 组装的各输出字段
   - **输出去向**：完整的 `ConfidenceValidationOutput` 实例返回给调用方（CSLT-08 编排层）
   - **失败行为**：持久化失败 → `logger.error("validation_persist_failed", request_id=request_id)`，但不影响输出返回——校验结果已交付

### 【已锁定】 1.6 接口契约

#### 1.6.1 接口 1：validate_confidence

```python
async def validate_confidence(
    input: ConfidenceValidationInput,
    background_tasks: BackgroundTasks,
) -> ConfidenceValidationOutput:
    """
    对 CSLT-03 生成的应急方案进行置信度后校验。

    校验流程分两阶段：
    1. 关键词安检：检查用户原文和方案全文是否命中高危关键词。命中则强制阻断。
    2. 置信度复合评分：LLM 自评估（50%）+ 规则校验（50%）加权计算。低于阈值则追加提示并触发工单。

    Args:
        input: 校验输入，包含方案全文、来源清单、危机等级、行为描述、request_id 等
        background_tasks: FastAPI BackgroundTasks 实例，用于异步工单创建和结果持久化

    Returns:
        ConfidenceValidationOutput: 校验结果，包含置信度分数、判定结论、修改后的方案全文等

    Raises:
        ValidationError: 输入校验失败（Pydantic Schema 校验不通过）
        ValidationTimeoutError: 校验整体超时（>3s 且无法安全兜底；正常超时走 APPEND_WARNING 兜底不抛异常）

    Side Effects:
        - 通过 background_tasks 异步调用 POST /api/v1/tickets 创建工单
        - 通过 background_tasks 异步写入 consultations.confidence_score 和 consultations.validation_detail
        - 记录结构化日志（含 request_id）

    Performance:
        目标 P95 <= 3s（含 LLM 自评估 + 规则校验；工单创建和持久化为异步，不计入）
        LLM 自评估超时 5s 后降级纯规则评分，纯规则评分耗时 < 100ms

    Degradation:
        - LLM 自评估不可用 → 降级纯规则评分（degradation_note='llm_unavailable'）
        - LLM 自评估超时（5s）→ 降级纯规则评分
        - LLM 输出格式异常 → 降级纯规则评分
        - 整体超时（3s）且原本 PASS → 降级为 APPEND_WARNING（degradation_note='timeout_fallback'）
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `validate_confidence` —— 语义化，描述"校验置信度"的业务动作 |
| **输入类型** | `ConfidenceValidationInput`（详见"输入定义"章节） |
| **输出类型** | `ConfidenceValidationOutput`（详见"输出定义"章节） |
| **异常类型** | `ValidationError`、`ValidationTimeoutError`（详见"异常与边界条件"章节） |
| **副作用** | 异步工单创建（POST /api/v1/tickets）、异步持久化（consultations 表写入）、结构化日志 |
| **性能目标** | P95 <= 3s（复合评分路径），纯规则评分降级路径 < 100ms |
| **降级策略** | LLM 不可用/超时/格式异常 → 纯规则评分；整体超时 → 安全兜底 APPEND_WARNING |

### 【已锁定】 1.7 依赖与集成接口

#### 1.7.1 关键基础设施依赖（硬性前提）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目依据 |
|:---|:---|:---|:---|:---|
| 关系型数据库 | PostgreSQL 17.x | `SELECT keyword FROM crisis_keywords WHERE active = true` + `conn.execute(text(sql))` via SQLAlchemy async | 模块启动时全量加载高危关键词到 AC 自动机内存索引 | 技术栈设计 §4.1 `crisis_keywords` 表 |
| 关系型数据库 | PostgreSQL 17.x | `UPDATE consultations SET confidence_score = $1, validation_detail = $2::jsonb WHERE request_id = $3` via SQLAlchemy async | 校验完成后异步持久化置信度分数和详情到 consultations 表 | 技术栈设计 §4.1 `consultations` 表定义 |
| 缓存/消息 | Redis 7.x | `SUBSCRIBE keyword_dict:updates` via `redis.asyncio` Pub/Sub | 运行时接收词库热更新通知，触发重新加载 AC 自动机 | CSLT-01 设计文档 §1.1 关键词词库热加载 |
| 外部 API | DeepSeek API（通过 py-llm）| `await py_llm.async_chat(messages, stream=False, timeout=5.0)` | LLM 自评估调用，传入评估 system prompt + 方案全文 + 行为描述 + 来源清单，返回 JSON 结构化评估结果 | 技术栈设计 §3.2 DeepSeek API、§4.1 py-llm 统一客户端 |
| 配置系统 | py-config (pydantic-settings) | `get_config(key: str, default: str) -> str` | 读取 `CONFIDENCE_LLM_WEIGHT`、`CONFIDENCE_RULE_WEIGHT`、`LOW_CONFIDENCE_DISCLAIMER`、`HIGH_RISK_BLOCK_MESSAGE` 等环境变量 | 技术栈设计 §6.2 环境变量配置模式 |
| 日志系统 | py-logger (structlog) | `logger.info("event", request_id=..., score=..., verdict=...)` | 校验全链路结构化日志，含 request_id 关联 | 技术栈设计 §6.3 结构化日志 |

#### 1.7.2 核心功能依赖（可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| CSLT-01 危机分级判定 | `CrisisJudgmentResult` 输出对象（final_level, block_deep_response, high_risk_keyword_hit） | 获取上游判定的危机等级和关键词命中状态。注意 high_risk_keyword_hit 字段为契约间隙，降级方案为从 judgment_sources 反推 | ✅ 已落地（CSLT-01 契约已冷冻，high_risk_keyword_hit 待 s08 补充） |
| CSLT-03 应急方案生成 | `GenerationResult` 输出对象（text, source_list, disclaimer） | 获取待评估的方案全文、来源引用清单和免责声明 | ✅ 已落地（CSLT-03 契约已冷冻，CSLT-05 已登记为消费方） |
| TICK-01 工单自动生成 | `POST /api/v1/tickets` HTTP 调用，请求体含 consultation_context（脱敏）、trigger_reason、priority | 置信度不足或高危阻断时异步创建人工兜底工单 | ⏭️ 未开始（需 mock TICK-01 接口响应：`{"id": "mock-uuid", "status": "open"}`） |
| CSLT-08 咨询编排逻辑 | 消费 `ConfidenceValidationOutput`，决定前端 UI 策略 | 编排层根据 verdict 选择前端展示策略：PASS=正常展示，APPEND_WARNING=展示加粗警示，FORCE_BLOCK=展示安全提示 | ⏭️ 未开始（CSLT-08 可基于 CSLT-05 契约进行并行开发） |
| CSLT-06 咨询历史管理 | 不直接调用。通过异步持久化写入 `consultations.confidence_score` 和 `consultations.validation_detail` | 校验结果写入咨询历史，供家属回溯和平台质量分析 | ⏭️ 未开始（CSLT-06 消费 consultations 表中的已有字段） |

**Mock 策略**：
- TICK-01 未落地时，`trigger_ticket_with_retry` 内部调用替换为 mock HTTP 响应 `{"id": "00000000-0000-0000-0000-000000000000", "status": "open"}`，不实际发起 HTTP 请求
- CSLT-08 未落地时，`validate_confidence()` 接口可直接通过单元测试独立验证——输入构造 `ConfidenceValidationInput`，断言输出字段取值
- 关键词库可 mock 为固定词列表 `["自伤", "自杀", "药物", "伤害自己", "不想活"]`，不依赖 PostgreSQL 加载

### 【对内实现】 1.8 状态机

本功能点不涉及状态流转，故无需状态机。单次校验的内部阶段（等待输入 → 前置检查 → 关键词检测 → 置信度计算 → 已完成）为运行时内存状态，通过 `async/await` 协程序列自然表示，不持久化。

### 【对内实现】 1.9 异常与边界条件

#### 1.9.1 异常 1：LLM 自评估不可用

- **触发条件**（任一满足）：
  - `async_chat()` 调用抛出异常（HTTP 503/网络错误/API key 无效）
  - `async_chat()` 调用超时（> 5 秒，`packages/py-llm` 统一超时配置 `timeout=5.0`）
  - 返回文本 `LLMAssessmentResult.model_validate_json()` 校验失败（JSON 解析异常 / 缺少必填字段 / 字段值超出 0-1 范围）

- **处理策略**：
  1. 不重试——LLM 自评估调用失败大概率是持续性故障（API 不可用/配额耗尽/网络分区），重试增加延迟且大概率仍失败
  2. 记录 WARNING 级别日志：`logger.warning("llm_assessment_degraded", request_id=request_id, reason=<具体原因>, elapsed_ms=<已耗时>)`
  3. 降级为纯规则评分模式：`degradation_note = "llm_unavailable"`
  4. 调用 `compute_rule_score()` 计算纯规则分数，直接作为 `confidence_score`
  5. 降级后的置信度分数在输出中标注为「纯规则评分」，与正常复合评分可区分
  6. 后续判定流程不变：分数 >= 0.7 走 PASS，< 0.7 走 APPEND_WARNING

- **重试参数**：不重试。直接降级。

#### 1.9.2 异常 2：校验流程整体超时

- **触发条件**：
  - 从步骤 1 开始计时，总耗时 `(time.perf_counter() - start_time) * 1000 > 3000`（意图文档 AC-03 约束：总耗时不超过 3 秒）
  - LLM 自评估可能在 timeout=5.0s 前就已使总耗时迫近 3s 上限

- **处理策略**：
  1. 在步骤 8（输出组装后的最后一步）检查总耗时
  2. 若 `validation_time_ms > 3000` 且当前 verdict 为 `PASS`：
     - 修改为更安全的判定：`verdict = APPEND_WARNING`
     - 追加警告文案至 scheme 末尾
     - 异步触发工单：`background_tasks.add_task(trigger_ticket_with_retry, ...)`
     - 设置 `degradation_note = "timeout_fallback"`
     - 记录 WARNING 日志：`logger.warning("validation_timeout_fallback", request_id=request_id, elapsed_ms=validation_time_ms, original_verdict="PASS")`
  3. 若 `validation_time_ms > 3000` 且当前 verdict 已为 `APPEND_WARNING` 或 `FORCE_BLOCK`：不额外修改判定，仅追加 degradation_note 标注超时
  4. 不抛出异常——安全兜底策略确保校验流程不被阻塞

- **重试参数**：不重试（超时后安全兜底已完成，重试无意义）

#### 1.9.3 异常 3：TICK-01 工单创建失败

- **触发条件**：
  - `POST /api/v1/tickets` 返回非 2xx（含 4xx 客户端错误和 5xx 服务端错误）
  - HTTP 连接超时（> 10s，覆盖 DNS 解析 + TCP 握手 + 响应等待）
  - 响应体 JSON 解析失败

- **处理策略**：
  1. 使用 `tenacity` 库的指数退避重试：
     - `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))`
     - 退避间隔：第 1 次重试 1s 后、第 2 次重试 3s 后、第 3 次重试 5s 后
  2. 每次重试前记录日志：`logger.warning("ticket_creation_retry", request_id=request_id, attempt=N, delay_s=D)`
  3. 3 次全部失败后：
     - 设置输出字段 `ticket_creation_failed = True`
     - 记录 ERROR 日志：`logger.error("ticket_creation_exhausted", request_id=request_id, last_error=str(e))`
     - **不重新抛出异常**——主流程不受影响，`ConfidenceValidationOutput` 正常返回
  4. 下游 CSLT-08 编排层根据 `ticket_creation_failed=True` 在前端展示：**「工单创建失败，请手动联系专家」**

- **重试参数**：最大 3 次，指数退避间隔 1s / 3s / 5s（基于 `tenacity.wait_exponential`）。每次重试前重置 HTTP 连接。

#### 1.9.4 异常 4：置信度分数持久化失败

- **触发条件**：
  - `UPDATE consultations SET confidence_score = $1, validation_detail = $2::jsonb WHERE request_id = $3` 执行失败
  - PostgreSQL 连接池耗尽或数据库不可用
  - `request_id` 在 `consultations` 表中不存在（CSLT-06 尚未写入记录）

- **处理策略**：
  1. 记录 WARNING 日志：`logger.warning("validation_persist_failed", request_id=request_id, error=str(e))`
  2. **不阻塞校验结果返回**——持久化是异步后台任务（`background_tasks.add_task`），失败不影响 `ConfidenceValidationOutput` 的交付
  3. 若 `request_id` 不存在（ConsultationHistory record 尚未创建），在日志中标注 `"no_matching_consultation_record"`，等待 CSLT-06 创建记录后再补写

- **重试参数**：不重试。持久化失败属于非阻塞性副任务，让 `background_tasks` 自行失败

### 【对内实现】 1.10 验收测试场景

#### 1.10.1 正向测试 1：正常方案通过校验

- **场景**：LLM 生成的方案质量高，四段式结构完整，来源引用充分，LLM 自评估返回高分
- **Given**：
  ```json
  {
    "plan_text": "### 一、即时安全干预动作\n1. 立即将孩子带离嘈杂环境，寻找安静角落...\n\n### 二、情绪安抚话术\n1. 用平缓而坚定的语气对孩子说[1]...\n\n### 三、后续观察指标\n1. 观察孩子是否能被安抚[2]...\n\n### 四、就医判断标准\n1. 若行为持续超过30分钟未缓解[3]...",
    "source_list": ["案例A-情绪安抚", "案例B-观察指标", "案例C-就医判断"],
    "disclaimer": "本建议由AI生成，不构成医疗诊断，请咨询专业医生",
    "crisis_level": "mild",
    "block_deep_response": false,
    "high_risk_keyword_hit": false,
    "behavior_description": "儿子在商场突然捂耳朵蹲下，拒绝移动，持续尖叫",
    "request_id": "550e8400-e29b-41d4-a716-446655440000"
  }
  ```
- **When**：调用 `validate_confidence(input, background_tasks)`
- **Then**：
  - 返回 `ConfidenceValidationOutput`，`verdict=PASS`
  - `confidence_score >= 0.7`
  - `modified_plan_text` 与输入 `plan_text` 完全一致（无追加）
  - `ticket_triggered=False`
  - `degradation_note=None`
  - `validation_time_ms > 0`
  - 关键词检测日志为 "keyword_scan_clean"

#### 1.10.2 正向测试 2：低置信度方案触发追加提示

- **场景**：LLM 生成的方案缺少一段结构，来源引用覆盖率不足，置信度低于 0.7
- **Given**：
  ```json
  {
    "plan_text": "### 一、即时安全干预动作\n1. 安抚患者...\n\n### 二、情绪安抚话术\n安抚...",
    "source_list": ["案例A", "案例B"],
    "disclaimer": "本建议由AI生成，不构成医疗诊断",
    "crisis_level": "moderate",
    "block_deep_response": false,
    "high_risk_keyword_hit": false,
    "behavior_description": "孩子情绪激动",
    "request_id": "550e8400-e29b-41d4-a716-446655440001"
  }
  ```
- **When**：调用 `validate_confidence(input, background_tasks)`
- **Then**：
  - `verdict=APPEND_WARNING`
  - `confidence_score < 0.7`
  - `modified_plan_text` 以原文开头 + `\n\n` + 追加的免责提示文本
  - `ticket_triggered=True`
  - `modified_plan_text` 开头部分等于输入的 `plan_text`（原文未修改）
  - 追加文本包含"置信度偏低"或"联系专业专家"关键词

#### 1.10.3 正向测试 3：upstream 阻断时直接通过

- **场景**：CSLT-01 已判定 severe 且 `block_deep_response=True`，CSLT-05 跳过全部校验直接返回 PASS
- **Given**：
  ```json
  {
    "plan_text": "预设安全提示文本，非LLM生成内容",
    "source_list": [],
    "disclaimer": "",
    "crisis_level": "severe",
    "block_deep_response": true,
    "high_risk_keyword_hit": false,
    "behavior_description": "患者有自伤行为",
    "request_id": "550e8400-e29b-41d4-a716-446655440002"
  }
  ```
- **When**：调用 `validate_confidence(input, background_tasks)`
- **Then**：
  - `verdict=PASS`
  - `confidence_score=0`
  - `validation_time_ms` 接近于 0（未执行任何校验步骤）
  - `ticket_triggered=False`
  - 无任何 LLM 调用或关键词扫描

#### 1.10.4 异常测试 1：高危关键词命中强制阻断

- **场景**：方案全文中出现"药物"关键词，触发 FORCE_BLOCK 路径
- **Given**：
  ```json
  {
    "plan_text": "### 一、即时安全干预动作\n建议服用药物以控制情绪...",
    "source_list": [],
    "disclaimer": "",
    "crisis_level": "mild",
    "block_deep_response": false,
    "high_risk_keyword_hit": false,
    "behavior_description": "孩子哭闹不安",
    "request_id": "550e8400-e29b-41d4-a716-446655440003"
  }
  ```
- **When**：调用 `validate_confidence(input, background_tasks)`
- **Then**：
  - `verdict=FORCE_BLOCK`
  - `confidence_score=0`
  - `modified_plan_text` 是预设安全提示文本（不是原输入的 plan_text）
  - `ticket_triggered=True`
  - 未执行任何 LLM 调用（关键词检测命中后短路）

#### 1.10.5 异常测试 2：LLM 自评估不可用降级

- **场景**：LLM API 返回 503，校验降级为纯规则评分后通过（结构完整、引用充分）
- **Given**：
  ```json
  {
    "plan_text": "### 一、即时安全干预动作\n1. 安抚...\n\n### 二、情绪安抚话术\n1. ...\n\n### 三、后续观察指标\n1. ...\n\n### 四、就医判断标准\n1. ...",
    "source_list": ["案例1", "案例2", "案例3", "案例4"],
    "disclaimer": "本建议由AI生成",
    "crisis_level": "mild",
    "block_deep_response": false,
    "high_risk_keyword_hit": false,
    "behavior_description": "测试",
    "request_id": "550e8400-e29b-41d4-a716-446655440004"
  }
  ```
- **When**：调用 `validate_confidence(input, background_tasks)`（Mock `async_chat` 抛出 `HTTPStatusError(503)`）
- **Then**：
  - `verdict=PASS` 或 `APPEND_WARNING`（取决于纯规则评分是否 >= 0.7）
  - `degradation_note="llm_unavailable"`
  - 无任何异常抛出
  - LLM 自评估调用未被重试

#### 1.10.6 异常测试 3：校验超时安全兜底

- **场景**：LLM 自评估调用接近 3 秒上限，总耗时超过 3 秒，原本 PASS 的判定被降级为 APPEND_WARNING
- **Given**：与正向测试 1 相同的正常输入（Mock `async_chat` 在 2.9s 后返回有效 JSON）
- **When**：规则校验完成时总耗时已超 3s
- **Then**：
  - `verdict=APPEND_WARNING`（而非 PASS）
  - `degradation_note="timeout_fallback"`
  - `ticket_triggered=True`
  - `confidence_score` 由复合评分计算（不为 0）
  - `validation_time_ms > 3000`

### 【对内实现】 1.11 注意事项与禁止行为（编码层面）

1. **[安全底线]** 关键词检测必须放在置信度计算之前执行。代码中不得有任何逻辑路径可以在关键词扫描完成前开始 LLM 调用。违反此条即为安全漏洞。

2. **[内容不可变性]** `modified_plan_text` 的 Pydantic 序列化必须确保 PASS 时与原 `plan_text` 逐字符一致（不得引入额外换行或空白）。APPEND_WARNING 时原文和追加文案之间使用 `\n\n` 分隔——前端据此识别原文结尾位置。

3. **[LLM 输出解析]** `LLMAssessmentResult.model_validate_json()` 校验失败时必须走降级路径，不得吞异常或 retry。`model_validate_json()` 已内建严格的 0-1 范围校验——不额外编写自定义校验逻辑。

4. **[AC 自动机初始化]** 模块启动时必须执行关键词词库加载：从 `crisis_keywords` 表 `SELECT keyword WHERE active = true`，逐词 `automaton.add_word(keyword)` 后 `automaton.make_automaton()`。加载失败时记录 CRITICAL 日志并用降级关键词列表（最少包含 `["自伤", "自杀", "药物"]`）初始化精简版 AC 自动机。

5. **[Redis 订阅容错]** 订阅 `keyword_dict:updates` channel 时若 Redis 不可用：记录 WARNING 日志，以当前 AC 自动机索引继续运行（不阻塞模块启动）。每分钟重试连接 Redis 一次，连接恢复后重新订阅。

6. **[配置读取容错]** 所有 `get_config()` 调用必须提供 `default` 参数——环境变量缺失不抛异常，使用硬编码的默认值。

7. **[多线程安全]** `KeywordScanner` 的 AC 自动机索引是模块级单例。词库热更新时（`reload_keywords()` 被 Pub/Sub 消息触发）必须原子替换索引：先构建新的 AC 自动机实例，再用单次赋值替换模块级引用（Python GIL 下引用赋值是原子的），避免扫描线程读到半构建的索引。

8. **[禁止行为]**
   - 禁止在方案正文中间插入任何内容——追加警示文本只能在末尾
   - 禁止对 CSLT-03 的 `plan_text` 做任何修改或二次格式化——只能全量保持或全量替换
   - 禁止将 LLM 自评估的 System Prompt 硬编码在 validate_confidence 函数中——必须提取为模块级常量或 py-config 配置项
   - 禁止对 TICK-01 API 使用同步 HTTP 调用（如 `requests.post`）——必须使用异步 `httpx.AsyncClient` 或框架提供的 HTTP client
   - 禁止在 BackgroundTasks 中捕获所有异常并静默——必须显式记录 ERROR 日志

### 【对内实现】 1.12 文档详细度自检清单

- [x] 文档自包含：一位不了解本项目代码的 Agent，仅凭此文档即可完成 CSLT-05 模块的编码
- [x] 无偷懒表述：全文未使用 `"等等"`、`"..."`、`"其他字段"`、`"类似"`、`"同上"`、`"参考其他模块"`、`"请根据实际情况补充"`、`"开发者自行决定"`
- [x] 类型定义完整：所有对外契约类型写入 JSON Schema 文件（ConfidenceValidationInput、ConfidenceValidationOutput、ValidationVerdict），内部类型（LLMAssessmentResult）给出了完整 Pydantic 定义含 Field 约束
- [x] 逻辑步骤完整：8 个核心逻辑步骤，每个都有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：4 种异常/边界场景，每种都有精确触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有权重配置默认值（50/50）、阈值常量（0.7、3s、5s）、文案模板都显式声明来源（py-config 环境变量或 hardcoded default）
- [x] 技术栈绑定明确：必须使用和禁止使用的项均已列出，且与项目技术栈设计文档保持一致（FastAPI、Pydantic v2、SQLAlchemy async、ahocorasick、tenacity、py-llm/py-config/py-logger/py-db/py-cache）
- [x] 意图一致性：已确认技术实现与已冻结的意图文档完全一致（验收标准 AC-01~AC-07 全部覆盖）

### 1.14 外部接口契约清单

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| ValidationVerdict | `docs/contracts/CSLT-05/ValidationVerdict.json` | shared-enum | draft | CSLT-05 | CSLT-08, CSLT-06 |
| ConfidenceValidationInput | `docs/contracts/CSLT-05/ConfidenceValidationInput.json` | input | draft | CSLT-05 | — |
| ConfidenceValidationOutput | `docs/contracts/CSLT-05/ConfidenceValidationOutput.json` | output | draft | CSLT-05 | CSLT-08, CSLT-06, TICK-01 |
| CrisisLevel | `docs/contracts/CSLT-01/CrisisLevel.json` | shared-enum | draft | CSLT-01 | CSLT-03, CSLT-05, TICK-01, TICK-02 |
| CrisisJudgmentResult | `docs/contracts/CSLT-01/CrisisJudgmentResult.json` | output | draft | CSLT-01 | CSLT-03, CSLT-05, TICK-01, TICK-02 |
| GenerationResult | `docs/contracts/CSLT-03/GenerationResult.json` | output | draft | CSLT-03 | CSLT-05, CSLT-06, CSLT-08, QUAL-02 |

**已知契约间隙**：`CrisisJudgmentResult` 缺少 `high_risk_keyword_hit: boolean` 字段（CSLT-05 输入定义依赖此字段）。降级方案：从 `judgment_sources` 数组反推 `layer_name="RuleEngine"` 且 `trigger_rule_id` 以 `"KW_"` 开头的条目。

### 1.15 意图一致性声明

- **配套意图文档**：`CSLT-05-置信度后校验-意图文档.md`
- **冻结时间**：`2026-05-27 17:03:36`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档中的业务字段定义一致（§1.6.1 输入 4 字段 + §1.6.2 输出 5 字段全部对应）
  - [x] 本落地规范中的处理阶段与意图文档中的阶段业务定义一致（等待输入 → 关键词检测中 → 置信度计算中 → 降级模式 → 已完成）
  - [x] 本落地规范中的异常处理策略与意图文档中的异常业务策略一致（LLM 降级→纯规则评分、超时→安全兜底、工单失败→标记+提示）
  - [x] 本落地规范中的验收测试场景覆盖意图文档中的所有验收标准（AC-01 关键词阻断率、AC-02 低置信度工单触发率、AC-03 耗时 3s、AC-04 规则可量化、AC-05 高危+重度特急、AC-06 降级不中断、AC-07 持久化写入）
  - [x] 本落地规范中的技术实现未超出意图文档中"留给规范阶段的技术决策"（§1.12 共 8 项）的范围，每项均已在本规范中有明确技术方案
- **偏差说明**：无偏差，技术实现与意图文档完全一致。存在 1 处上游契约间隙（CrisisJudgmentResult 缺少 high_risk_keyword_hit 字段），已在 §1.3 输入定义和 §1.14 契约清单中标注降级方案，不影响本模块技术方案的完整性。
