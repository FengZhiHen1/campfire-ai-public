"""Ngrok tunnel launcher — exposes local API server to the public internet.

Starts ngrok in the background, polls the local ngrok API for the public URL,
writes it to .ngrok-url so the mini-program build can pick it up.

Usage:
    from start_ngrok import start_ngrok, get_ngrok_url, cleanup_ngrok_url_file

    proc, url = start_ngrok(port=8000)
    print(f"Public URL: {url}")
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import urllib.request
import urllib.error

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NGROK_URL_FILE = PROJECT_ROOT / ".ngrok-url"

# ---------------------------------------------------------------------------
# ngrok binary detection
# ---------------------------------------------------------------------------

_DEFAULT_NGROK_PATHS: list[str] = [
    str(Path.home() / "ngrok" / "ngrok.exe"),
    str(Path.home() / "ngrok" / "ngrok"),
    "ngrok",
]

_NGROK_BIN: str | None = None


def _find_ngrok() -> str:
    """Locate the ngrok binary. Raises FileNotFoundError if not found."""
    global _NGROK_BIN
    if _NGROK_BIN is not None:
        return _NGROK_BIN

    import shutil
    for candidate in _DEFAULT_NGROK_PATHS:
        if shutil.which(candidate) or Path(candidate).is_file():
            _NGROK_BIN = candidate
            return candidate

    raise FileNotFoundError(
        "ngrok 未找到。请确保 ngrok 已安装并在 PATH 中，"
        "或放在 ~/ngrok/ngrok.exe。\n"
        "下载地址: https://ngrok.com/download"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_ngrok(port: int = 8000) -> tuple[subprocess.Popen, str]:
    """Start the ngrok HTTP tunnel and return (process, public_url).

    Args:
        port: Local port to forward traffic to (default 8000).

    Returns:
        (subprocess.Popen, str): The ngrok subprocess and the public URL.

    Raises:
        FileNotFoundError: ngrok binary not found.
        RuntimeError: ngrok failed to start or tunnel could not be obtained.
    """
    ngrok_bin = _find_ngrok()

    # Start ngrok — capture both stdout and stderr for diagnostics on failure
    try:
        proc = subprocess.Popen(
            [ngrok_bin, "http", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except OSError as exc:
        raise RuntimeError(f"无法启动 ngrok: {exc}") from exc

    # Poll the ngrok local API until we get the public URL
    api_url = "http://127.0.0.1:4040/api/tunnels"
    max_wait = 15  # seconds
    interval = 0.5

    for _ in range(int(max_wait / interval)):
        time.sleep(interval)
        # Check if process is still alive
        if proc.poll() is not None:
            out = ""
            if proc.stdout is not None:
                out += proc.stdout.read()
            if proc.stderr is not None:
                out += proc.stderr.read()
            hint = ""
            if "authtoken" in out.lower() or "forbidden" in out.lower():
                hint = " 请先配置 authtoken: ngrok config add-authtoken <token>"
            raise RuntimeError(
                f"ngrok 进程意外退出 (exit code: {proc.returncode})。{hint}\n"
                f"输出: {out.strip()[:800]}"
            )

        try:
            with urllib.request.urlopen(api_url, timeout=2) as resp:
                data = json.loads(resp.read().decode())
                tunnels = data.get("tunnels", [])
                for tunnel in tunnels:
                    public_url = tunnel.get("public_url", "")
                    if public_url.startswith("https://"):
                        # Write URL file for mini-program config
                        _write_url_file(public_url)
                        return proc, public_url
        except (urllib.error.URLError, json.JSONDecodeError, OSError):
            continue

    # Timed out
    out = ""
    if proc.stdout is not None:
        out += proc.stdout.read()
    if proc.stderr is not None:
        out += proc.stderr.read()
    proc.kill()
    proc.wait()
    raise RuntimeError(
        "ngrok 隧道获取超时（15s）。请检查网络连接或 ngrok 服务状态。\n"
        f"输出: {out.strip()[:800]}"
    )


def get_ngrok_url() -> str | None:
    """Read the cached ngrok URL from file (non-blocking)."""
    try:
        if NGROK_URL_FILE.exists():
            return NGROK_URL_FILE.read_text().strip()
    except OSError:
        pass
    return None


def cleanup_ngrok_url_file() -> None:
    """Remove the cached ngrok URL file (called on shutdown)."""
    try:
        NGROK_URL_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _write_url_file(url: str) -> None:
    """Persist the ngrok URL so the mini-program build can read it."""
    try:
        NGROK_URL_FILE.write_text(url)
    except OSError:
        pass
