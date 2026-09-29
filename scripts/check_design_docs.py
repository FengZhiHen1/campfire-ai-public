"""设计文档一致性检查：CI 与本地共用同一份实现。

放在 ``scripts/`` 而不是内联进 workflow，是为了避免同一套规则存在两份实现而漂移。

检查内容：

1. 有效设计文档中的相对链接必须存在（``docs/**/*.md`` 加 ``AGENTS.md`` 与
   ``archive/README.md``）。
2. 需求 ID 与验收行必须相互可解析。文档的实际格式是——
   需求：``**RQ-ACC-01 全应用登录**``（加粗行，不是标题）；
   验收：``| AC-01 | `RQ-ACC-01` | … |``（AC ID 是 ``AC-NN``，不带中段）。
3. 视觉契约（``docs/design/tokens.css`` 与 ``components.html``）存在时校验 token。

## 自检前置条件（重要）

本脚本会断言「提取到的需求数与验收行数不为零」。上一版的规则写的是
``^### RQ-…``，而文档从不用这种标题，于是这个检查长期**空跑**——一个永远不会
失败的闸门。自检就是为了让这种脱节立刻暴露，而不是静默通过。

## 当前降级为告警的两项

- **未覆盖的需求**：9 条已确认需求尚无对应验收行（脚本每次运行都会列出）。
  需求基线由用户拥有，补验收行是设计动作，故先告警不阻塞；补齐后应改为失败。
- **视觉契约缺失**：``docs/design/`` 尚未按新基线重建（旧契约已随 v3.0 归档，
  不得作为当前依据），而前端样式层在契约到位前不得动工
  （docs/项目结构设计.md 第 9 节）。

退出码：0 通过（可能带告警），1 有失败项。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

# 本文件位于 <仓库根>/scripts/，因此 parents[1] 是仓库根；
# 不依赖当前工作目录，便于从任意位置运行。
ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SPEC = DOCS / "需求" / "功能需求与验收.md"

REQUIRED_TOKENS = {
    "--bg",
    "--surface",
    "--fg",
    "--muted",
    "--border",
    "--accent",
    "--font-display",
    "--font-body",
    "--font-mono",
}

LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
# 需求声明：行首加粗的 RQ ID
REQUIREMENT_PATTERN = re.compile(r"^\*\*(RQ-[A-Z]+-\d{2})\b", re.M)
# 验收表数据行：| AC-01 | `RQ-…` | … |
AC_ROW_PATTERN = re.compile(r"^\|\s*(AC-\d{2})\s*\|(.*)$", re.M)
RQ_ID_PATTERN = re.compile(r"RQ-[A-Z]+-\d{2}")


def check_links(problems: list[str]) -> tuple[int, int]:
    """校验所有相对链接可解析；返回（文档数，链接数）。"""
    pages = sorted(DOCS.rglob("*.md"))
    pages += [ROOT / "AGENTS.md", ROOT / "archive" / "README.md"]

    link_count = 0
    for page in pages:
        if not page.is_file():
            continue
        for lineno, line in enumerate(page.read_text(encoding="utf-8-sig").splitlines(), 1):
            for href in LINK_PATTERN.findall(line):
                if re.match(r"^(?:https?://|mailto:|#)", href):
                    continue
                link_count += 1
                target = unquote(href.split("#")[0].split("?")[0])
                if target and not (page.parent / target).exists():
                    problems.append(f"断链 {page.relative_to(ROOT)}:{lineno} -> {href}")
    return len(pages), link_count


def check_requirement_coverage(problems: list[str], warnings: list[str]) -> tuple[int, int, list[str]]:
    """校验需求与验收相互可解析；返回（需求数，验收行数，未覆盖需求）。"""
    if not SPEC.is_file():
        problems.append(f"需求文档不存在：{SPEC.relative_to(ROOT)}")
        return 0, 0, []

    spec = SPEC.read_text(encoding="utf-8-sig")
    requirements = set(REQUIREMENT_PATTERN.findall(spec))
    ac_rows = AC_ROW_PATTERN.findall(spec)

    # 自检：规则与文档格式脱节时必须失败，不得静默通过
    if not requirements:
        problems.append(
            "提取不到任何需求 ID——检查规则与文档格式已脱节。"
            f"期望格式形如 `**RQ-ACC-01 全称**`（{SPEC.relative_to(ROOT)}）"
        )
    if not ac_rows:
        problems.append("提取不到任何验收行——检查规则与文档格式已脱节。期望格式形如 `| AC-01 | `RQ-ACC-01` | … |`")

    covered: set[str] = set()
    for _ac_id, rest in ac_rows:
        covered.update(RQ_ID_PATTERN.findall(rest))

    uncovered = sorted(requirements - covered)
    if uncovered:
        warnings.append(
            f"{len(uncovered)} 条需求尚无对应验收行（需求基线归用户所有，"
            f"补齐验收行后本项应改为失败）：{'、'.join(uncovered)}"
        )
    return len(requirements), len(ac_rows), uncovered


def check_visual_contract(problems: list[str], warnings: list[str]) -> None:
    """校验视觉契约；契约尚未重建时只记告警，不算失败。"""
    design = DOCS / "design"
    if not design.is_dir():
        warnings.append(
            "视觉契约未重建：docs/design/{tokens.css,components.html} 不存在，"
            "前端样式层在此之前不得动工（docs/项目结构设计.md 第 9 节）"
        )
        return

    tokens = (design / "tokens.css").read_text(encoding="utf-8-sig")
    components = (design / "components.html").read_text(encoding="utf-8-sig")
    defined = set(re.findall(r"(--[a-z][a-z0-9-]*)\s*:", tokens))
    for name in sorted(REQUIRED_TOKENS - defined):
        problems.append(f"tokens.css 缺少契约 token：{name}")
    for name in sorted(set(re.findall(r"var\((--[a-z][a-z0-9-]*)", components)) - defined):
        problems.append(f"components.html 引用未定义 token：{name}")


def main() -> int:
    """跑全部检查并打印结论；返回进程退出码。"""
    if not DOCS.is_dir():
        print(f"docs/ 不存在：{DOCS}", file=sys.stderr)
        return 1

    problems: list[str] = []
    warnings: list[str] = []

    pages, links = check_links(problems)
    requirements, ac_rows, _ = check_requirement_coverage(problems, warnings)
    check_visual_contract(problems, warnings)

    print(f"设计文档 {pages} 份，相对链接 {links} 条，需求 {requirements} 项，验收行 {ac_rows} 条")
    for item in warnings:
        # GitHub Actions 会把这一行渲染成一条告警注解
        print(f"::warning::{item}")
    if problems:
        print(f"失败 {len(problems)} 项：")
        print("\n".join(problems))
        return 1
    print("全部检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
