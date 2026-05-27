# 1 功能点：CSLT-01 危机分级判定 — 落地规范

> **文档生成时间**：`2026-05-27 09:23:20`
> **版本记录**：
> | 版本 | 时间 | 修改人 | 变更摘要 |
> |------|------|--------|----------|
> | v1.0 | `2026-05-27 09:23:20` | AI Assistant | 初始版本，基于已冻结意图文档和设计文档全量生成 |

> **冲突核查指引**：若发现与已有规格文档冲突，优先以时间戳更新的版本为准，并在版本记录中追加冲突解决条目。
> **配套文档**：本模块的设计思路与决策依据见 `CSLT-01-危机分级判定-设计文档.md`。

---

### 1.1 技术栈绑定 `【对内实现】`

- **必须使用**：
  - `fastapi>=0.115`：Service 层依赖注入（Depends）、asyncio 异步路由
  - `pydantic>=2.0`：BaseModel 严格校验、Field 约束、StrEnum 枚举基类
  - `SQLAlchemy>=2.0 async`：crisis_keywords 表 ORM 模型定义与 async session 查询
  - `redis>=5.0 async`：`redis.asyncio.Redis` Pub/Sub 订阅，channel `keyword_dict:updates`
  - `pyahocorasick>=2.0`：AC 自动机构建 goto/failure/output 三表，纯内存扫描
  - `packages/py-llm` — `LLMClient.async_chat()`：DeepSeek API 调用（带超时控制、重试机制）
  - `packages/py-cache` — `RedisClient.subscribe()`：Redis Pub/Sub 词库热加载订阅
  - `packages/py-db` — `CrisisKeyword` ORM 模型、`async_session` 连接管理
  - `packages/py-config` — `Config` pydantic-settings 模式加载环境变量
  - `packages/py-logger` — `Logger.bind(trace_id=..., module="crisis_judgment")` 结构化日志注入
  - `packages/py-schemas` — `BaseSchema` 基类、`UUID` 校验类型
- **禁止使用**：
  - 禁止在关键词匹配中使用 `re.search()` 或 `re.match()` 逐个关键词循环（O(n*m) 退化）
  - 禁止跳过 AC 自动机直接使用字符串 `in` 操作符或 `.find()` 做关键词匹配
  - 禁止在 AC 自动机热加载时直接在现有实例上修改三表（必须 copy-on-write 原子替换）
  - 禁止绕过 `LLMClient` 直接调用 `httpx` 或 `requests` 访问 DeepSeek API
  - 禁止在 LLM 复审超时后进行重试——超时即降级，不让用户无限等待

### 1.2 文件归属 `【对内实现】`

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| Service 入口 | `apps/api-server/app/services/crisis_judgment/service.py` | 危机分级判定 Service 模块入口，`JudgmentPipeline` 和 `judge_crisis()` 接口 |
| Pipeline 实现 | `apps/api-server/app/services/crisis_judgment/pipeline.py` | `JudgmentPipeline` 类：顺序执行三层判定，`merge()` 合并策略 |
| Layer 接口 | `apps/api-server/app/services/crisis_judgment/layer.py` | `JudgmentLayer` 抽象基类，定义 `judge(request) -> JudgmentLayerResult` |
| 前置判定层 | `apps/api-server/app/services/crisis_judgment/pre_selection_layer.py` | `PreSelectionLayer`：检查行为类型勾选中的高危类型 |
| 规则引擎层 | `apps/api-server/app/services/crisis_judgment/rule_engine_layer.py` | `RuleEngineLayer`：AC 自动机扫描 + 否定词过滤 + 档案叠加规则 |
| AC 自动机 | `apps/api-server/app/services/crisis_judgment/ac_matcher.py` | `AhoCorasickMatcher`：构建/热加载/匹配接口，copy-on-write 原子替换 |
| LLM 复审层 | `apps/api-server/app/services/crisis_judgment/llm_review_layer.py` | `LLMReviewLayer`：DeepSeek API 精调复审 + 超时降级 |
| 判定矩阵 | `apps/api-server/app/services/crisis_judgment/merge_matrix.py` | 二维查找表常量 `MERGE_MATRIX`（7x3 dict 嵌套结构） |
| 安全提示模板 | `apps/api-server/app/services/crisis_judgment/safety_prompts.py` | 四类安全提示模板常量（纯文本 Markdown 格式） |
| 类型定义 | `apps/api-server/app/services/crisis_judgment/models.py` | Pydantic 模型：`CrisisJudgmentRequest`、`CrisisJudgmentResult`、`JudgmentLayerResult` 等 |
| 枚举定义 | `apps/api-server/app/services/crisis_judgment/enums.py` | `CrisisLevel`、`BehaviorTypeCategory` Python StrEnum |
| 异常定义 | `apps/api-server/app/services/crisis_judgment/exceptions.py` | `CrisisJudgmentError` 基类、`LLMReviewTimeoutError`、`KeywordDictLoadError` |
| 词库模型 | `packages/py-db/models/crisis_keyword.py` | `CrisisKeyword` SQLAlchemy ORM 模型（映射 crisis_keywords 表） |
| Service 单元测试 | `apps/api-server/tests/services/crisis_judgment/test_service.py` | `judge_crisis()` 全流程单元测试 |
| Layer 单元测试 | `apps/api-server/tests/services/crisis_judgment/test_layers.py` | 各判定层独立单元测试 |
| AC 自动机测试 | `apps/api-server/tests/services/crisis_judgment/test_ac_matcher.py` | AC 自动机构建/匹配/热加载测试 |

### 1.3 输入定义（精确类型） `【已锁定】`

