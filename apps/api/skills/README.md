# skills —— 开放标准的 skill 内容产物

本目录放的是**内容**，不是 Python 代码（见 `docs/项目结构设计.md` 第 4 节）。

```text
skills/<skill-name>/SKILL.md      # 元数据 + 指令主体
skills/<skill-name>/references/   # 按需读取的文档
skills/<skill-name>/scripts/      # 可选：可执行代码（一期不执行，仅保留运行器端口）
skills/<skill-name>/assets/       # 可选：模板与数据
```

## frontmatter 只用标准的六个字段

| 字段 | 必填 | 约束 |
|---|---|---|
| `name` | 是 | ≤64 字符，仅小写字母、数字与连字符；必须与父目录同名；不以连字符开头或结尾；不得连续连字符 |
| `description` | 是 | ≤1024 字符，非空；必须同时说明**做什么**与**何时用**，含便于匹配的关键词 |
| `license` | 否 | 许可证名称或随附许可证文件的引用 |
| `compatibility` | 否 | ≤500 字符；环境要求 |
| `metadata` | 否 | 自由键值映射（string→string）；**本项目自有的元数据放这里**，不改格式 |
| `allowed-tools` | 否 | 空格分隔的**预授权**工具列表；标准标注为 experimental |

本项目在 `metadata` 下约定两个自有键（基座读取但不送入模型）：

- `autoload` —— 是否允许模型自动匹配
- `surface` —— 所属面，供目录预算（上限 4000 token）分组用

## 三条硬约束

1. **不合法即拒绝加载并在启动时失败**，不得以空元数据静默加载。
2. 渐进披露三层：元数据（约 100 token）随启动载入 → 命中后载入 `SKILL.md` 主体
   （建议 <5000 token、主体不超过 500 行）→ `references/`、`assets/`、`scripts/`
   按需读取。文件引用用**相对路径且保持一层深**，不做多级引用链。
3. 校验用标准参照实现 `skills-ref validate`，纳入工程检查。

## 状态

**一期的四个 skill 已落地**（2026-09-30）。内容正本在 `docs/技术设计/面/consult/skills/`，
本目录是它的内容产物——改内容须先改设计文档，再同步过来。

| 目录 | 定位 | 激活 | `references/` |
|---|---|---|---|
| `emergency-consulting` | 突发情境的即时咨询：六层闸门 → 现场 Action Card | 程序注入（`autoload: "false"`） | `gates.md`、`action-card.md` |
| `daily-consulting` | 日常咨询：澄清、带依据的建议 | 模型匹配 / 使用者选定 | `clarification.md`、`evidence-and-options.md` |
| `profile-curation` | 把对话中出现的信息整理成档案候选 | 模型匹配 / 使用者选定 | `extraction-rules.md`、`source-and-status.md` |
| `onboarding` | 首次日常会话的一次性引导 | 程序注入（`autoload: "false"`） | `seed-questions.md`、`telling-first.md` |

三条共同纪律（有据才给建议、目标不等于服从、专业判断与可读解释并给）在
`emergency-consulting`、`daily-consulting`、`profile-curation` 的正文里以
`<!-- shared:evidence-discipline -->` 标记块承载，三份**逐字一致**；
`onboarding` **不含**该标记块（语义前提不成立，豁免一致性检查）。

## 工程检查

`apps/api/tests/test_skills_content.py` 把上面几条变成可执行断言：
目录扫描 0 个 skill 即失败、六字段校验、标记块逐字一致、`allowed-tools` 与
[技能设计](../../../docs/技术设计/technical-details/技能设计.md)第 3 节的工具总表互查。

标准参照实现 `skills-ref validate` 的调用方式：CLI 在 PATH 上时由该测试直接调用；
不在 PATH 上时改用测试内的等价校验（判据对齐参照实现的规则），两种情形都在测试里
写明探测结论——**不留一条「校验了 0 个、因此必然通过」的真空闸门**。

手动跑参照实现：

```bash
npx --yes skills-ref@latest validate apps/api/skills/emergency-consulting
```
