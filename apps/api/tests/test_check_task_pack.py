"""`scripts/check_task_pack.py` 的自检：闸门本身必须能红。

## 为什么需要这个文件

`scripts/check_task_pack.py` 是「任务包出库前的机械自检」，
**它的存在理由是把编排器的 prose 纪律变成会失败的检查**。

**⇒ 但一个闸门若自己可以被静默改坏，那它就是"永远不会失败的检查"** ——
**这正是本项目明令禁止的东西（`AGENTS.md`：禁止留下永远不会失败的检查）。**

**★ 而且这不是假想风险**：该闸门的第一版**恰恰漏掉了它本该抓的那个案例** ——
它没有认出 `- **(b) 给 socket_timeout 一个足够大的值**` 这种枚举形态，
于是把 `T17.md` 判为「通过」。而 `T17.md` 正是 `(z78)` 那次失误的现场
（编排器把一个**实测证明原理上不可行**的方案列成了可选项）。

**⇒ 本文件把「闸门必须抓到 T17」钉死。** 若有人（或未来的我）削弱了匹配规则，
**这些用例会红**。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _find_repo_root() -> Path:
    """向上找仓库根：同时含 `pyproject.toml` 与 `scripts/` 的那一层。

    为什么不用 `parents[N]` 写死层数：本文件在 `apps/api/tests/` 下，层数是 3，
    而**写死层数会在目录调整时静默指向错误位置**（第一版写 `parents[2]`，
    于是去 `apps/scripts/` 找，直接 `FileNotFoundError`）。
    **⇒ 按【特征】定位比按【层数】定位更能自我校验**：找不到就立刻失败，不会指错地方。
    """
    required = ("pyproject.toml", "scripts")
    for path in Path(__file__).resolve().parents:
        if all((path / marker).exists() for marker in required):
            return path
    raise RuntimeError(f"未能在 {Path(__file__).resolve()} 的上级目录中找到仓库根")


_REPO_ROOT = _find_repo_root()
_SCRIPT = _REPO_ROOT / "scripts" / "check_task_pack.py"


def _load_script() -> ModuleType:
    """按路径加载脚本（`scripts/` 不是包，无法 import）。"""
    spec = importlib.util.spec_from_file_location("check_task_pack", _SCRIPT)
    assert spec is not None and spec.loader is not None, f"无法加载 {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    return _load_script()


class TestGateCatchesTheRealHistoricalCase:
    """★ 核心用例：闸门必须抓到 `(z78)` 的真实现场。

    这是本文件的立命之本 —— 若它红，说明闸门退化了。
    """

    def test_t17_option_enum_without_verification_marker_is_flagged(self, gate: ModuleType) -> None:
        """`T17` 的 `(b)` 方案没标注「已验证/未验证」⇒ 必须被报出。

        原文（`facts.md` 的 `(z78)`）：
        > 我在 `T17.md` 里把「给 `socket_timeout` 一个足够大的值」列为候选方案 (b)，
        > 而**执行者用实测证伪了它**（`socket_timeout=15` 只是把崩溃周期从约 10 秒
        > 拉长到约 20 秒，仍然崩）。
        """
        text = (
            "## 修法取舍\n\n"
            "- **(a) `socket_timeout=None`**：简单、能消除崩溃；代价是失去「卡死检测」；\n"
            "- **(b) 给 `socket_timeout` 一个足够大的值**（例如远大于正常 RTT）；\n"
            "- **(c) 别的做法**（例如 `health_check_interval`）——若你选这条，请给出上游依据。\n"
        )
        problems = gate.check_options_annotated(text)
        assert problems, "闸门漏掉了未标注验证状态的候选方案枚举 ⇒ 退化成了永不失败的检查"
        assert any("(b)" in p for p in problems), f"未报出 (b)：{problems}"

    def test_option_enum_with_verification_marker_passes(self, gate: ModuleType) -> None:
        """标注了验证状态 ⇒ 不应报出（否则闸门会变成噪音源，被忽略）。"""
        text = (
            "## 修法取舍\n\n"
            "- **(a) `socket_timeout=None`**：**已实测**能消除崩溃，但失去卡死检测；\n"
            "- **(b) 给一个足够大的值**：**已实测证伪** —— 有限读超时迟早触发，不存在这样的值；\n"
        )
        assert gate.check_options_annotated(text) == []


class TestGateDoesNotCryWolf:
    """误报会被忽略，而会被忽略的闸门等于没有。"""

    def test_instruction_to_the_executor_is_not_a_product_requirement(self, gate: ModuleType) -> None:
        """「**你必须**先用真实栈区分四种假设」是【给执行者的指令】，不是产品要求。"""
        text = "**⇒ 你必须先用真实栈把以下四种假设区分开**（贴真实读数）：\n"
        assert gate.check_requirement_kind(text) == []

    def test_markdown_heading_is_not_a_product_requirement(self, gate: ModuleType) -> None:
        """标题行是文档结构，不是「产品必须拒绝 X」这类要求。"""
        text = "### 附：还有一个**必须写进去**的已知问题\n"
        assert gate.check_requirement_kind(text) == []

    def test_bare_product_requirement_without_kind_is_flagged(self, gate: ModuleType) -> None:
        """产品的硬要求若不说清结果/机制，应当被报出（`(z76)` 的教训）。"""
        text = "新校验器必须拒绝空值。\n"
        problems = gate.check_requirement_kind(text)
        assert problems, "闸门漏掉了「未区分结果与机制」的产品硬要求"


class TestGateCatchesUnverifiedCompletionClaims:
    """`(z94)` 的教训：编排器把「在途」写成了「已完成」7 项，实际只落地 4 项。"""

    def test_completion_count_without_verification_demand_is_flagged(self, gate: ModuleType) -> None:
        text = "本轮共修 7 项（四项已修 + 三项在途）。\n"
        problems = gate.check_counts_verified(text)
        assert problems, "闸门漏掉了未要求当场核实的完成数"

    def test_completion_count_with_verification_demand_passes(self, gate: ModuleType) -> None:
        text = "本轮共修 7 项（**具体哪些已修以代码为准，请自己核**）。\n"
        assert gate.check_counts_verified(text) == []


class TestGateCatchesBodyPathsMissingFromScope:
    """`(z161)` 的教训：T27 的 §正文点名了两个文件，§授权范围却没列它们。

    ⇒ 执行者会面临「照正文做 = 越界 / 照清单做 = 没完成」的两难。
    它当时选了"照正文做且不碰硬禁区"（对），但那是靠它的判断力兜住的。
    """

    #: 一份"正文点名了 memory.py / runner.py，授权里只有 session_items.py"的合成包。
    _MISMATCHED = (
        "## 三、你要做的\n"
        "你要改 `apps/api/src/campfire/tools/memory.py` 与\n"
        "`apps/api/src/campfire/agent/runtime/runner.py`。\n"
        "\n"
        "## 五、授权范围\n"
        "**你可以改**：`apps/api/src/campfire/modules/accounts/session_items.py`、\n"
        "相应的测试文件。\n"
        "**⚠ 不要碰**：`docs/**`。\n"
    )

    def test_body_path_absent_from_scope_is_flagged(self, gate: ModuleType) -> None:
        """正文点名、授权未列 ⇒ 必须报出（这正是 `(z161)` 那次）。"""
        problems = gate.check_scope_matches_body(self._MISMATCHED)
        joined = "\n".join(problems)
        assert "memory.py" in joined, f"闸门漏掉了正文点名的 memory.py：{problems}"
        assert "runner.py" in joined, f"闸门漏掉了正文点名的 runner.py：{problems}"

    def test_body_path_listed_in_scope_passes(self, gate: ModuleType) -> None:
        """同一个文件既在正文又在授权 ⇒ 不该报。"""
        text = self._MISMATCHED.replace(
            "**你可以改**：`apps/api/src/campfire/modules/accounts/session_items.py`、",
            "**你可以改**：`apps/api/src/campfire/tools/memory.py`、\n"
            "`apps/api/src/campfire/agent/runtime/runner.py`、",
        )
        assert gate.check_scope_matches_body(text) == []

    def test_glob_in_scope_covers_body_path(self, gate: ModuleType) -> None:
        """授权里的 `/**` 通配应当覆盖它下面的文件。

        ⚠ 这条来自一次真实的失败：本检查第一版的正则要求"以扩展名结尾"，
        **于是 `.../consult/**` 这种写法抽不出来** ⇒ 通配失效 ⇒
        **把已被通配覆盖的 `answers.py` 误报成"不在授权里"**。
        """
        text = (
            "## 三、你要做的\n"
            "你要改 `apps/api/src/campfire/surfaces/consult/answers.py`。\n"
            "\n"
            "## 五、授权范围\n"
            "**你可以改**：`apps/api/src/campfire/surfaces/consult/**`。\n"
        )
        assert gate.check_scope_matches_body(text) == []

    def test_read_only_reference_is_not_flagged(self, gate: ModuleType) -> None:
        """「**先读** 某文档」是只读指引，不是"要改它"。

        ⚠ 同一个失败的第三半：只看路径不看动词，必然把"读"当成"改"。
        """
        text = (
            "## 三、你要做的\n"
            "**⚠ 若要新增**，**先读 `docs/技术设计/面/consult/HTTP与SSE契约.md`**。\n"
            "\n"
            "## 五、授权范围\n"
            "**你可以改**：`apps/api/src/campfire/modules/accounts/session_items.py`。\n"
        )
        assert gate.check_scope_matches_body(text) == []

    def test_test_file_covered_by_blanket_phrase_passes(self, gate: ModuleType) -> None:
        """授权写「相应的测试文件」时，不该逐个要求列出 `test_*.py`。"""
        text = (
            "## 三、你要做的\n"
            "你要改 `apps/api/tests/test_memory_tools.py`。\n"
            "\n"
            "## 五、授权范围\n"
            "**你可以改**：`apps/api/src/campfire/tools/memory.py`、相应的测试文件。\n"
        )
        assert gate.check_scope_matches_body(text) == []

    def test_run_only_command_is_not_flagged(self, gate: ModuleType) -> None:
        """「跑一下某个既有脚本」是门禁命令，不是「要改它」。

        ⚠ 第三个误报类（`(z204)`）：T31 的 §第 4 步 写
        「`uv run python scripts/check_design_docs.py` / 前端 `lint`+`typecheck`…」——
        那是**运行**仓库既有脚本，`scripts/check_design_docs.py` 根本不在该包授权范围内
        （也不该在）⇒ 只看路径不看谓语，必然把"运行"当成"改"。
        """
        text = (
            "## 三、你要做的\n"
            "跑门禁：`uv run python scripts/check_design_docs.py`。\n"
            "\n"
            "## 五、授权范围\n"
            "**你可以改**：`apps/api/src/campfire/modules/accounts/session_items.py`。\n"
        )
        assert gate.check_scope_matches_body(text) == []

    def test_pack_without_scope_section_reports_undecidable(self, gate: ModuleType) -> None:
        """没有 §授权范围 的任务包 ⇒ `check_*` 返回空（不是 findings），
        但 `_undecidable_notices` 必须报出「判不了」这件事。

        ⚠ 为什么两件事要分开（第五种漏法的修法）：
        ① 旧包（37 份里 26 份没有这一节）**不能判失败** —— 那是早期写法；
        ② 但**静默跳过会让本检查在旧包上恒绿**，而"恒绿"与"通过"读数完全一样
           （`(z155)`）。
        ⇒ 取中间态：**提示可见、但不改退出码**。
        """
        text = "## 三、你要做的\n你要改 `apps/api/src/campfire/tools/memory.py`。\n"
        # 不产生 findings（不误伤旧包）
        assert gate.check_scope_matches_body(text) == []
        # 但必须可见
        notices = gate._undecidable_notices(text)
        assert len(notices) == 1
        assert "判不了" in notices[0]

    def test_undecidable_notice_does_not_change_exit_code(self, gate: ModuleType, tmp_path: Path) -> None:
        """「判不了」的提示不得让退出码变成非 0（否则 26 份旧包全红）。"""
        p = tmp_path / "旧包.md"
        p.write_text(
            "## 三、你要做的\n你要改 `apps/api/src/campfire/tools/memory.py`。\n",
            encoding="utf-8",
        )
        assert gate.main(["check_task_pack.py", str(p)]) == 0

    def test_module_level_markers_match_the_check(self, gate: ModuleType) -> None:
        """模块级 `_SCOPE_MARKERS`/`_BODY_MARKERS` 必须与检查体里用的两份一致。

        ⚠ 这是防"两份定义漂移"的自检：它们描述同一件事，却存在于两处。
        """
        assert gate._SCOPE_MARKERS == ("授权范围", "你可以改")
        assert gate._BODY_MARKERS == ("要做的", "你要做", "修法", "第 0 步", "第 1 步")
        # 一致性：同一个"无授权节 + 有正文标记"的输入，两边都得认为它没有授权节
        text = "## 三、你要做的\n你要改 `apps/api/src/campfire/tools/memory.py`。\n"
        assert not any(m in text for m in gate._SCOPE_MARKERS)
        assert any(m in text for m in gate._BODY_MARKERS)

    def test_note_without_body_markers_stays_silent(self, gate: ModuleType) -> None:
        """不是任务包（没有正文标记）的文档 ⇒ 保持静默，不对随手笔记报提示。"""
        text = "# 随手记\n今天看了 `apps/api/src/campfire/tools/memory.py`，没别的事。\n"
        assert gate.check_scope_matches_body(text) == []
        assert gate._undecidable_notices(text) == []

    def test_scope_section_before_body_is_still_checked(self, gate: ModuleType) -> None:
        """§授权范围 写在正文【之前】时，正文仍要检查。

        ⚠ 第四种漏法（`(z204)`）：第一版取 `lines[:scope_start]` 当正文 ⇒
        授权节在前时正文是空串 ⇒ **检查恒绿**（而"恒绿"与"通过"读数一样）。
        """
        text = (
            "## 五、授权范围\n"
            "**你可以改**：`apps/api/src/campfire/modules/accounts/session_items.py`。\n"
            "\n"
            "## 三、你要做的\n"
            "你要改 `apps/api/src/campfire/tools/memory.py`。\n"
        )
        problems = gate.check_scope_matches_body(text)
        assert len(problems) == 1
        assert "memory.py" in problems[0]

    def test_bare_directory_in_scope_covers_its_files(self, gate: ModuleType) -> None:
        """授权以裸目录 `…/consult/` 给出时，它下面的文件算已授权（第六种漏法）。"""
        text = (
            "## 三、你要做的\n"
            "你要改 `apps/api/src/campfire/surfaces/consult/answers.py`。\n"
            "\n"
            "## 五、授权范围\n"
            "**你可以改**：`apps/api/src/campfire/surfaces/consult/`。\n"
        )
        assert gate.check_scope_matches_body(text) == []

    def test_same_file_both_allowed_and_forbidden_is_flagged(self, gate: ModuleType) -> None:
        """同一文件同时列在「可以改」与「不要碰」⇒ 自相矛盾（第七种漏法）。

        ⚠ 它比"正文点名但未授权"更隐蔽：执行者照哪一句做都会被另一句判成越界。
        """
        text = (
            "## 三、你要做的\n"
            "你要改 `apps/api/src/campfire/modules/accounts/session_items.py`。\n"
            "\n"
            "## 五、授权范围\n"
            "**你可以改**：`apps/api/src/campfire/modules/accounts/session_items.py`。\n"
            "**⚠ 不要碰**：`apps/api/src/campfire/modules/accounts/session_items.py`。\n"
        )
        problems = gate.check_scope_matches_body(text)
        assert len(problems) == 1
        assert "自相矛盾" in problems[0]


class TestGateExitCodes:
    """退出码语义：发现问题必须【非 0】（CI 风格，不是告警）。"""

    def test_missing_file_is_usage_error(self, gate: ModuleType, tmp_path: Path) -> None:
        assert gate.main(["check_task_pack.py", str(tmp_path / "不存在.md")]) == 2

    def test_no_arguments_is_usage_error(self, gate: ModuleType) -> None:
        assert gate.main(["check_task_pack.py"]) == 2

    def test_clean_pack_passes(self, gate: ModuleType, tmp_path: Path) -> None:
        pack = tmp_path / "T99.md"
        pack.write_text("# T99\n\n只改一个文件。\n", encoding="utf-8")
        assert gate.main(["check_task_pack.py", str(pack)]) == 0

    def test_dirty_pack_fails(self, gate: ModuleType, tmp_path: Path) -> None:
        pack = tmp_path / "T99.md"
        pack.write_text(
            "- **(a) 方案甲**\n- **(b) 方案乙**\n",
            encoding="utf-8",
        )
        assert gate.main(["check_task_pack.py", str(pack)]) == 1