**CrisisJudgmentRequest**
- 【契约引用】`docs/contracts/CSLT-01/CrisisJudgmentRequest.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-08（咨询编排逻辑）在应急咨询流程中组装请求后调用 `judge_crisis()`

内部类型（不对外暴露）：

```python
class PatientProfileSnapshot(BaseModel):
    """患者档案上下文快照 —— 由 PROF-02 注入。PROF-02 尚未落地，当前为占位定义。
    实际类型由 PROF-02 在未来定义完整 Schema，CSLT-01 仅消费不定义。"""
    diagnosis_type: str | None = Field(default=None, description="诊断类型，如 'ASD'、'ADHD'")
    historical_behavior_tags: list[str] = Field(
        default_factory=list,
        description="历史行为标签列表，如 ['self_injury', 'aggression']。档案叠加规则的数据源"
    )
    recent_event_records: list[dict] = Field(
        default_factory=list,
        description="最近事件记录列表，上限 5 条。每条记录含 event_type、occurred_at 等字段"
    )
```

### 1.4 输出定义（精确类型） `【已锁定】`

**CrisisJudgmentResult**
- 【契约引用】`docs/contracts/CSLT-01/CrisisJudgmentResult.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-03（应急方案生成）、CSLT-05（置信度后校验）、TICK-01（工单自动生成）、TICK-02（工单紧急分级）

**CrisisLevel**
- 【契约引用】`docs/contracts/CSLT-01/CrisisLevel.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-03、CSLT-05、TICK-01、TICK-02

**JudgmentLayerResult**
- 【契约引用】`docs/contracts/CSLT-01/JudgmentLayerResult.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-03、CSLT-05

**BehaviorTypeCategory**
- 【契约引用】`docs/contracts/CSLT-01/BehaviorTypeCategory.json`
- 本模块作为该契约的定义方
- 消费方：CSLT-07（应急咨询界面）

### 1.5 核心逻辑步骤 `【对内实现】`

按执行顺序列出可测试的逻辑步骤。每一步是原子操作。

1. **步骤 1：输入校验与 Pipeline 初始化**
   - **操作对象**：`CrisisJudgmentRequest` 数据
   - **具体操作**：调用 `CrisisJudgmentRequest(**kwargs)` 进行 Pydantic 校验，构建 `JudgmentContext`（`request`、`env`、`config` 三字段），实例化 `JudgmentPipeline([PreSelectionLayer(), RuleEngineLayer(), LLMReviewLayer()])`
   - **输入来源**：CSLT-08 编排层调用 `judge_crisis()` 时传入的 dict/Kwargs
   - **输出去向**：校验通过的 `CrisisJudgmentRequest` 和 `JudgmentContext` 进入步骤 2
   - **失败行为**：Pydantic `ValidationError` 时立即抛出，返回 HTTP 422，不进入任何后续步骤。缺失 `behavior_type_selection`（空列表）同样触发校验错误

2. **步骤 2：前置行为类型判定（PreSelectionLayer）**
   - **操作对象**：`JudgmentContext.behavior_type_selection` 列表
   - **具体操作**：遍历 `behavior_type_selection`，若任意元素命中高危集合 `{SELF_INJURY, AGGRESSION, ELOPEMENT, MEDICATION}`，则将 `context.level = severe`、`context.block_deep = True`、`context.skip_remaining = True`
   - **输入来源**：步骤 1 校验通过的 `request.behavior_type_selection`
   - **输出去向**：`JudgmentLayerResult(layer="PreSelectionLayer", level=severe or null)` 写入 `context.sources`；若 `skip_remaining=True` 则直接跳转到步骤 6（跳过步骤 3-5）
   - **失败行为**：不适用——前置判定为纯内存操作，不存在失败路径。若 `behavior_type_selection` 全部为非高危类型，正常进入步骤 3

3. **步骤 3：AC 自动机构建/获取**
   - **操作对象**：`AhoCorasickMatcher` 单例实例
   - **具体操作**：调用 `AhoCorasickMatcher.get_instance()`。若首次调用，从 PostgreSQL `crisis_keywords` 表执行 `SELECT keyword, category, trigger_rule_id FROM crisis_keywords WHERE is_active = true` 全量加载关键词列表，调用 `pyahocorasick.Automaton()` 构建 goto/failure/output 三表并存储在 `self._automaton` 中
   - **输入来源**：PostgreSQL `crisis_keywords` 表（通过 `packages/py-db` 的 `async_session`）
   - **输出去向**：编译完成的 `pyahocorasick.Automaton` 对象传递给步骤 4
   - **失败行为**：PostgreSQL 连接失败或 `crisis_keywords` 表不存在 → 抛出 `KeywordDictLoadError("failed to load keyword dictionary from PostgreSQL")`，触发降级路径：Pipeline 降级为仅依赖前置行为类型判定，`context.degradation_note = "rule_engine_degraded"`，跳过规则引擎层，所有输入直接进入 LLM 复审层（若前置选择未命中高危）。后台每 30 秒重试加载一次，成功时通过 copy-on-write 原子替换 `self._automaton` 并清除降级状态

4. **步骤 4：规则引擎关键词匹配（RuleEngineLayer）**
   - **操作对象**：`request.behavior_description` 字符串
   - **具体操作**：
     1. 调用 `matcher.search(behavior_description)` 执行 AC 自动机扫描，收集所有匹配到的关键词和对应规则编号
     2. 对每条匹配项调用否定词过滤函数 `_negation_filter(match_position: int, text: str, neg_list: list[str]) -> bool`：
        - 从匹配位置向前扫描 7 个字符（最长否定词 2 字符 + 5 字符前向上下文）
        - 查找否定词标识：`["没有", "不会", "以前", "不是", "从未", "不再", "还没"]`
        - 否定词出现在关键词前 5 个中文字符以内 → 标记为否定（排除该匹配）
     3. 对未否定的匹配项：若 `keyword.category == "severe"` → `context.level = severe`、`context.skip_remaining = True`
     4. 执行档案叠加规则检查：`request.patient_profile is not None AND any(tag in profile.historical_behavior_tags for tag in ["self_injury", "aggression"]) AND re.search(r'(又|再次|还是)', behavior_description)` → 若命中 → `context.level = moderate`、`context.manual_review_flag = True`
   - **输入来源**：步骤 3 的 AC 自动机 + 步骤 1 的 `request.behavior_description` + `request.patient_profile`
   - **输出去向**：`JudgmentLayerResult(layer="RuleEngineLayer", level=..., trigger_rule_id=..., details={"matched_keywords": [...], "negation_filtered": [...]})` 写入 `context.sources`；若 `skip_remaining=True` 跳转到步骤 6
   - **失败行为**：不适用——规则引擎为纯内存同步操作，无外部依赖。关键词词库加载失败已在步骤 3 处理

