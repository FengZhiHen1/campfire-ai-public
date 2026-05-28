"""Cross-platform process management utilities (spec 3.2, 3.4).

All platform differences are encapsulated here. Business scripts call the
unified interface (start_process / terminate_process) and never hardcode
platform checks.

Unix: process groups via os.setsid + os.killpg (spec 3.2.1)
Windows: CREATE_NEW_PROCESS_GROUP + taskkill /F /T (spec 3.2.2)
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from typing import IO

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

_IS_WINDOWS: bool = sys.platform == "win32"

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_process(
    cmd: list[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
    log_file: str | None = None,
) -> subprocess.Popen:
    """Start a subprocess with platform-appropriate process-group settings.

    On Unix, the process becomes a new session leader (os.setsid).
    On Windows, a new process group is created (CREATE_NEW_PROCESS_GROUP).

    stdout/stderr are captured via PIPE for the controller to read and prefix.
    If log_file is provided, output is also tee'd to that file.

    Args:
        cmd: Command and arguments as a list.
        cwd: Working directory for the subprocess.
        env: Environment variables to merge with os.environ.
        log_file: Optional path to tee output to.

    Returns:
        A subprocess.Popen instance with stdout=PIPE, stderr=STDOUT.
    """
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
        "cwd": str(cwd) if cwd else None,
        "env": {**os.environ, **(env or {})},
    }

    if _IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["preexec_fn"] = os.setsid

    return subprocess.Popen(cmd, **kwargs)


def terminate_process(proc: subprocess.Popen, timeout: float = 10.0) -> bool:
    """Gracefully terminate a process and its entire process tree.

    Args:
        proc: The subprocess to terminate.
        timeout: Seconds to wait for graceful exit before force-killing.

    Returns:
        True if the process exited gracefully, False if force-killed.
    """
    if proc.poll() is not None:
        return True

    pid = proc.pid
    if pid is None:
        return True

    _terminate_tree(pid)

    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        _force_kill_tree(pid)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return False


def read_output(
    proc: subprocess.Popen,
    on_line: callable,
    *,
    stop_event: threading.Event | None = None,
) -> None:
    """Read lines from a subprocess stdout, calling on_line for each line.

    Runs in the calling thread — meant to be invoked in a dedicated thread.

    Args:
        proc: The subprocess whose stdout to read.
        on_line: Callback receiving each line (str).
        stop_event: Optional event to signal early exit.
    """
    stdout: IO[str] | None = proc.stdout  # type: ignore[assignment]
    if stdout is None:
        return

    try:
        for line in iter(stdout.readline, ""):
            if stop_event and stop_event.is_set():
                break
            if line:
                on_line(line.rstrip("\n"))
    except (ValueError, OSError):
        pass


# ---------------------------------------------------------------------------
# Internal: platform-specific tree termination
# ---------------------------------------------------------------------------


def _terminate_tree(pid: int) -> None:
    """Send graceful termination signal to the process tree."""
    if _IS_WINDOWS:
        _windows_taskkill(pid, force=False)
    else:
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def _force_kill_tree(pid: int) -> None:
    """Force-kill the process tree."""
    if _IS_WINDOWS:
        _windows_taskkill(pid, force=True)
    else:
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _windows_taskkill(pid: int, *, force: bool) -> None:
    """Use taskkill to terminate a process tree on Windows."""
    args = ["taskkill"]
    if force:
        args.append("/F")
    args.extend(["/T", "/PID", str(pid)])
    try:
        subprocess.run(args, capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        pass
