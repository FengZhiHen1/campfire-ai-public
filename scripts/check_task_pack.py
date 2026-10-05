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

    #: "这句话是【叫你不要动】某个文件，不是叫你去改它" 的标记。
    #:
    #: ⚠ 为什么需要它（`(z204)`，第四个误报类，**而且它把方向判反了**）：
    #: T27 的 §第 0 步 写「**不要去改**提示词里的业务内容（`apps/api/skills/**` 的 skill 正文）」
    #: —— 那是**明令禁止**，而被判成"点名了但没授权"。
    #: **⇒ 前三种误报是"把不是改动对象的当成改动对象"；这一种是"把禁止当成了要求"。**
    forbidden_markers = ("不要碰", "不要去改", "不要改", "禁止", "不得修改", "不能改", "不要动")

    #: "这句话是【叫你去运行】某个脚本，不是叫你去改它" 的标记。
    #:
    #: ⚠ 为什么还需要它（`(z204)`，本检查的第三个误报类）：T31 的 §第 4 步 写
    #: 「`uv run python scripts/check_design_docs.py` / 前端 `lint`+`typecheck`…」——
    #: 那是**门禁命令**，而 `scripts/check_design_docs.py` 是**仓库既有的脚本**，
    #: 执行者只是**运行**它，**根本不在本包的授权范围内**（也不该在）。
    #: **⇒ 只看路径不看【那行的谓语】，必然把"运行"也当成"改"。**
    run_only_markers = ("uv run", "python -m", "pytest", "pnpm", "npm run", "运行", "跑一次", "命令")

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
        # 没有授权范围节。**⚠ 这里刻意仍然【不报问题】**，但理由要说清（P2-2）：
        #
        # ① 存量任务包大多没有这一节（T01–T26 共 31 份里只有 T13 有）——那是本仓
        #    早期写法，不是缺陷。若把"没有授权节"判成问题，会对全部旧包误伤；
        # ② **但"静默跳过"这个形态本身是危险的**：它会让本检查在旧包上恒绿，
        #    而"恒绿"与"检查通过"读数完全一样（`(z155)`：载体在 ≠ 使它成立的东西在）。
        #
        # 处置：**不再静默返回空**（见 `_undecidable_notices`：main 会把它印成
        #     `·` 提示、**不计入 findings、不改变退出码**）。
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
    #: 授权节里以【裸目录】形式给出的路径（`apps/api/src/campfire/surfaces/consult/`）——
    #: 既没有扩展名、也没有 `/**`，**`path_re` 抽不出它** ⇒ 它覆盖的文件会被误报
    #: （`(z204)` 的第六个漏法）。这里单独扫一遍，与 `scope_globs` 同样处理。
    #: ⚠ 只认【以 `/` 结尾】的写法：不带尾斜杠时无法区分"目录"与"文件"，不做猜测
    #: （宁可不豁免，也不要凭空放宽 —— 放宽会让检查变成恒绿）。
    dir_re = re.compile(r"`?((?:apps|scripts|infrastructure|docs)/[\w./\-]+/)`?")
    scope_dirs = dir_re.findall(scope_text)
    #: 授权里写"相应的测试文件"这类统称时，放开对 test_*.py 的检查。
    tests_blanket = any(k in scope_text for k in ("相应的测试文件", "对应测试", "及其测试"))

    #: 正文 = **除授权范围节以外的全文**，而不是"授权节之前的那部分"。
    #:
    #: ⚠ 为什么（`(z204)` 的第四个漏法）：第一版取 `lines[:scope_start]` ⇒
    #: **若任务包把 §授权范围 写在正文【之前】，正文就变成空串 ⇒ 检查恒绿**
    #: （"授权节在正文之前"是一种完全正常的排版）。
    #: ⇒ 正确做法是"挖掉授权节这一块"，而不是"取它之前的那一块"。
    body_lines_all = lines[:scope_start] + lines[scope_end:]
    body_text = "\n".join(body_lines_all)
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
        # 裸目录豁免：授权以 `…/consult/` 形式覆盖时，它的子文件都算已授权。
        if any(path.startswith(d) for d in scope_dirs):
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
        # 禁止豁免：该路径出现在「不要碰 / 不要去改」的语境里 ⇒ 它是在说"别动它"，
        # 而不是"你得改它"。
        # ⚠ 为什么需要（`(z204)` 实测）：T27 的 §第 0 步 写
        # 「**不要去改**提示词里的业务内容（`apps/api/skills/**` 的 skill 正文）」——
        # 那是**明令禁止**，而被第一版判成"点名了但没授权"（**方向完全判反**）。
        if any(m in window for m in forbidden_markers):
            continue
        # 运行豁免：该路径是用门禁命令点名的（`uv run python scripts/…` 之类），
        # 说明这是叫执行者去**运行**它，不是去**改**它。
        if any(m in window for m in run_only_markers):
            continue
        problems.append(
            f":{line_no} 正文点名了 `{path}`，但它不在 §授权范围里 "
            f"⇒ 执行者会面临「照正文做 = 越界 / 照清单做 = 没完成」的两难（(z161) 的教训）"
        )

    # ⑦ 同一文件同时出现在「你可以改」与「不要碰」两处 ⇒ 任务包自相矛盾
    #    （`(z204)` 的第七个漏法）。这与第 4 项是【不同的失败】：
    #    第 4 项管"正文说了、授权没说"；这一项管"授权自己说了两遍且互斥"。
    #    ⚠ 它比第 4 项更隐蔽：执行者照哪一句做都能被另一句判成越界。
    #
    # ⚠ 做法必须【按行就近判定】，不能"先切出一段 allowed、再切一段 forbidden"
    #    —— 第一版那样做，实测在 T29 上误报：T29 的授权是一张**表格**，
    #    `授权范围` 一词出现在表格行里（不是标题）⇒ `scope_end` 取到了文件末尾
    #    ⇒ 后面的「环境/硬约束/报告」几节全被并进 forbidden 段 ⇒
    #    同一个 `test_check_task_pack.py`（在表格里是"可改"，在报告节里是"跑一下"）
    #    被误判成自相矛盾。**⇒ 局部判定天然免疫这种段落切分错误。**
    allowed_hits: dict[str, int] = {}
    forbidden_hits: dict[str, int] = {}
    for idx in range(scope_start, scope_end):
        line = lines[idx]
        negated = any(m in line for m in forbidden_markers)
        for p in path_re.findall(line):
            (forbidden_hits if negated else allowed_hits).setdefault(p, idx + 1)
    for fpath in sorted(set(allowed_hits) & set(forbidden_hits)):
        problems.append(
            f"`{fpath}` 同时出现在「可以改」(:{allowed_hits[fpath]}) 与「不要碰」"
            f"(:{forbidden_hits[fpath]}) 两处 ⇒ 任务包自相矛盾，执行者照哪一句做都会被"
            f"另一句判成越界。请明确它到底能不能改（(z204) 第七个漏法）"
        )
    return problems


