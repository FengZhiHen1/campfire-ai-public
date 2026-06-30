"""Worker 服务启动器 — Redis BLPOP consumer for background tasks.

Usage:
    from start_worker import WorkerLauncher
    launcher = WorkerLauncher()
    proc = launcher.start()
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from launcher_contract import ServiceLauncher
from utils.logger import logger
from utils.process_utils import start_process, terminate_process_tree_by_pid

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKER_PID_FILE = PROJECT_ROOT / ".tmp" / "worker.pid"


# ===========================================================================
# 残留进程清理
# ===========================================================================


def _read_pid_file() -> int | None:
    """读取 PID 文件，返回记录的 PID；文件不存在或内容无效时返回 None。"""
    if not WORKER_PID_FILE.exists():
        return None
    try:
        return int(WORKER_PID_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _write_pid_file(pid: int) -> None:
    """将 Worker 根进程 PID 写入文件，供下次启动时清理残留。"""
    WORKER_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORKER_PID_FILE.write_text(str(pid), encoding="utf-8")


def _remove_pid_file() -> None:
    """删除 PID 文件，忽略文件不存在的场景。"""
    try:
        WORKER_PID_FILE.unlink()
    except FileNotFoundError:
        pass


def _kill_stale_worker() -> None:
    """根据 PID 文件终止上一次运行残留的 Worker 进程树。

    Worker 不占用固定端口，scripts/start.py 的端口清理逻辑无法覆盖它。
    若上一次 Worker 因强制退出、信号未正确传递等原因残留，重启后会出现
    新旧 Worker 同时消费 Redis 队列、旧代码仍在执行的“死进程”问题。
    """
    pid = _read_pid_file()
    if pid is None:
        return

    import psutil

    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        _remove_pid_file()
        return

    logger.info(
        service="scripts",
        message=f"发现残留 Worker 进程 (PID {pid})，正在终止...",
        op_type="worker_cleanup",
        extra={"pid": pid},
    )
    terminated = terminate_process_tree_by_pid(pid, timeout=5.0)
    if terminated:
        logger.info(
            service="scripts",
            message=f"残留 Worker 进程 (PID {pid}) 已终止",
            op_type="worker_cleanup",
            extra={"pid": pid},
        )
    else:
        logger.warning(
            service="scripts",
            message=f"残留 Worker 进程 (PID {pid}) 未能完全终止",
            op_type="worker_cleanup",
            extra={"pid": pid},
        )
    _remove_pid_file()
    time.sleep(0.5)


# ===========================================================================
# WorkerLauncher
# ===========================================================================


class WorkerLauncher(ServiceLauncher):
    name = "worker"
    display_name = "Worker"

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root or PROJECT_ROOT

    def _pre_check(self) -> None:
        """启动前清理可能残留的 Worker 进程。"""
        _kill_stale_worker()

    def _do_start(self) -> subprocess.Popen:
        return start_process(
            ["uv", "run", "--package", "worker", "worker"],
            cwd=self._project_root,
        )

    def _post_check(self, proc: subprocess.Popen) -> None:
        """启动成功后记录 PID，便于下次启动清理残留。"""
        super()._post_check(proc)
        if proc.pid is not None:
            _write_pid_file(proc.pid)


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