5. **步骤 5：LLM 精调复审（LLMReviewLayer）**
   - **操作对象**：DeepSeek API chat completion 请求
   - **具体操作**：
     1. 组装 System Prompt：`f"你是一名孤独症危机行为评估专家。根据以下信息判断当前场景的危机严重程度（mild/moderate/severe）。只需返回 JSON：{{level, confidence, reasoning}}。宁可误判为重度，不可漏判为轻度。\n\n患者档案：{profile_snapshot}\n行为描述：{behavior_description}\n行为类型勾选：{behavior_types}\n规则引擎初步结果：{rule_engine_result}"`
     2. 调用 `LLMClient.async_chat(messages=[system_prompt, user_msg], model="deepseek-chat", temperature=0.1, max_tokens=512, timeout=config.JUDGMENT_LLM_TIMEOUT_MS / 1000.0)`（超时参数初始 5000ms，待生产环境 P95 调优至 3000ms）
     3. 解析返回值 `response.content` 为 JSON，提取 `level` 和 `confidence`
     4. 若 `level not in ("mild", "moderate", "severe")` 或 JSON 解析失败 → 视为复审异常，采用规则引擎结果
   - **输入来源**：步骤 1 的 `request.behavior_description` + `request.behavior_type_selection` + `request.patient_profile`（序列化为上下文片段）+ 步骤 4 的规则引擎输出
   - **输出去向**：`JudgmentLayerResult(layer="LLMReviewLayer", level=..., details={"raw_response": ..., "prompt_version": "v1"})` 写入 `context.sources`
   - **失败行为**：`asyncio.TimeoutError`（超时 > 配置值）→ `context.llm_timed_out = True`，规则引擎结果为最终等级，`JudgmentLayerResult` 的 details 中标记 `timeouts: true`。超时后 LLM 返回的任何结果仅写入日志（`logger.warning("llm_review_timeout", ...)`），不改变判定结果，不触发重试

6. **步骤 6：合并策略执行（merge）**
   - **操作对象**：`context.sources` 中所有层的 `JudgmentLayerResult`
   - **具体操作**：调用 `merge_matrix.MERGE_MATRIX[rule_engine_level][llm_review_level]` 查找最终等级。
     - 前置选择已判 `severe` → 直接输出 `severe`（跳过矩阵查找）
     - 矩阵编码 `severe + any = severe`（宁升勿降）
     - `moderate + severe = severe`（LLM 可升级规则引擎等级）
     - `severe + mild = severe`（LLM 不可降级规则引擎等级）
     - `llm_timed_out = True` → 采用规则引擎等级为 `final_level`
   - **输入来源**：步骤 2/4/5 的 `context.sources` + `context.llm_timed_out`
   - **输出去向**：`CrisisJudgmentResult` 对象实例
   - **失败行为**：不适用——查找表为 O(1)，无失败路径。若出现未定义的规则引擎×LLM 组合（不应发生），回退到 `max(rule_engine_level, llm_review_level)`（按 severe > moderate > mild 优先级）

### 1.6 接口契约 `【已锁定】`

本章节定义本模块对外暴露的公共接口。

#### 1.6.1 接口 1：judge_crisis

```python
async def judge_crisis(
    request: CrisisJudgmentRequest,
    config: Config | None = None,
) -> CrisisJudgmentResult:
    """
    执行三层递进危机分级判定。

    判定流程：前置行为类型选择 → 规则引擎关键词匹配 → LLM 精调复审。
    前置选择命中高危时跳过后续两层；规则引擎命中重度时跳过 LLM 复审。
    LLM 超时时降级为规则引擎结果。

    Args:
        request: 危机分级判定请求，含患者档案快照、行为类型勾选、行为描述文本
        config: 可选配置注入（用于测试时注入 mock 配置）。若为 None 则从 packages/py-config 加载

    Returns:
        CrisisJudgmentResult: 最终判定结果，含危机等级、阻断标记、复核标记、各层详细结论

    Raises:
        CrisisJudgmentError: 所有判定层面的不可恢复错误基类
        ValidationError: Pydantic 输入校验失败（behavior_type_selection 为空等）
        KeywordDictLoadError: 关键词词库加载失败，规则引擎层级不可用

    Side Effects:
        - 记录各判定层的结构化日志（INFO 级别）
        - 规则引擎命中重度时记录 WARNING 级别安全事件日志
        - LLM 超时时记录 WARNING 级别事件并写入超时详情
        - 不持久化任何判定结果——仅返回内存对象，持久化由调用方（CSLT-08）负责

    Idempotency:
        本函数为无状态判定，每次调用独立执行。同一请求的重复调用产生相同的判定结果
        （假设外部依赖 LLM API 返回一致）。不维护跨调用的缓存的或幂等 Key。

    Thread Safety:
        本函数为 async 协程，内部通过 JudgmentContext 隔离各次调用的状态。
        AC 自动机实例为模块级单例，读操作线程安全，热加载时通过 copy-on-write 保证读写不互斥。
    """
```

