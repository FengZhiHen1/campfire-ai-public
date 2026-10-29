# CareBench 运行工具（`evaluation/carebench`）

> 状态：**工具已实现并用少量真实校准调用验证过；正式 40 例未运行**。
> 正式案例的冻结与正式批次运行由主 agent 在集成修复后执行（见文末「主 agent 待办」）。
> 本目录不含任何正式成绩，也不含任何专家背书。

把 CareBench 协议（[`protocol/`](protocol/)，01–05 号原文快照）落成可执行工具的目录。
一句话：**用产品自己的运行时跑 A/B/C 三组真实运行，把原始输出与轨迹原样留下，人工评分
导入后才出分，任何对不上都会被 `verify` 抓住**。

---

## 1. 它做什么、不做什么

做：

- `preflight`：开工前核对工作区、案例、知识快照与**独立评测库**、模型/嵌入端点、技能与工具池、
  C 组生产装配能否装出来（默认**不发起生成调用**）。
- `freeze`：把案例集与配置冻结成不可再改的身份（字节复制 + 三层 hash）。
- `run` / `resume`：按案例 × 组别跑满 A/B/C，逐轮逐尝试落盘；中断后只补缺的轮次。
- `review-export`：导出**盲化**评审包（组别被替换成 `X1/X2/X3`）与**空**评分表。
- `review-import`：严格校验并导入人工评分（空值 / `pending` 一律拒收）。
- `summarize`：只按实测数据出计数、时延、token；导入人工评分后才出硬失败计数与五维分。
- `verify`：复算全部 hash、分母、输入对称性、盲化与 summary 一致性。

不做（每一条都有对应的实现约束）：

| 不做 | 为什么 / 在哪里挡住了 |
|---|---|
| 不造简化假 C、不用 FakeModel、不合成回答 | C 组走 `surfaces.consult.composition.install` + `assembly.get_runner`（生产装配），`systems/agent.py` |
| 不新造评测平台/服务 | 复用产品模型网关、检索链、工具池、技能注册表、AgentRunner、SQLAlchemy 会话 |
| 不让 LLM 代评 | 硬失败与五维分只能来自 `review-import` 的 CSV；`review.py` 拒收空值与 `pending` |
| 不填分 | 无人评审时 `summary.json` 的 `human_scores` 是 `null`；`verify` 会拦住「无评分却有分」 |
| 不把故障注入写成一句提示 | 注入点在真实接缝上（B 的检索、C 的工具池），未实现的 fixture 标 `applied=false`，`faults.py` |
| 不混批 | 批次指纹 = 案例 hash + 配置 hash + 代码提交；`resume` 不一致直接拒绝 |
| 不碰开发/生产库 | 库名必须以 `campfire_carebench` 开头，否则拒绝运行；知识快照逐条核对许可清单 |
| 不抹除失败 | `outputs.jsonl` 只追加；每条记录自带内容 hash；首错保留 |

---

## 2. 目录结构

```text
evaluation/carebench/
├── protocol/                 # 01–05 协议快照（逐字节副本 + 来源/哈希表）
├── cases/                    # 案例输入：calibration（8 例，工具自检用）+ 评分表表头
├── knowledge/snapshot.json   # 知识许可裁定表（included / blocked / excluded_corpora）
├── frozen/<label>/           # freeze 产物：cases.frozen.jsonl + freeze.json（默认不入库）
├── runs/<run_id>/            # 一批次的全部证据（默认不入库，见 §7「证据留存」）
│   ├── manifest.json         #   批次身份：配置/案例/知识/代码/组别装配/环境/评审状态
│   ├── freeze.json           #   案例与配置身份
│   ├── cases.frozen.jsonl    #   冻结案例字节副本
│   ├── outputs.jsonl         #   逐 case-group × 轮次 × 尝试的原始记录（只追加）
│   ├── errors.jsonl          #   派生：失败/拒答嫌疑/空输出的索引
│   ├── state.json            #   派生：进度快照（verify 会核对）
│   ├── traces/<case>__<sys>__t<n>__a<n>.json   # 事件流水/检索材料/消息体
│   ├── review/               #   blind-packet.jsonl / blind-map.json（内部） / ratings-empty.csv / ratings.imported.csv / import-report.json
│   └── summary.json/.md      #   汇总（无评审则无质量分）
├── config.py                 # RunConfig：组别、轮换、超时、重试、推理参数、评审种子 + 规范 hash
├── cases.py                  # 案例读取与结构校验
├── freeze.py                 # 冻结
├── knowledge.py              # 许可裁定表核对 + 库内条目核对 + 评测库隔离守卫
├── faults.py                 # 故障注入注册表与计划
├── records.py                # 「哪条记录算数」的唯一口径（有效记录/最终结论/进度）
├── runner.py                 # 批次编排（新会话 / 固定二轮 / 轮换 / 重试 / 续跑）
├── systems/                  # A / B / C 适配器（chat.py 为 A/B 共用的一半）
├── review.py                 # 盲化导出与评分导入
├── summarize.py              # 汇总
├── verify.py                 # 证据包校验
├── preflight.py              # 预检
├── cli.py / __main__.py      # 命令行
└── tests/                    # 工具自身的确定性测试（不联网、不连库）
```

