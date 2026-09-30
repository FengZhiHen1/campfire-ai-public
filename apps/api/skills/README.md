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

**一期 skill 尚未落地**：四个 skill（`emergency-consulting`、`daily-consulting`、
`profile-curation`、`onboarding`）的方法论与 `SKILL.md` 正文要点仍在
`docs/技术设计/面/consult/skills/` 下待确认。确认后每个 skill 在此建一个自包含目录。
