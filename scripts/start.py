#!/usr/bin/env python3
"""Campfire-AI 统一启动控制台。

Usage:
  python scripts/start.py                        # 交互式菜单
  python scripts/start.py --mode fullstack-h5     # 预设模式
  python scripts/start.py --services api,worker   # 自定义组合
  python scripts/start.py --all                   # 启动全部
  python scripts/start.py --skip-infra            # 跳过 Docker
  python scripts/start.py --skip-checks           # 跳过前置检查
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

PROJECT_NAME = "篝火智答 (Campfire-AI)"
MAX_NAME_WIDTH = 8

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
        "services": [],
    },
}

MODE_BY_KEY: dict[str, str] = {m["key"]: num for num, m in PRESET_MODES.items()}

AVAILABLE_SERVICES: dict[str, str] = {
    "api": "API 服务 (FastAPI, port 8000)",
    "worker": "Worker 服务 (Redis 消费者)",
    "web-h5": "Web-H5 服务 (Taro H5 dev, port 5173)",
    "web-weapp": "Web-小程序 服务 (Taro 微信小程序 dev)",
}

# ---------------------------------------------------------------------------
# 日志导入（sys.path 设置后）
# ---------------------------------------------------------------------------

from utils.logger import logger  # noqa: E402
from utils.log_utils import (  # noqa: E402
    print_banner,
    print_check_fail,
    print_check_ok,
    print_error,
    print_info,
    print_running_status,
    print_separator,
    print_service_failed,
    print_service_starting,
    print_stage,
    print_warning,
)
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
from utils.launcher_utils import (  # noqa: E402
    run_standalone,
    shutdown_services,
    start_log_readers,
)


# ====================================================================
# 启动器工厂
# ====================================================================


def _create_launcher(service_key: str, project_root: Path = PROJECT_ROOT):
    """根据服务标识创建对应的启动器实例。"""
    if service_key == "api":
        from start_api import ApiLauncher
        return ApiLauncher(project_root=project_root)
    elif service_key == "worker":
        from start_worker import WorkerLauncher
        return WorkerLauncher(project_root=project_root)
    elif service_key == "web-h5":
        from start_web import WebLauncher
        return WebLauncher(mode="h5", project_root=project_root)
    elif service_key == "web-weapp":
        from start_web import WebLauncher
        return WebLauncher(mode="weapp", project_root=project_root)
    raise ValueError(f"未知服务: {service_key}")


# ====================================================================
# 前置检查
# ====================================================================


def run_preflight_checks(services: list[str], *, skip_infra: bool) -> bool:
    """执行所有前置检查。全部通过返回 True。"""
    print_stage("阶段一：前置检查")
    all_ok = True

    checks: list[tuple[str, tuple[bool, str]]] = []

    # .env 检查
    checks.append((".env 配置文件", check_env_file()))

    # Python 工具链
    if "api" in services or "worker" in services:
        checks.append(("uv 包管理器", check_uv_available()))
        checks.append(("Python 依赖", check_python_deps_installed()))

    # Node.js 工具链
    if "web-h5" in services or "web-weapp" in services:
        checks.append(("pnpm 包管理器", check_pnpm_available()))
        checks.append(("Node.js 依赖", check_node_deps_installed()))

    # 端口
    if "api" in services:
        checks.append(("端口 8000 (API)", check_port_available(8000)))
    if "web-h5" in services:
        checks.append(("端口 5173 (H5)", check_port_available(5173)))

    # 基础设施
    if not skip_infra:
        docker_ok, docker_msg = check_docker_available()
        checks.append(("Docker", (docker_ok, docker_msg)))
        if docker_ok:
            checks.append(("数据库 (PostgreSQL)", check_postgres_connectivity()))
            checks.append(("Redis", check_redis_connectivity()))
            checks.append(("MinIO", check_minio_connectivity()))

    for name, (ok, msg) in checks:
        if ok:
            print_check_ok(name, msg)
        else:
            print_check_fail(name, msg)
            logger.warning(service="scripts", message=f"前置检查失败: {name}",
                           op_type="preflight_check", extra={"detail": msg})
            all_ok = False

    print()
    return all_ok


# ====================================================================
# 服务启动编排
# ====================================================================


def start_services(services: list[str], *, skip_infra: bool) -> list[tuple]:
    """按序启动所有选中服务。返回 [(进程, 服务名), ...] 列表。

    微信小程序 + API 同时启动时自动开启 ngrok 隧道。
    任一服务启动失败则回滚已启动的进程。
    """
    print_separator()
    print()
    print_stage("阶段二：服务启动")

    procs: list[tuple] = []

    def _cleanup() -> None:
        from utils.process_utils import terminate_process
        for proc, _name in procs:
            if proc.poll() is None:
                terminate_process(proc, timeout=5.0)

    # --- 基础设施 ---
    if not skip_infra:
        from start_infra import InfraLauncher
        print(f"  ● {'Infra':<20s} 正在启动 Docker 容器...", flush=True)
        infra = InfraLauncher()
        infra_proc = infra.start()
        stdout, _ = infra_proc.communicate(timeout=60)
        if infra_proc.returncode == 0:
            print_check_ok("Infra", "Docker 容器已就绪")
            logger.info(service="scripts", message="Docker 容器已启动", op_type="infra_start")
            time.sleep(2)
        else:
            print_check_fail("Infra", "Docker 启动失败")
            logger.error(service="scripts", message="Docker 容器启动失败",
                         op_type="infra_start", extra={"exit_code": infra_proc.returncode})
            if stdout:
                print(f"     {stdout}")
            return []

    # --- Ngrok（weapp + api 同时启动时） ---
    ngrok_url: str | None = None
    if "web-weapp" in services and "api" in services:
        try:
            from start_ngrok import NgrokLauncher
            print()
            print_info("正在启动 ngrok 内网穿透...")
            ngrok = NgrokLauncher(port=8000)
            ngrok_proc = ngrok.start()
            ngrok_url = ngrok.url
            procs.append((ngrok_proc, "ngrok"))
            print_check_ok("ngrok", f"公网地址: {ngrok_url}")
            print()
        except Exception as exc:
            print_warning(f"ngrok 启动失败: {exc}")
            logger.warning(service="scripts", message=f"ngrok 启动失败: {exc}",
                           op_type="ngrok_start")

    # --- 业务服务 ---
    for key in services:
        try:
            launcher = _create_launcher(key)
            proc = launcher.start()
            procs.append((proc, launcher.display_name))
            print_service_starting(launcher.display_name, proc.pid)
        except Exception as exc:
            print_service_failed(launcher.display_name if 'launcher' in dir() else key, str(exc))
            _cleanup()
            return []

    print()
    print_separator()
    print()
    print_stage("阶段三：运行中")
    print_running_status(services)

    return procs


# ====================================================================
# 交互式菜单
# ====================================================================


def _custom_service_menu() -> list[str]:
    """逐个选择服务。"""
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

    if "web-h5" in selected and "web-weapp" in selected:
        print_warning("H5 和小程序共享构建目录，不能同时启动。请只选择其中一个。")
        return []

    return selected


def _interactive_menu() -> list[str]:
    """两级菜单：预设模式 → 自定义服务选择。"""
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
        return []
    if raw == "":
        return PRESET_MODES["1"]["services"]
    if raw in PRESET_MODES:
        if raw == "6":
            return _custom_service_menu()
        return PRESET_MODES[raw]["services"]

    print_warning(f"无效选项: {raw}，使用默认模式 (全栈 H5)")
    return PRESET_MODES["1"]["services"]


# ====================================================================
# CLI 参数解析
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
    group.add_argument("--mode", type=str, default=None, help="预设启动模式")
    group.add_argument("--services", type=str, default=None, help="服务列表，逗号分隔")
    group.add_argument("--all", action="store_true", default=False, help="启动全部服务")

    parser.add_argument("--skip-infra", action="store_true", default=False, help="跳过 Docker")
    parser.add_argument("--skip-checks", action="store_true", default=False, help="跳过前置检查")

    return parser.parse_args()


def _resolve_services(args: argparse.Namespace) -> list[str]:
    """根据 CLI 参数解析目标服务列表。"""
    if args.mode:
        if args.mode == "custom":
            services = _custom_service_menu()
            if not services:
                print_error("未选择任何服务。")
                sys.exit(1)
            return services
        if args.mode in MODE_BY_KEY:
            return list(PRESET_MODES[MODE_BY_KEY[args.mode]]["services"])
        print_error(f"未知模式: {args.mode}")
        print_info(f"可用模式: {', '.join(MODE_BY_KEY.keys())}")
        sys.exit(1)

    if args.all:
        return ["api", "worker", "web-h5"]

    if args.services:
        services = [s.strip() for s in args.services.split(",") if s.strip()]
        invalid = [s for s in services if s not in AVAILABLE_SERVICES]
        if invalid:
            print_error(f"未知服务: {', '.join(invalid)}")
            print_info(f"可用服务: {', '.join(AVAILABLE_SERVICES.keys())}")
            sys.exit(1)
        if "web-h5" in services and "web-weapp" in services:
            print_error("H5 和小程序共享构建目录，不能同时启动。请只选择其中一个。")
            sys.exit(1)
        return services

    return _interactive_menu()


# ====================================================================
# 主入口
# ====================================================================


def main() -> None:
    args = _parse_args()
    services = _resolve_services(args)

    # 仅基础设施模式
    if not services:
        from start_infra import InfraLauncher
        print()
        print_stage("阶段二：服务启动")
        infra = InfraLauncher()
        infra_proc = infra.start()
        stdout, _ = infra_proc.communicate(timeout=60)
        if infra_proc.returncode == 0:
            print_info("Docker 容器已启动（仅基础设施模式）")
        else:
            print_error("Docker 容器启动失败")
            if stdout:
                print(stdout)
        return

    print_banner(PROJECT_NAME)

    # 阶段一：前置检查
    if not args.skip_checks:
        if not run_preflight_checks(services, skip_infra=args.skip_infra):
            print_error("前置检查未通过，启动已中止。请修复上述问题后重试。")
            sys.exit(1)
    else:
        print_warning("已跳过前置检查 (--skip-checks)")

    # 阶段二：启动服务
    procs = start_services(services, skip_infra=args.skip_infra)
    if not procs:
        print_error("没有服务需要启动。")
        sys.exit(0)

    # 阶段三：运行监控
    threads, stop_event = start_log_readers(procs, MAX_NAME_WIDTH)
    _shutdown_done = False

    def _do_shutdown() -> None:
        nonlocal _shutdown_done
        if not _shutdown_done:
            _shutdown_done = True
            shutdown_services(procs, stop_event)

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
                        print_service_failed(name, f"意外退出 (exit code: {exit_code})")
                        logger.error(service="scripts", message=f"{name} 意外退出",
                                     op_type="service_crash", extra={"exit_code": exit_code})
                    _do_shutdown()
                    sys.exit(exit_code if exit_code > 0 else 0)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _do_shutdown()


if __name__ == "__main__":
    main()
