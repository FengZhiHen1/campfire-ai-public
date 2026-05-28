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

# Preset startup modes (spec: 避免 h5/weapp 同时启动导致 dist/ 目录竞态)
PRESET_MODES: dict[str, dict] = {
    "1": {
        "key": "fullstack-h5",
        "name": "全栈 H5 开发",
        "desc": "API + Worker + H5 (port 5173)",
        "services": ["api", "worker", "web-h5"],
    },
    "2": {
        "key": "fullstack-weapp",
        "name": "全栈小程序开发",
        "desc": "API + Worker + 微信小程序",
        "services": ["api", "worker", "web-weapp"],
    },
    "3": {
        "key": "backend",
        "name": "仅后端",
        "desc": "API + Worker",
        "services": ["api", "worker"],
    },
    "4": {
        "key": "frontend-h5",
        "name": "仅前端 H5",
        "desc": "H5 only (port 5173)",
        "services": ["web-h5"],
    },
    "5": {
        "key": "frontend-weapp",
        "name": "仅前端小程序",
        "desc": "微信小程序 only",
        "services": ["web-weapp"],
    },
    "6": {
        "key": "custom",
        "name": "自定义",
        "desc": "逐个选择服务",
        "services": [],  # resolved via sub-menu
    },
}

MODE_BY_KEY: dict[str, str] = {m["key"]: num for num, m in PRESET_MODES.items()}

