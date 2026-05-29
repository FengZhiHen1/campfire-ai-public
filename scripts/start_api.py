"""API 服务启动器 — FastAPI via uvicorn with hot-reload.

Usage:
    from start_api import ApiLauncher
    launcher = ApiLauncher()
    proc = launcher.start()
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from launcher_contract import ServiceLauncher
from utils.process_utils import start_process

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ApiLauncher(ServiceLauncher):
    name = "api"
    display_name = "API"
    port = 8000

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root or PROJECT_ROOT

    def _do_start(self) -> subprocess.Popen:
        return start_process(
            [
                "uv", "run", "--package", "api-server",
                "uvicorn", "app.main:app",
                "--host", "0.0.0.0",
                "--port", str(self.port),
                "--reload",
            ],
            cwd=self._project_root,
        )


# ---------------------------------------------------------------------------
# 向后兼容：保留函数式接口
# ---------------------------------------------------------------------------

def start() -> tuple[subprocess.Popen, str]:
    """启动 API 服务。返回 (进程, 展示名称)。"""
    launcher = ApiLauncher()
    return launcher.start(), launcher.display_name


# ---------------------------------------------------------------------------
# 独立运行入口
# ---------------------------------------------------------------------------

def main() -> None:
    from utils.launcher_utils import run_standalone
    run_standalone(ApiLauncher())


if __name__ == "__main__":
    main()
