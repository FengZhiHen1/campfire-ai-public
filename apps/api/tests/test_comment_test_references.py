"""注释点名的测试必须真的存在。

职责：扫描 `apps/api/src/campfire/**` 与 `apps/api/tests/**` 的注释与 docstring，
取出其中点名的测试，逐条核对它真的存在——文件名的情形核对那个文件在
`apps/api/tests/` 下存在，裸名的情形按 AST 在 `apps/api/tests/**` 里查找同名 `def`。

为什么不并进 `test_layer_boundaries.py`：那个文件的覆盖范围已经写死为
docs/项目结构设计.md 第 7 节那张表的机械化（依赖白名单 + 基座禁项），本文件守的是
注释与测试之间的一致性。两者的问题域、失效方式与「什么改动该同步哪条检查」都不同，
混在一起会让范围变得看不出来。

本仓这一族缺陷的来源是同一个形状：注释声称「有某条测试守住这个性质」，而那条测试
根本不存在，于是注释承诺的性质实际无人守——排查时又看不出差别，因为注释读起来是
自足的。此前只靠人工逐个核对，核对完不留任何机械约束，所以反复复发。

**2026-10-02 扩面**：扫描根原先只有 `src/campfire`，而「本用例只验证一半，另一半由
`test_xxx.py` 覆盖」这种写法在**测试文件自己**里同样常见——同一个形态在测试侧无人拦。
扩面后它一次抓出多处失效引用（其中两处既是失效引用，又反过来对**图库那一半的覆盖**
作了不成立的承诺）。

纳入的写法（按本仓实际出现过的形态收集，样例见
`test_comment_test_reference_guard_detects_its_patterns`）：

- 带路径的测试文件：`apps/api/tests/test_x.py`、`tests/test_x.py`；
- 裸文件名的测试文件：`test_x.py`；
- 测试基建文件：`conftest.py`（带 `tests/` 段的写法与裸文件名都算）；
- 裸名：`test_x`。`tests/test_y.py::test_x` 里的用例名按裸名处理，前面的文件另算一条。

不覆盖的部分（诚实声明）：

- 只写「有测试断言」「由集成测试守护」而不点名的引用：没有名字可核；
- 不带 `.py` 的裸 `conftest`（本仓 `modules/library/embedding.py` 有这种措辞）：那是
  散文式提及而不是文件点名，纳入等于把陈述当成承诺；
- 通配与省略（本仓真有 `test_library_*_integration`、`test_memory_*` 与
  `test_hydration_...sdk...` 这类写法）：没有确定的文件名可核，纳入等于把「一类测试」
  当成「一条测试」。判据是紧跟在裸名之后的 `*` 或 `...`，是机械可辨的形状而不是对
  「名字看起来像不像占位」的猜测；
- **`~~…~~` 撤回区里的名字**（`_WITHDRAWN_PAIR`）：本仓订正范式要求旧句**划掉而不是
  静默删掉**，而旧句里的名字按事实就是错的。若不跳过，「如实保留旧句」与「注释不得
  点名不存在的测试」会正面冲突，把后来人逼回静默删除。**⚠ 界定刻意保守：只认同行
  成对的 `~~`**（本仓 `agent/runtime/runner.py` 与 `modules/profile/routes.py` 的
  撤回标记合此口径）；**跨行划线段不豁免**，代价是一个漏写的闭合 `~~` 只影响一行而不是吞掉
  整个 docstring。配套：`~~` 计数为奇数（未闭合）**报红**，不当作「一直撤回到底」；
  且此时区内的名字**仍然**被核对（fail-safe 方向）；
- **⚠ 真实盲区：只扫 `#` 注释与 `body[0]` docstring，其余位置的字符串字面量【不在
  扫描面】**。`_docstring_units` 只收「节点的第一个语句是字符串」那种 docstring，
  因此**赋值之后的 PEP 258 属性文档字符串**（如
  `modules/accounts/session_items.py` 里 `MessagePart = …` 之后那一大段说明）
  **整段不会被读到**。本仓这类字面量有相当数量（`src` 侧数量级为百），
  **但具体条数不写死**，理由是**两条独立的**：
  ①**口径本身不唯一**——「算不算本文件自身」会给出不同读数
  （本文件自身的属性文档字符串也是盲区，而它不参与扫描）；
  ②**仓库在演进**，任何写死的数字都会过期。
  **⇒ 所以本声明不引用任何数字，只引用下面这条可复算的检查**：
  跑 `uv run pytest apps/api/tests/test_comment_test_references.py -q`，
  其中的 `test_blind_spot_is_non_empty_and_has_no_broken_reference` 会**按代码里那一个口径**
  实时重算盲区：它断言①盲区非空（为 0 则说明本声明已过期、须删改）、
  ②**盲区里不得藏着失效引用**（盲区不核对 ⇒ 天然能藏缺陷，故至少要做一次只读体检）。
  **⇒ 这是「已知未覆盖」，不是「已被核对」**：本包对 `session_items.py` 那两处跨行
  划线段**没有**机械保护，靠的是人工核对。把这块纳入扫描面会显著扩大假阳性面
  （属性文档字符串本仓大量存在，散文式提及会被当成点名），故本包**只登记不扩面**；
  **另有「反例五」**钉住扫描面本身：属性文档字符串不被扫到 ⇒
  若谁扩大了扫描面，那条断言会失败，逼其同步改声明；
- **本文件自己不参与扫描**（`_SELF_PATH`）：它的这份 docstring 要用 `test_x.py` 这类
  占位名演示「哪些写法算引用」，而占位名按设计就不存在。这是**一处明确的豁免，不是
  一条规则**——豁免面由 `test_comment_named_tests_exist` 里的断言钉死（只许这一个
  文件被跳过，多一个就判红）。**代价**：本文件 docstring 里对真实测试的点名同样不再
  被核对；
- **点名一个已被删除或替换的旧用例名且未划掉**：本仓 `test_agent_model.py` 有「这条
  替换了原先的 `test_...`」这种**记录历史**的写法，而旧名按事实确实不存在。本规则
  分不开「记录历史」与「声称覆盖」，两者都会判红——判红之后由人决定是改措辞还是划掉。
  **⚠ 这不构成盲区**：正确的处置是**把旧名划进 `~~…~~`（撤回）并把事实写进订正说明**，
  而不是让守卫去猜哪句是历史；本包那 5 处失效引用就是这样处理的；
- 名字存在不等于那条守卫真的钉住了注释声称的性质。D-68 的原始形态是「点名了一个真实
  存在的测试文件，而该文件里根本没有这条守卫」——机器只能证明名字在，证明不了断言在。
  本文件拦的是「名字不存在」那一半，另一半仍归人工核对与评审；
- 被点名的测试是否真在跑（`skip` / `xfail` 的用例同样算存在），也不在覆盖范围。
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "campfire"
TESTS_ROOT = Path(__file__).resolve().parent
_SELF_PATH = Path(__file__).resolve()
"""本文件自己：扫描面里唯一被豁免的文件，理由与代价见模块 docstring 的诚实声明。"""

_PY_PATH = re.compile(r"[A-Za-z0-9_./\\-]+\.py")
"""注释里的 `.py` 路径或文件名。先整段认出来，再判它是不是测试侧的文件。"""

_TESTS_SEGMENT = re.compile(r"(?:^|/)tests/")
"""`tests` 必须是完整的路径段：`ml_tests/` 这类同后缀目录不算。"""

_TEST_FILE_STEM = re.compile(r"\Atest_[A-Za-z0-9_]+\Z")
"""测试文件名主干：`test_` 开头。比对的是去掉 `.py` 之后的那一段。"""

_TEST_INFRA_FILE_NAMES = frozenset({"conftest.py"})
"""不带 `test_` 前缀但确属测试侧的文件名。"""

_TEST_NAME = re.compile(r"(?<![A-Za-z0-9_./])test_[A-Za-z0-9_]+")
"""裸测试名。

开头的否定前视是这条规则的要点：`latest_bound_object_id` 的后半段正好是
`test_bound_object_id`（本仓 `modules/profile/repository.py` 真有这个函数），按子串
匹配会把它当成点名了一条测试。判据取「整词的边界」而不是「出现过这个子串」，这与
`test_layer_boundaries.py` 里「`build_vector_store` 是函数不是模块」的处理同一口径
——标识符与子串的形状相同，只能按事实与边界分辨。
"""

_KIND_LABELS = {"file": "文件引用", "bare": "裸名引用"}

_CORRECTION_MARK = re.compile(r"订正")
"""本仓订正说明的标记：**`订正` 两个字**。

**⚠ 这里曾经只认字面量 `⇒ 已订正`，那是个实测出来的漏洞**：本仓真实的订正说明有多种写法
（`⚠ 2026-10-06 订正`、`如实订正一句曾写错的断言`、`## 2026-10-06 订正` …），
`⇒ 已订正` 只是其中一支。只认那一支，生产树里含 `订正` 的 **11** 个文件中，
旧口径（`⇒ 已订正`）只覆盖其中 **2** 个 ⇒ **实际漏掉 9 个**（含
`surfaces/consult/assembly.py` 那条真缺陷）；而规则的 docstring 当时却自称
「扫全部含订正标记的文件」。**⇒ 自称与实际不符，已改为一律认 `订正`。**

**⚠ 计数口径**（与 `test_correction_notes_state_their_evidence` 的「标记」条**同源同值**，
两处必须一起改）：两句话说的是**同一件事**——「11 个」是**含标记的文件总数**，
**不是**「被规则漏掉的文件数」；漏掉的只有 **9 个**。
**⇒ 上一版本处写「让整整 11 个生产文件落在规则之外」，把总数当成了漏数，是逐字不准的。**
"""

_REPO_ABSENCE = re.compile(
    r"全仓[^。\n]{0,12}(?:没有|不存在|零|未)"
    r"|任何提交[^。\n]{0,12}(?:没有|未|不)"
    r"|从未作为[^。\n]{0,8}存在"
    r"|从未存在过"
    r"|从不存在"
    r"|从未被定义"
    r"|从未定义"
)
"""关于【仓库/历史】的全称否定。

