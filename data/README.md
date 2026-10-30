# 冷启动数据（`data/`）

> **这是什么**：两库（资料库 / 案例库）的**冷启动输入语料**——`cli ingest` 的入参。
> 它是可重建的两库真源：删库后照本文重跑 CLI 即可复原，不依赖任何一次性的数据库快照。
>
> **这不是什么**：不是运行时数据目录（运行时数据在具名 Docker 卷里，见 `docker-compose.yml`），
> 也不是设计权威（设计真源在 `docs/`）。本目录只承载"喂给摄取链的输入"。

## 目录布局

```text
data/
├── README.md                      # 本文件：目录口径、许可流程、重建方式、已知边界
├── knowledge/                     # 资料库入参（cli ingest <md>）
│   ├── autism-corpus/             # 已完成许可核查的成品 + 采集与对账留痕
│   └── autism-md/                 # 结构化整理件（许可结论逐件见 frontmatter 与 ATTRIBUTION.md）
├── cases/                         # 案例库入参（cli ingest <包目录> --library case）
│   └── <包目录>/                  # manifest.json + L1 叙事 + L2 卡片
└── originals/                     # 原件层，**不进版本库**（见 .gitignore）
    ├── autism-corpus/             # 大件与许可受限件
    ├── autism-md/                 # 原封释放件
    └── provenance/                # 加工过程留痕（裁决表、复核记录）
```

**本仓当前实际包含哪些文件，以 `git ls-files data/` 为准**——本文不逐件复述目录内容，
避免文档与磁盘漂移。语料层的授权声明见 [`LICENSE-DATA`](../LICENSE-DATA)，
逐件来源与义务见 [`ATTRIBUTION.md`](../ATTRIBUTION.md)。

## 一、什么能进本仓（准入规则）

新增任何语料或第三方素材之前，必须先在 PR 或提交说明里留下许可凭据：**来源、许可类型、
获取日期，以及授权范围是否覆盖再分发**。缺凭据的一律不进本仓。

这条规则来自公开化整改的直接教训：此前有语料只凭文档里的一句"免费商用授权"入库，
而全仓找不到任何授权文件。

三类结论要分开写，不要混为一谈：

| 结论 | 含义 | 能否入库 | 能否被检索 |
| --- | --- | --- | --- |
| 可再分发 | 许可允许本仓随附发布 | 能 | 能 |
| 可引用 | 允许引用与注明出处，但不允许再分发正文 | 不进本仓 | 不能 |
| 授权不足 | 非商业、限内部使用或需另行确认 | 不进本仓 | 不能 |

**「可引用」不等于「可再分发」**——这类件只登记出处，不复制正文。

## 二、摄取闸门（缺元数据即拒绝）

摄取链要求每份 Markdown 带 `source` 与 `applicable_scope`（来自文件 frontmatter 或命令行
参数，两者都缺则**拒绝入库**），并要求 frontmatter 里写清 `license` 结论。整理件在
搬运、改名或补元数据时，正文必须与来源保持一致；任何修改都要在留痕文件里说明做法与核对方式。

## 三、案例库语料

`data/cases/` 只放**虚构演示样例**，用于说明卡片结构与导入流程，不对应任何真实家庭。

真实访谈案例不随本仓分发：当事人同意范围只覆盖「AI 检索与建议」，不包含公开再分发，
且其中含未成年人诊断与年龄信息。相关处置与原因见 [`NOTICE`](../NOTICE) 第三节。

## 四、重建方式

```bash
# 资料库（单文件；元数据来自文件 frontmatter，故无需 --source/--scope）
uv run python -m campfire.cli ingest data/knowledge/autism-corpus/nhc-0-6-autism-screening-intervention.md
uv run python -m campfire.cli ingest data/knowledge/autism-corpus/pmc-hume-third-generation-review.md

# 资料库（结构化整理件，逐件许可结论确认后再摄取）
uv run python -m campfire.cli ingest data/knowledge/autism-md/01_孤独症谱系障碍儿童干预康复指南_2026.md

# 案例库（包目录，含 manifest.json）
uv run python -m campfire.cli ingest data/cases/2026-11-06_1000_fictional-supermarket-meltdown --library case
```

按 RAG 策略第 7 节的纪律：摄取应在**部署目标机器、同一镜像与同一 lockfile 的容器内**执行
（分块与嵌入结果需可复现，换环境会漂移），凭据复用应用既有配置，不新增第二套。

**语料随镜像发布**：`infrastructure/docker/Dockerfile.api` 把语料层复制进镜像的 `/app/data`；
生产编排没有挂载语料目录，因此生产环境内摄取一律用容器内路径：

```bash
docker exec campfire-api python -m campfire.cli ingest /app/data/knowledge/autism-corpus/nhc-0-6-autism-screening-intervention.md
```

镜像只含**语料层**（本文件、`knowledge/`、`cases/`）。`data/originals/`、`data/cache/`、
`data/tmp/` 等原件与运行时目录由 `.dockerignore` 排除——原件不在版本库，也不得进生产产物。

## 五、已知边界（如实列出）

生产导入台账（批次、条目 UUID、逐次节点计数）与未核实项登记在 `docs/development/checkpoints/data-ingest-ledger.md`——该文件仅内部开发仓提供，含真实案例标识，不随公开仓分发。

- **整理件不是逐字转录**：`autism-md/` 下各件是结构化整理，正文未与来源原件逐字核对；
  引用前请回到原始发布渠道复核。
- **部分整理件的许可仍待确认**：带非商业或保留权利条款的件，在许可落实前不建索引、
  不随仓分发；逐件实际条款写在各文件 frontmatter 的 `license` 键里。
- **数量与清单以磁盘为准**：本文不登记条数与 ID。生产库的导入台账、条目 UUID 与逐次
  节点计数属运维记录，不在本仓维护（其中含真实案例标识，不随公开仓分发）。
- **未做检索质量评测**：评测集依赖完整语料录入，语料未完整前不宣称检索效果。
