"""启动器公共工具 — 独立运行模式 & 日志监控。

供各启动器的 main() 函数复用，消除跨脚本的样板代码。
"""

from __future__ import annotations

import signal
import subprocess
import sys
import threading

from launcher_contract import ServiceLauncher

from utils.log_utils import (
    print_exit_header,
    print_running_status,
    print_separator,
    print_service_log,
    print_service_starting,
    print_service_terminated_forced,
    print_service_terminated_ok,
    print_service_terminating,
    print_stage,
)
from utils.logger import logger
from utils.process_utils import read_output, terminate_process


def run_standalone(launcher: ServiceLauncher) -> None:
    """以独立模式运行启动器（python start_xxx.py）。

    处理完整的生命周期：启动 → 日志流 → 信号捕获 → 优雅关闭。
    """
    name = launcher.display_name
    proc = launcher.start()

    logger.info(
        service="scripts",
        message=f"{name} 已启动",
        op_type="service_start",
        extra={"pid": proc.pid, "launcher": launcher.name},
    )

    print_separator()
    print_stage("阶段二：服务启动")
    print_service_starting(name, proc.pid)
    print_separator()
    print_stage("阶段三：运行中")
    print_running_status()

    _shutdown_done = False
    max_width = launcher.log_prefix_width

    def _on_shutdown(signum: int, frame) -> None:
        nonlocal _shutdown_done
        if _shutdown_done:
            return
        _shutdown_done = True

        signame = signal.Signals(signum).name
        logger.info(
            service="scripts",
            message=f"收到 {signame}，正在关闭 {name}",
            op_type="service_stop",
            extra={"pid": proc.pid},
        )

        print()
        print_exit_header()
        print_service_terminating(name, proc.pid)
        ok = terminate_process(proc)
        if ok:
            print_service_terminated_ok()
            logger.info(service="scripts", message=f"{name} 已优雅关闭", op_type="service_stop")
        else:
            print_service_terminated_forced()
            logger.warning(
                service="scripts",
                message=f"{name} 被强制终止",
                op_type="service_stop",
                extra={"pid": proc.pid},
            )
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_shutdown)
    signal.signal(signal.SIGTERM, _on_shutdown)

    read_output(proc, lambda line: print_service_log(name, line, max_width))


def start_log_readers(
    procs: list[tuple[subprocess.Popen, str]],
    max_name_width: int = 8,
) -> tuple[list[threading.Thread], threading.Event]:
    """为每个进程启动一个日志读取线程。

    Args:
        procs: [(进程, 服务名), ...]
        max_name_width: 日志前缀的固定宽度

    Returns:
        (线程列表, 停止事件)
    """
    stop_event = threading.Event()
    threads: list[threading.Thread] = []

    for proc, name in procs:
        t = threading.Thread(
            target=read_output,
            args=(
                proc,
                lambda line, n=name: print_service_log(n, line, max_name_width),
            ),
            kwargs={"stop_event": stop_event},
            daemon=True,
        )
        t.start()
        threads.append(t)

    return threads, stop_event


def shutdown_services(
    procs: list[tuple[subprocess.Popen, str]],
    stop_event: threading.Event,
) -> None:
    """优雅关闭所有服务。"""
    logger.info(
        service="scripts",
        message="开始关闭所有服务",
        op_type="shutdown",
        extra={"service_count": len(procs)},
    )

    print()
    print_exit_header()

    stop_event.set()

    for proc, name in procs:
        if proc.poll() is not None:
            continue
        print_service_terminating(name, proc.pid)
        exited_gracefully = terminate_process(proc, timeout=10.0)
        if exited_gracefully:
            print_service_terminated_ok()
        else:
            print_service_terminated_forced()
            logger.warning(
                service="scripts",
                message=f"{name} 被强制终止",
                op_type="shutdown",
                extra={"pid": proc.pid},
            )

    from start_ngrok import cleanup_ngrok_url_file

    cleanup_ngrok_url_file()

    from utils.log_utils import print_exit_footer

    print()
    print_exit_footer()
