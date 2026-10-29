# 案例输入（本目录只放**校准/自检**用案例）

| 文件 | 内容 | 用途 |
| --- | --- | --- |
| `cases-calibration-v0.1.jsonl` | 协议专题提供的 8 条校准案例（`CFB-C-001`…`CFB-C-008`，全部 `synthetic` / `draft_unreviewed`） | 只用于验证适配器、轮换、落盘、评审包与汇总**工具本身**；结果不得并入任何正式成绩 |

上游还提供了一份 `ratings-template.csv` 表头，**未纳入本仓库**：它是带 BOM 与 CRLF 的参考表头，
直接入库会在换行规范化后改变字节 hash，从而让「同一份模板」变得无法核对。本工具的评分表由
`review-export` 现生成（列口径见 `review.RATINGS_COLUMNS`，含 `blind_id`、不含 `system_id`），
空表本身就是权威模板。

## 来源与许可

本文件是 inbox 协议专题（`/srv/workspaces/repos/inbox/chatgpt/Campfire-AI/evaluation/scenario-benchmark/data/`）
的**逐字节副本**，合成样例、可公开：

- `cases-calibration-v0.1.jsonl`：SHA-256 `e62bba11c73570ef0821160b80b5af32dc0738aebb6d2cafcc05c538242ed756`

## 为什么正式 40 例不在这里

协议 05 与主 agent 的裁决都要求：**正式集在适配器与量表校准完成后冻结**，且冻结前后
不得因结果好看而改题。因此本仓库只带校准集；正式集由主 agent 用

```bash
uv run python -m evaluation.carebench freeze --cases <正式集路径> --label test
```

冻结，`freeze.json` 会记录其 `dataset_sha256`。任何「拿正式集反复调工具」的用法都会
破坏该集的未接触状态（协议 02 第 5 节），本目录因此在设计上不含它。

## 正式 40 例（`cases-test-v0.1.jsonl`）

| 项 | 值 |
| --- | --- |
| 文件 | `cases-test-v0.1.jsonl`（40 条，`split=test`，含 6 条固定第二轮） |
| 来源 | `/srv/workspaces/repos/inbox/chatgpt/Campfire-AI/evaluation/scenario-benchmark/data/cases-test-v0.1.jsonl`（**逐字节副本**，`cp` 后复算 hash 一致） |
| SHA-256 | `f7d4462e344db2d0a6553aad3d13703d2ce13f9f668eee8fe3845371f1dd50d3`（21 128 B） |
| `review_status` | 全部 `draft_unreviewed`（**没有改成 `approved`**：领域审核尚未发生） |
| 冻结状态 | **未冻结、未运行**（2026-10-29 现状；`frozen/test/` 不存在，`runs/` 无 `label=test` 批次） |

**语料定位（必须写进任何报告，不得含糊）**：这 40 例是**公开挑战集 / 非独立未见样本**，
不是密封测试集。其中 `CFB-T-009`（商场捂耳哭闹、单人带娃的应急场景）是**设计阶段就用过的
黄金场景**——它参与过提示词与技能的打磨，因此该题的分数**不能**当作「模型未见过」的证据。
其余题目按同一口径保守处理：本仓库无法证明任何一题对被测模型完全未见。

**故障注入计划**见 [`../fixtures-formal.example.json`](../fixtures-formal.example.json)
（T033 空结果、T035 检索不可用/超时、T040 客户端渲染故障按 `out_of_harness` 记未覆盖）。
