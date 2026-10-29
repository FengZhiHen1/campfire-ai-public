# CareBench Interactive 执行说明

协议唯一正文：[PROTOCOL.md](PROTOCOL.md)。本文件只说明实现入口与产物。
历史 v0.1 保留在[原工具](../README.md)，其分数与本轮不合并；见[局限](HISTORY-LIMITATIONS.md)。

## 准备

在干净的已提交版本上执行。需要本机 `campfire_carebench_interactive_*` 数据库、独立 Redis
DB14、`carebench_interactive_*` FalkorDB 图，以及许可清单内的知识文件与对应真实节点。
配置放忽略的 `.env`。不使用开发或生产库；不得把真实家庭资料导入评测库。

```bash
uv sync --frozen
uv run pytest evaluation/carebench/tests
uv run python -m evaluation.carebench.interactive --help
uv run python -m evaluation.carebench.interactive prepare \
  --split calibration --run-id 20261029-interactive-calibration-01
```

`prepare` 不生成模型答案；它核对实际知识，装配真实产品运行器，然后一次冻结协议、案例、
预算、三组提示身份、模型/端点/嵌入/知识内容、所有评分和模拟家长提示。输出根目录是由 Git
公共目录解析的原始仓库 `deliverables/2026-ai-opensource/<run-id>`，存在即拒绝覆写。
正式 `--split test` 固定 24×3×3，校准固定 8×3×1。

## 执行

```bash
uv run python -m evaluation.carebench.interactive run --root <批次绝对路径> --dry-run
uv run python -m evaluation.carebench.interactive run --root <批次绝对路径>
uv run python -m evaluation.carebench.interactive score --root <批次绝对路径>
uv run python -m evaluation.carebench.interactive summarize --root <批次绝对路径>
uv run python -m evaluation.carebench.interactive verify --root <批次绝对路径> --require-complete
```

本地端点的 system-only 指令探针未被遵从，三组统一使用 `SystemMessageTransport`，在首个用户消息重述已有系统指令；原始输入与实际 HTTP 消息分别保存。模拟家长与评分也采用冻结的协议重述包装。详见协议的兼容条件，不能把本轮直接解释为线上端点表现。

生成与评分必须继续使用冻结的干净提交及同一运行身份。每批只有一个写进程；进程内并发在冻结时
确定，默认 3。重复执行 `run` 只跳过已封存终局；已发起但被中断的任务封存为失败，不重采。
评分每角色最多 3 次结构尝试，调用前占用尝试编号；中断不增加预算，已保存的有效原始评分可恢复。
若预算耗尽仍无有效评分，保留未决，不改提示或判据补分。

## 产物

| 文件 | 用途 |
|---|---|
| `manifest.json`、`cases.frozen.jsonl`、`protocol.frozen.md`、`prompts.frozen.json` | 生成前冻结件，只创建一次 |
| `journal.jsonl`、`episodes.jsonl`、`traces/` | 请求开始、原始输出、真实入口请求、终局与工具事件 |
| `policy-attempts.jsonl` | 每次语义识别、有效或无效响应、冻结家长回复 |
| `calls.jsonl`、`http.jsonl` | 模拟家长/评分调用开始与结束；共享对话客户端的 HTTP 请求和响应头，保留内部重试，不保存认证头 |
| `rating-reservations.jsonl`、`rating-attempts.jsonl`、`ratings.jsonl` | 尝试预算、原始评分、两套独立结果、分歧及裁定 |
| `summary.json`、`verification.json` | 可重新计算的派生件；不替代原件 |

JSONL 各行包含内容 hash；核验同时检查分母、重复记录、轨迹 hash、逐轮披露、评分输入和原始
评分的可复算性。hash 用于发现变动，不构成外部可信签名。未记录嵌入 HTTP 尝试、供应商内部行为，
HTTP 响应头也不代表流式正文已完成；实际输出以轨迹与终局为准。

汇总保留任务完成、风险门槛、首轮帮助、澄清与修订、来源状态、交互负担和失败类型。没有综合
质量均分。重复按案例聚类，校准不能并入正式成绩。原始大文件留在原始根；脱敏摘要与证据索引
按[材料流程](../../../docs/development/materials.md)入库，不撰写完整报告或准备视频。
