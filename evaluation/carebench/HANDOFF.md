# HANDOFF — CareBench 评测工具交接（2026-10-29）

> 这一批是**真实性修复 + 正式集入库**，**没有开任何正式模型运行**，也没有冻结正式集。
> 下面按「已做（含定向测试）」/「未做（明确原因）」/「新环境怎么接」三块写清。

## 0. 当前事实（不要当成别的样子）

- 正式 40 例已入库：`evaluation/carebench/cases/cases-test-v0.1.jsonl`，
  sha256 `f7d4462e344db2d0a6553aad3d13703d2ce13f9f668eee8fe3845371f1dd50d3`，
  40 条、`split=test`、6 条固定二轮、`review_status` 全为 `draft_unreviewed`（**未改 approved**）。
- **未冻结、未运行**：`frozen/test/` 不存在；`runs/` 里没有 `label=test` 批次。
- 语料定位：公开挑战集 / 非独立未见样本。`CFB-T-009` 是设计阶段用过的黄金场景，
  该题分数**不得**当作「模型未见过」的证据。
- 校准批次 `runs/calib-smoke-3/4` 是**适配期冒烟**，其 `code.commit` 是在 `evaluation/`
  尚未提交时取的，不可当「按该 commit 可复现」的证据（此前的 `--untracked-files=no`
  缺陷已修，见 §1.6）。

## 1. 本批已修（每项都有定向测试）

### 1.1 C 组结构化输出不再丢（`systems/base.py`、`render.py`、`systems/agent.py`、`runner.py`、`review.py`）
- `TurnOutcome` 现在分开保存 `raw_output`（文本增量逐字）/ `structured`（行动卡、提问的原始载荷）/
  `output_text`（**规范文本投影**，只贴标签不改写）。
- 状态判据：正文或结构化**任一非空** → `completed`（此前纯卡片 = `no_output`，是错的：
  产品 live 与 history 都把卡片当可见产出）。
- 盲评包用投影（评审者不用读 JSON），同时保留 `structured_output` 原文。
- 测试：`tests/test_evidence_fidelity.py::test_projection_*`、`test_structured_only_turn_is_recorded_as_completed_output`。

### 1.2 注入替身不再泄漏故障（`systems/agent.py::_injected_search_tool`）
- 替身的 `name` / `description` / `args_model` **逐项复用产品原工具**，只换 `handler`；
  故障只在实际 handler 边界显现（空结果 / `ToolFailure(tool_failed)` / 挂住到产品预算超时）。
- 记录里加 `system_meta.tool_overrides`（含 `description_sha256`），证明说明是复用的。
- 测试：`test_injected_tool_reuses_product_description_and_args`、`test_injected_tool_never_leaks_injection`。

### 1.3 「请求了注入」≠「注入发生了」（`runner._fixture_records`）
- 每条 fixture 记录新增 `status`（`applied`/`not_applicable`/`unsupported`/`out_of_harness`/`unknown`）、
  `observed`、`observed_calls`；替身装上但模型没调用 → `observed=false` 并在 note 里说明。
- 测试：`test_fixture_observation_marks_uncalled_tool`。

### 1.4 C 组结束原因保真（`systems/agent.py`）
- `RunFinishedEvent.reason` 现在被真正消费：`timeout` → `STATUS_TIMEOUT`（此前记成 `completed`），
  `cancelled` → `STATUS_ERROR(code=run_cancelled)`。

### 1.5 重试不污染下一次（`records.py`、`runner._run_case_group`）
- 适配器声明 `retry_safety`：C 组按**会话条目数前后对比**判定——失败尝试已落库（条目增长或读不到）
  → `new_session`：**换新会话从第 1 轮重开**，旧记录全部保留；A/B 成功后才追加历史 → `same_session` 可原地重试。
- 重试预算按**整组**计（`group_attempts_used`），避免「第 1 轮重开、第 2 轮又重试」变成两次重试。
- 每条记录带 `retry: {attempt, retry_safety}`。
- 测试：`test_retry_on_dirty_session_restarts_with_new_session`、`test_retry_budget_is_per_group_not_per_turn`。

### 1.6 代码脏判定与正式批次闸门（`manifest.code_facts`、`runner`、`freeze.py`）
- `git status --porcelain --untracked-files=normal`：**未跟踪的代码也算脏**
  （产物目录由 `.gitignore` 排除，跑批不会把仓库标脏）；记录 `dirty_tracked_count` / `dirty_untracked_count` / `dirty_files`。
- `label=test`（`FORMAL_LABEL`）：`freeze` 与 `run` 都**拒绝脏工作区**；`calibration` 允许但如实记 dirty。
- 测试：`test_code_facts_counts_untracked_code`、`test_formal_label_refuses_dirty_tree`。

### 1.7 冻结幂等（`freeze.py`）
- 案例字节一致但 `config/code/protocol/label/turns/review_status` 任一不同 → **拒绝**，
  且**不改写**已有 `freeze.json`（此前 `record.update(payload)` 会把旧记录洗成新条件）。
- 测试：`test_refreeze_with_different_config_is_refused`。

