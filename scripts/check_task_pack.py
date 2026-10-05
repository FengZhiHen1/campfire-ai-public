#!/usr/bin/env python
"""任务包出库前的机械自检（dev-orchestrator 编排器自用）。

## 为什么有这个脚本

一位独立决策质量审计者对本轮编排提出了本轮最尖锐的一条批评：

> **126 节几乎全是 prose 纪律、由你自己转化成机械闸门的 ≈0**
> （**现有闸门全是子代理提议**）；**同根因（「我以为」替代「实测」）重复编号约 9 次**。

另有一条：

> **任务包出库前的机械自检 gate（终结 (z26) 族复发）** ——
> 错前提/未验方案进任务包已复发 ≥7 次
> （`(z3)`/`(z26)`/`(z40)`/`(z52)`/`(z64)`/`(z78)`/`(z79)`），
> **每次只长 prose 纪律**。

⇒ 本脚本把那条 prose 纪律变成**会失败的检查**：
**任务包写完后必须能通过它，否则不许派发。**

## 检查哪三件事（对应审计的三问清单）

1. **候选方案是否标注了「已验证 / 未验证」** ——
   我在任务包里列多个方案时，若不标注，就暗示它们同等可行
   （`(z78)` 的教训：我把「给一个足够大的有限超时」写成可选项，而它在原理上不可行）；
2. **「必须 X」是否区分了「结果」与「机制」** ——
   `(z76)` 的教训：我写「校验器必须拒绝空值」，隐含假设了「校验器一定会被调用」，
   而事实是 SDK 先拦掉了；
3. **包内的数字/归因是否曾被订正过** ——
   `(z94)` 的教训：我把「7 项已修」写进包，而实际只落地 4 项。

## 用法

```bash
uv run --no-project python scripts/check_task_pack.py .tmp/dev-orchestrator/<会话>/tasks/*.md
```

**退出码非 0 即未通过**（CI 风格：发现问题就失败，不是告警）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

#: 出现这些词说明包内提供了候选方案 ⇒ 必须标注验证状态。
_OPTION_MARKERS = (
    "候选方案",
    "两条路线",
    "两条可行路线",
    "你选一条",
    "任选其一",
    "替代修法",
)

#: 候选方案的「枚举」形态：`- **(a) …**` / `方案 (b)` / `(c) 别的做法`。
#:
#: ⚠ 为什么要单独列这个模式（记一次真实的失败）：
#: 本脚本第一版只认 `_OPTION_MARKERS` 里的词，于是 **T17 那份任务包被判为「通过」** ——
#: 而 T17 恰恰就是 `(z78)` 那次失误的现场（我把「给 socket_timeout 一个足够大的值」
#: 写成可选项 (b)，**实测证明它原理上不可行**）。
#: ⇒ 「闸门没抓到它本该抓的那个案例」= 这个闸门当时是**永远不会失败的检查**。
#: ⇒ 教训：**新写的闸门必须拿【已知会红的历史案例】验证它能红**（否则它就是摆设）。
_OPTION_ENUM_PATTERN = re.compile(r"^\s*[-*\d.]*\s*\*{0,2}\(([abc])\)\s", re.MULTILINE)

#: 标注「已验证/未验证」的词。缺了它就被判为「未标注」。
_VERIFICATION_MARKERS = (
    "已验证",
    "未验证",
    "已核实",
    "未核实",
    "只是猜测",
    "实测证伪",
    "我已实测",
    "推测",
    "以代码为准",
    "以……为准",
    "以…为准",
    "请自己核",
    "不要抄",
    "以实际为准",
)

#: 候选方案那一行附近的窗口（字符），用于判断标注是否在同一段里。
_WINDOW = 900


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_options_annotated(text: str) -> list[str]:
    """候选方案是否标注了验证状态。"""
    problems: list[str] = []
    hits: list[tuple[int, str]] = []
    for marker in _OPTION_MARKERS:
        for hit in re.finditer(re.escape(marker), text):
            hits.append((hit.start(), f"候选方案标记「{marker}」"))
    for hit in _OPTION_ENUM_PATTERN.finditer(text):
        hits.append((hit.start(), f"候选方案枚举「({hit.group(1)})」"))

    for pos, what in hits:
        window = text[max(0, pos - _WINDOW) : pos + _WINDOW]
        if not any(m in window for m in _VERIFICATION_MARKERS):
            line = text[:pos].count("\n") + 1
            problems.append(
                f":{line} 出现{what}，但附近 {_WINDOW} 字符内没有「已验证/未验证」类标注"
                f" ⇒ 会暗示各方案同等可行（(z78) 的教训：我把一个原理上不可行的方案列成了可选项）"
            )
    return problems


def check_requirement_kind(text: str) -> list[str]:
    """「必须 X」是否区分了结果与机制。

    ## 只查【对产品的】硬要求，不查【对执行者的】指令

    第一版把这两种混为一谈，于是把「**你必须先用真实栈把以下四种假设区分开**」
    也报了出来 —— 那是**给执行者的操作指令**，不是产品行为要求，
    与 `(z76)`（结果 vs 机制）无关。

    ⇒ **误报会被忽略，而会被忽略的闸门等于没有** ⇒ 排除：
    - 行内出现「你」的（「你必须…」= 对执行者的指令）；
    - Markdown 标题行（`#` 开头，通常是文档结构而非产品要求）。
    """
    problems: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if "必须" not in line:
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "你" in line:
            # 「你必须 / 若你必须 / 请你必须」都是对执行者的指令，不是产品要求。
            continue
        if not re.search(r"必须[^。\n]{0,40}(拒绝|接受|返回|抛|调用|包含|不包含)", line):
            continue
        # 该行或紧邻上下文中，要说明这是「结果」还是「机制」。
        start = text.find(line)
        window = text[max(0, start - 400) : start + len(line) + 400]
        if not any(k in window for k in ("这要求的是结果", "结果还是", "由哪一层", "措辞以", "以……为准", "以…为准")):
            problems.append(
                f":{line_no} 有「必须 …」的硬要求，但没说清是【结果】还是【机制】"
                f" ⇒ 会诱导执行者实现一条不可达的路径（(z76) 的教训）：{stripped[:70]}"
            )
    return problems


def check_counts_verified(text: str) -> list[str]:
    """包内声称的「已完成/已修」类数字，是否要求执行者当场核实。"""
    problems: list[str] = []
    pattern = re.compile(r"(共\s*修|已修|本轮修了|已落地)[^。\n]{0,20}?(\d+)\s*项")
    for hit in pattern.finditer(text):
        start = hit.start()
        window = text[max(0, start - 600) : start + 600]
        if not any(k in window for k in ("以代码为准", "自己核", "不要抄", "当场", "grep", "实测", "以……为准")):
            line = text[:start].count("\n") + 1
            problems.append(
                f":{line} 声称「{hit.group(0)}」但没要求执行者自己核实 ⇒ 我可能把「在途」写成「已完成」（(z94) 的教训）"
            )
    return problems


CHECKS = (
    ("候选方案已标注验证状态", check_options_annotated),
    ("「必须 X」区分结果与机制", check_requirement_kind),
    ("声称的完成数要求当场核实", check_counts_verified),
)


def main(argv: list[str]) -> int:
    targets = [Path(a) for a in argv[1:]]
    if not targets:
        print("用法: check_task_pack.py <任务包.md> [更多任务包…]", file=sys.stderr)
        return 2

    missing = [t for t in targets if not t.is_file()]
    if missing:
        for t in missing:
            print(f"找不到文件: {t}", file=sys.stderr)
        return 2

    total = 0
    for path in targets:
        text = _read(path)
        findings: list[str] = []
        for label, check in CHECKS:
            for p in check(text):
                findings.append(f"[{label}] {p}")
        if findings:
            total += len(findings)
            print(f"\n=== {path} ===")
            for f in findings:
                print(f"  ⚠ {f}")
        else:
            print(f"✓ {path}")

    print()
    if total:
        print(f"任务包自检未通过：共 {total} 处需要补充说明。")
        print("⇒ 修好后再派发（本检查的存在理由见脚本 docstring 与 facts.md (z93)）。")
        return 1
    print(f"任务包自检通过：{len(targets)} 份，未发现问题。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