def _undecidable_notices(text: str) -> list[str]:
    """本检查**判不了**的情形 —— 印成提示，但既不计入 findings 也不改退出码。

    ⚠ 存在的理由（`(z204)` 的第五个漏法）：`check_scope_matches_body` 在
    「没有 §授权范围 节」时**静默返回空** ⇒ 检查在该包上**恒绿**，
    而**"恒绿"与"检查通过"的读数完全一样**（`(z155)`：载体在 ≠ 使它成立的东西在）。

    ⚠ 但**不能判成失败**：本仓 T01–T26 的任务包大多没有这一节（37 份里 26 份没有），
    那是早期写法、不是缺陷 ⇒ 判失败会大面积误伤存量。

    ⇒ 所以取中间态：**让"判不了"这件事可见**（打印 `·` 行），
    **但不改变退出码**，并在结尾明确告诉使用者"若这是新包请补上授权范围"。
    """
    if any(m in text for m in _SCOPE_MARKERS):
        return []
    if not any(m in text for m in _BODY_MARKERS):
        # 不是任务包（没有正文标记）⇒ 沉默，不对随手笔记报提示。
        return []
    return [
        "缺少 §授权范围 节 ⇒ 「正文点名的文件都在授权范围内」这一项【判不了】"
        "（不是失败）。若这是新任务包，请补上授权范围——否则正文与授权清单无从对照（(z161) 的教训）。"
    ]


#: 模块级副本：`_undecidable_notices` 需要在不构造检查闭包的情况下拿到这两个标记集
#: （它们原本定义在 `make_check` 内部）。**两份必须一致** —— 下方有单测钉住这一点。
_SCOPE_MARKERS = ("授权范围", "你可以改")
_BODY_MARKERS = ("要做的", "你要做", "修法", "第 0 步", "第 1 步")


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
    notices_total = 0
    for path in targets:
        text = _read(path)
        findings: list[str] = []
        for label, check in CHECKS:
            for p in check(text):
                findings.append(f"[{label}] {p}")
        notices = _undecidable_notices(text)
        if findings or notices:
            print(f"\n=== {path} ===")
            for f in findings:
                print(f"  ⚠ {f}")
            for n in notices:
                print(f"  · {n}")
        if findings:
            total += len(findings)
        if notices:
            notices_total += len(notices)
        if not findings and not notices:
            print(f"✓ {path}")

    print()
    if total:
        print(f"任务包自检未通过：共 {total} 处需要补充说明。")
        print("⇒ 修好后再派发（本检查的存在理由见脚本 docstring 与 facts.md (z93)）。")
        return 1
    if notices_total:
        print(f"任务包自检通过（{len(targets)} 份），但有 {notices_total} 条【无法判】提示 —— 见上方 `·` 行。")
        print("⇒ 「无法判」不是失败：旧任务包多为这种写法（本仓早期无 §授权范围 节）。")
        print("⇒ 但若你正要派发一份新包，请补上授权范围，否则第 4 项检查对它无效。")
        return 0
    print(f"任务包自检通过：{len(targets)} 份，未发现问题。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
