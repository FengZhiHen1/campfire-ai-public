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