---

## 3. 接口

入口统一为 `uv run python -m evaluation.carebench <命令>`（在仓库根执行）。
退出码：`0` 通过 / `1` 有阻断项或违反项（或批次未跑满）/ `2` 用法或输入错误。

### 3.1 `preflight`

```bash
uv run python -m evaluation.carebench preflight \
  --cases evaluation/carebench/cases/cases-calibration-v0.1.jsonl \
  [--frozen evaluation/carebench/frozen/<label>] [--config cfg.json] \
  [--knowledge-snapshot snapshot.json] [--fixtures fixtures.json] \
  [--db-prefix campfire_carebench] [--probe-model] [--probe-embedding] [--json]
```

给了 `--frozen` 时案例与配置都取自冻结记录，因此打印的 `config hash` 与随后 `run` 用的
是同一份（否则默认配置的 `label` 与冻结标签不同，两个 hash 并列出现会被误读成配置漂移）。

检查项与判定（`ready=false` 即阻断）：

| 项 | 判据 |
|---|---|
| 工作区 | 取 git commit/分支；有未提交改动只告警（并在 manifest 里记 `dirty`） |
| 协议快照 | `protocol/*.md` 逐文件 hash 与汇总 hash |
| 案例 | 结构校验、split、`review_status` 直方图、双轮数量、case-group 分母、案例自带 fixtures |
| 库隔离 | `DATABASE_URL` 的库名必须以 `--db-prefix`（默认 `campfire_carebench`）开头 |
| 知识快照 | `included` 文件 hash 与磁盘一致；**库内每个条目**的 `source_path` 基名必须在 `included` 内；不得有已撤下条目、不得有 0 节点的条目、不得有案例条目 |
| 端点 | 对话/嵌入端点主机；`chat_key`/`embedding_key` 是否已配；**嵌入端点与本机对话端点相同时阻断**（本机网关只有 chat，嵌入 404 会被误读成「没有资料」） |
| 装配 | `composition.install` + `get_runner` + 技能注册表 + 工具池（报工具数/skill 数） |
| 可选探测 | `--probe-model` 走 `GET /models`（不烧额度）；`--probe-embedding` 真调一次查询嵌入并检查全零向量 |

### 3.2 `freeze`

```bash
uv run python -m evaluation.carebench freeze --cases <案例 JSONL> --label {calibration|pilot|test} \
  [--config cfg.json] [--out evaluation/carebench/frozen/<label>] [--operator <名字>]
```

写出 `cases.frozen.jsonl`（与源文件**逐字节**相同）与 `freeze.json`：`dataset_sha256`、
`per_case_sha256`、`config_sha256`、`code`、`protocol_snapshot_sha256`、`turns_histogram`、
`review_status_counts`、`formal_ready`、`case_fixtures`、`operator`。
同一目录若已冻结**不同内容**会拒绝（`FreezeError`）；内容相同则只刷新元数据。

### 3.3 `run` / `resume`

```bash
uv run python -m evaluation.carebench run --frozen evaluation/carebench/frozen/calibration \
  [--runs-dir evaluation/carebench/runs] [--run-id <id>] [--case-ids CFB-C-001,CFB-C-003] \
  [--fixtures fixtures.json] [--config cfg.json] [--allow-config-drift] [--dry-run]

uv run python -m evaluation.carebench resume --run evaluation/carebench/runs/<id> \
  [--case-ids ...] [--fixtures fixtures.json] [--config cfg.json]
```

执行规则（每条都能在 `outputs.jsonl` 里核对）：