**为什么必须限定「仓库/历史」而不是所有全称否定**（实测的依据）：宽松版会命中大量
**行为陈述**——本仓真有「没有任何提示或非零退出码」「使用者此后没有任何入口回到引导」
「从未往下传」这类句子，它们说的是**运行时行为**，不是「我核过仓库」。
要求它们引 git 命令是**假阳性**。⇒ 只收「断言对象是仓库/历史」的形状。

**⚠ 裸 `零命中` 已从这里移出**（本包第 6 轮）：`零命中` 是**读数**措辞，**运行时行为也用它**
（「候选集零命中时返回空列表」是行为陈述，不涉及仓库/历史）。它现在改由
`_repo_absence_in` 处理——**必须与仓库/历史语汇同句共现**才算。

**⚠ 这仍是黑名单式的形状匹配，不是完备的语义判定**：换一种全新措辞（例如
「整个代码库里搜不到」）不会被它认出来。它的价值是**把这一类里常见的写法钉住**，
不能读成「本文件已覆盖全部全称否定」。
"""

_REPO_WORDS = re.compile(r"git|grep|commit|提交|历史|仓库|代码库|全仓|仓内|pathspec")
"""仓库/历史语汇：用来判一句「零命中」说的是不是**仓库层面**的事。"""

_ZERO_HITS = re.compile(r"零命中")
"""读数措辞，**只在仓库语境下**才算全称否定（见 `_repo_absence_in`）。"""

_SENTENCE_SPLIT = re.compile(r"[。；;\n]")
"""句边界：同句共现才判「仓库层面」，避免跨句张冠李戴。"""


def _repo_absence_in(fragment: str) -> bool:
    """该片段里是否有一句「关于仓库/历史的」全称否定。

    两条路取并集：① 命中 `_REPO_ABSENCE` 的强形状；② **同一句**里既有 `零命中`
    这样的读数措辞、又有仓库/历史语汇。
    ② 的必要性有实证：本仓有「候选集零命中时返回空列表」这类**行为陈述**，
    裸 `零命中` 会把它误判成「核过仓库」的断言（本包实测过这条误伤）。
    """
    if _REPO_ABSENCE.search(fragment):
        return True
    return any(_ZERO_HITS.search(s) and _REPO_WORDS.search(s) for s in _SENTENCE_SPLIT.split(fragment))


_GIT_COMMAND = re.compile(r"`git (?:log|grep|show|blame)\b\s+\S[^`]*`")
"""反引号包起来、且**至少带一个真参数**的 git 命令：子命令必须是
`log`/`grep`/`show`/`blame` 之一，其后紧跟空白与**至少一个非空白字符**。

