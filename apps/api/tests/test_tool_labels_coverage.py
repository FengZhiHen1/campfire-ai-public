"""工具行文案词表的完整性核对：前端中文友好名必须覆盖工具清单（含基座保留名）。

职责：把「工具清单」与「前端词表的键集合」两个方向都关上，并核对输出格式纪律已接进
每一条运行路径。

为什么需要这个文件（它挡的是什么）：OBS-01 的修复是「标识符 → 中文友好名」的映射，
而映射的失败形态是**静默的**——新增一个工具、忘了加映射，界面会走兜底文案
（`其他操作 · 已结束`）而不是报错。这正是项目禁止的「永远不会失败的检查」的隐蔽形态：
没有这条断言时，词表缺项在任何测试里都看不见，只有在真实对话里才表现为「这一行不像话」。

因此这里的断言是**跨语言集合相等**，不是「抽查几个键存在」：
- 左：`registry.build_product_tools()`（产品侧注册清单，真源）+ `pool.RESERVED_TOOL_NAMES`
  （基座保留名工具，同样经 `ToolBridge` 发出 `tool_call_*` 事件，因此同样会开出 `.tool-row`）；
- 右：`apps/web/.../MessageParts/toolLabels.ts` 里 `TOOL_LABELS` 的键集合。

判别性（本文件的用例必须真的会红）：往 `registry.build_product_tools` 里加一个工具
而不动前端词表 ⇒ `test_tool_labels_cover_every_product_tool` 失败。
`test_coverage_assertion_goes_red_on_a_new_unmapped_tool` 就是这条判别性的**自测**——
它用一份人为多出一个工具的清单去跑同一个比较函数，断言比较真的报出缺项。
没有这个自测，「完整性断言」本身可能是一条恒真的空闸门（例如正则没匹配到任何键、
于是两边都空集而「相等」），而那正是本项目明令禁止的形态。

数据来源：
- apps/api/src/campfire/surfaces/consult/registry.py: MUST — 产品侧工具清单（十个）
- apps/api/src/campfire/agent/tools/pool.py: MUST — 基座保留名工具（三个）
- apps/web/src/features/consult/view/MessageParts/toolLabels.ts: MUST — 前端词表（被核对对象）
- apps/web/src/features/consult/view/MessageParts/parts.tsx: MUST — 前端不渲染 markdown
  （正文纪律落地的依据：只按空行切段）
"""

from __future__ import annotations

import re
from pathlib import Path

from campfire.agent.tools.pool import RESERVED_TOOL_NAMES
from campfire.surfaces.consult.assembly import CONSULT_INSTRUCTIONS
from campfire.surfaces.consult.registry import build_product_tools

#: 仓库根：本文件位于 <根>/apps/api/tests/，故 parents[3]。
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: 前端词表文件（被核对对象）。
_TOOL_LABELS_TS = (
    _REPO_ROOT / "apps" / "web" / "src" / "features" / "consult" / "view" / "MessageParts" / "toolLabels.ts"
)

#: 前端正文渲染器（B 的判据依据：它不做行内解析）。
_PARTS_TSX = _REPO_ROOT / "apps" / "web" / "src" / "features" / "consult" / "view" / "MessageParts" / "parts.tsx"

#: 咨询面路由（两个 `RunRequest` 构造点都在这里）。
_ROUTES_PY = _REPO_ROOT / "apps" / "api" / "src" / "campfire" / "surfaces" / "consult" / "routes.py"

#: `TOOL_LABELS` 对象字面量里的键。只认 「  key: '值' 」这种一行一条的写法
#: （与该文件的既有风格一致）；`FALLBACK_TOOL_LABEL` 等不在该对象内的行不会命中，
#: 因为匹配范围先被 `_tool_labels_block` 收窄到对象内部。
_LABEL_ENTRY_PATTERN = re.compile(r"^\s{2}([a-z][a-z0-9_]*):\s*'", re.MULTILINE)


def _tool_labels_block() -> str:
    """取出 `toolLabels.ts` 里 `export const TOOL_LABELS ... = { ... };` 的正文。

    Raises:
        AssertionError: 找不到对象字面量（文件被改名或结构变了——此时必须失败而不是空集通过）。
    """
    source = _TOOL_LABELS_TS.read_text(encoding="utf-8")
    match = re.search(
        r"export const TOOL_LABELS[^=]*=\s*\{(?P<body>.*?)\n\};",
        source,
        re.DOTALL,
    )
    assert match is not None, (
        f"在 {_TOOL_LABELS_TS} 里找不到 TOOL_LABELS 对象字面量。"
        "本用例的判据依赖它的形状——结构变了要同步更新这里的解析，"
        "不能让正则失配后变成「空集 vs 空集」的恒真检查。"
    )
    return match.group("body")