1. **每个 case-group 一个新会话**：`session_id` 与合成 `account_id`（uuid4）落进记录；三组各用各的。
2. **固定第二轮**：案例自带 `followup` 才跑第 2 轮，文本逐字取自案例，不即兴。
3. **轮换**：第 i 个案例按 `ABC / BCA / CAB`（`ROTATION[i % 3]`）执行；顺序由配置派生，命令行改不了。
4. **超时**：单轮墙钟上限（默认 300 s，与产品运行上限一致）→ 记为 `timeout`，计入分母。
5. **外层重试**：只对 `error`/`timeout`，至多 `max_outer_retries`（默认 1）次；首错保留为独立记录。
6. **续跑**：只补「没有最终结论」的轮次；已有最终结论的轮次一律不重跑、不改写。
   `resume` 默认用批次自身的配置（`manifest.config`），因此不会因为「换了命令行参数」而变成另一批。
7. `--dry-run`：装配 + 写 manifest，**零模型调用**（用来看计划与分母）。

### 3.4 `review-export` / `review-import`

```bash
uv run python -m evaluation.carebench review-export --run <run_id>
uv run python -m evaluation.carebench review-import --run <run_id> --ratings <填好的 CSV> [--adjudication <裁定 CSV>]
```

- 盲化：案例内三组顺序由 `review_seed`（配置里预锁）与 `case_id` 派生；评审者只见
  `<case_id>-X1/X2/X3`。映射表 `review/blind-map.json` 带「不得交给评审者」标记，
  且不写进评审包；`verify` 会检查评审包里没有 `system_id` 一类字段。
- 空评分表：`run_id, case_id, blind_id, rater_id, critical_failure, failure_type, c1…c5,
  required_checks_applicable, required_checks_passed, completion_status, latency_ms,
  response_ref, comment, adjudication_status`。只有**客观事实**被预填（时延、工程状态、轨迹引用）；
  分数、硬失败、关键约束计数全部留空。
- 导入校验（整份文件全对才导入，任何一行不合法就整份拒绝）：
  `blind_id` 必须在映射里；`rater_id` 必填；`critical_failure ∈ {yes, no, needs_review}`
  （**空值与 `pending` 拒收**）；五维必须是 0–2 整数；`required_checks_passed ≤ applicable`；
  `(blind_id, rater_id)` 不得重复。
- 模式：计划双评且每个 case-group 都有 ≥2 位评分者 → `double_blind`；否则
  `single_rater_internal`（报告措辞必须降级为「内部探索性先导评测」）。

### 3.5 `summarize` / `verify`

```bash
uv run python -m evaluation.carebench summarize --run <run_id>
uv run python -m evaluation.carebench verify --run <run_id> [--require-complete]
```

`summarize` 永远给出：分母（案例数 × 组别数）、有末轮结论的组数、每组的完成/无输出/超时/失败
计数、末轮时延 p50/p95/max、token（并给出「有 usage 的组数」这个分母）、工具调用/失败次数、
引用数、按类别的计数、故障注入实施统计、**装配变体**（凡出现 `override` 就是注入改过装配，
报告必须交代，不能让注入过的批次看起来和纯生产批次一样）。**没有人评审时 `human_scores = null`**，
`summary.md` 里写「不产生任何质量分或安全结论」。
导入评分后追加：硬失败 `yes/needs_review/no` 分列、五维均值、C2 均值、关键约束 `passed/applicable`、
配对胜负、评分者一致性（逐维完全一致率与 ≤1 分一致率；κ 因需 2×2 表而返回 `null`，
说明写在该字段的 `note` 里，不用错误表硬算）。

`verify` 复算（任何一条不符即失败）：

- `cases.frozen.jsonl` 字节 hash = `freeze.json` = `manifest.dataset.sha256`；逐案 hash 一致；
- `config_sha256` 复算；`batch_id` 复算（案例+配置+代码）；
- 每条记录：必需字段、`batch_id`、案例/组别/轮次合法、**输入文本 hash 与案例渲染一致**、
  **三组输入 hash 相同**（信息对称）、轨迹文件存在、**记录内容 hash 未被改**；
- 进度：`case_groups_expected = 案例数 × 组别数`，`state.json` 与 manifest 一致；
- 评审：包内无组别标识、映射覆盖全部组别、导入评分与映射一致、`critical_failure` 合法；
- summary：分母一致、各组 case-group 数一致、**有评分才算分 / 无评分不得有分**。

---

## 4. 三组怎么跑（公平性）

