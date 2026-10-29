"""`python -m evaluation.carebench` 的入口：只负责把退出码交回 shell。

职责：调用 :func:`evaluation.carebench.cli.main` 并把它的返回值作为进程退出码。

边界：不含任何命令实现（见 `cli.py`）。
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":  # pragma: no cover —— 进程入口
    sys.exit(main())
