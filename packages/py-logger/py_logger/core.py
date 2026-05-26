"""
结构化日志核心模块。

提供 JSONFormatter、Logger 单例及 5 个公共日志方法：
debug / info / warning / error / critical。

日志输出链路：调用方传入参数 → contextvars 自动注入 trace_id →
组装 LogEntry dict → json.dumps 序列化 → stdout 输出 → Docker 日志驱动采集。

Zero external dependencies —— 仅使用 Python 3.12 标准库。
"""

from __future__ import annotations

import collections
import json
import logging
import sys
import uuid
from datetime import datetime, timezone

from .context import get_trace_id

# ============================================================================
# 常量
# ============================================================================

MAX_BUFFER_SIZE: int = 5000
"""环形缓冲区最大容量（条数）"""

BUFFER_HIGH_WATERMARK: int = int(MAX_BUFFER_SIZE * 0.8)  # 4000
"""高水位阈值 —— 达到此值时触发等级淘汰"""

BUFFER_LOW_WATERMARK: int = int(MAX_BUFFER_SIZE * 0.5)  # 2500
"""低水位阈值 —— 等级淘汰停止目标"""

SEVERITY_EVICTION_ORDER: list[str] = ["DEBUG", "INFO"]
"""等级淘汰优先级 —— 列表中越靠前的级别越优先被淘汰。
WARNING 和 ERROR 永不被淘汰。"""

# ============================================================================
# 环形缓冲区（模块级状态）
# ============================================================================

_buffer: collections.deque[tuple[str, str, str]] = collections.deque()
"""环形缓冲区：存储 (timestamp, severity, json_str) 元组"""

_buffer_warning_issued: bool = False
"""是否已向 stderr 输出过缓冲告警（仅首次输出一次）"""


# ============================================================================
# 工具函数
# ============================================================================

def _make_timestamp() -> str:
    """生成 UTC ISO 8601 时间戳，精确到毫秒，以 Z 结尾。"""
    now = datetime.now(timezone.utc)
    ms = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def _default_handler(obj: object) -> str:
    """json.dumps 的 default handler —— 对不可序列化对象返回占位字符串。"""
    return f"<{type(obj).__name__}: {repr(obj)[:100]}>"


# ============================================================================
# JSONFormatter
# ============================================================================

