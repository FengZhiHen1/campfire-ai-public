"""Web 服务启动器 — Taro H5 / 微信小程序 / React H5 dev server.

Usage:
    from start_web import WebLauncher
    launcher = WebLauncher(mode="h5")      # Taro H5
    launcher = WebLauncher(mode="weapp")   # 微信小程序
    launcher = WebLauncher(mode="react-h5") # React H5 (Vite)
    proc = launcher.start()
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from launcher_contract import ServiceLauncher
from utils.process_utils import start_process

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class WebLauncher(ServiceLauncher):
    def __init__(
        self,
        mode: str = "h5",
        project_root: Path | None = None,
    ) -> None:
        self._mode = mode
        self._project_root = project_root or PROJECT_ROOT

        if mode == "h5":
            self.name = "web-h5"
            self.display_name = "Web-H5"
            self.port = 5173
            self._package = "mini-program"
            self._script = "dev:h5"
        elif mode == "weapp":
            self.name = "web-weapp"
            self.display_name = "Web-Weapp"
            self.port = None
            self._package = "mini-program"
            self._script = "dev:weapp"
        elif mode == "react-h5":
            self.name = "web-react-h5"
            self.display_name = "React-H5"
            self.port = 5173
            self._package = "react-web"
            self._script = "dev"
        else:
            raise ValueError(f"未知 Web 模式: {mode!r}，可选: h5, weapp, react-h5")

    def _do_start(self) -> subprocess.Popen:
        return start_process(
            ["pnpm", "--filter", self._package, self._script],
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

    mode = os.environ.get("WEB_MODE") or os.environ.get("TARO_MODE", "h5")
    launcher = WebLauncher(mode=mode)
    if launcher.port:
        from utils.log_utils import print_info

        print_info(f"{launcher.display_name} 开发服务器将在 http://localhost:{launcher.port} 启动")
    run_standalone(launcher)


if __name__ == "__main__":
    main()