AVAILABLE_SERVICES: dict[str, str] = {
    "api": "API 服务 (FastAPI, port 8000)",
    "worker": "Worker 服务 (Redis 消费者)",
    "web-h5": "Web-H5 服务 (Taro H5 dev, port 5173)",
    "web-weapp": "Web-小程序 服务 (Taro 微信小程序 dev)",
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
from start_ngrok import start_ngrok, cleanup_ngrok_url_file  # noqa: E402
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
    if "web-h5" in services or "web-weapp" in services:
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

    if "web-h5" in services:
        ok, msg = check_port_available(5173)
        if ok:
            print_check_ok("端口 5173 (H5)", msg)
        else:
            print_check_fail("端口 5173 (H5)", msg)
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

    When both API and weapp are selected, automatically starts ngrok tunnel
    and writes the public URL to .ngrok-url for the mini-program build.

    Returns empty list if any service fails to start.
    """
    print_separator()
    print()
    print_stage("阶段二：服务启动")

    procs: list[tuple] = []
    ngrok_proc = None

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

    # --- Web-H5 ---
    if "web-h5" in services:
        try:
            from start_web import start as start_web

            proc, name = start_web(mode="h5")
            procs.append((proc, name))
            print_service_starting(name, proc.pid)
        except Exception as exc:
            print_service_failed("Web-H5", str(exc))
            _cleanup_procs(procs)
            return []

    # --- Web-Weapp (小程序) ---
    if "web-weapp" in services:
        # Start ngrok tunnel if API is also running (auto-detect)
        if "api" in services:
            try:
                print()
                print_info("正在启动 ngrok 内网穿透...")
                ngrok_proc, ngrok_url = start_ngrok(port=8000)
                procs.append((ngrok_proc, "ngrok"))
                print_check_ok("ngrok", f"公网地址: {ngrok_url}")
                print()
            except Exception as exc:
                print_warning(f"ngrok 启动失败: {exc}")
                print_warning("小程序将使用本地地址 http://127.0.0.1:8000")

        try:
            from start_web import start as start_web

            proc, name = start_web(mode="weapp")
            procs.append((proc, name))
            print_service_starting(name, proc.pid)
        except Exception as exc:
            print_service_failed("Web-Weapp", str(exc))
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

    # Clean up ngrok URL file
    cleanup_ngrok_url_file()

    print()
    print_exit_footer()


# ====================================================================
# Interactive menu (spec 3.5)
# ====================================================================


def _custom_service_menu() -> list[str]:
    """Individual service selection with mutual exclusion for h5/weapp."""
    print()
    print_info("选择要启动的服务（多选，逗号分隔，回车=全部）:")
    print()
    items = list(AVAILABLE_SERVICES.items())
    for i, (key, desc) in enumerate(items, 1):
        print(f"  {i}. {desc}")
    print()

    try:
        raw = input("请输入: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return []

    if not raw:
        return list(AVAILABLE_SERVICES.keys())

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
        if 1 <= idx <= len(items):
            selected.append(items[idx - 1][0])

    # h5 和 weapp 共享 dist/ 构建目录，同时启动会产生竞态导致 ENOENT
    if "web-h5" in selected and "web-weapp" in selected:
        print_warning("H5 和小程序共享构建目录，不能同时启动。请只选择其中一个。")
        return []

    return selected


def _interactive_menu() -> list[str]:
    """Two-stage menu: preset mode → (if custom) individual service selection."""
    print_info("请选择启动模式:")
    print()
    for num in ["1", "2", "3", "4", "5", "6"]:
        m = PRESET_MODES[num]
        print(f"  {num}. {m['name']:<18s} {m['desc']}")
    print()
    print("  0. 仅启动基础设施 (Docker 容器)")
    print()

    try:
        raw = input("请输入: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return []

    if raw == "0":
        return []  # infrastructure only
    if raw == "":
        return PRESET_MODES["1"]["services"]  # default: fullstack-h5
    if raw in PRESET_MODES:
        if raw == "6":
            return _custom_service_menu()
        return PRESET_MODES[raw]["services"]

    print_warning(f"无效选项: {raw}，使用默认模式 (全栈 H5)")
    return PRESET_MODES["1"]["services"]


# ====================================================================
# CLI argument parsing (spec 3.5)
# ====================================================================


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"{PROJECT_NAME} — 统一服务启动控制台",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python scripts/start.py                                交互式菜单\n"
            "  python scripts/start.py --mode fullstack-h5             全栈 H5 开发\n"
            "  python scripts/start.py --mode backend                  仅后端\n"
            "  python scripts/start.py --services api,worker           自定义组合\n"
            "  python scripts/start.py --all --skip-infra              跳过 Docker\n"
            "  python scripts/start.py --all --skip-checks             跳过前置检查\n"
            "\n"
            "可用模式: fullstack-h5, fullstack-weapp, backend, frontend-h5, frontend-weapp, custom"
        ),
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--mode",
        type=str,
        default=None,
        help="预设启动模式",
    )
    group.add_argument(
        "--services",
        type=str,
        default=None,
        help="要启动的服务，逗号分隔 (api,worker,web-h5,web-weapp)",
    )
    group.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="启动全部服务（不含 web-weapp，避免 dist/ 竞态）",
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
    if args.mode:
        # Resolve preset mode key → service list
        if args.mode == "custom":
            services = _custom_service_menu()
            if not services:
                print_error("未选择任何服务。")
                sys.exit(1)
        elif args.mode in MODE_BY_KEY:
            services = list(PRESET_MODES[MODE_BY_KEY[args.mode]]["services"])
        else:
            print_error(f"未知模式: {args.mode}")
            print_info(
                f"可用模式: {', '.join(MODE_BY_KEY.keys())}"
            )
            sys.exit(1)
    elif args.all:
        # --all 不再包含 web-weapp，避免 dist/ 竞态
        services = ["api", "worker", "web-h5"]
    elif args.services:
        services = [s.strip() for s in args.services.split(",") if s.strip()]
        invalid = [s for s in services if s not in AVAILABLE_SERVICES]
        if invalid:
            print_error(f"未知服务: {', '.join(invalid)}")
            print_info(f"可用服务: {', '.join(AVAILABLE_SERVICES.keys())}")
            sys.exit(1)
        # 自定义模式也做互斥保护
        if "web-h5" in services and "web-weapp" in services:
            print_error("H5 和小程序共享构建目录，不能同时启动。请只选择其中一个。")
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
