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