### 1.8 运行身份绑定（`manifest.runtime_identity` / `identity_drift`、`runner`）
- manifest 新增 `run_identity` + `run_identity_sha256`：`model_id`、chat 端点 host/port/base_path、
  `model_max_retries`、嵌入端点 + 固定模型名 + 维度 2560、知识快照 hash/条目/节点数、库名、会话策略。
  **无凭据**（只有「是否已配置」布尔与端点结构）。
- `resume` 逐项核对，不一致即 `ResumeRejected` 并点名哪个字段。批次指纹本身没改（避免破坏既有 hash）。
- 测试：`tests/test_identity.py`（含换模型、换知识快照两条负例）。

### 1.9 B 组时延口径（`systems/chat.py`）
- `started` 移到**任何工作之前**，检索耗时单独记 `system_meta.retrieval_ms`，`latency_ms` 现在包含检索。
- B 的证据块正文 hash 进轨迹：`trace.retrieval.evidence_text_sha256` / `evidence_text_chars`（可复算）。

### 1.10 `conversation_reset_each_case` 不留假配置
- 该字段进配置 hash 但没有「共享会话」代码路径：`RunConfig(conversation_reset_each_case=False)`
  直接 `ValueError`，不静默按 True 跑。测试：`test_shared_session_config_is_rejected`。

### 1.11 故障注册表（`faults.py`，版本 0.1 → 0.2）
- 新增真实接缝：`tool_search_timeout`（C，handler 挂住 420s > 产品 300s 预算 → 由产品预算结束）、
  `retrieval_timeout`（B，挂住到评测回合上限）。
- 新增 `OUT_OF_HARNESS` 分类：`client_render_fault` 记 `out_of_harness` + 原因（**未覆盖，不是已注入**）；
  summary 单列 `out_of_harness_counts` / `out_of_harness` 原因表。
- 正式计划草案：`evaluation/carebench/fixtures-formal.example.json`
  （T033 空结果、T035 不可用、T040 `client_render_fault`）。实测统计：applied 3 / out_of_harness 3 / unknown 0。

## 2. 未做（明确列出，不要默认已完成）

1. **AI 评审能力（agent 独立评分）整体未实现**。用户后来要求「两套独立 agent 盲评 + 独立 `ai_scores` +
   `reviewer_kind/model_id/prompt_sha256/rater_id` 字段 + 逐 must_check 判定 + 证据位置」——
   本批按「先正确性、后评分；暂停不新增功能」的口径**没有开始**。
   现有 `review.py` 仍是人工 CSV 单通道（盲化包 + 空表 + 严格导入 + `pending` 拒收），
   **没有** `ai_scores`、没有 AI 简报/批次包、没有分歧裁定 JSONL。
2. **知识快照的节点级锁定未做**。`knowledge.read_database_state` 现在核对：条目 `source_path`
   基名在许可表内、无案例条目、节点数 > 0；**没有**核对每个节点的正文/向量 hash 与 `source doc_hash`
   ——“节点数相同、内容变了”目前查不出来。主 agent 已将旧快照留存为
   `docs/development/checkpoints/2026-10-29-knowledge-snapshot.json`
   （逐条 doc_hash + nodes 内容/向量 hash），尚未接入运行时核验。**这是冻结正式集之前必须补的一条**。
3. **`verify` 未覆盖的新字段**：`run_identity`、`review.structured_output`、`retry`、
   fixture 的 `observed`/`status` 还没有对应的 verify 断言（现在只保证写入，未保证事后被校验）。
4. **`summarize` 未消费 `observed`**：统计里还没单列「注入了但没被观察到」的组数。
5. 正式集**未冻结、未运行**，`frozen/test/` 与 `label=test` 批次都不存在；`preflight` 未跑正式集。

## 3. 新环境怎么接（只读 eval worktree + 独立库）

```bash
cd <eval-worktree>            # 主 agent 已计划：集成 commit 后另建只读 worktree
uv sync --frozen
# 按新环境的凭据链配置本泳道 .env（不打印、不入库）；不要照搬旧机回环网关。
# DATABASE_URL 指向本次新建的 campfire_carebench* 专用评测库。

# 1) 预检（不会发生成调用）
uv run python -m evaluation.carebench preflight \
  --cases evaluation/carebench/cases/cases-test-v0.1.jsonl --probe-model --probe-embedding

# 2) 冻结（要求工作区干净，label=test）
uv run python -m evaluation.carebench freeze \
  --cases evaluation/carebench/cases/cases-test-v0.1.jsonl --label test

# 3) 计划内故障注入（先 dry-run 看覆盖统计）
uv run python -m evaluation.carebench run --frozen evaluation/carebench/frozen/test \
  --fixtures evaluation/carebench/fixtures-formal.example.json --dry-run
```

**接续实现顺序建议**（按「挡正式成绩」的优先级）：
① 知识快照节点级 hash（§2.2）→ ② verify 覆盖新字段（§2.3）→ ③ AI 评审通道（§2.1）→
④ summarize 消费 `observed`（§2.4）。

## 4. 测试与质量门禁现状

```bash
uv run pytest evaluation/carebench/tests -q   # 65 passed
uv run ruff check . && uv run ruff format --check evaluation/
```

全部为确定性测试：不联网、不连库、不发模型调用。