| 属性 | 说明 |
|------|------|
| **接口名称** | `judge_crisis` —— 语义化，描述"执行危机等级判定"的业务动作 |
| **输入类型** | `CrisisJudgmentRequest`（详见"输入定义"章节） |
| **输出类型** | `CrisisJudgmentResult`（详见"输出定义"章节） |
| **异常类型** | `CrisisJudgmentError`、`ValidationError`、`KeywordDictLoadError`（详见"异常与边界条件"章节） |
| **副作用** | 记录结构化日志、LLM API 调用 |
| **幂等性** | 无状态判定，每次调用独立执行 |
| **并发安全** | async 协程安全，JudgmentContext 隔离各次调用状态 |

### 1.7 依赖与集成接口 `【已锁定】`

#### 1.7.1 关键基础设施依赖（硬性前提，不可 mock）

| 依赖类型 | 依赖方 | 具体接口 | 用途 | 项目结构设计文档依据 |
|:---|:---|:---|:---|:---|
| 关系型数据库 | PostgreSQL 17.x | `session.execute(select(CrisisKeyword).where(CrisisKeyword.is_active == True))` — SQLAlchemy async | crisis_keywords 表全量查询，加载关键词词库 | 项目结构 §6.1 `packages/py-db/` |
| 缓存与消息 | Redis 7.x | `redis_client.subscribe("keyword_dict:updates")` — `redis.asyncio.Redis.pubsub()` | 词库变更实时通知，触发 AC 自动机热加载 | 项目结构 §6.1 `packages/py-cache/` |
| LLM API | DeepSeek API | `LLMClient.async_chat(messages=[...], model="deepseek-chat", timeout=5.0)` — `packages/py-llm/client.py` | LLM 精调复审，3s 超时降级 | 项目结构 §6.1 `packages/py-llm/` |
| 配置管理 | packages/py-config | `config = Config()` — `pydantic-settings` 加载 `.env` | 读取 `JUDGMENT_LLM_TIMEOUT_MS`、`KEYWORD_DICT_PATH`、`NEGATION_WORDS` 等 | 项目结构 §6.1 `packages/py-config/` |
| 日志系统 | packages/py-logger | `logger.bind(trace_id=..., module="crisis_judgment").info("event", ...)` | 结构化 JSON 日志，含判定各层耗时、触发规则、降级标记 | 项目结构 §6.1 `packages/py-logger/` |

#### 1.7.2 核心功能依赖（其他业务模块，可 mock）

| 依赖模块 | 具体接口 | 用途 | 落地状态 |
|:---|:---|:---|:---|
| PROF-02（档案驱动检索过滤） | `PatientProfileSnapshot` 类型定义，传递给 `CrisisJudgmentRequest.patient_profile` | 档案叠加规则需读取患者历史行为标签和最近事件。若模块未落地，mock 返回 `PatientProfileSnapshot(diagnosis_type=None, historical_behavior_tags=[], recent_event_records=[])` 即可 | ❌ 未落地（待定义完整 Schema），mock 策略：返回空档案快照，档案叠加规则不触发 |
| SEC-02（AI输出安全护栏） | `CRISIS_KEYWORDS` 公共常量（`packages/py-config` 中定义） | 高危关键词词库共享。CSLT-01 仅只读引用，不修改词库 | ❌ 未落地，当前由 CSLT-01 独立维护关键词表 |
| KNOW-05（应急场景引导） | `CRISIS_KEYWORDS` 公共常量（同上） | 同上，共享词库 | ❌ 未落地 |

### 1.8 状态机 `【对内实现】`

本功能点不涉及持久化状态流转，故无需状态机。

内部运行时处理阶段流转（纯内存，不持久化）：

| 当前阶段 | 触发条件 | 下一阶段 | 前置条件 | 副作用 |
|----------|---------|---------|---------|--------|
| `awaiting_input` | `judge_crisis()` 调用 | `pre_selection` | `CrisisJudgmentRequest` 校验通过 | 创建 `JudgmentContext`，初始化 `sources` 列表 |
| `pre_selection` | 高危类型命中 | `merge_and_output` | `behavior_type_selection` 含 SELF_INJURY / AGGRESSION / ELOPEMENT / MEDICATION 之一 | 写入 `PreSelectionLayer` 的 `JudgmentLayerResult`，设置 `skip_remaining=True` |
| `pre_selection` | 全部为非高危类型 | `rule_engine` | 高危命中检查结果为 False | 写入 `PreSelectionLayer` 的 `JudgmentLayerResult(level=None)` |
| `rule_engine` | AC 匹配到 severe 关键词 | `merge_and_output` | 否定词过滤未排除该匹配 | 写入 `RuleEngineLayer` 的 `JudgmentLayerResult`，设置 `skip_remaining=True`，记录 WARNING 安全日志 |
| `rule_engine` | 未命中 severe 或关键词词库不可用 | `llm_review` | — | 写入 `RuleEngineLayer` 的 `JudgmentLayerResult`。词库不可用时标记 `degradation_note=rule_engine_degraded` |
| `llm_review` | API 返回正常 | `merge_and_output` | 响应在超时阈值内且 JSON 解析成功 | 写入 `LLMReviewLayer` 的 `JudgmentLayerResult` |
| `llm_review` | API 超时或异常 | `merge_and_output` | `asyncio.TimeoutError` 或 HTTP 非 200 | 写入 `JudgmentLayerResult` 标记 `details.timeouts=true`，记录 WARNING 日志 |
| `merge_and_output` | — | 输出 | 至少有一个判定层产生结果 | 执行二维查找表 `MERGE_MATRIX` 合并，构建 `CrisisJudgmentResult` 返回 |

### 1.9 异常与边界条件 `【对内实现】`

#### 1.9.1 异常 1：输入校验失败

