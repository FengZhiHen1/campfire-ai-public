#!/usr/bin/env python3
"""Campfire-AI 统一启动控制台 (spec: 单体仓库全栈项目启动脚本规范).

Main orchestrator — CLI argument parsing, interactive menu, pre-flight checks,
parallel service startup, unified log output, and graceful process-tree shutdown.

Usage:
  python scripts/start.py                        # interactive menu
  python scripts/start.py --services api,worker  # start specific services
  python scripts/start.py --all                  # start all services
  python scripts/start.py --skip-infra           # skip docker compose
  python scripts/start.py --skip-checks          # skip pre-flight checks
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root (scripts/ → project root)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_NAME = "篝火智答 (Campfire-AI)"

AVAILABLE_SERVICES: dict[str, str] = {
    "api": "API 服务 (FastAPI, port 8000)",
    "worker": "Worker 服务 (Redis 消费者)",
    "web": "Web 服务 (Taro H5 dev, port 10086)",
}

MAX_NAME_WIDTH = 8

# ---------------------------------------------------------------------------
# Imports (after sys.path setup)
# ---------------------------------------------------------------------------

from utils.log_utils import (  # noqa: E402
    print_banner,
    print_check_fail,
    print_check_ok,
    print_error,
    print_exit_footer,
    print_exit_header,
    print_info,
    print_running_status,
    print_separator,
    print_service_failed,
    print_service_log,
    print_service_starting,
    print_service_terminated_forced,
    print_service_terminated_ok,
    print_service_terminating,
    print_stage,
    print_warning,
)
from utils.process_utils import read_output, terminate_process  # noqa: E402
from utils.check_utils import (  # noqa: E402
    check_docker_available,
    check_env_file,
    check_minio_connectivity,
    check_node_deps_installed,
    check_pnpm_available,
    check_port_available,
    check_postgres_connectivity,
    check_python_deps_installed,
    check_redis_connectivity,
    check_uv_available,
)


# ====================================================================
# Pre-flight checks
# ====================================================================


def run_preflight_checks(
    services: list[str], *, skip_infra: bool
) -> bool:
    """Execute all pre-flight checks (spec 3.1). Returns True if all pass."""
    print_stage("阶段一：前置检查")
    all_ok = True

    # --- .env check (always required) ---
    ok, msg = check_env_file()
    if ok:
        print_check_ok(".env 配置文件", msg)
    else:
        print_check_fail(".env 配置文件", msg)
        all_ok = False

    # --- Python toolchain ---
    if "api" in services or "worker" in services:
        ok, msg = check_uv_available()
        if ok:
            print_check_ok("uv 包管理器", msg)
        else:
            print_check_fail("uv 包管理器", msg)
            all_ok = False

        ok, msg = check_python_deps_installed()
        if ok:
            print_check_ok("Python 依赖", msg)
        else:
            print_check_fail("Python 依赖", msg)
            all_ok = False

    # --- Node.js toolchain ---
    if "web" in services:
        ok, msg = check_pnpm_available()
        if ok:
            print_check_ok("pnpm 包管理器", msg)
        else:
            print_check_fail("pnpm 包管理器", msg)
            all_ok = False

        ok, msg = check_node_deps_installed()
        if ok:
            print_check_ok("Node.js 依赖", msg)
        else:
            print_check_fail("Node.js 依赖", msg)
            all_ok = False

    # --- Port checks ---
    if "api" in services:
        ok, msg = check_port_available(8000)
        if ok:
            print_check_ok("端口 8000 (API)", msg)
        else:
            print_check_fail("端口 8000 (API)", msg)
            all_ok = False

    if "web" in services:
        ok, msg = check_port_available(10086)
        if ok:
            print_check_ok("端口 10086 (H5)", msg)
        else:
            print_check_fail("端口 10086 (H5)", msg)
            all_ok = False

    # --- Infrastructure connectivity (only if not skipped) ---
    if not skip_infra:
        ok, msg = check_docker_available()
        if ok:
            print_check_ok("Docker", msg)
        else:
            print_check_fail("Docker", msg)
            all_ok = False

        if ok:  # only probe if Docker is available
            ok, msg = check_postgres_connectivity()
            if ok:
                print_check_ok("数据库 (PostgreSQL)", msg)
            else:
                print_check_fail("数据库 (PostgreSQL)", msg)
                all_ok = False

            ok, msg = check_redis_connectivity()
            if ok:
                print_check_ok("Redis", msg)
            else:
                print_check_fail("Redis", msg)
                all_ok = False

            ok, msg = check_minio_connectivity()
            if ok:
                print_check_ok("MinIO", msg)
            else:
                print_check_fail("MinIO", msg)
                all_ok = False

    print()
    return all_ok


# ====================================================================
# Service startup
# ====================================================================


def _cleanup_procs(procs: list[tuple]) -> None:
    """Terminate all processes in the list (rollback on partial start failure)."""
    for proc, name in procs:
        if proc.poll() is None:
            terminate_process(proc, timeout=5.0)


def start_services(
    services: list[str], *, skip_infra: bool
) -> list[tuple]:
    """Start selected services and return list of (proc, name, module).

    Returns empty list if any service fails to start.
    """
    print_separator()
    print()
    print_stage("阶段二：服务启动")

    procs: list[tuple] = []

    # --- Infrastructure (Docker compose up) ---
    if not skip_infra:
        from start_infra import start_infra

        print(f"  ● {'Infra':<20s} 正在启动 Docker 容器...", flush=True)
        infra_proc = start_infra()
        stdout, _ = infra_proc.communicate(timeout=60)
        if infra_proc.returncode == 0:
            print_check_ok("Infra", "Docker 容器已就绪")
            time.sleep(2)
        else:
            print_check_fail("Infra", "Docker 启动失败")
            if stdout:
                print(f"     {stdout}")
            return []

    # --- API server ---
    if "api" in services:
        try:
            from start_api import start as start_api

            proc, name = start_api()
            procs.append((proc, name))
            print_service_starting(name, proc.pid)
        except Exception as exc:
            print_service_failed("API", str(exc))
            _cleanup_procs(procs)
            return []

    # --- Worker ---
    if "worker" in services:
        try:
            from start_worker import start as start_worker

            proc, name = start_worker()
            procs.append((proc, name))
            print_service_starting(name, proc.pid)
        except Exception as exc:
            print_service_failed("Worker", str(exc))
            _cleanup_procs(procs)
            return []

    # --- Web (H5 dev server) ---
    if "web" in services:
        try:
            from start_web import start as start_web

            proc, name = start_web(mode="h5")
            procs.append((proc, name))
            print_service_starting(name, proc.pid)
        except Exception as exc:
            print_service_failed("Web", str(exc))
            _cleanup_procs(procs)
            return []

    print()
    print_separator()
    print()
    print_stage("阶段三：运行中")
    print_running_status()

    return procs


# ====================================================================
# Log reader threads
# ====================================================================


def start_log_readers(procs: list[tuple]) -> tuple:
    """Start a reader thread per service. Returns (threads, stop_event)."""
    stop_event = threading.Event()
    threads: list[threading.Thread] = []

    for proc, name in procs:
        t = threading.Thread(
            target=read_output,
            args=(proc, lambda line, n=name: print_service_log(n, line, MAX_NAME_WIDTH)),
            kwargs={"stop_event": stop_event},
            daemon=True,
        )
        t.start()
        threads.append(t)

    return threads, stop_event


# ====================================================================
# Shutdown
# ====================================================================


def shutdown(procs: list[tuple], stop_event: threading.Event) -> None:
    """Gracefully shut down all services (spec 3.6.5)."""
    print()
    print_exit_header()

    # Signal log reader threads to stop
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

    print()
    print_exit_footer()


# ====================================================================
# Interactive menu (spec 3.5)
# ====================================================================


def _interactive_menu() -> list[str]:
    """Display interactive service selection menu. Returns list of service keys."""
    print_info("请选择要启动的服务（输入编号，多个以逗号分隔，回车=全部）:")
    print()
    items = list(AVAILABLE_SERVICES.items())
    for i, (key, desc) in enumerate(items, 1):
        print(f"  {i}. {desc}")
    print()
    print("  0. 仅启动基础设施 (Docker 容器)")
    print()

    try:
        raw = input("请输入: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return []

    if not raw:
        return list(AVAILABLE_SERVICES.keys())

    # Parse comma-separated numbers
    selected: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            idx = int(part)
        except ValueError:
            print_warning(f"忽略无效输入: {part}")
            continue
        if idx == 0:
            return []  # infrastructure only
        if 1 <= idx <= len(items):
            selected.append(items[idx - 1][0])

    return selected


# ====================================================================
# CLI argument parsing (spec 3.5)
# ====================================================================


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"{PROJECT_NAME} — 统一服务启动控制台",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python scripts/start.py                       交互式菜单\n"
            "  python scripts/start.py --services api,worker  启动 API + Worker\n"
            "  python scripts/start.py --all                   启动全部服务\n"
            "  python scripts/start.py --all --skip-infra      跳过 Docker，直接启动应用\n"
            "  python scripts/start.py --all --skip-checks     跳过前置检查\n"
        ),
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--services",
        type=str,
        default=None,
        help="要启动的服务，逗号分隔 (api,worker,web)",
    )
    group.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="启动全部服务",
    )

    parser.add_argument(
        "--skip-infra",
        action="store_true",
        default=False,
        help="跳过 Docker 基础设施启动（容器已运行时使用）",
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        default=False,
        help="跳过前置检查（加快重复启动）",
    )

    return parser.parse_args()


# ====================================================================
# Main
# ====================================================================


def main() -> None:
    args = _parse_args()

    # --- Determine target services ---
    if args.all:
        services = list(AVAILABLE_SERVICES.keys())
    elif args.services:
        services = [s.strip() for s in args.services.split(",") if s.strip()]
        invalid = [s for s in services if s not in AVAILABLE_SERVICES]
        if invalid:
            print_error(f"未知服务: {', '.join(invalid)}")
            print_info(f"可用服务: {', '.join(AVAILABLE_SERVICES.keys())}")
            sys.exit(1)
    else:
        services = _interactive_menu()
        if not services:
            # Infrastructure only mode
            print()
            print_stage("阶段二：服务启动")
            from start_infra import start_infra
            infra_proc = start_infra()
            stdout, _ = infra_proc.communicate(timeout=60)
            if infra_proc.returncode == 0:
                print_info("Docker 容器已启动（仅基础设施模式）")
            else:
                print_error("Docker 容器启动失败")
                if stdout:
                    print(stdout)
            return

    print_banner(PROJECT_NAME)

    # --- Phase 1: Pre-flight checks ---
    if not args.skip_checks:
        all_ok = run_preflight_checks(services, skip_infra=args.skip_infra)
        if not all_ok:
            print_error("前置检查未通过，启动已中止。请修复上述问题后重试。")
            sys.exit(1)
    else:
        print_warning("已跳过前置检查 (--skip-checks)")

    # --- Phase 2: Start services ---
    procs = start_services(services, skip_infra=args.skip_infra)
    if not procs:
        print_error("没有服务需要启动。")
        sys.exit(0)

    # --- Phase 3: Running (log monitoring) ---
    threads, stop_event = start_log_readers(procs)
    _shutdown_done = False

    def _do_shutdown() -> None:
        nonlocal _shutdown_done
        if not _shutdown_done:
            _shutdown_done = True
            shutdown(procs, stop_event)

    def _on_signal(signum: int, frame) -> None:
        _do_shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        while True:
            for proc, name in procs:
                exit_code = proc.poll()
                if exit_code is not None:
                    if exit_code != 0 and exit_code != -signal.SIGINT:
                        print()
                        print_service_failed(
                            name, f"意外退出 (exit code: {exit_code})"
                        )
                    _do_shutdown()
                    sys.exit(exit_code if exit_code > 0 else 0)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _do_shutdown()


if __name__ == "__main__":
    main()
