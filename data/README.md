# 冷启动数据（`data/`）

> **这是什么**：两库（资料库 / 案例库）的**冷启动输入语料**——`cli ingest` 的入参。
> 它是可重建的两库真源：删库后照本文重跑 CLI 即可复原，不依赖任何一次性的数据库快照。
>
> **这不是什么**：不是运行时数据目录（运行时数据在具名 Docker 卷里，见 `docker-compose.yml`），
> 也不是设计权威（设计真源在 `docs/`）。本目录只承载"喂给摄取链的输入"。

## 为什么放这里

原 `.gitignore` 有 `data/` 一条整目录忽略规则，导致 `data/.gitkeep` **从未生效**——
克隆后目录根本不存在，而它一直被当作语料位使用。2026-10-06 改为
「放行语料层、继续忽略运行时子目录」，并实测验证：

| 路径 | 判定 |
|---|---|
| `data/README.md`、`data/knowledge/**`、`data/cases/**`、`data/.gitkeep` | **进版本库** |
| `data/originals/`、`data/cache/`、`data/tmp/`、`data/*.dump`、`data/*.sql` | 忽略 |

（判据为 `git check-ignore -q <path>` 的退出码：0 = 忽略，1 = 会跟踪。）

## 目录布局

```text
data/
├── README.md                      # 本文件：登记、许可结论、重建方式、未核实项
├── knowledge/                     # 资料库入参（cli ingest <md>）
│   ├── autism-corpus/             # 已入库的 2 份成品 + 采集与对账留痕
│   └── autism-md/                 # 16 份结构化整理（尚未入库，见下）
├── cases/                         # 案例库入参（cli ingest <包目录> --library case）
│   ├── 2026-05-25_1448_respecting-pace-asd/
│   ├── 2026-05-30_2243_emotion-growth-asd/
│   └── 2026-05-31_0850_adult-pdd-social/
└── originals/                     # 原件层，**不进版本库**（见 .gitignore）
    ├── autism-corpus/             # NHC PDF 等大件与许可受限件
    ├── autism-md/                 # zip 原封释放件
    └── provenance/                # 加工过程留痕（裁决表、复核记录）
```

## 一、资料库语料

### 1.1 `knowledge/autism-corpus/` —— 已入库（2 条 / 92 节点）

| 成品 | 出处 | 许可 | 入库 |
|---|---|---|---|
| `nhc-0-6-autism-screening-intervention.md` | 国家卫健委公报 2022 年第 8 期，第 7–28 页 | 中国政府公开发布，可引用 | 1 条目 / 23 节点 |
| `pmc-hume-third-generation-review.md` | Hume et al., *J Autism Dev Disord* 2021;51(11):4013-4032，DOI `10.1007/s10803-020-04844-2` | CC BY 4.0（需署名） | 1 条目 / 69 节点 |

同目录两份留痕文件是**加工过程的证据**，不是语料，不要拿去 ingest：

- `加工与对账记录.md` —— 加工方式、守恒对账、修复的 6 处缺陷、复现命令、未做事项；
- `采集出处与许可清单.md` —— 采集通道分层、许可核查结论、被排除件与理由。

**许可排除留档**：`02-BMJ-ProjectAIM-2023.html` 技术上可加工（`cli convert` 已实测），
但按 2026-09-29 用户裁决排除——文章页标 CC BY-**NC** 4.0，而站点级声明保留
文本与数据挖掘、AI 训练权利，两处冲突时排除成本远低于误用。登记于 `EVID-B`。

### 1.2 `knowledge/autism-md/` —— 尚未入库（16 份）

依据用户提供的《孤独症资料清单.xlsx》整理（**该 xlsx 全盘未找到，见未核实项**）。
本批在搬运时修了两处实测损坏，并补齐了摄取闸门要求的 frontmatter 键：

1. **文件名 mojibake**：原盘 4 个中文名被写成 GBK 双编码（如 `01_瀛ょ嫭鐥囪氨绯婚殰…`）。
   已按 GBK→UTF-8 还原，并**用 SHA256 逐份核对内容未变**。