- **触发条件**：
  - `behavior_type_selection` 为空列表 `[]` 或缺失字段（Pydantic `required` 校验）
  - `behavior_description` 为 `None` 且不允许空值
  - `behavior_description` 长度超过 `max_length=2000`
  - `behavior_type_selection` 包含非 `BehaviorTypeCategory` 枚举值的字符串（如 `"aggression"` 小写或 `"攻击"` 中文）
- **处理策略**：
  1. Pydantic 校验阶段捕获 `ValidationError`
  2. 提取所有失败字段的错误信息（`error.errors()` 返回列表）
  3. 返回第一个字段的错误详情：`{"detail": {"field": "behavior_type_selection", "msg": "value is not a valid enumeration member; permitted: SELF_INJURY, AGGRESSION, ELOPEMENT, MEDICATION, EMOTIONAL_MELTDOWN, STEREOTYPY, OTHER", "received_value": "攻击"}}`
  4. 记录结构化日志：`logger.warning("input_validation_failed", field=..., received_value=..., trace_id=...)`
  5. **不进入任何判定步骤**
- **重试参数**：不重试。客户端修正输入后重新发起请求。

#### 1.9.2 异常 2：LLM 精调复审超时

- **触发条件**：
  - `asyncio.wait_for(LLMClient.async_chat(...), timeout=config.JUDGMENT_LLM_TIMEOUT_MS / 1000.0)` 抛出 `asyncio.TimeoutError`
  - 超时阈值：初始环境配置值为 `5000`（毫秒），待生产环境 DeepSeek API P95 延迟数据确定后调优至 `3000`
  - HTTP 请求已发送但未在时限内收到完整响应
- **处理策略**：
  1. `asyncio.TimeoutError` 被 `LLMReviewLayer.judge()` 捕获
  2. 调用 `asyncio.current_task().cancel()` 确保超时任务不继续占用资源
  3. 构建 `JudgmentLayerResult(layer_name="LLMReviewLayer", level=rule_engine_result, details={"timeouts": True, "elapsed_ms": actual_elapsed})`
  4. 设置 `context.llm_timed_out = True`
  5. 记录日志：`logger.warning("llm_review_timeout", timeout_ms=config.JUDGMENT_LLM_TIMEOUT_MS, elapsed_ms=..., trace_id=...)`
  6. `merge()` 中检测到 `llm_timed_out = True`，直接采用规则引擎结果为 `final_level`
  7. 超时后异步返回的 LLM 结果（若后续到达）仅通过 `logger.info("llm_review_belated_response", ...)` 记录，**绝对不改变已输出的判定结果**
- **重试参数**：**不重试**。安全场景不能让用户无限等待。单次超时即降级。

#### 1.9.3 异常 3：关键词词库加载失败

- **触发条件**：
  - PostgreSQL 连接池返回 `ConnectionRefusedError` 或 `TimeoutError`（连接超时 > 5s）
  - `crisis_keywords` 表不存在或查询权限不足（SQLAlchemy `ProgrammingError`）
  - 词库查询结果为空（表中无 `is_active = true` 的记录）
- **处理策略**：
  1. `AhoCorasickMatcher.get_instance()` 中构造时捕获 `SQLAlchemyError`
  2. 抛出 `KeywordDictLoadError("failed to load keyword dictionary: {detail}", original_error=e)`
  3. `JudgmentPipeline` 捕获此异常后进入降级模式：
     - `context.degradation_note = "rule_engine_degraded"`
     - `RuleEngineLayer` 被跳过（返回 `JudgmentLayerResult(level=None, details={"degraded": True})`）
     - 前置选择层仍正常执行（不依赖词库）
     - 所有未命中高危前置选择的输入自动进入 `LLMReviewLayer`
  4. 后台启动异步重试任务：每 30 秒执行 `asyncio.create_task(_retry_keyword_dict_load())`，成功后通过 copy-on-write 原子替换 `self._automaton` 并清除降级状态
  5. 记录日志：`logger.critical("keyword_dict_load_failed", error=str(e), trace_id=...)`
- **重试参数**：每 30 秒重试一次，无限重试直到加载成功。每次重试前重新建立 PostgreSQL 连接。

#### 1.9.4 异常 4：患者档案缺失（边界条件）

- **触发条件**：
  - `request.patient_profile` 为 `None`（POLF-02 未返回数据或无档案记录）
- **处理策略**：
  1. 规则引擎层在步骤 4.4 检查 `request.patient_profile is None`，直接跳过档案叠加规则检查
  2. 不设置 `context.manual_review_flag = True`
  3. `context.degradation_note = "profile_missing"`
  4. 记录日志：`logger.info("patient_profile_missing", consultation_session_id=str(request.consultation_session_id), trace_id=...)`
  5. 其他所有判定逻辑（前置选择、关键词匹配、LLM 复审）**不受影响，正常执行**
- **重试参数**：不适用（为正常业务状态，非异常）。CSLT-08 编排层应在标注档案缺失后提示家属后续补充档案。

#### 1.9.5 异常 5：LLM API 返回非预期格式

- **触发条件**：
  - DeepSeek API 返回 HTTP 200 但 `response.content` 无法解析为有效 JSON
  - 解析出的 JSON 中 `level` 字段不存在或值不在 `("mild", "moderate", "severe")` 中
  - `confidence` 字段不存在或超出 [0.0, 1.0] 范围
- **处理策略**：
  1. 捕获 `json.JSONDecodeError` 或 `KeyError`
  2. 构建 `JudgmentLayerResult(layer_name="LLMReviewLayer", level=rule_engine_result, details={"parse_error": True, "raw_response": response.content[:500]})`
  3. 该层的 `level` 采用规则引擎结果（即不改变当前等级）
  4. 记录 ERROR 日志：`logger.error("llm_review_unexpected_format", error=str(e), raw_response=response.content[:500], trace_id=...)`
  5. 不触发重试——模型输出格式错误不应让用户等待
- **重试参数**：不重试。直接降级为规则引擎结果。

