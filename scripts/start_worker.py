"""Worker 服务启动器 — Redis BLPOP consumer for background tasks.

Usage:
    from start_worker import WorkerLauncher
    launcher = WorkerLauncher()
    proc = launcher.start()
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from launcher_contract import ServiceLauncher
from utils.process_utils import start_process

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class WorkerLauncher(ServiceLauncher):
    name = "worker"
    display_name = "Worker"

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root or PROJECT_ROOT

    def _do_start(self) -> subprocess.Popen:
        return start_process(
            ["uv", "run", "--package", "worker", "worker"],
            cwd=self._project_root,
        )


# ---------------------------------------------------------------------------
# 向后兼容：保留函数式接口
# ---------------------------------------------------------------------------

def start() -> tuple[subprocess.Popen, str]:
    """启动 Worker 服务。返回 (进程, 展示名称)。"""
    launcher = WorkerLauncher()
    return launcher.start(), launcher.display_name


# ---------------------------------------------------------------------------
# 独立运行入口
# ---------------------------------------------------------------------------

def main() -> None:
    from utils.launcher_utils import run_standalone
    run_standalone(WorkerLauncher())


if __name__ == "__main__":
    main()
