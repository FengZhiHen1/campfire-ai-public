"""本地摄取入口的诚实失败语义。

设计（RAG 策略第 7 节）把入口形态定成 ``python -m campfire.cli ingest <路径>``。
摄取流水线尚未实现，本组用例锁住两件事：

1. 入口真的接好了（能通过 ``-m`` 跑到 ``main()``）；
2. 它**不假装成功**——退出码非 0，且说明缺什么。
"""

import subprocess
import sys

from campfire.cli.__main__ import main


def test_cli_entry_returns_failure_code_instead_of_pretending_success() -> None:
    assert main() == 2


def test_cli_module_is_runnable_via_dash_m() -> None:
    """``python -m campfire.cli`` 必须真的能跑（否则入口形态形同虚设）。"""
    completed = subprocess.run(
        [sys.executable, "-m", "campfire.cli"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "尚未实现" in completed.stderr
