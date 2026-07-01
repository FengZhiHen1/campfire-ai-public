"""Pre-flight check utilities (spec 3.1).

Each check returns a (passed: bool, message: str) tuple.
Heavy imports happen inside functions to keep the module import fast.
Connectivity checks use TCP socket probes — lightweight and no driver dependencies.
"""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root resolution
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# 3.1.1 — Configuration file check
# ---------------------------------------------------------------------------


def check_env_file() -> tuple[bool, str]:
    """Verify .env exists. If not, point to .env.example."""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        return True, "已就绪"

    example = PROJECT_ROOT / ".env.example"
    if example.exists():
        return False, ("未找到 .env 文件\n        请从 .env.example 复制并填入真实值:\n          cp .env.example .env")

    return False, "未找到 .env 或 .env.example 文件"


# ---------------------------------------------------------------------------
# 3.1.2 — Critical dependency checks
# ---------------------------------------------------------------------------


def _run_cmd(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Run a command after resolving the executable via process_utils."""
    from utils.process_utils import resolve_exe

    resolved = [resolve_exe(cmd[0])] + cmd[1:]
    return subprocess.run(resolved, capture_output=True, text=True, timeout=timeout)


def check_uv_available() -> tuple[bool, str]:
    """Verify uv package manager is installed."""
    try:
        result = _run_cmd(["uv", "--version"], timeout=10)
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, "uv 未正确安装"
    except FileNotFoundError:
        return False, "uv 未安装 — 请访问 https://docs.astral.sh/uv/ 安装"
    except subprocess.TimeoutExpired:
        return False, "uv 检查超时"


def check_pnpm_available() -> tuple[bool, str]:
    """Verify pnpm package manager is installed."""
    try:
        result = _run_cmd(["pnpm", "--version"], timeout=10)
        if result.returncode == 0:
            return True, f"v{result.stdout.strip()}"
        return False, "pnpm 未正确安装"
    except FileNotFoundError:
        return False, "pnpm 未安装 — 请运行: npm install -g pnpm"
    except subprocess.TimeoutExpired:
        return False, "pnpm 检查超时"


def check_docker_available() -> tuple[bool, str]:
    """Verify Docker daemon is reachable."""
    try:
        result = _run_cmd(["docker", "info"], timeout=15)
        if result.returncode == 0:
            return True, "已就绪"
        return False, "Docker 未运行或权限不足 — 请启动 Docker Desktop"
    except FileNotFoundError:
        return False, "Docker 未安装"
    except subprocess.TimeoutExpired:
        return False, "Docker 检查超时"


def check_python_deps_installed() -> tuple[bool, str]:
    """Check whether Python dependencies have been synchronized."""
    venv = PROJECT_ROOT / ".venv"
    if venv.exists() and (venv / "pyvenv.cfg").exists():
        return True, "已安装（.venv 存在）"
    return False, "Python 依赖未安装 — 请运行: uv sync"


def check_node_deps_installed() -> tuple[bool, str]:
    """Check whether Node.js dependencies have been installed."""
    node_modules = PROJECT_ROOT / "node_modules"
    pnpm_store = PROJECT_ROOT / "node_modules" / ".pnpm"
    if node_modules.exists() and pnpm_store.exists():
        return True, "已安装"
    return False, "Node.js 依赖未安装 — 请运行: pnpm install"


# ---------------------------------------------------------------------------
# 3.1.3 — Port availability checks
# ---------------------------------------------------------------------------


def _tcp_connect(host: str, port: int, timeout: float = 3.0) -> tuple[bool, str]:
    """Low-level TCP connect probe. Returns (reachable, error_message)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((host, port))
        if result == 0:
            return True, ""
        return False, f"{host}:{port} 不可达"
    except socket.gaierror as e:
        return False, f"DNS 解析错误: {e}"
    except Exception as e:
        return False, str(e)
    finally:
        sock.close()


def check_port_available(port: int) -> tuple[bool, str]:
    """Verify a TCP port is free (not bound by another process)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
        sock.close()
        return True, f"端口 {port} 未被占用"
    except OSError:
        sock.close()
        return False, f"端口 {port} 已被占用 — 请先释放该端口"


# ---------------------------------------------------------------------------
# 3.1.4 — Infrastructure connectivity checks (TCP probe)
# ---------------------------------------------------------------------------


def check_postgres_connectivity(host: str = "localhost", port: int = 5432) -> tuple[bool, str]:
    """Probe PostgreSQL TCP port."""
    ok, err = _tcp_connect(host, port)
    if ok:
        return True, "已就绪"
    return False, f"数据库连接失败 → {err}，请确认 PostgreSQL 容器已启动"


def check_redis_connectivity(host: str = "localhost", port: int = 6379) -> tuple[bool, str]:
    """Probe Redis TCP port."""
    ok, err = _tcp_connect(host, port)
    if ok:
        return True, "已就绪"
    return False, f"Redis 连接失败 → {err}，请确认 Redis 容器已启动"


def check_minio_connectivity(host: str = "localhost", port: int = 9000) -> tuple[bool, str]:
    """Probe MinIO TCP port."""
    ok, err = _tcp_connect(host, port)
    if ok:
        return True, "已就绪"
    return False, f"MinIO 连接失败 → {err}，请确认 MinIO 容器已启动"
