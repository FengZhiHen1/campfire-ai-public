# @contract
"""OBS-01 结构化日志 — 行为契约（ABC 模板方法）。

定义结构化日志记录器的契约骨架：
- @final debug/info/warning/error/critical = 唯一外部入口
- @abstractmethod _do_emit() = 实现者填写的日志输出钩子
- _validate_entry() = 基线校验（日志等级、必填字段）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import final

from py_logger.types import LogSeverity, ServiceName


class BaseStructuredLogger(ABC):
    """结构化日志记录器契约。

    定义"校验日志条目 → 输出日志"的流程。
    外部调用者只能通过 @final 的 debug/info/warning/error/critical
    方法写入日志，无法绕过校验。

    实现者只能覆写 _do_ 前缀的钩子。
    """

    # === @final 公共方法：外部唯一入口 ===
    # 所有方法委托到 _emit()，确保校验逻辑单一变更点。

    @final
    def debug(
        self,
        service: str,
        message: str,
        op_type: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        """写入 DEBUG 级别日志。"""
        self._emit("DEBUG", service, message, op_type, extra)

    @final
    def info(
        self,
        service: str,
        message: str,
        op_type: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        """写入 INFO 级别日志。"""
        self._emit("INFO", service, message, op_type, extra)

    @final
    def warning(
        self,
        service: str,
        message: str,
        op_type: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        """写入 WARNING 级别日志。"""
        self._emit("WARNING", service, message, op_type, extra)

    @final
    def error(
        self,
        service: str,
        message: str,
        op_type: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        """写入 ERROR 级别日志。"""
        self._emit("ERROR", service, message, op_type, extra)

    @final
    def critical(
        self,
        service: str,
        message: str,
        op_type: str,
        extra: dict[str, object] | None = None,
    ) -> None:
        """写入审计日志（CRITICAL 级别）。

        op_type 为必填参数——调用方无法通过省略参数绕过审计。
        类型检查器即可在代码提交前发现遗漏。
        """
        if not op_type or not op_type.strip():
            raise ValueError("op_type is required for critical audit log")
        self._emit("CRITICAL", service, message, op_type, extra)

    # === 内部转发（不可覆写） ===

    @final
    def _emit(
        self,
        severity: LogSeverity,
        service: str,
        message: str,
        op_type: str | None,
        extra: dict[str, object] | None,
    ) -> None:
        """校验 → 输出的统一入口。所有 @final 公共方法委托到此。"""
        svc = ServiceName(service)
        self._validate_entry(severity, svc, message)
        self._do_emit(severity, svc, message, op_type, extra)

    # === @abstractmethod 钩子：实现者必填 ===

    @abstractmethod
    def _do_emit(
        self,
        severity: LogSeverity,
        service: ServiceName,
        message: str,
        op_type: str | None,
        extra: dict[str, object] | None,
    ) -> None:
        """将日志条目输出到目标通道。

        实现者在此填写实际的日志输出逻辑（序列化、写 stdout、写文件）。
        参数校验已由 @final 公共方法处理，实现者无需关心。

        Args:
            severity: 日志严重等级。
            service: 产生日志的服务模块名称。
            message: 人类可读的事件描述文本。
            op_type: 业务操作类别（审计日志必填）。
            extra: 结构化业务上下文。
        """
        ...

    # === 校验器：模板提供基线校验 ===

    def _validate_entry(
        self,
        severity: LogSeverity,
        service: ServiceName,
        message: str,
    ) -> None:
        """基线日志条目校验。

        子类可通过 super() 叠加额外的校验逻辑。

        Raises:
            ValueError: 必填字段为空。
        """
        if not service:
            raise ValueError("service must not be empty")
        if not message:
            raise ValueError("message must not be empty")