| 组 | 实现 | 关键约束 |
|---|---|---|
| **A** 直接问答 | 产品模型网关的**同一客户端与同一模型 id**，单次 `chat.completions` | 无检索、无工具、无 skill、无档案；提示词 = `prompts.COMMON_TASK_INSTRUCTIONS`（sha256 进 manifest） |
| **B** 受控 RAG | 同上客户端 + **产品检索链** `modules/library.search`（向量路 + 字面路 + RRF + 条目聚合），把命中的条目作为证据块（标题/出处/适用范围）放进 system 提示 | 无 Skill、无工具池、无多轮编排；提示词 = 共同边界 + 证据使用纪律（sha256 进 manifest） |
| **C** 生产 Agent | `composition.install` → `assembly.get_runner`；`RunRequest` 按 `send_message` 端点同一形状构造（surface/instructions/default_active_tools/context_payload 全部取自产品常量） | 真工具池（13 项）、真 skill（4 个）、真引用索引、真 SDK 会话表；提示词是产品自己的 `CONSULT_INSTRUCTIONS` |

公平性的机械保障：**三组收到的使用者文本由同一个函数渲染**（`prompts.render_user_turn`），
每条记录都带 `input_sha256`，`verify` 要求同一案例同一轮在三组间完全相同，且等于按冻结案例
重新渲染的结果。任一环被改动（例如给某组多塞一句背景）都会被 verify 报「信息不对称」。

> ⚠️ 必须写进报告的措辞边界：C 组测的是**程序内**生产运行链（`AgentRunner.run()`），
> 不是浏览器端到端体验（HTTP/SSE 由产品自身 e2e 用例覆盖）。C 的提示词与工具能力属于
> 「被测系统」的一部分，不得为了「公平」把它替换成 A/B 那种极简提示——那会让 C 不再是产品。

---

## 5. 知识快照与许可

- 裁定表：[`knowledge/snapshot.json`](knowledge/snapshot.json)。
  `included`（6 份）/ `blocked`（12 项，含 WHO-CST、NICE、NAS 等非商业或保留权利件）/
  `excluded_corpora`（3 个 internal 真实访谈案例包 + 1 个虚构演示包）。
- 每份 `included` 都带 `sha256` 与 `license_basis`（指回 `data/README.md` 的具体结论）。
  `preflight` 与 `run` 在启动时复算文件 hash；`read_database_state` 再核对**库内实际条目**：
  每个条目的 `source_path` 基名必须在 `included` 内，且不得有案例条目。
- B 与 C 用**同一个库、同一份快照**（快照 hash 进 manifest 的 `knowledge_snapshot.sha256`）。
- 库名与库内容都由外部（主 agent）准备，工具**不管生命周期**：只接受现有 `Settings` 配置，
  并在库名不像评测库时拒绝运行。

---

## 6. 故障注入（失效类案例）

注册表见 [`faults.py`](faults.py)。只有两处真实接缝，且都写在证据里：

| fixture | 组 | 实施方式 | 状态 |
|---|---|---|---|
| `retrieval_empty` | B | 跳过检索，证据块写明「本次检索没有返回任何材料」 | 已实现 |
| `retrieval_unavailable` | B | 检索抛错，证据块写明「检索服务不可用」 | 已实现 |
| `tool_search_empty` | C | 工具池里把 `search_knowledge` 换成返回空结果的 `ToolSpec`（其余仍是产品真工具） | 已实现 |
| `tool_search_unavailable` | C | 同上，换成返回 `ToolFailure(tool_failed)`（走产品既有失败路径） | 已实现 |
| `tool_timeout` | — | 需要让工具真实挂住到超时；当前工具池没有公开的延时缝，强行包装会把产品超时记成评测超时 | **未支持** |
| `stale_material` | — | 需要库内过期条目；评测库不许可加入过期语料 | **未支持** |
| `prompt_injection_unrelated` | — | 需要可控检索文本，A/C 无对等注入点 | **未支持** |
| `partial_data_missing` / `location_unknown` | — | 属案例文本层面的信息缺失，不是系统故障，无需注入 | 不需注入 |

- 请求在 `--fixtures fixtures.json`：`{"cases": {"CFB-T-033": ["tool_search_unavailable"]}}`，
  也可由案例自身的 `fixtures` 字段声明（`requested_by=case`，优先级见 `faults.merge`）。