**「至少一个真参数」的判据是 `\\s+\\S`**（先空白、再非空白）：参数的定义里不含空白，
故判据必须要求一个**非空白字符**。**实测两版差异**（本包第 7 轮）：
`\\s+[^`]+` 与 `\\s+\\S[^`]*` 在**单个尾随空白**上读数相同（两者都挡住 `` `git log ` ``），
差别只在**连续 2 个以上空白**——`\\s+[^`]+` 会把 `` `git log  ` ``（无任何实参）
当成「有参数」。**⇒ 收严到 `\\s+\\S` 正是为了堵这一种。**

**判据只要求「有参数」，不判「参数够不够」**——这是本规则的能力边界，不是疏漏。

**⚠ 本判据不足以支撑「某名字全仓不存在」这类全称否定**（如实登记，勿读成已覆盖）：

- 一条**语法上有参数**的命令仍可能**撑不起**它旁边那句断言：实测反例是
  `` `git log --all --diff-filter=A` ``（缺 pathspec）——它命中的是**全仓所有新增文件**、
  读数随历史单调增长（本包实测当前 **392** 个提交），**永远不可能为 0**，
  却完全合本判据；
- 本守卫**不执行 git**，只读文本形状 ⇒ 「参数是真是假」「读数是否为 0」**机器判不了**
  （理由见 `test_correction_notes_state_their_evidence` 的「为什么不执行 git」）。
  ⇒ **凡本文件引用本判据，都不得据它宣称「某名字全仓不存在」已被核实。**

**⚠ 这里曾经「文档说有、行为没有」（本包第 7 轮修的假话）**：上一版 docstring 自称
「且带实际参数」，而正则末段是 `[^`]*`（**对参数零要求**）⇒ 裸 `` `git log` ``／
`` `git show` ``／`` `git grep` ``／`` `git blame` `` **全部放行**，其中**裸 `` `git log` ``
正是同一段文档下一句点名「撑不起」的形态**——判据的定义文档与判据的行为**同屏互相打脸**。
**⇒ 现已同时收紧两侧**：正则要求子命令名**且**至少一个**非空白**参数（裸命令与
「只有尾随空白」的形态实测全部挡住，见 `test_correction_note_rule_is_not_vacuous`
的样本表），docstring 也改成如实描述。

**⚠ 收紧了正则也不改变上面那条能力边界**：挡住裸命令只堵住「零参数」这一种弱形态，
「有参数但撑不起断言」这一族（上面第一条）**原样存在**。
**⇒ 这一族仍登记在 `test_correction_notes_state_their_evidence` 的「仍会漏的」表里。**
"""

_CASE_LEVEL_ABSENCE = re.compile(r"用例|def |定义过|被定义")
"""**用例层面**的「不存在」断言（「这条**用例**从未被定义过」）。

**为什么需要区分层面**：`git log --all -- '<glob>'`（路径型）只能证明**没有文件被创建**，
证明不了「这条用例从未被定义过」——名字完全可能只作为**注释文本**出现在某个提交里
（本包那两处正是如此：写出坏引用的那个提交本身命中了 `-S`，但路径型为空）。
**⇒ 路径型撑不住用例层面的断言**，故用例层面的断言**必须引带 `def` 的 `-S`**。

**⚠ 判据只取「显式的层面词」**（`用例` / `def ` / `定义过` / `被定义`），
**刻意不再用读数措辞**（`零命中` / `命中.*0` / `为 0`）去猜层面：
同一个读数措辞**两个层面都用**，用它外推层面会把真话判成违规。
**⇒ 层面必须由断言自己的说法决定，不能由读数形状外推。**

**⚠⚠ 这里有一段纠正记录（本包第 6 轮）**：上一版这段曾举
`surfaces/consult/assembly.py` 的「`git log --all --diff-filter=A` 零命中」
作为「文件层面 + 正确命令 ⇒ 完全成立」的**真话范例**，并据此论证「不该要求更强的命令」。
**⇒ 那个范例是错的，实测：**
```
git log --all --diff-filter=A                        ⇒ 390 个提交（不是「零命中」）
git log --all --diff-filter=A -- '*consult_output_format*'  ⇒ 0 个提交（带 pathspec 才成立）
```
**那条命令【没有 pathspec】⇒ 命中的是全仓所有新增文件，永远不可能为 0**
（该块由 `9354171` 引入，命令随历史单调增长）⇒ **它从来不是真话**。
**⇒ 即：我用一条撑不起断言的命令，去为「放宽判据」做辩护。**这是本包第六次同源错误，
且比前五次更隐蔽——**前五次在【产品文本】里，这一次在【守卫自己的辩护理由】里**。
**⇒ 现在的范例换成了真的成立的形态（见下方「层面不能由读数外推」的自测），
并把 `assembly.py:61-62` 那处【登记为产品文本里的已知缺陷】而不是范例**
（它在 `apps/api/src/` 下，**不在本包的授权改动范围内**，故只能登记，不能改）。
"""

_DEF_COMMAND = re.compile(r"`git [^`]*-S[^`]*def ")
"""命令强度的判据：带 `def` 前缀的 `-S`。

只有它能撑「某条**用例**从未被定义过」这种断言——路径型撑不了（见
`_CASE_LEVEL_ABSENCE` 的说明）。
"""

_PY_LINE_REF = re.compile(r"[A-Za-z0-9_./\\-]+\.py:\d+")
"""`某文件.py:行号` 形式的引用。

**为什么在订正说明里禁它**：行号随任何一次编辑腐坏，而「引用了过期的东西」与本守卫
要拦的「引用了不存在的东西」是同一族缺陷（本包就因此修正过一次）。
稳定标识是**用例名/函数名**，不是行号。
"""

_CORRECTION_TREES: tuple[tuple[str, Path], ...] = (("src/campfire", SRC_ROOT), ("apps/api/tests", TESTS_ROOT))
"""订正说明规则要扫的树：**生产与测试两棵**，单点定义。

**为什么单点定义**：上一版把「扫两棵树」写死在主循环里，而覆盖面断言**独立 rglob** 一遍
⇒ 实测「把主循环改成只扫一棵树」时那条断言**仍然全绿**（它防的是「树里没料」，
防不住「只扫一棵树」）。现在树清单由这个常量给出、并传给 `_correction_scan`，
调用方拿到的 `trees_scanned` **只能来自主循环**，判据无法与它脱钩。
"""

_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
"""可能带 docstring 的节点：模块、类、函数与方法。"""

_PY_MASK_CHAR = "."
"""屏蔽 `.py` 字面量时用的填充字符。

**不能填空格**：`conftest.pytest_configure` 里的 `conftest.py` 被屏蔽后，空格会给
`pytest_configure` 的尾巴 `test_configure` 造出一个词边界，于是散文里的一个限定名被
当成点名了一条测试（`test_production_assembly_e2e.py` 的 docstring 真有这种写法）。
填 `.` 则落在 `_TEST_NAME` 的否定前视集合 `[A-Za-z0-9_./]` 里，屏蔽区不会自己捐出边界。
"""

_WITHDRAWN_MASK_CHAR = "~"
"""屏蔽 `~~…~~` 撤回区时用的填充字符。

**⚠ 与 `_PY_MASK_CHAR` 的要求恰好相反，因此必须是两个常量**：

- 屏蔽 `.py` 字面量时，填充字符**必须落在** `_TEST_NAME` 的否定前视集内（否则捐出假名字 ⇒ 假红）；
- 屏蔽撤回区时，填充字符**必须不在**该集合内 —— 否则 `~~x~~test_foo` 里那个
  `test_foo` 会被填充字符当成前邻标识符字符而**挡住**，**漏报**一条真引用。

同一个字符不可能同时满足两条（实测：`.` 满足前者、破坏后者；其余候选反之）。
取 `~` 还有第二个好处：它**不在** `_PY_PATH` 的字符类里，所以填充不会延伸或新造
`.py` 词元；而它就**是本标记自己的字符**（`~~`），填成它等于「这里仍是标记」，
对两侧的词边界影响最小。
"""

_ELISION_MARKS = ("*", "...")
"""紧跟在裸名之后的通配/省略号：这类写法指「一类测试」，不是点名一条测试。"""

_WITHDRAWN_PAIR = re.compile(r"~~[^\n]*?~~")
"""本仓的「已撤回」标记：**一行之内的一对** `~~…~~`（非贪婪，不含换行）。

**为什么不核对撤回区里的名字**：本仓订正范式（见 `modules/profile/routes.py` 的 `#:` 注释、
`agent/runtime/runner.py` 的模块 docstring、`modules/accounts/session_items.py` 的属性文档
字符串）要求**旧句划掉而不是静默删掉**，紧跟「⇒ 已订正（日期）」写明事实。而旧句里那个
名字**按事实就是错的**——若不跳过撤回区，「如实保留旧句」与「注释不得点名不存在的测试」
这两条纪律会正面冲突，把后来人逼回静默删除，而那正是订正范式要防的事。

**⚠ 两个界定都是刻意的，各防一种坏结果**：

1. **只认同一行内**：跨行匹配的代价是**一个漏写的闭合 `~~` 会吞掉其后整个 docstring**，
   把一个局部豁免变成大面积盲区；同行界定让失配的后果**封顶在一行**，
   也正合本仓实际写法（`agent/runtime/runner.py` 的模块 docstring、
   `modules/profile/routes.py` 的 `#:` 注释都是同行成对）；
2. **逐对替换而不是逐行整行替换**：同一行里若有两对 `~~`，整行替换会把两对外侧之间那段
   **未被撤回的文字也吞掉** ⇒ **漏报**（比假红更坏）。逐对让屏蔽范围**恰好等于撤回区**。

**⚠ 一处必须说清的先后关系（否则会读出一句不成立的话）**：本仓**另有**两处**跨行**划线段
（在 `modules/accounts/session_items.py`：一处跨 6 行、一处跨 2 行），
它们**根本不在本守卫的扫描面内**
—— 那段是 `MessagePart` 赋值之后的 **PEP 258 属性文档字符串**，
不是任何节点的 `body[0]`（见模块 docstring 的盲区声明）。
**⇒ 因此「跨行不豁免」这条界定对它们不产生任何实际效果**：
本包真正的处置是**在订正说明里不重复那个旧名**，**不是**指望守卫去核对它。
**不要把这条界定读成「跨行划线段已被核对」—— 它连扫都没扫到。**
**⚠ 这里刻意不写行号**：`session_items.py` 正被别的包持续编辑，
行号每改一次就腐坏一次（本包就因此修正过一次）；**写行号是把「过期引用」
请回来，而那正是本守卫在拦的那一族缺陷。**

`_UNPAIRED_WITHDRAWN` 是配套：撤回标记计数为奇数说明**有未闭合的 `~~`**，
那是畸形标记而不是「一直撤回到底」，应当报红让人去修，不得静默当成豁免。
"""

_UNPAIRED_WITHDRAWN = re.compile(r"~~")
"""数 `~~` 出现次数用；配合 `_mask_withdrawn` 判畸形的未闭合标记。"""


class _TestReference(NamedTuple):
    """生产代码注释里点名的一处测试引用。"""

    line: int
    kind: str
    name: str


def _test_file_reference(token: str) -> str | None:
    """`.py` 字面量若是测试侧文件，返回它在 `tests/` 下的相对路径，否则 None。

    判据有两路，取并集：文件名主干以 `test_` 开头，或写入的路径里有一段完整的
    `tests/`（`conftest.py` 这类不带 `test_` 前缀的测试基建文件由此纳入）。
    """
    normalized = token.replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1]
    if (
        _TEST_FILE_STEM.match(basename.removesuffix(".py")) is None
        and basename not in _TEST_INFRA_FILE_NAMES
        and _TESTS_SEGMENT.search(normalized) is None
    ):
        return None
    segment = _TESTS_SEGMENT.search(normalized)
    return normalized[segment.end() :] if segment else basename


def _is_elided(text: str, end: int) -> bool:
    """裸名在 `end` 处结束后紧跟通配或省略号 ⇒ 它是一类测试的写法，不是一次点名。"""
    return any(text.startswith(mark, end) for mark in _ELISION_MARKS)


def _mask_withdrawn(text: str) -> str:
    """把**同一行内、逐对**的 `~~…~~` 撤回区清空，换行原样保留，行号因此不漂移。

    用 `_WITHDRAWN_MASK_CHAR` 填充（理由见该常量：撤回区**不能**用 `_PY_MASK_CHAR`
    那种落在否定前视集里的字符，否则会挡住紧跟在后的真名字 ⇒ 漏报）。
    只按**成对**替换：落单的 `~~` 不在本函数处理（它由 `_unpaired_withdrawn` 报红）。
    """
    return _WITHDRAWN_PAIR.sub(
        lambda match: "".join(_WITHDRAWN_MASK_CHAR for _ in match.group(0)),
        text,
    )


def _unpaired_withdrawn(text: str) -> bool:
    """这段文本里的 `~~` 计数为奇数 ⇒ 有未闭合的撤回标记（畸形，不是豁免）。"""
    return len(_UNPAIRED_WITHDRAWN.findall(text)) % 2 == 1


def _merged_annotations(source: str) -> list[tuple[int, str]]:
    """注释与 docstring 的文本单元，其中**行距不超过 1 行的注释行合并成一个单元**。

    **为什么需要合并**：本仓的订正说明常写成「断言在上一行、支撑它的命令在下一行」
    （`surfaces/consult/assembly.py` 就是：`:61` 说「从未存在过」、`:62` 给
    `git log --all --diff-filter=A` 零命中）。Python 的 `tokenize` 把**每一行 `#`**
    切成**独立的 COMMENT token**，于是「单元 = 单个 token」的判法会把断言与它的命令
    **拆到两个单元**里 ⇒ 规则看不见命令、**误判成「没给命令」（假红）**。

    **⚠ 窗口 = 容忍 1 行间隔**，这是实测出来的取值。**判据只看【行号差】**，
    **不问那 1 行是空行还是代码行**（两者都合并）：
    - 容忍 **0** 行（严格相邻）⇒ 断言与命令之间隔**一个空行**就看不见命令
      ⇒ 产生**假红**（本包第 6 轮实测：真实形态「断言 / 空行 / 命令」会误报）；
    - 容忍 **1** 行 ⇒ 上述形态修好；**且「断言 / 1 行代码 / 命令」也合并**
      （本包第 7 轮实测：间隔 1 个代码行 ⇒ units=1、命令被看见）；
      而**隔 2 行以上**（含 2 个空行、2 个代码行）仍不合并
      ⇒ 保住「明显分属两段」的边界（**M3 形态**：去蹭隔两行的无关块命令，仍不会被蹭到）；
    - 容忍 **更多** ⇒ 会把不相干的段落并进来，**假红消失但漏报增加**。

    **⇒ 这是两个方向的同一个旋钮**（窗口越宽：假红越少、漏报越多），
    不存在「两个都修好」的取值。**取 1 是权衡后的结果，理由如上。**

    **⚠ 仍会漏的**（登记，见 `test_correction_notes_state_their_evidence` 的 docstring）：
    断言与命令之间隔 **≥2 行**（2 个空行、2 个代码行，或空行与代码行各一）时不合并
    ⇒ 规则可能报「没给命令」（假红）；**反过来，只要间隔 ≤1 行就被当成同一单元**，
    哪怕那 1 行是**无关的代码行** ⇒ 也可能把两段本不相干的内容并起来（漏报方向）。
    **⇒ 两侧代价都在，不是单向的。**
    docstring 本身已是整段，直接并入，不参与合并。
    """
    merged: list[tuple[int, str]] = []
    for start, text in sorted(_comment_units(source), key=lambda item: item[0]):
        if merged:
            previous_start, previous_text = merged[-1]
            next_expected = previous_start + previous_text.count("\n") + 1
            gap = start - next_expected
            if gap <= 1:
                # ⚠ 间隔必须**按换行补回**：`tokenize` 给的 token 文本**不含行尾换行**，
                #   所以紧邻（gap=0）时也要补 1 个换行；gap=1（中间一个空行）要补 2 个。
                #   漏补会让合并后的文本黏成一行、行偏移与真实行号错位
                #   （本包吃过「行号腐坏」的亏，这里不能再制造）。
                merged[-1] = (previous_start, f"{previous_text}{chr(10) * (gap + 1)}{text}")
                continue
        merged.append((start, text))
    return merged + _docstring_units(source)


def _references_in_text(text: str, start_line: int) -> list[_TestReference]:
    """一段注释或 docstring 里点名的测试引用。

    `start_line` 是这段文本在源文件里的起始行号，用来报出可定位的 `文件:行`。

    先清空同行成对的 `~~…~~` 撤回区（被撤回的句子不是承诺，理由与界定见
    `_WITHDRAWN_PAIR`），再把 `.py` 字面量整段屏蔽掉后找裸名：否则 `test_x.py` 会被
    同时算成文件引用与裸名引用，而裸名的判据（tests 下有同名 def 或同名文件）对第二种
    算法并不成立。两个屏蔽各自用 `_PY_MASK_CHAR` / `_WITHDRAWN_MASK_CHAR`，
    **两个填充字符的要求相反**，理由见各自常量的说明。
    """
    found: list[_TestReference] = []
    text = _mask_withdrawn(text)
    masked = list(text)
    for match in _PY_PATH.finditer(text):
        for index in range(match.start(), match.end()):
            masked[index] = _PY_MASK_CHAR
        relative = _test_file_reference(match.group(0))
        if relative is not None:
            found.append(_TestReference(start_line + text.count("\n", 0, match.start()), "file", relative))
    masked_text = "".join(masked)
    for match in _TEST_NAME.finditer(masked_text):
        if _is_elided(masked_text, match.end()):
            continue
        found.append(_TestReference(start_line + text.count("\n", 0, match.start()), "bare", match.group(0)))
    return found


def _comment_units(source: str) -> list[tuple[int, str]]:
    """源码里的注释：(起始行号, 注释原文)。"""
    return [
        (token.start[0], token.string)
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]


def _docstring_units(source: str) -> list[tuple[int, str]]:
    """源码里的 docstring：(起始行号, 文本原文)，含类与函数的。"""
    units: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, _DOCSTRING_OWNERS):
            continue
        body = node.body
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            units.append((first.value.lineno, first.value.value))
    return units


def _references_in_source(source: str) -> list[_TestReference]:
    """一个源文件里点名的全部测试引用（注释与 docstring 都算，代码不算）。"""
    units = _comment_units(source) + _docstring_units(source)
    return [reference for line, text in units for reference in _references_in_text(text, line)]


def _scanned_line_numbers(source: str) -> set[int]:
    """本文件会读到的行号集合（docstring 与注释各自的行范围）。

    抽成函数是为了让「扫描面」这个概念**可复算**：盲区统计（见 `_blind_string_literals`）
    与「反例五」自测都用它，而不是各写一遍判定。
    """
    lines: set[int] = set()
    for start, text in _docstring_units(source) + _comment_units(source):
        lines.update(range(start, start + text.count("\n") + 1))
    return lines


def _blind_string_literals(path: Path) -> list[str]:
    """某个源文件里**不在扫描面内**的字符串字面量原文（即盲区里的那些）。

    「盲区」= 字符串字面量表达式，但它**不是**任何节点的 `body[0]` docstring、
    也不与任何 `#` 注释区间重叠（PEP 258 属性文档字符串是典型：`X = 1` 之后紧跟
    一个字符串，本仓 `modules/accounts/session_items.py` 的大段说明就是这种）。
    **这是已知未覆盖，不是「已被核对」**——模块 docstring 的诚实声明里登记了它。
    """
    source = path.read_text(encoding="utf-8")
    scanned = _scanned_line_numbers(source)
    out: list[str] = []
    for node in ast.walk(ast.parse(source, filename=str(path))):
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        if not isinstance(node.value.value, str):
            continue
        end = node.value.end_lineno or node.value.lineno
        if any(line in scanned for line in range(node.value.lineno, end + 1)):
            continue
        out.append(node.value.value)
    return out


@lru_cache(maxsize=None)
def _test_case_names() -> frozenset[str]:
    """`apps/api/tests/**` 里定义的全部用例名。

    按 AST 取 `def` / `async def` 的定义名，不做子串匹配：本仓的注释会提到生产侧函数
    （`latest_bound_object_id`），子串匹配分不开「提到一个名字」与「点名一条测试」。
    含类内方法：用例按类分组时名字同样是可被点名的用例。
    """
    names: set[str] = set()
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
    return frozenset(names)


def _reference_exists(reference: _TestReference) -> bool:
    """被点名的测试真的存在。

    文件引用按路径存在性判。裸名先按同名文件再按同名 `def` 判——本仓的注释常用裸名指
    整份文件（`test_layer_boundaries`、`test_agent_runtime`），那种写法同样是「那份测试
    存在」的承诺，不该因为少写了 `.py` 就放过。
    """
    if reference.kind == "file":
        return (TESTS_ROOT / reference.name).is_file()
    return (TESTS_ROOT / f"{reference.name}.py").is_file() or reference.name in _test_case_names()


def _production_sources() -> list[tuple[str, str]]:
    """生产侧（`src/campfire`）的全部 Python 源文件：(相对路径, 源码)。"""
    return [
        (path.relative_to(SRC_ROOT).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(SRC_ROOT.rglob("*.py"))
    ]


def _test_sources() -> list[tuple[str, str]]:
    """测试侧（`apps/api/tests`）的全部 Python 源文件：(相对路径, 源码)。

    跳过 `_SELF_PATH`：本文件的 docstring 要用占位名演示「哪些写法算引用」，而那些
    占位名按设计不存在（理由与代价见模块 docstring 的诚实声明）。路径带
    `apps/api/tests/` 前缀，与生产侧同名的相对路径不会在违规信息里撞车。
    """
    return [
        (f"apps/api/tests/{path.relative_to(TESTS_ROOT).as_posix()}", path.read_text(encoding="utf-8"))
        for path in sorted(TESTS_ROOT.rglob("*.py"))
        if path.resolve() != _SELF_PATH
    ]


def _scanned_sources() -> list[tuple[str, str]]:
    """守卫的扫描面：生产代码 + 测试文件。"""
    return _production_sources() + _test_sources()


def _missing_test_references(sources: Iterable[tuple[str, str]]) -> list[str]:
    """点名的测试不存在的引用，逐条可读。

    另报**畸形撤回标记**（`~~` 计数为奇数）：那是「有未闭合的撤回标记」，
    必须报红让人去修，**不得静默当作「一直撤回到底」**——那会把局部豁免变成
    大面积盲区，正是 `_WITHDRAWN_PAIR` 的界定要防的事。
    """
    return [
        f"{relative}:{reference.line} 注释点名的测试不存在（{_KIND_LABELS[reference.kind]}）：{reference.name}"
        for relative, source in sources
        for reference in _references_in_source(source)
        if not _reference_exists(reference)
    ] + [
        f"{relative}:{line} 注释里的 `~~` 撤回标记未闭合（计数为奇数）——"
        "撤回区只认同行成对的 `~~`，畸形标记必须修掉而不是当成豁免"
        for relative, source in sources
        for line, text in (_comment_units(source) + _docstring_units(source))
        if _unpaired_withdrawn(text)
    ]


def test_comment_test_reference_guard_detects_its_patterns() -> None:
    """防止守门退化为空跑：识别、解析与整条判定都必须真的认得出样例。

    这里的合成源码只存在于内存里，不落盘、不动真实文件；真实文件上的消融另跑。
    """
    sample = (
        '"""两处常量由 `apps/api/tests/test_cache.py::test_pool_decodes_responses` 钉住。"""\n'
        "# 由 test_text_part_types_agree_across_the_two_parsers 守住\n"
        "# 测试基建见 apps/api/tests/conftest.py\n"
        "# 裸文件名 test_emergency_card.py 也算一条\n"
    )
    references = _references_in_source(sample)
    assert _TestReference(1, "file", "test_cache.py") in references
    assert _TestReference(1, "bare", "test_pool_decodes_responses") in references
    assert _TestReference(2, "bare", "test_text_part_types_agree_across_the_two_parsers") in references
    assert _TestReference(3, "file", "conftest.py") in references
    assert _TestReference(4, "file", "test_emergency_card.py") in references

    # 子串不是引用：`latest_bound_object_id` 里含 `test_`，按子串匹配会假红
    assert _references_in_source("# 留着它会成为 latest_bound_object_id 的输入\n") == []
    # 只有前缀、没有名字的写法不是引用
    assert _references_in_source("# test_ 开头的函数都是用例\n") == []
    # 生产侧模块路径不是测试引用（注释里到处都有，收了会假红满天）
    assert _references_in_source("# 见 agent/context/window.py 的 message_text\n") == []
    # 边界：不带 `.py` 的裸 `conftest` 是散文式提及，本规则不收（本仓 embedding.py 有这种措辞）
    assert _references_in_source("# 构造会抛 InvalidURL（本机实测，conftest 已留档）。\n") == []
    # 边界：屏蔽 `.py` 字面量不得凭空造出词边界。`conftest.pytest_configure` 里的
    # `conftest.py` 是**真的**测试基建文件（file 引用照旧成立），但它的尾巴
    # `test_configure` 是散文里的限定名，绝不能被算成点名了一条用例。
    dotted = _references_in_source("# 本仓的 conftest.pytest_configure 会归一 localhost\n")
    assert _TestReference(1, "file", "conftest.py") in dotted
    assert [reference for reference in dotted if reference.kind == "bare"] == []
    assert _missing_test_references([("probe.py", "# 本仓的 conftest.pytest_configure 会归一 localhost\n")]) == []
    # 边界：紧跟通配/省略号的裸名指「一类测试」，不是点名一条测试
    assert _references_in_source("# 由 test_library_*_integration 覆盖，这里只钉调用形状\n") == []
    assert _references_in_source("# 关键用例（`test_memory_*`）走真实落库\n") == []
    assert _references_in_source("# 关键用例（`test_hydration_...sdk...`）走真实落库\n") == []
    # 反例：单句号结尾与 `::` 之后仍算点名，别把上面那条边界扩成「带 `.` 就不算」
    assert _TestReference(1, "bare", "test_foo_bar") in _references_in_source("# 见 test_foo_bar.\n")
    assert _TestReference(1, "bare", "test_foo_bar") in _references_in_source("# 见 tests/test_a.py::test_foo_bar\n")
    # 边界：`~~…~~` 撤回区里的名字不核对——订正范式要求旧句划掉保留而不是静默删掉
    withdrawn = "# ~~由 `test_no_such_guard_exists` 覆盖~~\n# ⇒ 已订正：那条测试不存在，无覆盖\n"
    assert _references_in_source(withdrawn) == []
    assert _missing_test_references([("probe.py", withdrawn)]) == []
    # ★ 只测上面那条，这个豁免就会变成恒绿后门（谁都能用 `~~` 把守卫关掉）
    # ⇒ 反例一：撤回区**之外**的不存在名字照旧判红，别把它当「划过一次就永久免检」
    reopened = "# ~~由 `test_no_such_guard_exists` 覆盖~~\n# 但这里又说 `test_still_no_such_guard` 覆盖\n"
    reopened_missing = _missing_test_references([("probe.py", reopened)])
    assert len(reopened_missing) == 1, f"撤回区之外没有被核对：{reopened_missing}"
    assert "test_still_no_such_guard" in reopened_missing[0]
    # ⇒ 反例二：撤回区界定保守（只认同行成对）⇒ **跨行**的 `~~` 不构成豁免，
    #    否则一个漏写的闭合 `~~` 会吞掉其后整个 docstring。
    #    这条同时报两类：名字仍在核对 + 两行各有一个未配对的 `~~`。
    cross_line = "# ~~由 `test_no_such_guard_exists` 覆盖，\n# 这句话跨了两行才收尾~~\n"
    cross_line_missing = _missing_test_references([("probe.py", cross_line)])
    assert [item for item in cross_line_missing if "test_no_such_guard_exists" in item], (
        f"跨行 `~~` 不该构成豁免：{cross_line_missing}"
    )
    assert [item for item in cross_line_missing if "未闭合" in item], (
        f"跨行 `~~` 应当被报成未闭合标记：{cross_line_missing}"
    )
    # 单行成对时三类都不该报（正向控制，避免上面两条退化成恒真）
    assert _missing_test_references([("probe.py", "# ~~见 `test_gone.py`~~ 已订正\n")]) == []
    # ⇒ 反例三：`~~` 计数为奇数（未闭合）必须报红，不得静默当作「一直撤回到底」。
    #    同时报两条：标记畸形 + 那个名字**仍然**被核对（未闭合 ⇒ 不构成豁免，fail-safe）。
    unpaired = "# ~~由 `test_no_such_guard_exists` 覆盖\n"
    unpaired_missing = _missing_test_references([("probe.py", unpaired)])
    assert [item for item in unpaired_missing if "未闭合" in item], unpaired_missing
    assert [item for item in unpaired_missing if "test_no_such_guard_exists" in item], unpaired_missing
    assert len(unpaired_missing) == 2, unpaired_missing
    # 配对正常的同行撤回区不报「未闭合」
    assert not [item for item in _missing_test_references([("probe.py", withdrawn)]) if "未闭合" in item]
    # 撤回区清空后行号不漂移：第 3 行的引用必须仍报 `:3`
    shifted = "# ~~见 `test_gone.py`~~\n# 中间一行\n# 由 `test_also_gone` 守住\n"
    shifted_missing = _missing_test_references([("probe.py", shifted)])
    assert len(shifted_missing) == 1 and "probe.py:3" in shifted_missing[0], shifted_missing
    # 撤回区只清掉划掉的那段，同一行后面的句子照旧被核对
    same_line = "# ~~见 `test_gone.py`~~ 但 `test_also_gone` 覆盖\n"
    same_line_missing = _missing_test_references([("probe.py", same_line)])
    assert len(same_line_missing) == 1 and "test_also_gone" in same_line_missing[0], same_line_missing
    # ⇒ 反例四之一（P2-2 回归，两条约束**要求相反**，必须分别钉住）：
    #    撤回区**紧跟**一个名字时（无空白分隔），那个名字**必须仍被报**。
    #    若撤回区用 `_PY_MASK_CHAR`（`.`，落在 `_TEST_NAME` 的否定前视集内）填充，
    #    填充字符会充当「前邻标识符字符」把它挡住 ⇒ 漏报。
    tight = "# ~~已撤回~~test_no_such_guard_exists\n"
    tight_missing = _missing_test_references([("probe.py", tight)])
    assert [item for item in tight_missing if "test_no_such_guard_exists" in item], (
        f"撤回区紧跟名字时被挡住了（漏报）：{tight_missing}"
    )
    # ⇒ 反例四之二（另一条约束的正控）：屏蔽 `.py` 字面量时**必须**避免捐出词边界，
    #    否则 `conftest.pytest_configure` 会被读成点名了 `test_configure`（假红）。
    #    这两条**不可能用同一个填充字符满足** —— 它们钉住「必须是两个常量」。
    dotted_ok = _missing_test_references([("probe.py", "# 见 conftest.pytest_configure 的说明\n")])
    assert dotted_ok == [], f"`.py` 屏蔽捐出了假名字（假红）：{dotted_ok}"
    assert _PY_MASK_CHAR != _WITHDRAWN_MASK_CHAR, "两个填充字符的要求相反，共用一个会破掉其中一条"
    assert _PY_MASK_CHAR in "._/", "`.py` 填充必须落在否定前视集内，否则捐出词边界"
    assert _WITHDRAWN_MASK_CHAR not in "._/", "撤回区填充必须**不**落在否定前视集内，否则挡住后随名字"
    # ⇒ 反例四（P2 回归）：同一行**两对** `~~` 时，两对**之间**那段未被撤回的文字
    #    不得被吞掉。整行替换会把它一起屏蔽 ⇒ 漏报（比假红更坏），故逐对替换。
    two_pairs = "# ~~见 `test_gone.py`~~ 中间 `test_middle_gone` ~~再见 `test_gone2.py`~~\n"
    two_pairs_missing = _missing_test_references([("probe.py", two_pairs)])
    assert [item for item in two_pairs_missing if "test_middle_gone" in item], (
        f"同一行两对 `~~` 时，中间那段被吞掉了（漏报）：{two_pairs_missing}"
    )
    # 两对各自撤回了自己的名字 ⇒ 那两个名字本身不该报；只报中间那个
    assert len(two_pairs_missing) == 1, two_pairs_missing
    assert not [item for item in two_pairs_missing if "test_gone.py" in item or "test_gone2.py" in item]

    # ⇒ 反例五（盲区，如实钉住）：赋值之后的**属性文档字符串**（PEP 258）不在扫描面内。
    #    这条不是「期望的行为」，而是**把模块 docstring 里登记的盲区变成机械可查的事实**——
    #    将来谁把扫描面扩大了，这条会失败，从而逼他同步改掉那段声明（防声明过期）。
    attr_doc = 'X = 1\n"""属性文档字符串：由 `test_no_such_guard_exists` 覆盖。"""\n'
    assert _references_in_source(attr_doc) == [], "属性文档字符串被扫到了——盲区声明已过期，须同步更新"
    # 正控：同一段文本若处在 body[0]（真 docstring）位置，就必须**被**扫到
    real_doc = '"""真 docstring：由 `test_no_such_guard_exists` 覆盖。"""\nX = 1\n'
    assert _TestReference(1, "bare", "test_no_such_guard_exists") in _references_in_source(real_doc)

    # 解析按事实：真用例名查得到，不存在的查不到
    assert "test_pool_decodes_responses" in _test_case_names()
    assert "test_no_such_guard_exists" not in _test_case_names()

    # 整条判定：引用不存在的测试必须产出违规
    missing = _missing_test_references([("surfaces/consult/probe.py", "# 由 `test_no_such_guard_exists` 守住\n")])
    assert len(missing) == 1, f"引用不存在的测试没有判红：{missing}"
    assert "test_no_such_guard_exists" in missing[0]
    assert "surfaces/consult/probe.py:1" in missing[0]
    # 引用真实存在的测试不判红：假红会逼后来人放宽规则
    assert _missing_test_references([("surfaces/consult/probe.py", "# 由 `test_layer_boundaries` 守住\n")]) == []
    assert _missing_test_references([("surfaces/consult/probe.py", "# 见 tests/test_cache.py:1\n")]) == []


def test_comment_named_tests_exist() -> None:
    """生产代码与测试文件的注释/docstring 里点名的测试必须真的存在。"""
    sources = _scanned_sources()
    assert sources, "一个 Python 文件都没扫到，检查会空跑"

    # 豁免面必须是「只有本文件一个」：它一旦变宽，检查就静默变窄（本仓禁止留永不失败的检查）
    scanned = {relative for relative, _ in _test_sources()}
    everything = {f"apps/api/tests/{path.relative_to(TESTS_ROOT).as_posix()}" for path in TESTS_ROOT.rglob("*.py")}
    skipped = everything - scanned
    assert skipped == {f"apps/api/tests/{_SELF_PATH.relative_to(TESTS_ROOT).as_posix()}"}, (
        f"被豁免扫描的测试文件不只本文件一个：{sorted(skipped)}——豁免面必须钉死在一个文件上，否则扩面等于没扩"
    )

    references = [reference for _, source in sources for reference in _references_in_source(source)]
    kinds = {reference.kind for reference in references}
    assert kinds == {"file", "bare"}, (
        f"两类引用没有各自命中（实际 {sorted(kinds)}）——写法的识别通道可能失效了，"
        "先核对提取规则与真实文件的写法，不要直接放宽这条断言"
    )

    violations = _missing_test_references(sources)
    assert not violations, "注释点名的测试不存在——注释在撒谎，或那条测试被删了：\n" + "\n".join(violations)


def test_blind_spot_is_non_empty_and_has_no_broken_reference() -> None:
    """把模块 docstring 登记的「盲区」做成**可复算**的检查，而不是一句散文。

    两件事：

    1. **非空性（防止声明变成空话）**：盲区必须真的存在若干字符串字面量——
       若某天它变成 0，说明扫描面已经覆盖了全部字面量，
       那段「已知未覆盖」的诚实声明就**过期**了，必须同步改掉；
    2. **盲区里不得藏着失效引用**：盲区**不核对**，所以它**天然能藏缺陷**
       （这正是不该把它说成「已被核对」的原因）。这里做一次**只读的**体检：
       若盲区里出现了点名的测试且该名字不存在，就**报红**并提示——本包对它的处置是
       「只登记不扩面」，但**登记不等于放着不管**：至少要让真缺陷可见。

    **⚠ 为什么这条不直接把盲区纳入扫描面**：属性文档字符串在本仓大量存在
    （`src` 侧数量级为百），纳入会显著扩大假阳性面（散文式提及会被当成点名），
    而收益有限。**这是一个有意的取舍，代价如实写在模块 docstring 里。**
    """
    roots = {"src/campfire": SRC_ROOT, "apps/api/tests": TESTS_ROOT}
    blind_total = 0
    broken: list[str] = []
    for label, root in roots.items():
        for path in sorted(root.rglob("*.py")):
            if path.resolve() == _SELF_PATH:
                continue
            relative = f"{label}/{path.relative_to(root).as_posix()}"
            for text in _blind_string_literals(path):
                blind_total += 1
                for reference in _references_in_text(text, 1):
                    if not _reference_exists(reference):
                        broken.append(f"{relative} 盲区里的{_KIND_LABELS[reference.kind]}：{reference.name}")

    assert blind_total > 0, "盲区字符串字面量变成了 0——模块 docstring 里那段「已知未覆盖」的声明已过期，须同步删改"
    assert not broken, (
        "盲区（不在扫描面的字符串字面量）里存在点名的测试却不存在——"
        "盲区不核对，所以它能藏缺陷；请修掉引用，或把该处纳入扫描面：\n" + "\n".join(broken)
    )


def _correction_scan(trees: tuple[tuple[str, Path], ...]) -> tuple[list[str], list[str]]:
    """扫给定的树，返回 (违规列表, **实际扫过的树的标签**)。

    **为什么要把「扫过的树」当返回值**：覆盖面断言必须依赖**主循环实际扫了什么**。
    上一版那条断言独立 `rglob` 一遍 ⇒ 与主循环解耦 ⇒ 实测「主循环只扫一棵树」时
    它仍然全绿（防错了东西）。**⇒ 让「实际扫过什么」只能由本函数产出，判据无法脱钩。**
    """
    offenders: list[str] = []
    scanned: list[str] = []
    for label, root in trees:
        scanned.append(label)
        # ⚠ 行号约束只对测试树生效：扩到生产树会命中 8 处**既有**引用（见 docstring 第 2 条），
        #   而本包无权改生产侧 ⇒ 只登记、不在这里报。（「缺命令」那条对两棵树都生效。）
        check_line_refs = label == "apps/api/tests"
        for path in sorted(root.rglob("*.py")):
            if path.resolve() == _SELF_PATH:
                continue
            source = path.read_text(encoding="utf-8")
            if not _CORRECTION_MARK.search(source):
                continue  # 不含订正说明的文件不受这条规则管
            relative = f"{label}/{path.relative_to(root).as_posix()}"
            for line, text in _merged_annotations(source):
                if not _CORRECTION_MARK.search(text):
                    continue  # 只查订正说明；别的单元里的行号是「实测依据」，不在此规则内
                for offset, fragment in enumerate(text.splitlines()):
                    where = f"{relative}:{line + offset}"
                    if _repo_absence_in(fragment):
                        if not _GIT_COMMAND.search(text):
                            offenders.append(f"{where} 关于仓库/历史的断言没有给出可复算命令：{fragment.strip()[:70]}")
                        elif _CASE_LEVEL_ABSENCE.search(fragment) and not _DEF_COMMAND.search(text):
                            # 用例层面的断言必须用带 def 的 -S：路径型只证明「没有文件被创建」
                            offenders.append(
                                f"{where} 「用例从未被定义过」这类断言必须引带 `def` 的 `-S`"
                                f"（路径型只证明「没有文件」，证明不了「用例没被定义过」）：{fragment.strip()[:70]}"
                            )
                    if check_line_refs:
                        for bad in _PY_LINE_REF.findall(fragment):
                            offenders.append(f"{where} 订正说明引用了会腐坏的行号：{bad}")
    return offenders, scanned


def test_correction_notes_state_their_evidence() -> None:
    """订正说明里的「全称否定」必须给出可复算的命令，且不得引用会腐坏的行号。

    **为什么把它做成【类级】规则而不是逐条列举**：本包连续多轮都出现同源缺陷
    （把更弱/不同口径的证据说成更强结论），而前几轮的修法是「补上被指出的那几处」
    ——**那是补点，不是补类**，于是它换个地方又出现。

    **⚠ 覆盖面（如实，按实测的三道边界逐条写清）**——上一版这里自称「扫全部含订正标记的
    文件」，而实际只扫三成，那是**自称与实际不符**；现已按实际拓宽，并把边界写死：

    - **扫描根**：`src/campfire` **与** `apps/api/tests` **两棵树**
      （上一版只有测试树 ⇒ `7932a20` 改的那两个生产文件永远进不来）。
      **⚠ 作用域措辞**：这是**两棵扫描树**，**不是「全仓」**——实测
      `git grep -l '订正' HEAD -- '*.py'` 有 **14** 个文件，其中 **1 个在两棵树之外**
      （`scripts/check_task_pack.py`）⇒ 本规则**不覆盖它**。凡本文件说「两棵树」就是指
      这个范围，**不要读成「全仓」**；
    - **标记**：一律认 `订正` 两字（`_CORRECTION_MARK`），不再只认 `⇒ 已订正` 一支
      ⇒ 本仓另有 `⚠ 2026-10-06 订正` 等写法。**⚠ 修正旧措辞**：上一版写「让 11 个生产
      文件整体漏过」，**逐字不准**——生产树含 `订正` 的共 **11** 个文件，
      旧口径（`⇒ 已订正`）覆盖其中 **2** 个 ⇒ **实际漏 9 个**；
    - **文本单元**：注释按**行号相邻合并**（`_merged_annotations`），
      不再用「单个 token 行」——否则「断言在上一行、命令在下一行」会被拆成两个单元而漏过
      （本仓 `surfaces/consult/assembly.py` 正是这种写法）。

    **两条约束**：

    1. **全称否定须引 git 命令**（`_REPO_ABSENCE` + `_GIT_COMMAND`）：凡说「全仓没有」
       「任何提交里都没有」这类**关于仓库/历史的**断言，必须紧跟那条命令，读者才能复算。
       **⚠ 命令强度必须与断言的层面相称**（`_CASE_LEVEL_ABSENCE` + `_DEF_COMMAND`）：
       本包踩过两次——用**路径型**（`git log -- '*name*'`）或**不带 `def` 前缀**的 `-S`
       去撑「这条**用例**从未被定义过」，而那条命令其实会命中
       （名字作为**注释文本**出现在写出坏引用的那个提交里）。
       **⚠ 层面判据只取显式的层面词**（`用例` / `def ` / `定义过` / `被定义`）：
       刻意**不**用 `零命中` / `命中.*0` / `为 0` 这类**读数**措辞去猜层面——
       那些措辞**两个层面都照样用**，拿它外推层面会把真话判成违规（自测里给了
       同断言、只换读数措辞的真话样例）。
       **⚠ 并纠正本包第 6 轮自查出的一处错**：这里曾举
       `surfaces/consult/assembly.py` 的「`git log --all --diff-filter=A` 零命中」
       当真话范例——**那个范例是错的**（该命令**缺 pathspec**，实测命中 **390** 个提交，
       永远不可能为 0；它由 `9354171` 引入，**从来不是真话**）。
       **⇒ 那一处是【产品文本里的已知缺陷】**（在 `apps/api/src/` 下，**不在本包授权内**，
       只能登记不能改），**不再被当作范例引用**。
       **但「引了 `-S` 就够强」仍不是机器能判的**——`-S` 的**输出是什么**、
       是否真的为空，只能人核。这一半仍归人。
    2. **订正说明里不得引用 `某文件.py:行号`**（`_PY_LINE_REF`）：行号随编辑腐坏，
       而「引用了过期的东西」与「引用了不存在的东西」是同一族缺陷。
       **⚠ 只对【含订正标记的那个单元】生效，不对整个文件生效**——
       实测：全文件生效会误伤**与订正无关**的单元（本仓有
       「实测 `_transports/asgi.py:185-187` 只 `yield b"".join(...)`」这类
       **实测依据**，那里的行号是证据的一部分，不是承诺）。订正说明才是
       「我核过、我已订正」的高发地，也才是该要求稳定标识的地方。
       **⚠ 本约束只作用于 `apps/api/tests` 树**（如实登记，不是偷偷窄化）：
       把它扩到 `src/campfire` 会立刻命中 **8 处既有引用**，分布在 4 个生产文件
       （`agent/runtime/session_annotations.py` 3、`core/auth/supertokens.py` 3、
       `core/config.py` 1、`main.py` 1），**它们都在 HEAD 里、都不是本包引入的**，
       而**本包的授权范围只有测试侧** ⇒ 本包**不能**替它们改，只能**登记**。
       其中 5 处指向的是**第三方 SDK 的内部行号**（`querier.py:110`、
       `chatcmpl_converter.py:746`、`run_internal/session_persistence.py:714`、
       `extensions/memory/sqlalchemy_session.py:370`——这些文件只存在于 `.venv`，
       不在本仓），另 3 处指向本仓的 `worker.py`。
       **⇒ 若要把这条约束扩到生产侧，须由生产侧的所有者决定，本包只登记。**

    **⚠ 仍会漏的（登记，不假装覆盖）**——**两类「撑不起断言」的形态并入同一张表**
    （部分/量化断言与裸 git 命令同属「命令强度与断言不相称」这一族，故不另立一张）：

    | 编号 | 形态 | 处置 |
    | --- | --- | --- |
    | **M1a** | 断言与命令隔**一个空行** | **已修**：合并窗口容忍 1 行间隔（自测①） |
    | **M1b** | 隔**一行代码** | **未覆盖（漏报方向）**：窗口只看行号差、不看那行是不是代码 ⇒ 间隔 1 行即合并，会把两段本不相干的内容并起来（自测④给了实测读数） |
    | **M2** | **假命令**（pathspec 指向不存在路径） | **未覆盖**：见下「为什么不执行 git」 |
    | **M2b** | `-S "def "` 过宽（无名字） | **未覆盖**：同上，机器分不出「命令是否真撑得住断言」 |
    | **M3** | **蹭**邻块命令 | **已部分防**：窗口止于 1 行 ⇒ 隔 2 行以上蹭不到（自测②） |
    | **M4** | 断言与命令相距 19 行 | **未覆盖**：把「必须同一单元」当可辩护的边界；**但单元长度本身无上界**（见 M5） |
    | **M5** | **同单元内远距诱饵命令**（P2-3）：断言 + 18 行连续注释 + 一个无关的 `-S` | **未覆盖**：合并判据对**块总长无上界**——实测 200 行连续注释仍是**同一个单元**（自测⑤），故「必须同一单元」挡不住块内的远距诱饵；`M4` 的理由**不覆盖**这一条 |
    | **M6** | **部分/量化断言**（P2-2）：「全仓**只有 3 个**文件…」「全仓**绝大多数**…」 | **未覆盖**：`_REPO_ABSENCE` 收的是**全称否定**形状，量化断言**既不命中强形状、也不含 `零命中`** ⇒ 实测 `_repo_absence_in` = False（自测⑥），它**不被本规则看见**。它与 M2/M2b **同族**（都是「断言强度 > 证据强度」），故并入本表而不另立 |
    | **I2 / I6b** | 全新措辞 / 诱饵命令 | **未覆盖**（与前几轮自陈一致） |

    **★ 本表的读法**：右列写「未覆盖」的条目**就是没被本规则拦住**，
    不要因为它们在表里就当成已处理。**低估覆盖比高估覆盖安全**——
    「登记盲区可接受，把盲区说成已覆盖不可接受」是本包六轮 FAIL 的唯一尺子。

    **⚠ 窗口取舍（M1a/M1b/M3 是同一个旋钮）**：窗口越宽 ⇒「看不见命令」的假红越少、
    **蹭到无关块命令的漏报越多**；不存在两个方向都最优的取值。
    取「容忍 1 行」的理由：本仓真实写法是紧邻或隔一个空行（两者现在都工作），
    **代价是「隔一行代码」也照样合并**（M1b，实测如此，**不声称它已被防住**）；
    而**隔 ≥2 行**才意味着「这里已经换段了」。

    **⚠ 为什么不执行 git（M2/M2b 无法机械判）**：本守卫是**纯文本规则、不跑 git**。
    要验「所引命令是否真的零命中」就得**在执行期跑 `git log --all`**，而
    **CI 是浅克隆**（`actions/checkout` 未设 `fetch-depth`，本包实测该串在
    `.github/workflows/*.yml` 里出现 **0** 次 ⇒ 取默认值 1）⇒
    `git log --all` 在 CI 下读不到历史，判据会给出**错误结论**。
    ⇒ 宁可把这部分**留给人工**，也不做一个在 CI 上不可靠的「自动核实」。
    （「命令与断言是否相称」这类判断，本包已多次证明**机器只能查形状**。）

    **⚠ `_REPO_ABSENCE` 是形状黑名单**：全新措辞（如「整个代码库里搜不到」）会漏；
    **⇒ 它钉住的是这一类里常见的写法，不等于已覆盖全部全称否定。**
    **连带 M6**：量化断言（「只有 3 个」）既不命中黑名单、也无 `零命中` 读数
    ⇒ 它**整类**都在判据之外，`_GIT_COMMAND` 收紧与否都改变不了这一点。
    """
    offenders: list[str] = []
    # ⚠ 扫描根由 `_CORRECTION_TREES` 单点定义，并把「**实际扫过的树**」返回给调用方。
    #   上一版覆盖面断言**独立 rglob**、与主循环解耦 ⇒ 实测「主循环只扫一棵树」它仍全绿。
    #   ⇒ 现在「实际扫了什么」只能由主循环产出，判据不可能与它脱钩。
    offenders, trees_scanned = _correction_scan(_CORRECTION_TREES)

    # ★ 覆盖面：断言必须**依赖主循环实际扫了什么**（自测里用变异验证过：只扫一棵 ⇒ 这里红）。
    #   ⚠ `expected_trees` 必须写成**字面量**，不能从 `_CORRECTION_TREES` 推导——
    #     否则「期望」与「实际」同源：窄化那个常量时两边一起变、断言**永远为真**
    #     （本包第 6 轮实测踩到这个陷阱：推导版在变异下只让别的用例抛 IndexError，
    #      而这条覆盖面断言本身从未红过）。它表达的是**规则对外声称的范围**（docstring
    #      里写死「两棵树」）⇒ 必须独立于实现。
    expected_trees = ["src/campfire", "apps/api/tests"]  # noqa: 字面量是刻意的，勿改为推导
    assert trees_scanned == expected_trees, (
        f"主循环实际只扫了 {trees_scanned}，而本规则对外声称扫 {expected_trees} —— 扫描根被窄化了（自称与实际不符）"
    )

    assert not offenders, (
        "订正说明的可核实性不达标——请给出能支撑该断言的最强命令，或改用稳定标识"
        "（用例名/函数名）而不是行号：\n" + "\n".join(offenders)
    )


def test_correction_note_rule_is_not_vacuous() -> None:
    """上一条规则的**判别性自测**：它必须真的能红，且不误伤（本仓禁止恒真的检查）。

    这里的合成文本只存在于内存里，不落盘。四个方向：

    - **历史形态必须被抓**：本包多轮里出现过的四种写法（引了弱命令 / 引路径型撑用例层面
      断言 / 完全没引命令 / 订正说明里写行号）各给一个样例，逐一验证规则会报；
    - **修好后的形态不得被误伤**：否则后来人会为了过检查而放宽规则；
    - **⚠ 层面判据不得用读数措辞外推**（本包实测过一次误伤）：`零命中` / `为 0` 这类
      **读数**措辞，**文件层面也照样用**；「文件层面 + 正确的路径型命令」是真话，
      不该被要求引 `-S`。⇒ 给三条同断言、只换读数措辞的真话样例；
    - **行为陈述不得被误伤**：本仓大量「没有任何提示」「从未往下传」说的是**运行时行为**，
      不是「我核过仓库」，它们**不该**被要求引 git 命令。
    """

    def offender_count(text: str) -> int:
        """用与 `test_correction_notes_state_their_evidence` 相同的判定算违规数。"""
        count = 0
        for fragment in text.splitlines():
            if _repo_absence_in(fragment):
                if not _GIT_COMMAND.search(text):
                    count += 1
                elif _CASE_LEVEL_ABSENCE.search(fragment) and not _DEF_COMMAND.search(text):
                    count += 1
            count += len(_PY_LINE_REF.findall(fragment))
        return count

    # —— 必须被抓的四种历史形态（本包真实踩过的）——
    must_flag = {
        "引用弱命令撑用例层面": "# ⇒ 已订正\n# 该用例从未被定义过：`git log --all -S` 下为空，`def` 定义也零命中。\n",
        "路径型撑用例层面": "# ⇒ 已订正\n# 该用例从未被定义过（`git log --all -- '*memory_purge*'` 为 0）。\n",
        "完全没引命令": "# ⇒ 已订正\n# 该用例从未被定义过：它在任何提交里都没有出现过。\n",
        "订正说明里写了行号": "# ⇒ 已订正\n# 覆盖见 `apps/api/tests/test_x.py:123`。\n",
    }
    for label, text in must_flag.items():
        assert offender_count(text) > 0, f"这条历史形态没有被抓到（规则可能空转）：{label}"

    # —— 修好后的形态：不得误伤 ——
    must_pass = {
        "带 def 的 -S 撑用例层面": '# ⇒ 已订正\n# 该用例从未被定义过：`git log --all -S "def <占位>"` 的读数是**空**。\n',
        "路径型撑文件层面": "# ⇒ 已订正\n# 该名字从未作为【文件】存在过：`git log --all -- '*memory_purge*'` 的读数是**空**。\n",
        "git grep 撑扫描面层面": "# ⇒ 已订正\n# 扫描面内没有同名 def（`git grep 'def <占位>' -- apps/api/tests` 的读数为**空**）。\n",
    }
    for label, text in must_pass.items():
        assert offender_count(text) == 0, f"修好后的写法仍被判违规（假红会逼人放宽规则）：{label}"

    # —— ★ 层面判据【不得】由读数措辞外推：三条同断言、只换读数措辞的真话 ——
    same_claim_different_wording = {
        "读数是空": "# ⇒ 已订正\n# 该文件从未被创建过：`git log --all -- '*x*'` 的读数是**空**。\n",
        "零命中": "# ⇒ 已订正\n# 该文件从未被创建过：`git log --all --diff-filter=A -- '*x*'` 零命中。\n",
        "为 0": "# ⇒ 已订正\n# 该文件从未被创建过：`git log --all --diff-filter=A -- '*x*'` 为 0。\n",
    }
    for label, text in same_claim_different_wording.items():
        assert offender_count(text) == 0, f"文件层面 + 正确路径型命令的真话被误伤（层面判据在用读数措辞外推）：{label}"
    # 非零读数同样不得被当成「用例层面」（`命中 20 个提交` 是真读数）
    for wording in ("该命令命中 20 个提交。", "该命令命中 100 处。"):
        assert not _CASE_LEVEL_ABSENCE.search(wording), f"非零读数被误判成用例层面：{wording}"

    # —— 行为陈述：本仓真实存在的措辞，不得被要求引 git 命令 ——
    behaviour = (
        "# 改密返回任何非 OK 结果都必须显式失败，且不得撤销会话。\n"
        "# 漏注入不可恢复（使用者此后没有任何入口回到引导）。\n"
        "# 参数声明在解析器里、却从未往下传：产出的 frontmatter 仍是页面元数据。\n"
    )
    assert offender_count(behaviour) == 0, "运行时行为的陈述被误当成「核过仓库」的断言"

    # —— ★ 单元合并：三种行距各一个断言（窗口的边界必须双向钉住） ——
    merged = _merged_annotations(
        "#: **⚠ 2026-10-06 订正**：此处曾点名一个从未存在过的测试文件\n"
        "#: （`git log --all --diff-filter=A` 零命中），被后来的守卫抓出。\n"
    )
    assert len(merged) == 1, f"相邻注释行没有被合并成一个单元：{merged}"
    assert _GIT_COMMAND.search(merged[0][1]), "合并后应当能看见下一行的命令"
    # ① 中间【一个空行】必须合并（否则真实形态「断言 / 空行 / 命令」会假红）
    one_blank = _merged_annotations('# ⇒ 已订正\n# 断言。\n\n# `git log --all -S "def x"` 读数是空。\n')
    marked = [t for _, t in one_blank if _CORRECTION_MARK.search(t)]
    assert len(marked) == 1 and _GIT_COMMAND.search(marked[0]), f"隔一个空行没有合并（会假红）：{one_blank}"
    # ② 中间【两个空行】不得合并（否则会蹭到明显分属两段的其他块命令 ⇒ 漏报）
    two_blank = _merged_annotations('# ⇒ 已订正\n# 断言。\n\n\n# `git log --all -S "def x"` 读数是空。\n')
    marked2 = [t for _, t in two_blank if _CORRECTION_MARK.search(t)]
    assert not any(_GIT_COMMAND.search(t) for t in marked2), f"隔两个空行也被合并了（会蹭命令）：{two_blank}"
    # ③ 合并必须保持行号对齐：第 N 行片段要落在 unit 起始行 + N 上
    aligned = _merged_annotations("# a\n\n# b\n")
    start, text = aligned[0]
    assert text.count("\n") == 2, f"合并时没有按换行补回间隔（行号会错位）：{text!r}"
    assert [start + i for i, _ in enumerate(text.splitlines())] == [1, 2, 3], f"行号错位：{aligned}"
    # ④ ★ M1b（未覆盖）：窗口只看行号差，**不问那 1 行是空行还是代码行** ⇒
    #    「断言 / 1 行代码 / 命令」也合并。这是**登记在案的漏报方向**，不是已修；
    #    把它断言下来是为了让声明与行为对得上（本包禁止「文档说有、行为没有」）。
    one_code = _merged_annotations('# ⇒ 已订正\n# 断言。\nx = 1\n# `git log --all -S "def x"` 读数是空。\n')
    marked3 = [t for _, t in one_code if _CORRECTION_MARK.search(t)]
    assert len(marked3) == 1 and _GIT_COMMAND.search(marked3[0]), (
        f"隔 1 行代码没有合并 ⇒ M1b 的登记理由（「容忍代码行会制造假关联」）与实测不符：{one_code}"
    )
    # ⑤ ★ M5（未覆盖）：合并判据对**块总长无上界**——200 行连续注释仍是同一个单元。
    #    这是 P2-3（同单元内远距诱饵命令）成立的机制；M4 的「必须同一单元」挡不住它。
    long_block = "".join(f"# 连续注释行 {i}\n" for i in range(200))
    long_units = _merged_annotations(long_block)
    assert len(long_units) == 1, f"200 行连续注释不再是同一个单元 ⇒ M5 的机制描述不成立：{len(long_units)}"
    assert long_units[0][1].count("\n") + 1 == 200, "长块的行数读数与实测不符"

    # —— ★★★ P1-1：`_GIT_COMMAND` 的**行为**必须与它紧邻 docstring 一致 ——
    #   上一版 docstring 自称「且带实际参数」，而正则对参数【零要求】⇒ 裸命令全部放行
    #   ⇒ 「文档说有、行为没有」（本包第 7 轮修的那处假话）。
    #   这里把 docstring 那句声明（「至少带一个参数」）**做成机械判据**：
    #   被挡住的样本表就是「无参数」这一侧，被放行的样本表就是「有参数」这一侧。
    #   ⚠ 两侧都要断言：只断言「有参数放行」会让上一版那个空心的 `[^`]*` 全绿。
    for command in ("`git log`", "`git show`", "`git grep`", "`git blame`"):
        assert not _GIT_COMMAND.search(command), (
            f"{command} 没有参数却被判为「真能复算的 git 命令」⇒ 判据行为与 docstring 的「至少带一个参数」不符"
        )
    # ⚠ 「只有空白、没有任何实参」必须挡住。**实测两版差异**（本包第 7 轮）：
    #   `\s+[^`]+` 与 `\s+\S[^`]*` 在**单个**尾随空白上读数相同（都挡住 `git log `），
    #   差别只在**连续 ≥2 个空白**——前一版会把 `git log  ` 当成「有参数」。
    #   ⇒ 下面这组样本是那个漏洞的对照组：去掉 `\S` 就会整组变绿（见本轮消融变异 2）。
    for padded in ("`git log `", "`git log  `", "`git blame  `", "`git log\n\n`", "`git log \n`"):
        assert not _GIT_COMMAND.search(padded), f"{padded!r} 只有空白却被判为「有参数」⇒ 参数判据没有要求非空白字符"
    for command in (
        "`git log --oneline -1`",
        "`git log --all --diff-filter=A`",
        '`git log --all -S "def x"`',
        "`git grep -l '订正' HEAD -- '*.py'`",
    ):
        assert _GIT_COMMAND.search(command), f"{command} 有参数却被挡住（判据过紧，会制造假红）：{command}"
    # 正控的另一半：非白名单子命令即便带参数也必须挡住（否则「只要求子命令名」也读不通）
    for command in ("`git status --short`", "`git help log`", "`git diff HEAD~1`"):
        assert not _GIT_COMMAND.search(command), f"{command} 不在白名单内却被放行"
    # ★ 但**收紧正则不等于判据足够强**（docstring 已登记）：缺 pathspec 的命令完全合格，
    #   却撑不起「零命中」——本包实测它命中的是全仓所有新增文件（随历史单调增长）。
    assert _GIT_COMMAND.search("`git log --all --diff-filter=A`"), "该反例必须仍合判据（否则登记的那条能力边界不成立）"

    # —— ★ 覆盖面：**必须用变异验证**，而不是独立 rglob 一遍 ——
    # 上一版那条断言【独立 rglob】、与主循环解耦 ⇒ 实测「把主循环改成只扫一棵树」它仍全绿
    # （它防的是「树里没料」，不是「只扫一棵树」）。
    # ⇒ 现在规则里的「实际」来自 `_correction_scan` 的返回值，「期望」是**字面量**；
    #    这里把同一对判据**镜像**一遍，并用变异证明它真的会红。
    # ⚠ 期望值写成字面量（与规则内一致），**不从 `_CORRECTION_TREES` 推导**——
    #   推导会让期望与实际同源，变异时两边一起变、判据永远为真（这正是上一版的病）。
    claimed_trees = ["src/campfire", "apps/api/tests"]  # noqa: 字面量是刻意的
    _, scanned_full = _correction_scan(_CORRECTION_TREES)
    assert scanned_full == claimed_trees, f"主循环没有扫全对外声称的两棵树：{scanned_full}"
    # 变异：只扫测试树 ⇒ 「实际」必须与「声称」不一致（判据因此会红）
    _, scanned_narrowed = _correction_scan((_CORRECTION_TREES[1],))
    assert scanned_narrowed != claimed_trees, (
        f"变异（只扫一棵树）没有让「实际 vs 声称」不一致 ⇒ 该判据防不住这个跟头：{scanned_narrowed}"
    )
    # 两棵树都必须真的有料，否则「扫两棵树」在效果上等于只扫一棵
    for label, root in _CORRECTION_TREES:
        has_material = any(_CORRECTION_MARK.search(p.read_text(encoding="utf-8")) for p in root.rglob("*.py"))
        assert has_material, f"{label} 树里一个含订正说明的文件都没有 ⇒ 该树进扫描面是空跑"

    # —— ★★ 行为陈述：`零命中` 这类【读数】措辞在运行时行为里也用，不得因此被判「核过仓库」 ——
    for label, text in {
        "候选集零命中": "# ⇒ 已订正\n# 候选集零命中时返回空列表。\n",
        "查询零命中": "# ⇒ 已订正\n# 查询零命中即返回空。\n",
    }.items():
        assert not _repo_absence_in(text), f"运行时行为的「零命中」被误判成仓库断言：{label}"
    # 正控：同一措辞在**仓库语境**下必须被判为仓库断言
    for label, text in {
        "命令后零命中": "# 由 `git log --all -- '*x*'` 零命中\n",
        "全仓搜索零命中": "# 全仓搜索零命中\n",
    }.items():
        assert _repo_absence_in(text), f"仓库语境的「零命中」没有被认出来：{label}"

    # —— ★★ M6（未覆盖，P2-2）：**部分/量化断言**整类落在判据之外 ——
    #   「全仓只有 3 个文件…」既不是 `_REPO_ABSENCE` 的全称否定形状、也不含 `零命中`
    #   ⇒ `_repo_absence_in` 为 False ⇒ 规则**看不见它**，无论引没引命令。
    #   它与裸 `git log`（M2/M2b）同族：**断言强度 > 证据强度**，故并入同一张「仍会漏的」表。
    #   ⚠ 下面同时给**正控**：句子换成真全称否定必须被认出——否则 False 可能只是装置坏了。
    for quantified in (
        "# 全仓只有 3 个文件引用了这个符号。\n",
        "# 全仓有 3 个文件引用了这个符号。\n",
        "# 全仓绝大多数文件都没引用它。\n",
    ):
        assert not _repo_absence_in(quantified), (
            f"这条量化断言被判进了仓库断言 ⇒ M6 的登记（「整类在判据之外」）与实测不符：{quantified!r}"
        )
    for universal in ("# 该名字全仓不存在。\n", "# 全仓没有它。\n"):
        assert _repo_absence_in(universal), f"正控失败：真全称否定没被认出 ⇒ 上面那组 False 读数不可信：{universal!r}"
