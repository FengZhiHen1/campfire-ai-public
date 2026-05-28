"""API server launcher — FastAPI via uvicorn with hot-reload.

Starts the Campfire-AI API server on port 8000 with --reload enabled.
"""

from __future__ import annotations

from pathlib import Path

from utils.process_utils import start_process

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SERVICE_NAME = "API"
MAX_NAME_WIDTH = 8


def start() -> tuple:
    """Start the API server subprocess.

    Returns:
        (subprocess.Popen, service_name: str)
    """
    proc = start_process(
        [
            "uv", "run",
            "--package", "api-server",
            "api-server",
        ],
        cwd=PROJECT_ROOT,
    )
    return proc, SERVICE_NAME


def main() -> None:
    """CLI entry point for standalone use."""
    import signal
    import sys

    from utils.log_utils import (
        print_running_status,
        print_separator,
        print_service_log,
        print_service_starting,
        print_stage,
        print_exit_header,
        print_service_terminating,
        print_service_terminated_ok,
    )
    from utils.process_utils import read_output, terminate_process

    proc, name = start()
    print_separator()
    print_stage("阶段二：服务启动")
    print_service_starting(name, proc.pid)
    print_separator()
    print_stage("阶段三：运行中")
    print_running_status()

    stop_event = None  # simplified standalone mode

    def _on_shutdown(signum, frame):
        nonlocal stop_event
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