2. **`05_WHO_自闭症事实清单.md` 磁盘缺失**（README 索引列了 16 份、磁盘只有 15 份）。
   已从同目录 zip 补回，与 zip 内容逐字符一致。
3. **补 `applicable_scope` 与 `license`**：原 16 份缺这两个键，
   按 `RAG策略` 第 1 节的不变量（`RQ-KB-02`，缺 `source` 或 `applicable_scope` 即拒）**会被全部拒绝入库**——
   已用项目自身的 `parse_frontmatter` 实测：补前 18 份只有 2 份通过，补后 **18/18 通过**。

**⚠ 许可待裁决（`EVID-B`）**：本批 16 份中有 **8 份带非商业或保留权利条款**，
与 BMJ 被排除的理由同类。逐份实际条款已写进各文件 frontmatter 的 `license` 键：

| 文件 | 许可实际条款 |
|---|---|
| 01–04 NHC 两份指南与两份解读 | 中国政府公开发布，可引用 |
| 05 WHO 自闭症事实清单 | © WHO，再利用须遵 WHO 条款，**未取得明文授权** |
| 06–09 WHO CST 四份 | **CC BY-NC-SA 3.0 IGO**（非商业） |
| 10 NICE CG170 | © NICE，**限私人研究/学习/内部使用，不得分发** |
| 11 CDC 走失应急 | 美国政府作品，通常可再利用 |
| 12–15 NAS 四份 | © National Autistic Society，**再利用须另行确认** |
| 16 Autism Speaks 视觉支持 | 原文件允许原样传播，部分图像另有版权 |

**按 `EVID-B`「未取得许可不建索引」，上述带限制的 8 份在许可落实前不应摄取。**
`01`–`04`、`11` 五份的许可结论相对清晰，可优先摄取。**这条需用户裁决**，
本文不代替裁决，也不预先替你判断。

## 二、案例库语料（3 包 / 10 张卡片）

**来源在仓库之外**：`E:\Project\Tool\speech-to-text\exports\case-extraction\`
（上游 FunASR 转写 + `case-extraction` skill 抽取；ASR 与抽取**留在链外**，
故只搬导出物，不搬 1–2 GB 模型权重与 torch）。搬入理由是**上游那 2 个包当时未进版本控制**，
随时可能丢；本项目仓库为 private，同意范围已覆盖 AI 检索与建议。

### 2.1 已补 `manifest.json`

上游把元数据写在 `L1_*.md` 页脚，**机器不可读**，而摄取链要求每包含 `manifest.json`
（缺失即退出码 1，见 `apps/api/tests/test_cli_case_ingest.py`）。三个包的 manifest 已按
`CaseManifest`（`apps/api/src/campfire/modules/library/case_schema.py`）补写，
并**用项目自身的 `load_manifest` + `validate_card` 实测通过**（3 包 / 10 卡 / 0 错误）。

| 包 | 标题 | 卡片 | 主体 |
|---|---|---|---|
| `2026-05-25_1448_respecting-pace-asd` | 从强迫到尊重：ASD儿童家庭干预中的节奏调整与规则建立 | 3 | 家长 |
| `2026-05-30_2243_emotion-growth-asd` | 从不定期炸弹到自我调节：ASD儿童成长中的情绪管理与环境支持 | 4 | 家长 |
| `2026-05-31_0850_adult-pdd-social` | 成年才被看见：PDD晚诊断人士的情绪管理与社交重建 | 3 | 家长 |

**manifest 取值的依据与边界**（不编造）：

- `review_status: owner` —— 2026-09-29 用户决定「当前 3 个案例导入时标为已核准」。
  上游自称 `INSTITUTIONAL（待专家审核）`，故**不得**显示为专业审阅；
- `reviewer: null` —— 与 `owner` 档一致（契约**对称校验**：非 `professional` 填具名审阅者会被拒，
  因为那会把「所有者核准」冒充成专业审阅）；
- `authorization` —— 如实写明"用户裁决同意范围覆盖 AI 检索与建议，
  **但本项目未持有同意文本本身**"。上游 `data/audio` 与转写记录中**未见同意书**，
  其设计文档只写了"采访前已获得知情同意"这一要求；
- `status: internal` —— 真实访谈转写，**不是** `fictional`（`AC-06` 要求虚构样例可辨，不得误标）；
- `transcript_ref` —— 指回上游路径，**转写原文不入库**（可能含未脱敏内容，且属上游）。

## 三、重建方式

```bash
# 资料库（单文件；元数据来自文件 frontmatter，故无需 --source/--scope）
uv run python -m campfire.cli ingest data/knowledge/autism-corpus/nhc-0-6-autism-screening-intervention.md
uv run python -m campfire.cli ingest data/knowledge/autism-corpus/pmc-hume-third-generation-review.md

