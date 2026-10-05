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


def check_scope_matches_body(text: str) -> list[str]:
    """§"要做什么"里点名的代码文件，是否都出现在 §"授权范围"里。

    ## 为什么加这一条（它来自一次真实的失败，`(z161)`）

    T27 的任务包里，§三之二（要做什么）**明确要求改** `tools/memory.py` 与
    `agent/runtime/runner.py`（我引了它们的代码行、给了判据），
    而 §五（授权范围）**没有列这两个文件** ——
    **⇒ 执行者面临两难：照正文做 = 越界；照清单做 = 没完成。**
    **它选了"照正文做且不碰硬禁区"（正确），但这是靠它的判断力兜住的，不是靠任务包。**

    **⇒ 本检查把那条纪律变成会失败的检查。**

    ## 判定方式（保守，只报"正文点名了但授权里没有"）

    1. 从 §"要做什么/修法/判据"这类正文里抽出**形如代码路径**的串
       （`apps/...`、`scripts/...`、`infrastructure/...`，含反引号包裹）；
    2. 从 §"授权范围"里抽出同样的串（含通配写法 `apps/web/src/features/consult/**`）；
    3. **正文里有、授权里没有（且不被任何通配覆盖）⇒ 报问题。**

    ## ⚠ 边界（它防得住什么、防不住什么）

    - **防得住**：我漏列一个正文点名的文件（T27 那种）；
    - **防不住**：① 我**两边都漏**（正文没点名、授权也没有，而实际需要改）；
      ② 路径写得不成形状（如只写"那个文件"）⇒ 抽不出来；
      ③ 正文里提到某文件只是**作为现状描述**（不是"要改它"）⇒ 会误报。
    **⇒ 因此它报出来的是【待人工确认】，不是"必须改"** ——
    但对第 ③ 种情况，**正确做法是在正文里写清"该文件只读"**，那也算本检查的收益。
    """
    problems: list[str] = []

    #: 代码路径的形态：以这些前缀开头、可含通配。
    #:
    #: ⚠ 两处必须同时支持（记一次真实的失败，本检查第一版漏了它们、于是【误报】了 T28）：
    #: ① **带扩展名的具体文件**：`apps/.../answers.py`；
    #: ② **以 `/**` 结尾的通配**：`apps/api/src/campfire/surfaces/consult/**` ——
    #:    第一版的正则要求"以扩展名结尾"，**于是通配写法抽不出来** ⇒
    #:    `scope_globs` 恒空 ⇒ **通配覆盖失效** ⇒ 把被通配覆盖的文件误报成"不在授权里"。
    path_re = re.compile(
        r"`?((?:apps|scripts|infrastructure|docs)/[\w./\-*]+?"
        r"(?:/\*\*|\.(?:py|ts|tsx|md|conf|yml|yaml|sh)))`?"
    )

    #: "这句话只是【叫你去读】某个文件，不是叫你去改它" 的标记。
    #:
    #: ⚠ 为什么需要它（同一个失败的另一半）：T28 正文里写
    #: 「**先读** `docs/技术设计/…HTTP与SSE契约.md` 与通用基座 7.2 节」——
    #: 那是**只读**指引，而被第一版判成"点名了但没授权"。
    #: **⇒ 只看路径不看动词，必然把"读"当成"改"。**
    read_only_markers = ("先读", "只读", "读一下", "参见", "见 `", "依据", "参考")

    #: 找 §"要做什么"这一段的起点标记（本仓任务包的既有写法）。
    body_markers = ("要做的", "你要做", "修法", "第 0 步", "第 1 步")
    scope_markers = ("授权范围", "你可以改")

    lines = text.splitlines()
    scope_start = None
    for i, line in enumerate(lines):
        if any(m in line for m in scope_markers):
            scope_start = i
            break
    if scope_start is None:
        # 没有授权范围节 ⇒ 这一条无法判（不报问题，避免对旧任务包误伤）。
        return problems

    # 授权范围一直到下一个同级或更高级标题为止。
    scope_end = len(lines)
    scope_heading = len(lines[scope_start]) - len(lines[scope_start].lstrip("#"))
    for j in range(scope_start + 1, len(lines)):
        s = lines[j]
        if s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            if level <= scope_heading and s.strip():
                scope_end = j
                break
    scope_text = "\n".join(lines[scope_start:scope_end])
    scope_paths = set(path_re.findall(scope_text))

    # 通配前缀（如 apps/web/src/features/consult/**）⇒ 它能覆盖的子路径。
    scope_globs = [p[:-3] for p in scope_paths if p.endswith("/**")]
    #: 授权里写"相应的测试文件"这类统称时，放开对 test_*.py 的检查。
    tests_blanket = any(k in scope_text for k in ("相应的测试文件", "对应测试", "及其测试"))

    body_text = "\n".join(lines[:scope_start])
    seen: set[str] = set()
    body_lines = body_text.splitlines()
    for hit in path_re.finditer(body_text):
        path = hit.group(1)
        if path in seen:
            continue
        seen.add(path)
        if path in scope_paths:
            continue
        if any(path.startswith(g) for g in scope_globs):
            continue
        # 测试文件的统称豁免（正文常写 `test_x.py` 而授权写"相应的测试文件"）。
        name = path.rsplit("/", 1)[-1]
        if tests_blanket and name.startswith("test_"):
            continue
        if not any(m in body_text for m in body_markers):
            continue
        # 只读豁免：该路径所在的那一行（加前后各一行）里若有"先读/参见"类词，
        # 说明这是叫执行者去**看**它，不是去**改**它。
        line_no = body_text[: hit.start()].count("\n") + 1
        window_lines = body_lines[max(0, line_no - 2) : line_no + 1]
        window = "\n".join(window_lines)
        if any(m in window for m in read_only_markers):
            continue
        problems.append(
            f":{line_no} 正文点名了 `{path}`，但它不在 §授权范围里 "
            f"⇒ 执行者会面临「照正文做 = 越界 / 照清单做 = 没完成」的两难（(z161) 的教训）"
        )
    return problems


CHECKS = (
    ("候选方案已标注验证状态", check_options_annotated),
    ("「必须 X」区分结果与机制", check_requirement_kind),
    ("声称的完成数要求当场核实", check_counts_verified),
    ("正文点名的文件都在授权范围内", check_scope_matches_body),
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
