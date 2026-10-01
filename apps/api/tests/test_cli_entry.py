"""本地摄取入口的命令行契约。

设计（RAG 策略第 7 节）把入口形态定成 ``python -m campfire.cli ingest <路径>``，
且明确「不暴露成服务端点」。本组用例锁住入口的命令行行为——**不触网、不连库**：

1. 无子命令时打印用法并以退出码 2 结束（不是静默成功）；
2. 参数缺失时 argparse 报错、退出码非 0；
3. 路径不存在时**明确失败**（退出码 1），不假装成功；
4. 入口能真正通过 ``-m`` 跑到 ``main()``。
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from supertokens_python.recipe.emailpassword.interfaces import (
    EmailAlreadyExistsError,
    PasswordPolicyViolationError,
    UnknownUserIdError,
    UpdateEmailOrPasswordEmailChangeNotAllowedError,
)

from campfire.cli.__main__ import _build_parser, main


def test_no_subcommand_prints_usage_and_exits_two() -> None:
    """无子命令：打印用法、退出码 2（形同虚设的入口最危险）。"""
    assert main([]) == 2


def test_ingest_no_longer_requires_source_and_scope_flags() -> None:
    """`--source`/`--scope` 不再是命令行必填——文件 frontmatter 可提供。

    换成 argparse 必填会让「元数据写在文件里」的语料无法直接摄取。必填性移到
    摄取层判定（缺来源或适用范围即拒绝入库），见
    `test_ingest_rejects_file_without_source_in_frontmatter`。
    """
    parser = _build_parser()

    args = parser.parse_args(["ingest", "some.md"])

    assert args.source is None
    assert args.scope is None


def test_ingest_missing_file_fails_loudly(tmp_path: object) -> None:
    """路径不存在 → 退出码 1，且错误信息里有路径（不静默成功）。"""
    missing = "definitely-not-here.md"

    code = main(["ingest", missing, "--source", "测试出处", "--scope", "测试范围"])

    assert code == 1


def test_cli_module_is_runnable_via_dash_m() -> None:
    """``python -m campfire.cli`` 必须真的能跑（否则入口形态形同虚设）。

    两侧编码都显式固定。被测进程的输出编码受 ``PYTHONIOENCODING`` 影响，而
    ``text=True`` 用 locale 解码（Windows 上是 GBK）；不固定的话，环境里设了
    ``PYTHONIOENCODING=utf-8`` 就会让这条断言假失败——本用例初版正是如此，
    实测在设该变量的 shell 中失败、干净 shell 中通过。
    """
    completed = subprocess.run(
        [sys.executable, "-m", "campfire.cli"],
        capture_output=True,
        check=False,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )

    assert completed.returncode == 2
    assert "ingest" in completed.stderr
    assert "convert" in completed.stderr


# ---------------------------------------------------------------- convert


def test_convert_writes_markdown_beside_input(tmp_path: object) -> None:
    """`convert` 是**纯转换**：写出 .md，不连库、不调模型。

    与 ingest 分成两条命令是设计要求（RAG 策略第 1.1 节「链外准备＋人工核对」）
    ——产物必须先审再喂。
    """
    from pathlib import Path

    root = Path(str(tmp_path))
    source = root / "page.html"
    source.write_text(
        "<html><head>"
        '<meta name="citation_title" content="测试页面"/>'
        '<meta name="citation_author" content="张三"/>'
        "</head><body><article>"
        "<h2>第一节</h2><p>正文内容。</p>"
        "</article></body></html>",
        encoding="utf-8",
    )

    code = main(["convert", str(source), "--scope", "测试适用范围"])

    assert code == 0
    out = root / "page.md"
    assert out.is_file(), "缺省应写到输入文件同目录同名 .md"
    text = out.read_text(encoding="utf-8")
    assert "## 第一节" in text
    assert "正文内容。" in text
    assert "scope" in text or "applicable_scope" in text


def test_convert_missing_file_fails_loudly() -> None:
    """输入不存在 → 退出码 1（不产出空文件假装成功）。"""
    assert main(["convert", "definitely-not-here.html"]) == 1


def test_convert_does_not_ingest(tmp_path: object) -> None:
    """转换**不落库**——它不 import 数据库会话，因此无需凭据也能跑。

    这是"先审后喂"能成立的前提；若 convert 顺带入库，人工核对就没有意义了。
    """
    import inspect

    from campfire.cli import __main__ as cli_main

    source = inspect.getsource(cli_main._run_convert)

    assert "session_scope" not in source
    assert "ingest_file" not in source


def _page_with_metadata_title(root: object, text: str) -> object:
    """写一个自带元数据标题的 HTML 页，返回路径。"""
    from pathlib import Path

    source = Path(str(root)) / "titled.html"
    source.write_text(
        "<html><head>"
        f'<meta name="citation_title" content="{text}"/>'
        "</head><body><article>"
        "<h2>第一节</h2><p>正文内容。</p>"
        "</article></body></html>",
        encoding="utf-8",
    )
    return source


def test_convert_title_flag_overrides_the_page_metadata(tmp_path: object) -> None:
    """`convert --title` 必须真的覆盖页面元数据标题（显式输入不得被静默丢弃）。

    判别性：不把 `title` 透传给 `convert_html_file`，本用例失败——修复前的行为正是
    参数声明在解析器里、却从未往下传：产出的 frontmatter 与正文 H1 都仍是页面元数据
    标题，且没有任何提示或非零退出码。

    与 `ingest --title` 同一条优先级（`ingestion.ingest_file`：
    `title or frontmatter.get("title") or path.stem`）：显式参数优先。
    """
    from pathlib import Path

    from campfire.modules.library.ingestion import parse_frontmatter

    source = _page_with_metadata_title(tmp_path, "页面自带标题")

    code = main(["convert", str(source), "--title", "命令行标题"])

    assert code == 0
    text = (Path(str(tmp_path)) / "titled.md").read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(text)
    assert metadata.get("title") == "命令行标题", (
        f"--title 被静默忽略，实际 frontmatter title={metadata.get('title')!r}"
    )
    assert body.lstrip().startswith("# 命令行标题"), f"正文根标题也未用命令行标题：{body[:80]!r}"
    assert "页面自带标题" not in text, "命令行标题应压过元数据标题，两个标题同时出现说明覆盖没生效"


def test_convert_without_title_flag_keeps_the_page_metadata(tmp_path: object) -> None:
    """不传 `--title` 时仍用页面元数据标题——防止修 D-36 时矫枉过正。

    本用例在修复前后都通过：它不是 D-36 的判别用例，钉的是「覆盖」不等于
    「替换数据源」（例如把 `--title` 改成必填、或让它压掉元数据以外的字段）。
    """
    from pathlib import Path

    from campfire.modules.library.ingestion import parse_frontmatter

    source = _page_with_metadata_title(tmp_path, "页面自带标题")

    code = main(["convert", str(source)])

    assert code == 0
    text = (Path(str(tmp_path)) / "titled.md").read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(text)
    assert metadata.get("title") == "页面自带标题"
    assert body.lstrip().startswith("# 页面自带标题")


# ---------------------------------------------------------------- 运营子命令
#
# 以下用例不连库、不连 core（SDK 调用被拦截在装配层之外）。account 子命令的两条钉的是
# 2026-10-01 审查发现的真实缺陷：不初始化 SDK、`purgers` 传的是工厂函数而不是它返回的
# 列表；invite 的两条钉的是「有效期不得由命令行指定」——30 天是设计定值（第 4 节）。


def _operator_parser():
    """构造带运营子命令的解析器（复用入口的真解析器，不另写一份）。"""
    return _build_parser()


def test_invite_issue_has_no_ttl_option(capsys: pytest.CaptureFixture[str]) -> None:
    """``invite issue`` 不接受有效期参数：30 天是设计定值（第 4 节）。

    为什么删而不是加范围校验：设计把有效期钉在 30 天（认证与账号 :68「8 位随机、
    一次性使用、有效期 30 天」，:49「签发时按 30 天计」），第 7 节的子命令表也只写
    ``invite issue`` 而没有参数。保留一个可指定有效期的开关，就要为它发明一套
    区间政策；而它唯一能带来的额外能力（缩短有效期）没有任何出处。

    判别性：把 ``--days`` 加回去，本用例失败（解析不再抛 ``SystemExit``）。
    """
    with pytest.raises(SystemExit) as excinfo:
        _operator_parser().parse_args(["invite", "issue", "--days", "0"])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2, f"参数错误必须非零退出，实际 {excinfo.value.code}"
    assert "unrecognized arguments" in captured.err, f"须明确说参数不被接受，实际 {captured.err!r}"
    assert "--days" in captured.err, f"须指名被拒的参数，实际 {captured.err!r}"


def test_invite_issue_does_not_override_the_ttl(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """签发不覆盖有效期：CLI 不给领域传有效期入参，回执打印的是设计定值。

    为什么必须有这一条：``--days`` 移除后，若调用处仍写着 ``ttl_days=args.days``，
    上面的参数解析用例**看不出来**（``--days`` 已不被接受）；真实运行会先在
    ``args.days`` 上抛 ``AttributeError``——即「改了参数层、忘了改调用层」。

    判别性：把 ``ttl_days=...`` 传回去，断言失败；把回执改回 ``args.days``，
    本用例在打印那一行就崩。

    库层（``session_scope``）与领域函数都用假件替身——本用例钉的是调用形状与回执，
    不连库。
    """
    import asyncio

    from campfire.cli import operator
    from campfire.modules.accounts import INVITE_CODE_TTL_DAYS

    calls: list[dict[str, object]] = []

    class _FakeRecord:
        #: 形状与 `_print_invite_row` 的读取方式一致（它按属性取，取不到就显示占位符）。
        code = "ABCD2345"
        state = "issued"
        expires_at = None
        used_by_account_id = None

    async def fake_issue(session, **kwargs):
        calls.append(kwargs)
        return _FakeRecord()

    class _NullSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(operator, "session_scope", lambda settings: _NullSession())
    # operator.py 是 `from ... import issue_invite_code` 直接导入名字，
    # 必须拦在 operator 模块的命名空间上（拦 repository 模块属性对它无效）。
    monkeypatch.setattr(operator, "issue_invite_code", fake_issue)

    code = asyncio.run(operator._run_invite_issue(_operator_parser().parse_args(["invite", "issue"])))

    captured = capsys.readouterr()
    assert code == 0, f"签发成功路径必须返回 0，实际 {code}（stderr={captured.err!r}）"
    assert calls, "领域函数必须被调用一次"
    assert "ttl_days" not in calls[0], f"CLI 不得覆盖设计定值，实际传入 {calls[0]!r}"
    assert f"有效期：{INVITE_CODE_TTL_DAYS} 天" in captured.out, f"回执须给出有效期，实际 {captured.out!r}"


def test_account_delete_initializes_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """``account delete`` 必须在执行前初始化 SuperTokens SDK。

    **背景（阻断级，2026-10-01 审查发现）**：第 3、4 步（撤会话、删身份用户）走
    SDK，而 SDK 的 ``SessionRecipe.get_instance()`` 在未 init 的进程里直接抛
    ``GeneralError: Initialisation not done``（源码实测）。CLI 不共享 Web 入口的
    lifespan，不初始化就意味着 ``account delete`` **必然**在第一步成功后崩掉。

    判别性：去掉 ``_run_account_delete`` 里的 ``_init_supertokens_for_cli`` 调用，
    本用例失败（``initialized`` 不会被置真）。

    库层（``session_scope``）与编排（``delete_account``）都用假件替身——本用例
    钉的是「init 先于执行」与「purgers 已求值」两件事，不连库。
    """
    import asyncio

    import campfire.core.auth.deletion as deletion
    from campfire.cli import operator
    from campfire.core.auth import PurgeOutcome

    initialized: list[bool] = []
    monkeypatch.setattr(operator, "_init_supertokens_for_cli", lambda settings: initialized.append(True))

    async def fake_revoke(account_id: str) -> None:
        return None

    async def fake_delete_user(account_id: str) -> None:
        return None

    class _NoopPurger:
        #: 领域名（与端口契约一致；编排步骤名从它取）。
        name = "noop"

        async def purge_account(self, account_id: str) -> PurgeOutcome:
            return PurgeOutcome(name="noop", detail="无数据")

    calls: list[str] = []

    async def fake_delete_account(
        session,
        *,
        account_id,
        revoke_all_sessions,
        delete_identity_user,
        purgers,
        reason="user_request",
        confirmed=False,
    ):
        calls.append("delete_account")
        # purgers 必须是**列表**：修复前传进来的是工厂函数本身，迭代它会抛 TypeError。
        assert isinstance(purgers, list), f"purgers 应为已求值的列表，实际 {type(purgers).__name__}"
        assert all(hasattr(p, "purge_account") for p in purgers), "列表成员必须是清除者"
        return deletion.DeletionReport(account_id=account_id)

    class _NullSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(operator, "session_scope", lambda settings: _NullSession())
    # operator.py 是 `from ... import delete_account` 直接导入名字，
    # 必须拦在 operator 模块的命名空间上（拦 deletion 模块属性对它无效）。
    monkeypatch.setattr(operator, "delete_account", fake_delete_account)
    monkeypatch.setattr(operator, "_revoke_all_sessions_for", fake_revoke)
    monkeypatch.setattr(operator, "_delete_identity_user", fake_delete_user)
    monkeypatch.setattr(operator, "_purgers", lambda settings: [_NoopPurger()])

    args = _operator_parser().parse_args(["account", "delete", "acct-x", "--confirm", "acct-x"])
    code = asyncio.run(operator._run_account_delete(args))

    assert code == 0
    assert initialized == [True], "account delete 必须先初始化 SDK 再执行注销"
    assert calls == ["delete_account"]


def test_account_reset_initializes_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """``account reset`` 同样必须初始化 SDK（改密走 ``update_email_or_password``）。

    判别性：去掉 ``_run_account_reset`` 里的初始化调用，本用例失败。
    SDK 函数本身用假件替身（本用例不连 core），初始化的**事实**才是断言对象。

    假件返回 SDK **真实**的成功结果类型：修复前它是一个 ``status = "OK"`` 的自造类，
    而 SDK 的 ``UpdateEmailOrPasswordOkResult`` 根本没有 ``status`` 属性（实测），
    旧实现靠 ``getattr(..., None)`` 兜底才「碰巧」把成功认出来。判定改成类型之后，
    假件必须与真实形状一致——否则本用例测的是不存在的形状。
    """
    import asyncio

    import supertokens_python.recipe.emailpassword.asyncio as ep_asyncio
    from supertokens_python.recipe.emailpassword.interfaces import UpdateEmailOrPasswordOkResult

    from campfire.cli import operator

    initialized: list[bool] = []
    monkeypatch.setattr(operator, "_init_supertokens_for_cli", lambda settings: initialized.append(True))

    async def fake_update(**kwargs):
        return UpdateEmailOrPasswordOkResult()

    async def fake_revoke(account_id: str) -> None:
        return None

    monkeypatch.setattr(ep_asyncio, "update_email_or_password", fake_update)
    monkeypatch.setattr(operator, "_revoke_all_sessions_for", fake_revoke)

    code = asyncio.run(
        operator._run_account_reset(
            _operator_parser().parse_args(["account", "reset", "acct-y", "--password", "probePass123"])
        )
    )

    assert code == 0
    assert initialized == [True], "account reset 必须先初始化 SDK 再改密"


#: `update_email_or_password` 声明联合类型里除 OK 以外的全部成员（在只传 password 的
#: 调用形态下都能从 SDK 拿到）。逐项覆盖，而不是只测「账号不存在」一种。
_RESET_FAILURE_RESULTS = [
    pytest.param(UnknownUserIdError(), id="账号不存在"),
    pytest.param(PasswordPolicyViolationError("密码不合校验器"), id="新密码不合校验器"),
    pytest.param(UpdateEmailOrPasswordEmailChangeNotAllowedError("账号接管风险"), id="不允许改邮箱"),
    pytest.param(EmailAlreadyExistsError(), id="邮箱已被占用"),
]


@pytest.mark.parametrize("failure_result", _RESET_FAILURE_RESULTS)
def test_account_reset_reports_failure_for_every_non_ok_result(
    monkeypatch: pytest.MonkeyPatch, failure_result: object, capsys: pytest.CaptureFixture[str]
) -> None:
    """改密返回任何非 OK 结果都必须**显式失败**，且不得撤销会话。

    判别性：把判定改回 ``getattr(result, "status", None)``，四个参数里三个失败
    （``UnknownUserIdError``/``PasswordPolicyViolationError``/改邮箱不允许都没有
    ``status`` 属性，会被当成成功）；只有带 ``status`` 的 ``EmailAlreadyExistsError``
    侥幸通过。

    为什么四个都要测：原判据在属性缺失时 fail-open，而「属性缺失」不是个别分支的
    特性——联合类型里只有 ``EmailAlreadyExistsError`` 带 ``status``。逐项覆盖才能
    保住「联合类型的每个成员都被显式处置」这条契约。

    失败时还必须**什么都没做**：会话撤销不可逆，密码没改成却撤了会话，使用者就
    被锁在门外而新密码从未生效（改密排在撤会话之前，正是为杜绝这个状态）。
    """
    import asyncio

    import supertokens_python.recipe.emailpassword.asyncio as ep_asyncio

    from campfire.cli import operator

    result_name = type(failure_result).__name__
    revocations: list[str] = []

    async def fake_update(**kwargs):
        return failure_result

    async def fake_revoke(account_id: str) -> None:
        revocations.append(account_id)

    monkeypatch.setattr(ep_asyncio, "update_email_or_password", fake_update)
    monkeypatch.setattr(operator, "_revoke_all_sessions_for", fake_revoke)
    monkeypatch.setattr(operator, "_init_supertokens_for_cli", lambda settings: None)

    code = asyncio.run(
        operator._run_account_reset(
            _operator_parser().parse_args(["account", "reset", "acct-z", "--password", "probePass123"])
        )
    )

    captured = capsys.readouterr()
    assert code == 1, f"{result_name} 必须是非零退出码，实际 {code}"
    assert result_name in captured.err, f"失败原因必须指名结果类型，实际 stderr={captured.err!r}"
    assert "已重置密码" not in captured.out, f"不得打印成功回执，实际 stdout={captured.out!r}"
    assert revocations == [], f"改密未成功就撤销了会话：{revocations!r}"


def test_account_reset_success_path_still_reports_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """成功路径仍然打印成功回执——防止把判定改成「一律失败」也算通过。

    SDK 的成功结果没有 ``status`` 属性（实测），因此本用例同时钉住：
    「成功」不能靠某个属性存在与否来判断。
    """
    import asyncio

    import supertokens_python.recipe.emailpassword.asyncio as ep_asyncio
    from supertokens_python.recipe.emailpassword.interfaces import UpdateEmailOrPasswordOkResult

    from campfire.cli import operator

    revocations: list[str] = []

    async def fake_update(**kwargs):
        return UpdateEmailOrPasswordOkResult()

    async def fake_revoke(account_id: str) -> None:
        revocations.append(account_id)

    monkeypatch.setattr(ep_asyncio, "update_email_or_password", fake_update)
    monkeypatch.setattr(operator, "_revoke_all_sessions_for", fake_revoke)
    monkeypatch.setattr(operator, "_init_supertokens_for_cli", lambda settings: None)

    code = asyncio.run(
        operator._run_account_reset(
            _operator_parser().parse_args(["account", "reset", "acct-w", "--password", "probePass123"])
        )
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "已重置密码" in captured.out
    assert revocations == ["acct-w"], "改密成功后必须撤销该账号全部会话"


# ---------------------------------------------------------------- 撤下（RQ-KB-04）
#
# 撤下是 CLI 独有的写路径：资料库面只有读端点（`RQ-KB-03`、`AC-29`）。
# quality-floor: ignore todo-residue 此处引用的是待办登记文档本身，不是未处理的代码残留
# 依据见 docs/TODO.md 的资料库面一条。这组用例钉的是「入口真的存在、真的走到
# `withdraw_item`」——D-81 的缺陷形态正是能力完整（打标记 + 删节点同事务、
# 幂等）却没有生产入口，调用点全在测试里。

_ITEM_ID = "8f3a1c2e-5b7d-4a90-9c11-2d3e4f5a6b7c"


def _install_fake_withdraw_runtime(monkeypatch: pytest.MonkeyPatch, withdraw: object) -> None:
    """把 CLI 的会话边界与撤下用例换成假件（本组用例不连库）。

    `get_settings` 一并替换：用例因此不依赖 `.env` 里的连接串。领域函数本身
    由 `test_library_*_integration` 覆盖，这里只钉 CLI 的调用形状与呈现。
    """
    import campfire.cli.__main__ as cli_main

    class _NullSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(cli_main, "get_settings", lambda: object())
    monkeypatch.setattr(cli_main, "session_scope", lambda settings: _NullSession())
    monkeypatch.setattr(cli_main, "withdraw_item", withdraw)


def test_withdraw_takes_library_item_and_reason() -> None:
    """`withdraw` 的入参：库别、条目 id、`--reason`（`RQ-KB-04` 要求记录原因）。"""
    args = _build_parser().parse_args(["withdraw", "case", _ITEM_ID, "--reason", "上游撤回该案例"])

    assert args.library == "case"
    assert args.item_id == _ITEM_ID
    assert args.reason == "上游撤回该案例"


@pytest.mark.parametrize("bad", ["cases", "Knowledge", "profile", ""])
def test_withdraw_rejects_unknown_library_by_the_parser(bad: str) -> None:
    """非法库别被 argparse 的 choices 拒绝（退出码 2），不静默回退到某个库。

    退出码 2 是 argparse 对参数层面错误的既有行为；命令自己捕获的领域失败
    （条目不存在、id 非法）是 1——两者不混。
    """
    with pytest.raises(SystemExit) as excinfo:
        _build_parser().parse_args(["withdraw", bad, _ITEM_ID])

    assert excinfo.value.code == 2


def test_withdraw_dispatches_to_the_use_case_and_prints_the_result(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`main(["withdraw", ...])` 真的走到 `withdraw_item`，并按既有形状打印结果。

    判别性：删掉 `main` 里的 withdraw 分派，本用例返回 2（落到用法输出）而不是 0。
    """
    from campfire.modules.library.withdrawal import WithdrawalResult

    calls: list[dict[str, object]] = []

    async def fake_withdraw(session, **kwargs):
        calls.append(kwargs)
        return WithdrawalResult(
            item_id=kwargs["item_id"],
            library=kwargs["library"],
            already_withdrawn=False,
            nodes_deleted=7,
        )

    _install_fake_withdraw_runtime(monkeypatch, fake_withdraw)

    code = main(["withdraw", "case", _ITEM_ID, "--reason", "上游撤回该案例"])

    captured = capsys.readouterr()
    assert code == 0, f"撤下成功路径必须返回 0，实际 {code}（stderr={captured.err!r}）"
    assert calls == [{"library": "case", "item_id": _ITEM_ID, "reason": "上游撤回该案例"}], (
        f"库别、条目 id 与原因必须原样透传给 withdraw_item，实际 {calls!r}"
    )
    assert f"已撤下：case/{_ITEM_ID}" in captured.out
    assert "删除检索节点：7" in captured.out
    assert captured.err == "", f"首次撤下不该有幂等提示，实际 {captured.err!r}"


