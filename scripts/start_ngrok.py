"""Ngrok 隧道启动器 — 将本地 API 暴露到公网。

Usage:
    from start_ngrok import NgrokLauncher
    launcher = NgrokLauncher(port=8000)
    proc = launcher.start()
    print(launcher.url)
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import urllib.request
import urllib.error

from launcher_contract import ServiceLauncher

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NGROK_URL_FILE = PROJECT_ROOT / ".ngrok-url"

# ---------------------------------------------------------------------------
# ngrok 二进制检测
# ---------------------------------------------------------------------------

_DEFAULT_NGROK_PATHS: list[str] = [
    str(Path.home() / "ngrok" / "ngrok.exe"),
    str(Path.home() / "ngrok" / "ngrok"),
    "ngrok",
]

_NGROK_BIN: str | None = None


def _find_ngrok() -> str:
    """定位 ngrok 可执行文件。找不到则抛出 FileNotFoundError。"""
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
# NgrokLauncher
# ---------------------------------------------------------------------------


class NgrokLauncher(ServiceLauncher):
    name = "ngrok"
    display_name = "ngrok"

    def __init__(self, port: int = 8000) -> None:
        self._port = port
        self._url: str | None = None

    @property
    def url(self) -> str | None:
        """获取已缓存的 ngrok 公网 URL。"""
        return self._url

    def _pre_check(self) -> None:
        _find_ngrok()  # 提前验证，失败则不给实现者机会

    def _do_start(self) -> subprocess.Popen:
        ngrok_bin = _find_ngrok()
        try:
            proc = subprocess.Popen(
                [ngrok_bin, "http", str(self._port)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except OSError as exc:
            raise RuntimeError(f"无法启动 ngrok: {exc}") from exc

        self._url = self._poll_for_url(proc)
        if self._url:
            _write_url_file(self._url)
        return proc

    def _poll_for_url(self, proc: subprocess.Popen) -> str:
        """轮询 ngrok 本地 API 直到获取公网 URL。"""
        api_url = "http://127.0.0.1:4040/api/tunnels"
        max_wait = 15
        interval = 0.5

        for _ in range(int(max_wait / interval)):
            time.sleep(interval)
            if proc.poll() is not None:
                out = self._read_process_output(proc)
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
                    for tunnel in data.get("tunnels", []):
                        public_url = tunnel.get("public_url", "")
                        if public_url.startswith("https://"):
                            return public_url
            except (urllib.error.URLError, json.JSONDecodeError, OSError):
                continue

        out = self._read_process_output(proc)
        proc.kill()
        proc.wait()
        raise RuntimeError(
            "ngrok 隧道获取超时（15s）。请检查网络连接或 ngrok 服务状态。\n"
            f"输出: {out.strip()[:800]}"
        )

    @staticmethod
    def _read_process_output(proc: subprocess.Popen) -> str:
        out = ""
        if proc.stdout is not None:
            out += proc.stdout.read()
        if proc.stderr is not None:
            out += proc.stderr.read()
        return out


# ---------------------------------------------------------------------------
# URL 文件管理（供外部使用）
# ---------------------------------------------------------------------------


def get_ngrok_url() -> str | None:
    """从文件读取缓存的 ngrok URL（非阻塞）。"""
    try:
        if NGROK_URL_FILE.exists():
            return NGROK_URL_FILE.read_text().strip()
    except OSError:
        pass
    return None


def cleanup_ngrok_url_file() -> None:
    """删除缓存的 ngrok URL 文件。"""
    try:
        NGROK_URL_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _write_url_file(url: str) -> None:
    try:
        NGROK_URL_FILE.write_text(url)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 向后兼容：保留函数式接口
# ---------------------------------------------------------------------------


def start_ngrok(port: int = 8000) -> tuple[subprocess.Popen, str]:
    """启动 ngrok 隧道。返回 (进程, 公网 URL)。"""
    launcher = NgrokLauncher(port=port)
    proc = launcher.start()
    return proc, launcher.url or ""