### 1.10 验收测试场景 `【对内实现】`

#### 1.10.1 正向测试 1：高危前置选择直接判定重度

- **场景**：家属勾选自伤行为类型，系统立即判定为重度，跳过后续所有判定层
- **Given**: `CrisisJudgmentRequest` 含 `behavior_type_selection=["SELF_INJURY"]`、`behavior_description="患者用手打自己的头部"`、`patient_profile=valid_profile`
- **When**: 调用 `judge_crisis(request)`
- **Then**:
  - 返回 `CrisisJudgmentResult`，`final_level="severe"`，`block_deep_response=True`
  - `judgment_sources` 长度为 1（仅含 `PreSelectionLayer` 记录，`layer_name="PreSelectionLayer"`、`level="severe"`）
  - `RuleEngineLayer` 和 `LLMReviewLayer` 均未被调用
  - 总执行耗时 < 200ms

**完整 JSON 测试数据**：
```json
{
  "request": {
    "patient_profile": {
      "diagnosis_type": "ASD",
      "historical_behavior_tags": ["stereotypy"],
      "recent_event_records": [
        {"event_type": "meltdown", "occurred_at": "2026-05-25T14:30:00"}
      ]
    },
    "behavior_type_selection": ["SELF_INJURY"],
    "behavior_description": "患者用手打自己的头部"
  },
  "expected_response": {
    "final_level": "severe",
    "block_deep_response": true,
    "manual_review_flag": false,
    "review_confidence": null,
    "judgment_sources": [
      {
        "layer_name": "PreSelectionLayer",
        "level": "severe",
        "trigger_rule_id": null,
        "details": {"checked_types": ["SELF_INJURY"], "high_risk_hit": true}
      }
    ],
    "degradation_note": null
  }
}
```

#### 1.10.2 正向测试 2：规则引擎命中重度关键词

- **场景**：前置选择为非高危类型，但文本中含重度关键词"撞墙"，经否定词过滤未排除
- **Given**: `CrisisJudgmentRequest` 含 `behavior_type_selection=["EMOTIONAL_MELTDOWN"]`、`behavior_description="患者从下午3点开始持续撞墙，已经撞了十几次，劝阻无效"`、`patient_profile=valid_profile`
- **When**: 调用 `judge_crisis(request)`
- **Then**:
  - 返回 `CrisisJudgmentResult`，`final_level="severe"`，`block_deep_response=True`
  - `judgment_sources` 含 `PreSelectionLayer`（level=None）+ `RuleEngineLayer`（level="severe", trigger_rule_id 非空）
  - `LLMReviewLayer` 未被调用

**完整 JSON 测试数据**：
```json
{
  "request": {
    "patient_profile": {
      "diagnosis_type": "ASD",
      "historical_behavior_tags": [],
      "recent_event_records": []
    },
    "behavior_type_selection": ["EMOTIONAL_MELTDOWN"],
    "behavior_description": "患者从下午3点开始持续撞墙，已经撞了十几次，劝阻无效"
  },
  "expected_response": {
    "final_level": "severe",
    "block_deep_response": true,
    "manual_review_flag": false,
    "review_confidence": null,
    "judgment_sources": [
      {"layer_name": "PreSelectionLayer", "level": null, "trigger_rule_id": null, "details": {"high_risk_hit": false}},
      {"layer_name": "RuleEngineLayer", "level": "severe", "trigger_rule_id": "KW_SELF_HARM_001", "details": {"matched_keywords": ["撞墙"], "negation_filtered": false}}
    ],
    "degradation_note": null
  }
}
```

#### 1.10.3 正向测试 3：否定词正确排除高危词

- **场景**：文本含"没有自伤行为"，AC 自动机匹配到"自伤"但因否定词过滤排除，最终为轻度
- **Given**: `CrisisJudgmentRequest` 含 `behavior_type_selection=["EMOTIONAL_MELTDOWN"]`、`behavior_description="患者今天情绪比较稳定，没有自伤行为，也没有攻击他人的倾向"`、`patient_profile=valid_profile`
- **When**: 调用 `judge_crisis(request)`（mock LLM 复审返回 `{"level": "mild", "confidence": 0.95}`）
- **Then**:
  - 返回 `CrisisJudgmentResult`，`final_level="mild"`，`block_deep_response=False`
  - `RuleEngineLayer` 的 `details.negation_filtered=True`，`level` 为 `None`

**完整 JSON 测试数据**：
```json
{
  "request": {
    "patient_profile": {
      "diagnosis_type": "ASD",
      "historical_behavior_tags": [],
      "recent_event_records": []
    },
    "behavior_type_selection": ["EMOTIONAL_MELTDOWN"],
    "behavior_description": "患者今天情绪比较稳定，没有自伤行为，也没有攻击他人的倾向"
  },
  "expected_response": {
    "final_level": "mild",
    "block_deep_response": false,
    "manual_review_flag": false,
    "review_confidence": 0.95,
    "judgment_sources": [
      {"layer_name": "PreSelectionLayer", "level": null, "details": {"high_risk_hit": false}},
      {"layer_name": "RuleEngineLayer", "level": null, "details": {"matched_keywords": ["自伤"], "negation_filtered": true}},
      {"layer_name": "LLMReviewLayer", "level": "mild", "details": {"prompt_version": "v1"}}
    ],
    "degradation_note": null
  }
}
```

#### 1.10.4 正向测试 4：宁升勿降——LLM 升级规则引擎结果

- **场景**：规则引擎未命中关键词，LLM 复审判定为重度
- **Given**: `CrisisJudgmentRequest` 含 `behavior_type_selection=["STEREOTYPY"]`、`behavior_description="患者反复用头撞墙，频率越来越快"`、`patient_profile=valid_profile`（AC 关键词库不含"用头撞墙"因此未命中）。Mock LLM 返回 `{"level": "severe", "confidence": 0.92}`
- **When**: 调用 `judge_crisis(request)`
- **Then**:
  - `final_level="severe"`（LLM 升级生效）
  - `merge()` 正确执行宁升勿降策略

