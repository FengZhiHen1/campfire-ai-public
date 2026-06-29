"""API 服务启动器 — FastAPI via uvicorn with hot-reload.

Usage:
    from start_api import ApiLauncher
    launcher = ApiLauncher()
    proc = launcher.start()
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from launcher_contract import ServiceLauncher
from utils.logger import logger
from utils.process_utils import start_process

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ===========================================================================
# 端口占用检测与清理
# ===========================================================================


def _find_pid_by_port(port: int) -> int | None:
    """查找占用指定端口的进程 PID。跨平台兼容。

    Args:
        port: 要检查的端口号。

    Returns:
        PID（整数），端口空闲时返回 None。
    """
    if sys.platform == "win32":
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, encoding="gbk", timeout=10,
        )
        for line in (result.stdout or "").splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                try:
                    return int(parts[-1])
                except (ValueError, IndexError):
                    continue
    else:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=10,
        )
        if result.stdout.strip():
            try:
                return int(result.stdout.strip().split()[0])
            except (ValueError, IndexError):
                pass
    return None


def _kill_process_by_pid(pid: int) -> bool:
    """强制终止指定 PID 的进程。跨平台兼容。

    Args:
        pid: 要终止的进程 PID。

    Returns:
        True 表示成功终止或进程已不存在。
    """
    if sys.platform == "win32":
        result = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    else:
        import os
        import signal
        try:
            os.kill(pid, signal.SIGKILL)
            return True
        except ProcessLookupError:
            return True


def _resolve_port_conflict(port: int) -> None:
    """检测端口占用并自动清理。

    若端口被占用，记录日志并终止占用进程，等待端口释放。
    端口空闲时无操作。

    Args:
        port: 要检查的端口号。
    """
    pid = _find_pid_by_port(port)
    if pid is None:
        return

    logger.info(
        service="scripts",
        message=f"端口 {port} 被 PID {pid} 占用，正在终止...",
        op_type="port_conflict",
        extra={"port": port, "pid": pid},
    )
    _kill_process_by_pid(pid)
    time.sleep(0.5)

    # 二次确认
    if _find_pid_by_port(port) is not None:
        logger.warning(
            service="scripts",
            message=f"端口 {port} 仍然被占用，稍后可能启动失败",
            op_type="port_conflict",
            extra={"port": port},
        )


def _kill_all_uvicorn_processes() -> None:
    """终止所有残留的 uvicorn 进程，避免旧代码继续服务请求。

    Windows 下 uvicorn --reload 可能产生子进程残留，
    仅清理端口占用不够，需要主动清理所有 uvicorn 进程。
    """
    if sys.platform == "win32":
        result = subprocess.run(
            ["taskkill", "/F", "/IM", "uvicorn.exe"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.info(
                service="scripts",
                message="已终止所有残留 uvicorn.exe 进程",
                op_type="process_cleanup",
            )
        else:
            # 没有 uvicorn 进程或权限问题，通常可忽略
            pass
    else:
        result = subprocess.run(
            ["pkill", "-f", "uvicorn"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            logger.info(
                service="scripts",
                message="已终止所有残留 uvicorn 进程",
                op_type="process_cleanup",
            )


# ===========================================================================
# ApiLauncher
# ===========================================================================


class ApiLauncher(ServiceLauncher):
    name = "api"
    display_name = "API"
    port = 8000

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root or PROJECT_ROOT

    def _pre_check(self) -> None:
        """启动前自动检测并清理端口占用及残留 uvicorn 进程。"""
        _kill_all_uvicorn_processes()
        time.sleep(0.5)
        _resolve_port_conflict(self.port)

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