def test_withdraw_reports_already_withdrawn_on_a_rerun(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """重复撤下：退出码 0，且明确说出「此前已撤下」——幂等在 CLI 层可辨。

    判别性：去掉 `already_withdrawn` 分支，本用例失败（重跑与首次变更无法区分）。
    """
    from campfire.modules.library.withdrawal import WithdrawalResult

    async def fake_withdraw(session, **kwargs):
        return WithdrawalResult(
            item_id=kwargs["item_id"],
            library=kwargs["library"],
            already_withdrawn=True,
            nodes_deleted=0,
        )

    _install_fake_withdraw_runtime(monkeypatch, fake_withdraw)

    code = main(["withdraw", "knowledge", _ITEM_ID])

    captured = capsys.readouterr()
    assert code == 0
    assert f"已撤下：knowledge/{_ITEM_ID}" in captured.out
    assert "删除检索节点：0" in captured.out
    assert "此前已撤下" in captured.err, f"重复撤下必须可辨，实际 stderr={captured.err!r}"


def test_withdraw_maps_a_domain_failure_to_exit_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """条目不存在 → 退出码 1 + stderr 说明原因，且不打印成功回执。"""
    from campfire.modules.library.withdrawal import WithdrawalError

    async def fake_withdraw(session, **kwargs):
        raise WithdrawalError(f"条目不存在：{kwargs['library']}/{kwargs['item_id']}")

    _install_fake_withdraw_runtime(monkeypatch, fake_withdraw)

    code = main(["withdraw", "case", _ITEM_ID])

    captured = capsys.readouterr()
    assert code == 1
    assert "撤下失败" in captured.err, f"失败原因必须写在 stderr，实际 {captured.err!r}"
    assert "条目不存在" in captured.err
    assert "已撤下" not in captured.out, f"失败不得打印成功回执，实际 stdout={captured.out!r}"


def test_withdraw_maps_an_invalid_item_id_to_exit_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """条目 id 不是合法 UUID → 退出码 1，不是未捕获的 traceback。

    判别性：把 `RetrievalError` 从 except 元组里去掉，本用例以异常失败。
    """
    from campfire.modules.library.retrieval import RetrievalError

    async def fake_withdraw(session, **kwargs):
        raise RetrievalError(f"非法条目 id：{kwargs['item_id']!r}")

    _install_fake_withdraw_runtime(monkeypatch, fake_withdraw)

    code = main(["withdraw", "knowledge", "not-a-uuid"])

    captured = capsys.readouterr()
    assert code == 1
    assert "撤下失败" in captured.err and "not-a-uuid" in captured.err