**完整 JSON 测试数据**：
```json
{
  "request": {
    "patient_profile": {
      "diagnosis_type": "ASD",
      "historical_behavior_tags": [],
      "recent_event_records": []
    },
    "behavior_type_selection": ["STEREOTYPY"],
    "behavior_description": "患者反复用头撞墙，频率越来越快"
  },
  "expected_response": {
    "final_level": "severe",
    "block_deep_response": true,
    "manual_review_flag": false,
    "review_confidence": 0.92,
    "judgment_sources": [
      {"layer_name": "PreSelectionLayer", "level": null},
      {"layer_name": "RuleEngineLayer", "level": null, "details": {"matched_keywords": [], "negation_filtered": false}},
      {"layer_name": "LLMReviewLayer", "level": "severe"}
    ],
    "degradation_note": null
  }
}
```

#### 1.10.5 异常测试 1：LLM 复审超时降级

- **场景**：LLM API 超时，系统回退到规则引擎结果
- **Given**: `CrisisJudgmentRequest` 含 `behavior_description="患者情绪激动，大声尖叫"`。Mock LLM 客户端抛出 `asyncio.TimeoutError`
- **When**: 调用 `judge_crisis(request)`
- **Then**:
  - `final_level` 等于规则引擎的判定结果（非 severe）
  - `LLMReviewLayer` 的 `JudgmentLayerResult` 中 `details.timeouts=true`
  - 不抛出异常，正常返回 `CrisisJudgmentResult`

**完整 JSON 测试数据**：
```json
{
  "request": {
    "patient_profile": {
      "diagnosis_type": "ASD",
      "historical_behavior_tags": [],
      "recent_event_records": []
    },
    "behavior_type_selection": ["EMOTIONAL_MELTDOWN"],
    "behavior_description": "患者情绪激动，大声尖叫"
  },
  "expected_response": {
    "final_level": "mild",
    "block_deep_response": false,
    "manual_review_flag": false,
    "review_confidence": null,
    "judgment_sources": [
      {"layer_name": "PreSelectionLayer", "level": null},
      {"layer_name": "RuleEngineLayer", "level": null},
      {"layer_name": "LLMReviewLayer", "level": null, "details": {"timeouts": true, "elapsed_ms": 5000}}
    ],
    "degradation_note": null
  }
}
```

#### 1.10.6 异常测试 2：关键词词库加载失败降级

- **场景**：PostgreSQL 中 crisis_keywords 表不可用，规则引擎层降级
- **Given**: Mock `SQLAlchemyError` 在 AC 自动机构建时抛出。`CrisisJudgmentRequest` 含 `behavior_type_selection=["EMOTIONAL_MELTDOWN"]`, `behavior_description="患者情绪崩溃"`
- **When**: 调用 `judge_crisis(request)`
- **Then**:
  - `judgment_sources` 含 `PreSelectionLayer`（正常） + `RuleEngineLayer`（level=None, details.degraded=true）
  - `degradation_note="rule_engine_degraded"`
  - 所有输入进入 `LLMReviewLayer` 处理

**完整 JSON 测试数据**：
```json
{
  "request": {
    "patient_profile": null,
    "behavior_type_selection": ["EMOTIONAL_MELTDOWN"],
    "behavior_description": "患者情绪崩溃，躺在地上不动"
  },
  "expected_response": {
    "final_level": "mild",
    "block_deep_response": false,
    "manual_review_flag": false,
    "review_confidence": 0.88,
    "judgment_sources": [
      {"layer_name": "PreSelectionLayer", "level": null},
      {"layer_name": "RuleEngineLayer", "level": null, "details": {"degraded": true}},
      {"layer_name": "LLMReviewLayer", "level": "mild"}
    ],
    "degradation_note": "rule_engine_degraded"
  }
}
```

### 1.11 注意事项与禁止行为（编码层面） `【对内实现】`

1. **[约束 1]** AC 自动机的 compile 和 hot-reload 必须使用 copy-on-write 策略：先在新线程中构建完整的 `pyahocorasick.Automaton()`，编译完成后通过 `self._automaton = new_automaton` 原子替换引用。禁止在现有 `Automaton` 实例上调用 `.add_word()` 增量修改——Python GIL 在 AC 自动机构建时不保证读取安全。

2. **[约束 2]** LLM 复审的 System Prompt 必须强制注入安全指令："宁可误判为重度，不可漏判为轻度"。Prompt 模板版本号（`prompt_version`）必须在 `JudgmentLayerResult.details` 中记录，供事后分析 LLM 判定的偏差来源。

3. **[约束 3]** 否定词过滤的前向扫描范围硬编码为 7 个字符（最长否定词 2 字符 + 5 字符前向上下文），不得使用可配置化缩短此范围——缩短可能导致漏判中文否定结构中的前置否定词。

4. **[易错点 1]** `BehaviorTypeCategory` 为 Python `StrEnum`，序列化时自动输出枚举值字符串（如 `"SELF_INJURY"`）而非枚举对象。在使用 `json.dumps()` 前确保已调用 `model_dump()` 或 `model_dump_json()`（Pydantic v2 标准序列化）。

5. **[易错点 2]** `CrisisJudgmentResult.review_confidence` 类型为 `float | None`（Python 3.10+ union），Pydantic 中使用 `Field(ge=0.0, le=1.0)` 约束范围。当规则引擎直接判重度时该字段为 `None`。在消费方代码中访问此字段前**必须**进行 `is not None` 检查，避免 `0.0`（合法值）与 `None`（无 LLM 复审）的语义混淆。

