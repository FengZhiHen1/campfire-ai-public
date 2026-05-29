"""服务启动器契约 — ABC 模板方法定义。

所有服务启动器（API / Worker / Web / Infra / Ngrok）必须继承
ServiceLauncher 并实现 _do_start 钩子。公共入口 start() 由 @final
锁定，确保启动流程一致。

Usage:
    class ApiLauncher(ServiceLauncher):
        name = "api"
        display_name = "API"

        def _do_start(self) -> subprocess.Popen:
            return start_process(["uv", "run", "--package", "api-server", ...], cwd=...)
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod


class ServiceLauncher(ABC):
    """服务启动器抽象基类。

    Attributes:
        name: 服务标识（如 "api", "worker"），用于 CLI 参数匹配。
        display_name: 控制台展示名称（如 "API", "Worker"）。
        port: 默认端口号，None 表示不占用端口。
        log_prefix_width: 日志前缀的固定宽度。
    """

    name: str
    display_name: str
    port: int | None = None
    log_prefix_width: int = 8

    # ------------------------------------------------------------------
    # 公共接口（@final — 子类不得覆盖）
    # ------------------------------------------------------------------

    def start(self) -> subprocess.Popen:
        """模板方法：前置校验 → 子类启动 → 后置校验。

        Returns:
            已启动的 subprocess.Popen 实例。
        """
        self._pre_check()
        proc = self._do_start()
        self._post_check(proc)
        return proc

    # ------------------------------------------------------------------
    # 钩子（子类覆盖点）
    # ------------------------------------------------------------------

    def _pre_check(self) -> None:
        """前置校验（可选覆盖）。默认无操作。"""

    @abstractmethod
    def _do_start(self) -> subprocess.Popen:
        """启动子进程的具体逻辑（子类必须实现）。

        Returns:
            已启动的 subprocess.Popen 实例。
        """
        ...

    def _post_check(self, proc: subprocess.Popen) -> None:
        """后置校验（可选覆盖）。默认检查进程是否立即退出。"""
        if proc.poll() is not None:
            raise RuntimeError(
                f"{self.display_name} 进程启动后立即退出"
                f" (exit code: {proc.returncode})"
            )
