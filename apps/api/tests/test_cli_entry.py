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


# ---------------------------------------------------------------- 运营子命令
#
# 以下用例不连库、不连 core（SDK 调用被拦截在装配层之外），钉的是
# 2026-10-01 审查发现的两个 CLI 真实缺陷：account 子命令不初始化 SDK、
# `purgers` 传的是工厂函数而不是它返回的列表。


def _operator_parser():
    """构造带运营子命令的解析器（复用入口的真解析器，不另写一份）。"""
    return _build_parser()


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
    """
    import asyncio

    from campfire.cli import operator

    initialized: list[bool] = []
    monkeypatch.setattr(operator, "_init_supertokens_for_cli", lambda settings: initialized.append(True))

    class _OkResult:
        status = "OK"

    async def fake_update(**kwargs):
        return _OkResult()

    async def fake_revoke(account_id: str) -> None:
        return None

    import supertokens_python.recipe.emailpassword.asyncio as ep_asyncio

    monkeypatch.setattr(ep_asyncio, "update_email_or_password", fake_update)
    monkeypatch.setattr(operator, "_revoke_all_sessions_for", fake_revoke)

    code = asyncio.run(
        operator._run_account_reset(
            _operator_parser().parse_args(["account", "reset", "acct-y", "--password", "probePass123"])
        )
    )

    assert code == 0
    assert initialized == [True], "account reset 必须先初始化 SDK 再改密"