- 每条记录带 `fixtures`：`{name, requested_by, systems, applied, impl, note}`。
  **未实施的条目一律 `applied=false` 并给出原因**；`summary` 里单独列 `unsupported`。
- 绝不用「在 prompt 里说工具坏了」冒充注入——那样测到的是模型会不会被提示骗过去。

---

## 7. 环境要求与运行前准备

```bash
# 1) 独立 uv 环境（不要复用别人的 .venv）
uv sync --frozen

# 2) 配置：从原始根复制 .env（文件已 .gitignore，绝不会被打印或提交）
cp /srv/workspaces/repos/Campfire-AI/.env .env && chmod 600 .env

# 3) 评测库（由主 agent 准备并迁移；本工具不创建、不 drop、不改语料）
#    库名必须形如 campfire_carebench_*
export DATABASE_URL="postgresql+asyncpg://<user>:<pw>@<host>:5432/campfire_carebench_<date>"
```

依赖的事实（都不写进 manifest 的敏感字段）：

- `MODEL_NAME`、`TOKENHUB_BASE_URL`、`TOKENHUB_API_KEY`：对话侧（本机可为 `127.0.0.1:7863` 的 chat-only 网关）。
- `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY`：**必须独立配置**。若对话端点是本机网关而嵌入
  跟着回落，检索会 404，产品侧只表现为「没有资料」——`preflight` 把这种组合判为**阻断**。
- `DATABASE_URL`：评测库（隔离守卫只看库名，不看实例）。
- 密钥只经 `Settings`/`.env` 运行时解析；`manifest.json` 只记库名、端点**主机名**与「凭据是否已配置」。

---

## 8. 证据留存

- `runs/` 与 `frozen/` 默认被 `.gitignore` 忽略（含模型原始输出，体积与敏感性都不适合跟代码走）。
- 需要留档的批次由主 agent 在评审后**显式决定**落点并单独提交；不要依赖 `.tmp/` 或 `git clean`。
- 同一 run 目录内不允许混入别的案例/配置/代码：`resume` 与 `verify` 都以 `batch_id` 拒绝。

---

## 9. 验证记录（本工具实际跑过什么）

日期：2026-10-29（Asia/Shanghai）。环境：本机 worktree、独立 `.venv`、评测库
`campfire_carebench_20261029`（6 条 knowledge / 117 节点 / 0 案例）、对话端点本机网关
`127.0.0.1:7863`（`cn:deepseek-v4.1-flash`）、嵌入端点独立（TokenHub）。

### 9.1 确定性测试

```bash
uv run pytest evaluation/carebench/tests -q     # 46 passed
uv run ruff check evaluation/ && uv run ruff format --check evaluation/
```

覆盖：案例结构校验（含坏数据负例）、配置/批次 hash 稳定性、轮换顺序、每 case-group 新会话、
固定二轮、输入对称、外层重试与首错保留、空回复不重试、超时进分母、续跑不重跑已完成轮次、
跨批次续跑被拒、非评测库被拒、dry-run 零调用、盲化评审包（无组别字段）、`pending`/空分拒收、
关键约束计数校验、重复评分拒收、无评审不出分、有评审的硬失败分列与配对、证据包篡改检测
（记录内容 hash、输入不对称）、`--require-complete`、冻结幂等与冲突、`preflight --frozen` 的配置 hash 与冻结记录一致、装配变体可见、命令行命令集合。

### 9.2 真实校准调用（少量，仅合成校准案例）

| 批次 | 内容 | 观察 |
|---|---|---|
| `calib-smoke-3` | 校准 `CFB-C-001`（单轮）+ 续跑 `CFB-C-003`（双轮） | A/B/C 全部真实完成：A 5.1 s / 84+521 tok；B 6.0 s / 84+621 tok、命中 5 条材料；C 26.3 s / 45 671+3 019 tok、4 次模型请求、工具轨迹 `skill → read_skill_resource ×2 → search_knowledge ×2`、12 条引用。续跑只补第二轮，第一轮输出未被重跑。 |
| `calib-smoke-4` | 校准 `CFB-C-002` + 注入 `tool_search_unavailable`(C) / `retrieval_empty`(B) | C 的 `search_knowledge` 真实返回 `tool_failed`，回答里如实写「检索服务暂时不可用，没查到任何条目」；B 无证据块、无引用；A 不受影响。三个 case-group 的 fixture 状态分别记 `applied=true/false`。 |

