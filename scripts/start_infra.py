"""基础设施服务启动器 — Docker Compose (PostgreSQL, Redis, MinIO).

Usage:
    from start_infra import InfraLauncher
    launcher = InfraLauncher()
    proc = launcher.start()
    proc.communicate(timeout=60)  # 等待容器启动完成
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from launcher_contract import ServiceLauncher
from utils.process_utils import resolve_exe, start_process

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class InfraLauncher(ServiceLauncher):
    name = "infra"
    display_name = "Infra"

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root or PROJECT_ROOT

    def _do_start(self) -> subprocess.Popen:
        return start_process(
            ["docker", "compose", "up", "-d"],
            cwd=self._project_root,
        )

    def stop(self) -> None:
        """停止所有 Docker 容器（docker compose down）。"""
        docker = resolve_exe("docker")
        subprocess.run(
            [docker, "compose", "down"],
            cwd=str(self._project_root),
            capture_output=True,
            timeout=30,
        )


# ---------------------------------------------------------------------------
# 向后兼容：保留函数式接口
# ---------------------------------------------------------------------------


def start_infra() -> subprocess.Popen:
    """启动基础设施容器。返回已完成的 Popen。"""
    return InfraLauncher().start()


def stop_infra() -> None:
    """停止基础设施容器。"""
    InfraLauncher().stop()


# ---------------------------------------------------------------------------
# 独立运行入口
# ---------------------------------------------------------------------------


def main() -> None:
    from utils.log_utils import print_error, print_info
    from utils.logger import logger

    print_info("正在启动基础设施容器...")
    launcher = InfraLauncher()
    proc = launcher.start()
    stdout, _ = proc.communicate(timeout=60)
    if proc.returncode == 0:
        print_info("基础设施容器已启动。")
        logger.info(service="scripts", message="基础设施容器已启动", op_type="infra_start")
        if stdout:
            print(stdout)
    else:
        print_error(f"基础设施启动失败 (exit code {proc.returncode})")
        logger.error(
            service="scripts",
            message="基础设施容器启动失败",
            op_type="infra_start",
            extra={"exit_code": proc.returncode},
        )
        if stdout:
            print(stdout)
        import sys

        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
