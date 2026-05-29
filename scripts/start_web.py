"""Web 服务启动器 — Taro H5 / 微信小程序 dev server.

Usage:
    from start_web import WebLauncher
    launcher = WebLauncher(mode="h5")
    proc = launcher.start()
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from launcher_contract import ServiceLauncher
from utils.process_utils import start_process

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class WebLauncher(ServiceLauncher):
    display_name = "Web"

    def __init__(
        self,
        mode: str = "h5",
        project_root: Path | None = None,
    ) -> None:
        self.name = f"web-{mode}"
        self._mode = mode
        self.port = 5173 if mode == "h5" else None
        self._project_root = project_root or PROJECT_ROOT

    def _do_start(self) -> subprocess.Popen:
        return start_process(
            ["pnpm", "--filter", "mini-program", f"dev:{self._mode}"],
            cwd=self._project_root,
        )


# ---------------------------------------------------------------------------
# 向后兼容：保留函数式接口
# ---------------------------------------------------------------------------

def start(*, mode: str = "h5") -> tuple[subprocess.Popen, str]:
    """启动 Web dev server。返回 (进程, 展示名称)。"""
    launcher = WebLauncher(mode=mode)
    return launcher.start(), launcher.display_name


# ---------------------------------------------------------------------------
# 独立运行入口
# ---------------------------------------------------------------------------

def main() -> None:
    import os
    from utils.launcher_utils import run_standalone

    mode = os.environ.get("TARO_MODE", "h5")
    launcher = WebLauncher(mode=mode)
    if mode == "h5":
        from utils.log_utils import print_info
        print_info(f"H5 开发服务器将在 http://localhost:{launcher.port} 启动")
    run_standalone(launcher)


if __name__ == "__main__":
    main()