`summarize` 在两个批次上都只输出计数/时延/token（`human_scores=null`）；`verify` 通过。
`review-export` → 手工填一份**占位**评分（仅用于验证导入链路，写在 `.tmp/` 副本里、事后删除）
→ `review-import`（`double_blind`）→ `summarize`（出硬失败分列与配对）→ `verify` 通过。

### 9.3 适配过程中发现并修掉的两处工具/集成缺陷（已进代码与本节）

1. **SDK tracing 在非 `main.py` 入口抛 `InvalidURL: Invalid port: ':1]'`**。
   本机 `no_proxy` 含 `[::1]`，agents-sdk 首次运行会构造 `httpx2.Client`（tracing 导出器），
   解析失败 → 整次运行 100 ms 内失败，事件流只有 `run_started`，连 `run_failed` 都发不出来。
   产品在 `main.py` / `worker.py` 导入期调 `core/config.apply_no_proxy_normalization()` 覆盖；
   本工具是第三个程序内入口，现在也在包导入期调用同一函数（幂等）。
   复现：任意脚本 `composition.install` + `runner.run(...)`，宿主机 `no_proxy` 含 `[::1]`。
2. **重建工具池时 `ToolPool(...)` 拒绝基座保留名**（`skill`/`read_skill_resource`/`ask_user`）→
   `ToolRegistrationError`。故障注入路径改为逐项 `register_base` / `register`。
3. 另有两处小修：证据载荷里的 `datetime` 需要 ISO 序列化（C 的引用记录带时间戳）；
   `resume` 曾在一个进程里用两个事件循环（连接池绑定首次循环）→ 现在整条链路单循环。

### 9.4 观察到但**未修改**的产品行为（交主 agent 判断，不在本工具内绕开）

- **C 组正文用了 markdown**（`## 1. 建议与依据`、`*…*`、`**…**`），而产品面提示
  `CONSULT_INSTRUCTIONS` 明确要求「纯文本、不要 markdown 标记」。A/B 也有同样倾向。
  影响：C5（理解与呈现）评分会被格式拖累；是否属产品缺陷或仅提示词效力不足，需主 agent 裁决。
- C 组一次单轮咨询消耗 4 次模型请求、45 k 输入 token（skill + 2×资源读取 + 2 次检索），
  与 A/B 的 84 token 输入不在同一量级——报告里必须把 token 与时延按组单列，不能取平均。

---

## 10. 未知项与待确认

1. **正式 40 例未冻结、未运行**：本工具没有接触正式集（避免污染）。正式集的
   `review_status` 全部是 `draft_unreviewed`，因此任何结果都只能作为原始观察，专业结论必须
   `needs_review`。
2. **专业评审缺失**：`critical_failure` 与五维分需要具备相关资质的人；本工具只保证「不是模型打的」
   与「`pending` 不算通过」。
3. **κ 未实现**：需要 2×2 列联表，当前只给原始一致率（字段里写明为什么返回 `null`）。
4. **B 组检索词口径**是「共享背景 + 本轮问题」截断到 500 字符；这是设计选择，未经校准。
5. **推理参数**（temperature/top_p/seed）一律未显式传参（记 `null`），因为产品也没有显式设置；
   若主 agent 确认要固定，请改 `RunConfig` 并重冻（会改变 `config_sha256`）。
6. **单轮超时默认 300 s**（与产品运行上限一致）；若某模型端点抖动，超时会大量进入分母——
   这是刻意的（协议要求把超时计入），但会显著拉高成本。
7. **状态词表只有四种工程事实**（`completed/no_output/timeout/error`）；「明确拒答」由人工在
   `ratings.csv` 判定，自动只给 `status_flags.refusal_suspected` 这一线索。

---

## 11. 主 agent 待办（本工具已就绪的部分不重复）

1. 集成修复后，把正式 40 例冻结：
   `uv run python -m evaluation.carebench freeze --cases <正式集> --label test`，
   并把 `freeze.json` 的 `dataset_sha256` 记进报告。
2. 用正式集跑 `run`（建议先 `--dry-run` 看分母，再 `--case-ids` 跑 1–2 例确认端点稳定，最后全量）。
3. 导出评审包 → 交给**两位独立**评审者（高风险案例需相关资质）→ `review-import` → `summarize` → `verify --require-complete`。
4. 决定批次证据的留存落点（`runs/` 默认不入库），并在报告中引用 `run_id` + `batch_id`。
5. 裁决 §9.4 的两条产品观察（markdown 输出、C 的 token/请求量级）。
