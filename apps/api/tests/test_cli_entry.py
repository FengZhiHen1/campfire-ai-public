"""本地摄取入口的诚实失败语义。

设计（RAG 策略第 7 节）把入口形态定成 ``python -m campfire.cli ingest <路径>``。
摄取流水线尚未实现，本组用例锁住两件事：

1. 入口真的接好了（能通过 ``-m`` 跑到 ``main()``）；
2. 它**不假装成功**——退出码非 0，且说明缺什么。
"""

import os
import subprocess
import sys

from campfire.cli.__main__ import main


def test_cli_entry_returns_failure_code_instead_of_pretending_success() -> None:
    assert main() == 2


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
    assert "尚未实现" in completed.stderr