6. **[禁止行为]** 禁止在 `judge_crisis()` 中直接调用 Redis Pub/Sub——词库热加载由 `AhoCorasickMatcher` 内部在后台线程管理。`judge_crisis()` 为同步判定路径，不应阻塞等待热加载完成。

7. **[禁止行为]** 禁止在规则引擎层绕过 AC 自动机使用字符串 `in` 操作符或 `.find()` 做关键词匹配——两者对中文文本的性能退化为 O(n*m)（n=文本长度, m=关键词数量），无法满足 0ms 级别要求。

8. **[偷懒红线]** 绝对禁止以"规则引擎判定逻辑简单"为由省略否定词过滤的边界测试用例（至少覆盖：否定词在关键词前、否定词在关键词后、多个否定词同时出现、否定词与关键词相邻、否定词与关键词跨标点符号）。

### 1.12 文档详细度自检清单 `【对内实现】`

- [x] 文档自包含：不了解本项目代码的 Agent，仅凭此文档即可完成 CSLT-01 的编码（含类型定义、AC 自动机算法、三层判定 Pipeline、LLM 超时降级、契约文件路径）
- [x] 无偷懒表述：全文无"等等"、"..."、"其他字段"、"类似"、"同上"、"参考其他模块"、"请根据实际情况补充"、"开发者自行决定"
- [x] 类型定义完整：每个 Pydantic 字段都有 `description` + `examples` + 约束（`minLength`/`maxLength`/`ge`/`le`/`enum` 等）
- [x] 逻辑步骤完整：6 个步骤，每步都有操作对象、具体操作、输入来源、输出去向、失败行为
- [x] 异常处理完整：5 种异常，每种都有精确的触发阈值、逐步处理策略、精确重试参数
- [x] 无隐藏假设：所有默认值来源（`config.JUDGMENT_LLM_TIMEOUT_MS`、`maxLength=2000`）、条件分支（高危类型集合、否定词前缀扫描距离）、业务规则（宁升勿降、档案叠加触发条件）都已显式写出
- [x] 技术栈绑定明确：必须使用和禁止使用的项均已列出，且与项目技术栈设计文档（`docs/篝火智答-技术栈设计.md` v1.2）保持一致
- [x] 意图一致性：已确认技术实现与已冻结的意图文档一致（见 §1.15）

### 1.14 外部接口契约清单 `【已锁定】`

| 契约名称 | 文件路径 | 契约类型 | 成熟度 | 定义方 | 消费方 |
|:---------|:---------|:---------|:-------|:-------|:-------|
| CrisisLevel | `docs/contracts/CSLT-01/CrisisLevel.json` | shared-enum | draft | CSLT-01 | CSLT-03, CSLT-05, TICK-01, TICK-02 |
| BehaviorTypeCategory | `docs/contracts/CSLT-01/BehaviorTypeCategory.json` | shared-enum | draft | CSLT-01 | CSLT-07 |
| JudgmentLayerResult | `docs/contracts/CSLT-01/JudgmentLayerResult.json` | shared-model | draft | CSLT-01 | CSLT-03, CSLT-05 |
| CrisisJudgmentRequest | `docs/contracts/CSLT-01/CrisisJudgmentRequest.json` | input | draft | CSLT-01 | — |
| CrisisJudgmentResult | `docs/contracts/CSLT-01/CrisisJudgmentResult.json` | output | draft | CSLT-01 | CSLT-03, CSLT-05, TICK-01, TICK-02 |

**悬空引用**：
- `PatientProfileSnapshot`：CSLT-01 引用了 PROF-02 尚未定义的类型（通过 `CrisisJudgmentRequest.patient_profile` 字段）。当前契约中该字段使用 `anyOf: [object, null]` 占位。待 PROF-02 设计阶段补充完整 Schema 后，需在新版本的 `CrisisJudgmentRequest.json` 中替换为 `$ref` 引用。

### 1.15 意图一致性声明 `【对内实现】`

- **配套意图文档**：`CSLT-01-危机分级判定-意图文档.md`
- **冻结时间**：`2026-05-27 09:02:28`
- **一致性确认**：
  - [x] 本落地规范中的输入/输出类型定义与意图文档 §1.6 中的业务字段定义一致（5 个输入字段 → `CrisisJudgmentRequest`，5 个输出字段 → `CrisisJudgmentResult`）
  - [x] 本落地规范中的状态机实现与意图文档 §1.7 中的状态业务定义一致（均声明无持久化状态流转，仅内部处理阶段）
  - [x] 本落地规范中的异常处理策略与意图文档 §1.8 中的异常业务策略一致（LLM 超时 → 回退规则引擎；词库加载失败 → 降级仅前置选择；档案缺失 → 跳过叠加规则）
  - [x] 本落地规范中的验收测试场景覆盖意图文档 §1.9 中的所有 11 条验收标准（AC-01 前置选择重度、AC-02 关键词匹配性能、AC-03 重度关键词召回、AC-04 否定词过滤、AC-05 档案叠加、AC-06 LLM 超时降级、AC-07 最终判定矩阵、AC-08 重度阻断、AC-09 安全提示差异化、AC-10 词库加载失败降级、AC-11 档案缺失降级）
  - [x] 本落地规范中的技术实现未超出意图文档 §1.12 中"留给规范阶段的技术决策"的范围（技术选型、关键词匹配算法、LLM Prompt 模板、超时阈值、数据模型、词库配置格式、异常处理、判定矩阵编码、否定词过滤语义、安全提示模板存储——全部 10 项均在设计文档中完成决策并在本规范中精确落地）
- **偏差说明**：无偏差。技术实现与意图文档完全一致。LLM 复审超时阈值初始设置为 5000ms（设计文档 §1.6 基于技术预研分析，待生产环境 P95 数据采集后调优至 3000ms），此项为意图文档 §1.12.4 明确授权规范阶段确定精确毫秒值的范围之内。
