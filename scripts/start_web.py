"""Web launcher — Taro H5 dev server with hot-reload.

Starts the Taro H5 dev build. Opens in browser at http://localhost:10086.
API calls are proxied to localhost:8000 per config/dev.js.
"""

from __future__ import annotations

import os
from pathlib import Path

from utils.process_utils import start_process

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SERVICE_NAME = "Web"
MAX_NAME_WIDTH = 8
H5_DEFAULT_PORT = 10086


def start(*, mode: str = "h5") -> tuple:
    """Start the Taro dev build subprocess.

    Args:
        mode: Build target — "h5" (browser) or "weapp" (WeChat mini-program).

    Returns:
        (subprocess.Popen, service_name: str)
    """
    script = f"dev:{mode}"
    proc = start_process(
        ["pnpm", "--filter", "mini-program", script],
        cwd=PROJECT_ROOT,
    )
    return proc, SERVICE_NAME


def main() -> None:
    """CLI entry point for standalone use."""
    import signal
    import sys

    mode = os.environ.get("TARO_MODE", "h5")

    from utils.log_utils import (
        print_running_status,
        print_separator,
        print_service_log,
        print_service_starting,
        print_stage,
        print_exit_header,
        print_service_terminating,
        print_service_terminated_ok,
        print_info,
    )
    from utils.process_utils import read_output, terminate_process

    proc, name = start(mode=mode)
    print_separator()
    print_stage("阶段二：服务启动")
    print_service_starting(name, proc.pid)
    if mode == "h5":
        print_info(f"  H5 开发服务器将在 http://localhost:{H5_DEFAULT_PORT} 启动")
    print_separator()
    print_stage("阶段三：运行中")
    print_running_status()

    def _on_shutdown(signum, frame):
        print_exit_header()
        print_service_terminating(name, proc.pid)
        ok = terminate_process(proc)
        if ok:
            print_service_terminated_ok()
        else:
            from utils.log_utils import print_service_terminated_forced
            print_service_terminated_forced()
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_shutdown)
    signal.signal(signal.SIGTERM, _on_shutdown)

    read_output(proc, lambda line: print_service_log(name, line, MAX_NAME_WIDTH))


if __name__ == "__main__":
    main()