class JSONFormatter(logging.Formatter):
    """
    自定义 JSON 格式化器，将 LogRecord 格式化为单行 JSON 字符串。

    子类化 logging.Formatter，重写 format(record) 方法，
    输出包含 timestamp / severity / service / trace_id / message
    / op_type / extra 字段的 JSON 行。
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, object] = {
            "timestamp": _make_timestamp(),
            "severity": record.levelname,
            "service": getattr(record, "service", "unknown"),
            "trace_id": getattr(record, "trace_id", ""),
            "message": record.getMessage(),
            "op_type": getattr(record, "op_type", None),
            "extra": getattr(record, "extra", None),
        }
        return json.dumps(log_entry, default=_default_handler, ensure_ascii=False)


# ============================================================================
# Logger 单例
# ============================================================================

class _Logger:
    """
    结构化日志记录器单例。

    通过 ``from py_logger import logger`` 导入全局唯一实例。
    提供 5 个公共方法：debug / info / warning / error / critical。

    所有日志方法的外层异常屏障确保内部异常永不向调用方传播，
    critical() 的 op_type 校验异常除外（有意传播以强制调用方修正代码）。
    """

    def __init__(self) -> None:
        self._logging_logger = logging.getLogger("py-logger")
        self._logging_logger.setLevel(logging.DEBUG)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def debug(
        self,
        service: str,
        message: str,
        op_type: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        """
        写入 DEBUG 级别日志。用于开发调试，本地环境默认启用。

        Args:
            service: 来源服务名称。
            message: 日志消息正文，长度 1-4096 字符。
            op_type: 可选，操作类型。DEBUG 日志通常不填。
            extra: 可选，结构化补充数据。

        Returns:
            None —— 日志写入 stdout 不返回值。
        """
        self._write("DEBUG", service, message, op_type, extra)

    def info(
        self,
        service: str,
        message: str,
        op_type: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        """
        写入 INFO 级别日志。用于正常业务事件（请求开始/完成、用户操作）。

        Args:
            service: 来源服务名称。
            message: 日志消息正文，长度 1-4096 字符。
            op_type: 可选，操作类型。非关键动作可省略。
            extra: 可选，结构化补充数据。

        Returns:
            None —— 日志写入 stdout 不返回值。
        """
        self._write("INFO", service, message, op_type, extra)

    def warning(
        self,
        service: str,
        message: str,
        op_type: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        """
        写入 WARNING 级别日志。用于非错误但需关注的事件（重试发生、降级触发）。

        Args:
            service: 来源服务名称。
            message: 日志消息正文，长度 1-4096 字符。
            op_type: 可选，操作类型。
            extra: 可选，结构化补充数据。

        Returns:
            None —— 日志写入 stdout 不返回值。
        """
        self._write("WARNING", service, message, op_type, extra)

    def error(
        self,
        service: str,
        message: str,
        op_type: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        """
        写入 ERROR 级别日志。用于业务异常（数据库连接失败、外部 API 调用失败）。

        Args:
            service: 来源服务名称。
            message: 日志消息正文，长度 1-4096 字符。
            op_type: 可选，操作类型。
            extra: 可选，结构化补充数据（如异常堆栈摘要、错误码）。

        Returns:
            None —— 日志写入 stdout 不返回值。
        """
        self._write("ERROR", service, message, op_type, extra)

    def critical(
        self,
        service: str,
        message: str,
        op_type: str,
        extra: dict[str, object] | None = None,
    ) -> None:
        """
        写入审计日志（内部使用 INFO 级别输出）。用于 AI 调用、权限拒绝、工单创建。

        op_type 为必填参数 —— 调用方不得省略或传入空字符串。
        此方法在接口层面强制审计不可绕过。

        Args:
            service: 来源服务名称。
            message: 日志消息正文。
            op_type: 操作类型（必填）。合法值包括 "AI调用"、"权限拒绝"、"工单创建"。
            extra: 可选，结构化补充数据。

        Returns:
            None —— 日志写入 stdout 不返回值。

        Raises:
            ValueError: op_type 为空字符串或仅含空白字符。
        """
        if not op_type or not op_type.strip():
            raise ValueError("op_type is required for critical audit log")
        self._write("INFO", service, message, op_type, extra)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _write(
        self,
        severity: str,
        service: str,
        message: str,
        op_type: str | None,
        extra: dict[str, object] | None,
    ) -> None:
        """
        核心日志写入管线。

        步骤：获取 trace_id → 组装 LogEntry → JSON 序列化 → stdout 输出。
        最外层 try/except Exception 确保内部异常永不向调用方传播。

        Args:
            severity: 日志严重等级（DEBUG / INFO / WARNING / ERROR）。
            service: 来源服务名称。
            message: 日志消息正文。
            op_type: 操作类型（可为 None）。
            extra: 结构化补充数据（可为 None）。
        """
        try:
            # 步骤 1：获取 trace_id
            trace_id = get_trace_id()
            extra_dict: dict[str, object] = {}

            if extra is not None:
                extra_dict = dict(extra)

            if not trace_id:
                trace_id = uuid.uuid4().hex
                extra_dict["_trace_missing"] = True

            # 步骤 2：组装 LogEntry
            timestamp = _make_timestamp()
            log_entry: dict[str, object] = {
                "timestamp": timestamp,
                "severity": severity,
                "service": service,
                "trace_id": trace_id,
                "message": message,
                "op_type": op_type,
                "extra": extra_dict if extra_dict else ({} if extra is not None else None),
            }

            # 步骤 3：JSON 序列化
            try:
                json_str = json.dumps(
                    log_entry,
                    default=_default_handler,
                    ensure_ascii=False,
                )
            except (TypeError, ValueError):
                # JSON 序列化失败 → 构造降级日志
                json_str = self._build_fallback(
                    service, trace_id, message, extra_dict
                )
                print(
                    f"[py-logger] serialization failed for message: {message[:200]}",
                    file=sys.stderr,
                )

            # 步骤 4：stdout 输出（含缓冲/恢复逻辑）
            self._write_stdout(json_str, severity, timestamp)

        except Exception:
            # 终极安全网 —— 即使降级日志本身失败也不传播
            pass

    def _build_fallback(
        self,
        service: str,
        trace_id: str,
        message: str,
        extra: dict[str, object],
    ) -> str:
        """
        构造序列化失败时的降级日志 JSON 字符串。

        Args:
            service: 来源服务名称。
            trace_id: 当前 trace_id。
            message: 原始日志消息（用于 stderr 告警）。
            extra: 原始 extra dict（用于提取 original_keys / original_types）。

        Returns:
            降级日志的 JSON 字符串（severity="ERROR"，
            extra 含 _serialize_error=true）。
        """
        original_keys = list(extra.keys())[:20]
        original_types: dict[str, str] = {}
        for k in original_keys:
            original_types[k] = type(extra[k]).__name__

        fallback_entry: dict[str, object] = {
            "timestamp": _make_timestamp(),
            "severity": "ERROR",
            "service": service,
            "trace_id": trace_id,
            "message": (
                "日志序列化失败，"
                "原始数据类型见 extra._serialize_error"
            ),
            "op_type": None,
            "extra": {
                "_serialize_error": True,
                "original_keys": original_keys,
                "original_types": original_types,
            },
        }
        return json.dumps(fallback_entry, ensure_ascii=False)

    # ------------------------------------------------------------------
    # stdout 输出与环形缓冲区
    # ------------------------------------------------------------------

    def _write_stdout(
        self,
        json_str: str,
        severity: str,
        timestamp: str,
    ) -> None:
        """
        向 stdout 写入一行 JSON 日志。若 stdout 不可用则进入环形缓冲区。

        Args:
            json_str: JSON 字符串（不含末尾换行符）。
            severity: 日志等级（用于缓冲时按等级淘汰）。
            timestamp: 日志时间戳（用于缓冲时排序刷出）。
        """
        global _buffer_warning_issued

        try:
            # 优先尝试刷出缓冲区中的积压日志
            self._flush_buffer()

            # 写入当前日志条目
            sys.stdout.write(json_str + "\n")
            sys.stdout.flush()
        except (OSError, BrokenPipeError):
            # stdout 不可用 → 进入环形缓冲区
            self._buffer_log(timestamp, severity, json_str)

    def _buffer_log(
        self,
        timestamp: str,
        severity: str,
        json_str: str,
    ) -> None:
        """
        将日志条目追加到环形缓冲区，必要时触发等级淘汰。

        Args:
            timestamp: 日志时间戳。
            severity: 日志等级。
            json_str: JSON 字符串。
        """
        global _buffer, _buffer_warning_issued

        _buffer.append((timestamp, severity, json_str))
        current_count = len(_buffer)

        # 首次进入缓冲模式时输出告警
        if not _buffer_warning_issued:
            print(
                "[py-logger] stdout unavailable, buffering logs. "
                f"current buffer: {current_count} items",
                file=sys.stderr,
            )
            _buffer_warning_issued = True

        # 达到高水位 → 触发等级淘汰
        if current_count >= BUFFER_HIGH_WATERMARK:
            self._evict_buffer()

    def _evict_buffer(self) -> None:
        """
        等级淘汰：优先清除 DEBUG 级别全部条目，若仍超低水位则从头部
        清除 INFO 级别条目，直至降至 BUFFER_LOW_WATERMARK（2500）。

        WARNING 和 ERROR 永不被淘汰。
        """
        global _buffer

        target = BUFFER_LOW_WATERMARK

        # 阶段 1：全部清除 DEBUG 级别
        new_buffer: collections.deque[tuple[str, str, str]] = (
            collections.deque()
        )
        for ts, sev, js in _buffer:
            if sev == "DEBUG":
                print(
                    f"[py-logger] buffer evicted DEBUG entry at {ts}",
                    file=sys.stderr,
                )
            else:
                new_buffer.append((ts, sev, js))
        _buffer = new_buffer

        # 阶段 2：若仍需淘汰，从头部清除 INFO 级别
        if len(_buffer) > target:
            to_remove = len(_buffer) - target
            result: collections.deque[tuple[str, str, str]] = (
                collections.deque()
            )
            for ts, sev, js in _buffer:
                if sev == "INFO" and to_remove > 0:
                    print(
                        f"[py-logger] buffer evicted INFO entry at {ts}",
                        file=sys.stderr,
                    )
                    to_remove -= 1
                else:
                    result.append((ts, sev, js))
            _buffer = result

    def _flush_buffer(self) -> None:
        """
        将环形缓冲区中的积压日志按时间序刷出到 stdout。

        刷出成功（flush 无异常）后清空缓冲区并输出恢复通知到 stderr。
        若 stdout 仍不可用，保留缓冲区内容不变。
        """
        global _buffer, _buffer_warning_issued

        if not _buffer:
            return

        try:
            # 按时间戳升序排列后依次写入
            sorted_entries = sorted(_buffer, key=lambda x: x[0])
            count = len(sorted_entries)
            for _, _, json_str in sorted_entries:
                sys.stdout.write(json_str + "\n")
            sys.stdout.flush()

            # 清空缓冲区并输出恢复通知
            _buffer.clear()
            _buffer_warning_issued = False
            print(
                f"[py-logger] stdout recovered, flushed {count} buffered logs",
                file=sys.stderr,
            )
        except (OSError, BrokenPipeError):
            # stdout 仍未恢复，保留缓冲区内容
            pass


# ============================================================================
# 模块级单例
# ============================================================================

logger = _Logger()
"""全局日志记录器单例。

通过 ``from py_logger import logger`` 导入，直接调用 logger.info(...) 等方法。
"""