def frontend_tool_label_keys() -> set[str]:
    """解析前端词表的键集合。

    Raises:
        AssertionError: 解析出 0 个键（正则失配）——0 个键必须失败，不能静默通过。
    """
    keys = set(_LABEL_ENTRY_PATTERN.findall(_tool_labels_block()))
    assert keys, (
        f"在 {_TOOL_LABELS_TS} 的 TOOL_LABELS 里解析出 0 个键。"
        "解析失配会让「覆盖检查」变成恒真的空闸门，因此这里直接失败。"
    )
    return keys


def expected_tool_names() -> set[str]:
    """界面可能开出工具行的全部工具标识符。

    两个来源的并集，理由见模块 docstring：产品侧工具与基座保留名工具都会发
    `tool_call_started/finished`，因此都可能出现在 `.tool-row` 上。
    """
    return {tool.name for tool in build_product_tools()} | set(RESERVED_TOOL_NAMES)


def missing_labels(expected: set[str], mapped: set[str]) -> set[str]:
    """`expected` 里没有中文名的工具。抽成函数是为了让判别性自测能跑同一段比较逻辑。"""
    return expected - mapped


# ---------------------------------------------------------------------------
# 1. 完整性：工具清单 ⊆ 前端词表
# ---------------------------------------------------------------------------


def test_tool_labels_cover_every_product_tool() -> None:
    """产品侧十个工具全部有中文友好名。

    判别性：往 `registry.build_product_tools()` 加一个工具而不动前端词表 ⇒ 本用例失败
    （缺项会走兜底文案，界面上看不出错误，所以必须在这里挡住）。
    """
    mapped = frontend_tool_label_keys()
    missing = missing_labels({tool.name for tool in build_product_tools()}, mapped)
    assert not missing, (
        f"前端 toolLabels.ts 缺少这些产品工具的显示名：{sorted(missing)}。"
        "新增工具必须同时给面向使用者的中文名（OBS-01：界面不得暴露内部标识符）。"
    )


def test_tool_labels_cover_every_reserved_base_tool() -> None:
    """基座三个保留名工具也全部有中文友好名（它们同样会开出工具行）。"""
    mapped = frontend_tool_label_keys()
    missing = missing_labels(set(RESERVED_TOOL_NAMES), mapped)
    assert not missing, f"前端 toolLabels.ts 缺少这些基座保留名工具的显示名：{sorted(missing)}"


def test_tool_labels_have_no_stale_entries() -> None:
    """反方向：词表里的键必须都是真实存在的工具（已下线的工具名要清掉）。

    与上面的子集检查合起来两个方向都关上——多一个或少一个都会失败。
    残留的键会让「这个工具还在」这件事在代码里继续成立，而它已经没有实现。
    """
    mapped = frontend_tool_label_keys()
    stale = mapped - expected_tool_names()
    assert not stale, f"前端 toolLabels.ts 含并不存在的工具名（已下线？）：{sorted(stale)}"


def test_tool_labels_key_set_equals_the_full_tool_set() -> None:
    """词表键集合 == 产品工具 ∪ 基座保留名（集合相等，不只是包含）。"""
    mapped = frontend_tool_label_keys()
    assert mapped == expected_tool_names(), (
        f"词表与工具清单不一致：多 {sorted(mapped - expected_tool_names())}，"
        f"缺 {sorted(expected_tool_names() - mapped)}"
    )


# ---------------------------------------------------------------------------
# 2. 判别性自测：断言本身必须会红（反「恒真空闸门」）
# ---------------------------------------------------------------------------


def test_coverage_assertion_goes_red_on_a_new_unmapped_tool() -> None:
    """模拟「新增工具但没加映射」：同一个比较逻辑必须报出缺项。

    为什么需要这条：完整性断言最危险的失败形态不是漏报缺陷，而是**它自己恒真**
    （正则失配、两边都空集、比较写反）。这里用两组**合成集合**跑生产代码路径用的
    同一个 `missing_labels`，确认它确实报出缺项。

    为什么用合成集合而不是「真实清单 + 一个假工具」：后者会让这条自测**依赖真实工具清单**
    ——真实新增一个工具时，本用例会因为那个真实缺项而失败，从而把「自测」与「被自测的
    财产」搅在一起（消融实测确实如此）。自测应当只检验比较逻辑本身，因此两边都自造。
    """
    mapped = {"tool_a", "tool_b"}
    hypothetical = {"tool_a", "tool_b", "tool_c"}

    missing = missing_labels(hypothetical, mapped)

    assert missing == {"tool_c"}, (
        "完整性比较在「新增工具未加映射」时应当报出恰好那个缺项；"
        f"实际得到 {sorted(missing)}——说明这条断言不能真的挡住漏加映射。"
    )
    # 反向：不该把已映射的工具报成缺项（比较写反的另一半）。
    assert missing_labels(mapped, hypothetical) == set()