# 资料库（16 份整理包，许可裁决通过后）
uv run python -m campfire.cli ingest data/knowledge/autism-md/01_孤独症谱系障碍儿童干预康复指南_2026.md

# 案例库（包目录，含 manifest.json）
uv run python -m campfire.cli ingest data/cases/2026-05-25_1448_respecting-pace-asd --library case
```

按 `RAG策略` 第 7 节纪律：摄取应在**部署目标机器、同一镜像与同一 lockfile 的容器内**执行
（分块与嵌入结果需可复现，换环境会漂移），凭据复用应用既有配置，不新增第二套。

**语料随镜像发布（2026-10-07 起）**：`Dockerfile.api` 把语料层复制进镜像的 `/app/data`；
生产编排没有挂载语料目录，因此摄取一律用容器内路径：

```bash
docker exec campfire-api python -m campfire.cli ingest /app/data/knowledge/autism-corpus/nhc-0-6-autism-screening-intervention.md
docker exec campfire-api python -m campfire.cli ingest /app/data/cases/2026-05-25_1448_respecting-pace-asd --library case
```

镜像只含**语料层**（`README.md`、`knowledge/`、`cases/`）。`data/originals/`、`data/cache/`、
`data/tmp/` 等原件与运行时目录由 `.dockerignore` 排除——原件不在版本库，也不得进生产产物。

### ⚠ 已入库 2 份的 `source_path` 变更（重要）

摄取链的幂等键是 **`source_path` 全路径 + `doc_hash`**（`ingestion.py:361-369`）。
本次把两份成品从 `.tmp/autism-corpus/ingest-ready/` 搬到 `data/knowledge/autism-corpus/`，
**库内 `source_path` 仍是旧路径**。因此：

- 用新路径重摄取 ⇒ **不会命中幂等跳过，会新建重复条目并重复嵌入**；
- 现行库内 2 条目是有效的，**本次未改库**。

处置方向（择一，需用户决定，本文不擅自执行）：
① 不重摄取，接受库内 `source_path` 指向旧路径（本次未删旧文件，仍可取）；
② 先 `cli withdraw knowledge <item_id>` 撤下旧条目，再用新路径重摄取；
③ 直接改库内 `source_path`（**不建议**：绕过摄取链，且需手动对账 `doc_hash`）。

## 未核实项（如实登记）

- **`data/originals/` 中所有文件的许可**未逐份完成法律判断；本文只记录**文件自身声明**。
  带非商业/保留权利的 8 份能否入库，属 `EVID-B`，**未裁决**。
- **《孤独症资料清单.xlsx》全盘未找到**（整理包 README 称依据它整理）。
  它可能含授权信息，缺失意味着整理包的授权链**无法回溯到原始清单**。
- **案例的同意文本未见**：`consent_recorded_at` 全部为 `null`，
  因上游无任何可引用的同意记录。同意范围目前仅由用户裁决承载。
- **16 份整理包的正文未与来源原件逐字核对**（它们是"结构化整理，非逐字转录"）。
- **未做检索质量评测**：`RAG策略` 第 8 节的评测集依赖 `EVID-F` 语料完整录入。
- **`_ingest` 精修产物的 50 页 jpg 与 MinerU 原始档未搬入**
  （约 31 MB，属可重生成产物；`_verdicts.md` 等复核留痕已归入 `originals/provenance/`）。
- **本目录内容未做端到端摄取演练**：验证止于"项目自身的校验器接受这些输入"
  （`load_manifest` / `validate_card` / `parse_frontmatter`），
  **未**在真实库上跑一次 `cli ingest`（那会真实写库并调用嵌入）。
