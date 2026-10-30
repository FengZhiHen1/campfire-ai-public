# 协议快照（只读副本）

本目录是 CareBench 协议 01–05 的**逐字节副本**，来源：
内仓 inbox 的 `evaluation/scenario-benchmark/`（只读来源、路径不随本公开仓分发，
其内容由评测设计者维护，本仓库不修改它）。

为什么在评测目录里放副本而不是只引用 inbox：inbox 不在版本控制里、路径也可能移动；
而一份报告必须能定位到「当时按哪一版协议跑的」。`manifest.protocol_snapshot.sha256`
就是这张表的汇总 hash，`verify` 会用当前文件重算它。

**权威归属**：协议文本的真源是 inbox；这里只是快照。改动协议应改 inbox，再重新同步本目录
（同步后所有旧批次的 `protocol_snapshot.sha256` 都会对不上——这正是它存在的意义）。

| 文件 | SHA-256 |
| --- | --- |
| `01-评测目标与实验协议.md` | `ebe9ffc03de180dd1477fd77e2953dfad3c7fdec96d06bcb7689bdde00fada05` |
| `02-场景与标注规范.md` | `02db114a3362a565967e5c43df0f6041e63b3a058c0f7066af2307f58d0c392e` |
| `03-评分规则与安全门.md` | `650025171038465d54f9fcc752ae9d4b8edf66b16c282a13b203f87e4995adc8` |
| `04-执行操作与报告规范.md` | `86fedf515402b8043860818ed2df1e1507183f0465837507a045a58f964e6d14` |
| `05-快速先导评测执行合同.md` | `1bfd2fe8a9d7d5037f1a839bd96c7f5d60392906f318a17148aefdaef82c41d5` |

同步时间：2026-10-29（Asia/Shanghai）。

## 与工具实现的对应关系

| 协议要求 | 落实位置 |
| --- | --- |
| 01 §4 对照组定义与公平性 | `systems/direct.py`（A）、`systems/rag.py`（B）、`systems/agent.py`（C） |
| 01 §5 单例运行协议（新会话、固定轮次、原始输出不可改） | `runner.py`、`records.py` |
| 02 §3 案例字段与轮数 | `cases.py`、`freeze.py` |
| 03 §1 硬失败 / §2 五维量表（人工） | `review.py`（导入校验）、`summarize.py`（单独计数，不并入均分） |
| 03 §3 客观指标（时延、token、工具轨迹） | `runner.py` 落盘、`summarize.py` 汇总 |
| 03 §4 分母与配对比较 | `summarize.py` |
| 03 §5 两位独立评审与一致性 | `review.py`（盲化与双评模式）、`summarize.py`（一致性） |
| 04 §2 最小证据包（manifest/outputs/ratings/summary） | `store.py`、`manifest.py`、`review.py`、`summarize.py` |
| 04 §3 轮换顺序、单次重试、保留首错 | `config.py`（轮换与重试策略）、`records.py`（`is_final`） |
| 05 §4 A/B/C 公平实施顺序与降级 | `systems/build.py`、README「公平性」一节 |
| 05 §6 P0–P5 交付物 | `preflight.py`（P0）、`runner.py`（P2）、`review.py`（P3/P4）、`verify.py`（P5） |

## 未随快照搬运的内容

- `data/cases-test-v0.1.jsonl`（40 例正式候选）：**未**复制进本仓库的评测目录，
  正式集由主 agent 在集成后冻结（`freeze --cases <path> --label test`）。
  本目录只带 `cases/cases-calibration-v0.1.jsonl`（8 例校准，工具自检用）。
- `报告模板.md`：报告由 `summarize` 生成 `summary.md`，模板留作人工撰写时的参考（未复制，
  以免出现「模板被填成结果」的误读）。
- `scripts/validate_cases.py`：结构校验已由 `cases.py` 重实现（含轮数一致性等本工具额外需要的判据），
  两边口径若漂移，以本工具为准并在报告里注明。

