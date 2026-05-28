"""Console UI utilities for the startup controller.

Provides colored output, layout structure, and service log prefix formatting.
Colors follow semantic mapping (spec 3.6.1):
  green=success, yellow=warning/waiting, red=error, cyan=info

ANSI escape codes are never hardcoded in business scripts — all color output
goes through this module.
"""

from __future__ import annotations

import shutil
import sys

# ---------------------------------------------------------------------------
# ANSI escape codes (semantic mapping per spec 3.6.1)
# ---------------------------------------------------------------------------

_RESET = "\033[0m"

_COLORS: dict[str, str] = {
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "white": "",
}

# ---------------------------------------------------------------------------
# Symbols (spec 3.6.2)
# ---------------------------------------------------------------------------

_CHECK_OK = "✔"
_CHECK_FAIL = "✘"
_SPINNER = "●"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _supports_color() -> bool:
    """Detect whether the current terminal supports ANSI color output."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _colored(text: str, color: str) -> str:
    """Wrap text in ANSI color codes. Returns plain text if no TTY."""
    if not _supports_color():
        return text
    code = _COLORS.get(color, "")
    if not code:
        return text
    return f"{code}{text}{_RESET}"


# ---------------------------------------------------------------------------
# Layout helpers (spec 3.6.2)
# ---------------------------------------------------------------------------


def print_banner(project_name: str) -> None:
    """Print the startup banner with project name."""
    width = 70
    banner = f"  {project_name} 服务启动控制台  "
    pad_left = (width - len(banner)) // 2
    pad_right = width - pad_left - len(banner)
    print()
    print("╔" + "═" * width + "╗")
    print("║" + " " * pad_left + banner + " " * pad_right + "║")
    print("╚" + "═" * width + "╝")
    print()


def print_separator() -> None:
    """Print a horizontal separator line."""
    terminal_width = shutil.get_terminal_size().columns
    print("─" * min(terminal_width, 80))


def print_stage(title: str) -> None:
    """Print a stage header like [阶段一：前置检查]."""
    print(f"[{title}]")


# ---------------------------------------------------------------------------
# Pre-flight check output (spec 3.6.3)
# ---------------------------------------------------------------------------


def print_check_ok(name: str, detail: str = "已就绪") -> None:
    """Print a passed check item."""
    print(f"  {_colored(_CHECK_OK, 'green')}  {name:<24s} {detail}")


def print_check_fail(name: str, detail: str) -> None:
    """Print a failed check item with reason."""
    print(f"  {_colored(_CHECK_FAIL, 'red')}  {name:<24s} {_colored(detail, 'red')}")


# ---------------------------------------------------------------------------
# Service lifecycle output (spec 3.6.2, 3.6.4, 3.6.5)
# ---------------------------------------------------------------------------


def print_service_starting(name: str, pid: int) -> None:
    """Print a service starting message."""
    print(f"  {_colored(_SPINNER, 'yellow')} {name:<20s} 正在启动... (PID: {pid})")


def print_service_terminating(name: str, pid: int) -> None:
    """Print a service termination in-progress message (no newline)."""
    sys.stdout.write(f"  → 正在终止 {name:<16s} (PID: {pid}) ... ")
    sys.stdout.flush()


def print_service_terminated_ok() -> None:
    """Print termination success marker."""
    print(_colored(f"{_CHECK_OK} 已关闭", "green"))


def print_service_terminated_forced() -> None:
    """Print forced termination marker."""
    print(_colored("强制终止", "yellow"))


def print_service_failed(name: str, reason: str) -> None:
    """Print a service failure message."""
    print(f"  {_colored(_CHECK_FAIL, 'red')} {name:<20s} {_colored(reason, 'red')}")


def print_running_status() -> None:
    """Print the 'all services ready' message."""
    print(f"  所有服务已就绪。按下 {_colored('Ctrl+C', 'cyan')} 可安全终止所有服务。")
    print()


def print_exit_header() -> None:
    """Print shutdown phase header."""
    print_separator()
    print("接收到退出信号，正在安全关闭所有服务...")
    print()


def print_exit_footer() -> None:
    """Print shutdown completion footer."""
    print("所有服务已安全退出。")
    print_separator()


# ---------------------------------------------------------------------------
# Service log output (spec 3.6.4)
# ---------------------------------------------------------------------------


def print_service_log(service_name: str, line: str, max_name_width: int = 8) -> None:
    """Print a log line with fixed-width service name prefix.

    Args:
        service_name: Short service identifier (e.g. "API", "Worker").
        line: The raw log line from the subprocess.
        max_name_width: Fixed width for the service name column.
    """
    prefix = f"[{service_name:<{max_name_width}s}]"
    print(f"{prefix} {line}", flush=True)


def print_info(msg: str) -> None:
    """Print an informational message in cyan."""
    print(_colored(msg, "cyan"))


def print_error(msg: str) -> None:
    """Print an error message in red."""
    print(_colored(msg, "red"))


def print_warning(msg: str) -> None:
    """Print a warning message in yellow."""
    print(_colored(msg, "yellow"))