def test_label_key_parser_actually_parses() -> None:
    """解析器必须真的解析出词表内容（0 个键即时失败）。"""
    keys = frontend_tool_label_keys()

    # 十个产品工具是硬基线：解析出少于这个数说明解析器已经失配。
    assert len(keys) >= len(build_product_tools()), (
        f"从前端词表只解析出 {len(keys)} 个键，少于产品工具数 {len(build_product_tools())}——解析器大概已经失配。"
    )
    # 词表至少覆盖产品侧全部工具（与上面的完整性用例同源，此处只保证解析非空且合理）。
    assert {tool.name for tool in build_product_tools()} <= keys


# ---------------------------------------------------------------------------
# 3. B：正文输出格式纪律（位置 + 内容 + 接线）
# ---------------------------------------------------------------------------


def test_consult_instructions_forbid_markdown_emphasis_markers() -> None:
    """面提示必须明确禁止 markdown 标记，且点名界面无法渲染的那些记号。

    判据基于「哪些记号是界面渲染不出来、会原样显示给使用者的」——前端
    `parts.tsx` 的 `TextPart` 只按空行切段（不做行内解析），因此下列记号都会原样露出。
    只断言「提到了格式」会漏掉真正要防的东西，所以逐个点名。
    """
    for marker in ("**", "*", "#", "`"):
        assert marker in CONSULT_INSTRUCTIONS, (
            f"正文格式纪律没有点名禁止 {marker!r}——它在当前前端（不解析 markdown）下会原样显示。"
        )

    # 「纯文本」是这条纪律的立场本身；只列记号不说结论，模型可能理解成「换种写法」。
    assert "纯文本" in CONSULT_INSTRUCTIONS
    assert "markdown" in CONSULT_INSTRUCTIONS


def test_frontend_really_does_not_render_markdown() -> None:
    """B 选 b1（提示词侧禁止）的前提是前端确实不渲染 markdown。

    这里核对两件事，任一不成立则「禁止标记」这条纪律的前提已经变了（应改走渲染路线）：
    1. `parts.tsx` 的正文渲染还是「只按空行切段」的形状；
    2. `apps/web/package.json` 里没有引入 markdown 渲染库。

    为什么核对依赖：若将来前端加了 markdown 库，这条纪律就从「必要」变成「多余」，
    而那时本用例失败会把这个前提变化摆到明面上，而不是让它悄悄过期。
    """
    parts_source = _PARTS_TSX.read_text(encoding="utf-8")
    assert "text.split(/\\n{2,}/)" in parts_source, (
        "前端正文渲染器不再是「只按空行切段」的形状——B 的位置裁决前提已变，请复核。"
    )

    package_json = (_REPO_ROOT / "apps" / "web" / "package.json").read_text(encoding="utf-8")
    for library in ("markdown", "remark", "marked", "markdown-it", "rehype"):
        assert library not in package_json, (
            f"前端已引入 {library}——若确实改为渲染 markdown，正文纪律的位置裁决需要重新评估。"
        )


def test_both_run_paths_share_the_same_instructions() -> None:
    """日常发消息与应急入口两个 `RunRequest` 都必须带这份提示（否则是半修）。

    只改一处会留下「日常不显示星号、应急照样显示」的形态：应急由
    `emergency-consulting` 承担、日常由 `daily-consulting` 承担，两条路径的正文
    都经同一份面提示。这也覆盖 `onboarding`（它走日常发消息那条路径）。
    """
    routes_source = _ROUTES_PY.read_text(encoding="utf-8")
    uses = routes_source.count("instructions=assembly.CONSULT_INSTRUCTIONS")

    assert uses == 2, (
        f"预期两个 `RunRequest` 都用 `assembly.CONSULT_INSTRUCTIONS`，实际 {uses} 处。"
        "少一处意味着该路径的正文不受格式纪律约束（半修）。"
    )
    # 不得有别的字面量提示绕过它（绕过即漏掉纪律）。
    assert 'instructions="' not in routes_source, (
        "routes.py 里出现了内联的 instructions 字面量——它不会带上正文格式纪律。"
    )
