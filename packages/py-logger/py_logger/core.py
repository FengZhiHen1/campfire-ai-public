"""OBS-01 结构化日志核心模块 — StructuredLogger 实现。

实现 BaseStructuredLogger 契约：
- @final debug/info/warning/error/critical → 公共入口（不可覆写）
- _do_emit() → 实现者填写的日志输出钩子

日志输出链路：调用方传入参数 → contextvars 自动注入 trace_id →
组装 LogEntry dict → json.dumps 序列化 → stdout + 本地文件双通道输出。

Zero external dependencies —— 仅使用 Python 3.12 标准库。
"""

from __future__ import annotations

import collections
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from py_logger.context import get_trace_id
from py_logger.logger_contract import BaseStructuredLogger
from py_logger.types import LogSeverity, ServiceName, TraceId

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
"""等级淘汰优先级"""

# ============================================================================
# 环形缓冲区（模块级状态）
# ============================================================================

_buffer: collections.deque[tuple[str, str, str]] = collections.deque()
_buffer_warning_issued: bool = False

# ============================================================================
# 文件日志（模块级状态）
# ============================================================================

_log_file_path: Path | None = None
"""缓存日志文件的绝对路径，模块导入时初始化一次。"""


def _init_log_file_path() -> None:
    """初始化日志文件路径（模块导入时调用一次）。

    默认目录 logs/，文件名 app-YYYY-MM-DD.log（按天轮转）。
    """
    global _log_file_path
    log_dir = os.environ.get("LOG_FILE_DIR", "logs")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_path = Path(log_dir) / f"app-{today}.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _log_file_path = log_path.resolve()
        print(f"[py-logger] log file: {_log_file_path}", file=sys.stderr)
    except Exception as exc:
        _log_file_path = None
        print(f"[py-logger] failed to init log file: {exc}", file=sys.stderr)


def _write_file_line(json_str: str) -> None:
    """追加一行 JSON 到日志文件。

    任何异常都输出到 stderr 并继续，不阻塞主流程。
    """
    if _log_file_path is None:
        return
    try:
        with open(_log_file_path, "a", encoding="utf-8") as f:
            f.write(json_str + "\n")
    except Exception as exc:
        print(f"[py-logger] write failed: {exc}", file=sys.stderr)


# ============================================================================
# 工具函数
# ============================================================================


def _make_timestamp() -> str:
    now = datetime.now(timezone.utc)
    ms = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def _default_handler(obj: object) -> str:
    return f"<{type(obj).__name__}: {repr(obj)[:100]}>"


# ============================================================================
# JSONFormatter
# ============================================================================


class JSONFormatter(logging.Formatter):
    """自定义 JSON 格式化器，将 LogRecord 格式化为单行 JSON 字符串。"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, object] = {
            "timestamp": getattr(record, "timestamp", None) or _make_timestamp(),
            "severity": record.levelname,
            "service": getattr(record, "service", "unknown"),
            "trace_id": getattr(record, "trace_id", ""),
            "message": record.getMessage(),
            "op_type": getattr(record, "op_type", None),
            "extra": getattr(record, "extra", None),
        }
        return json.dumps(log_entry, default=_default_handler, ensure_ascii=False)


# ============================================================================
# DynamicStreamHandler
# ============================================================================


class _DynamicStreamHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """动态追踪 sys.stdout 的 StreamHandler。

    uvicorn/gunicorn 等 ASGI 服务器可能在启动时替换 sys.stdout。
    标准 StreamHandler 在构造时捕获 stream 引用，后续不再更新。
    本 Handler 重写 emit() 直接使用当前的 sys.stdout。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            sys.stdout.write(msg + self.terminator)
            self.flush()
        except (OSError, BrokenPipeError):
            raise
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)


# ============================================================================
# StructuredLogger — 实现 BaseStructuredLogger 契约
# ============================================================================


class StructuredLogger(BaseStructuredLogger):
    """结构化日志记录器 —— 实现 BaseStructuredLogger 契约。

    通过 ``from py_logger import logger`` 导入全局单例。
    """

    def __init__(self) -> None:
        self._logging_logger = logging.getLogger("py-logger")
        self._logging_logger.setLevel(logging.DEBUG)
        self._logging_logger.propagate = False
        self._ensure_handler()

    def _ensure_handler(self) -> None:
        """确保 logger 已配置 stdout handler（幂等）。"""
        if not self._logging_logger.handlers:
            handler = _DynamicStreamHandler()
            handler.setFormatter(JSONFormatter())
            self._logging_logger.addHandler(handler)

    # ------------------------------------------------------------------
    # 契约钩子：_do_emit
    # ------------------------------------------------------------------

    def _do_emit(
        self,
        severity: LogSeverity,
        service: ServiceName,
        message: str,
        op_type: str | None,
        extra: dict[str, object] | None,
    ) -> None:
        """将日志条目序列化并输出到 stdout + 文件。

        此方法实现 BaseStructuredLogger 契约的 _do_emit 钩子。
        包含：trace_id 注入 → 序列化 → 双通道输出。
        内部异常永不外溢（日志可用性优先原则）。
        """
        try:
            trace_id_val = get_trace_id()
            extra_dict: dict[str, object] = {}

            if extra is not None:
                extra_dict = dict(extra)

            if not trace_id_val:
                trace_id_val = TraceId(uuid.uuid4().hex)
                extra_dict["_trace_missing"] = True

            timestamp = _make_timestamp()
            log_entry: dict[str, object] = {
                "timestamp": timestamp,
                "severity": severity,
                "service": service,
                "trace_id": trace_id_val,
                "message": message,
                "op_type": op_type,
                "extra": (
                    extra_dict if extra_dict else ({} if extra is not None else None)
                ),
            }

            try:
                json_str = json.dumps(
                    log_entry, default=_default_handler, ensure_ascii=False
                )
            except (TypeError, ValueError):
                json_str = self._build_fallback(
                    service, trace_id_val, message, extra_dict
                )
                print(
                    f"[py-logger] serialization failed: {message[:200]}",
                    file=sys.stderr,
                )

            level = getattr(logging, severity, logging.INFO)
            record = logging.LogRecord(
                name=self._logging_logger.name,
                level=level,
                pathname="",
                lineno=0,
                msg=log_entry["message"],
                args=(),
                exc_info=None,
            )
            record.timestamp = log_entry["timestamp"]
            record.service = log_entry["service"]
            record.trace_id = log_entry["trace_id"]
            record.op_type = log_entry["op_type"]
            record.extra = log_entry["extra"]

            self._write_stdout(record, json_str, severity, timestamp)

        except Exception as exc:
            print(f"[py-logger] _do_emit crashed: {exc}", file=sys.stderr)

    def _build_fallback(
        self,
        service: str,
        trace_id: TraceId,
        message: str,
        extra: dict[str, object],
    ) -> str:
        """序列化失败时的降级 JSON 构造。"""
        original_keys = list(extra.keys())[:20]
        original_types: dict[str, str] = {}
        for k in original_keys:
            original_types[k] = type(extra[k]).__name__

        fallback_entry: dict[str, object] = {
            "timestamp": _make_timestamp(),
            "severity": "ERROR",
            "service": service,
            "trace_id": trace_id,
            "message": "日志序列化失败，原始数据类型见 extra._serialize_error",
            "op_type": None,
            "extra": {
                "_serialize_error": True,
                "original_keys": original_keys,
                "original_types": original_types,
            },
        }
        return json.dumps(fallback_entry, ensure_ascii=False)

    # ------------------------------------------------------------------
    # stdout + 文件双通道输出
    # ------------------------------------------------------------------

    def _write_stdout(
        self,
        record: logging.LogRecord,
        json_str: str,
        severity: LogSeverity,
        timestamp: str,
    ) -> None:
        """stdout + 文件双通道输出。"""
        global _buffer_warning_issued

        # 本地文件
        _write_file_line(json_str)

        # stdout（通过 stdlib logging 体系输出）
        try:
            self._flush_buffer()
            self._logging_logger.handle(record)
        except (OSError, BrokenPipeError):
            self._buffer_log(timestamp, severity, json_str)

    def _buffer_log(self, timestamp: str, severity: LogSeverity, json_str: str) -> None:
        """stdout 不可用时暂存到环形缓冲区。"""
        global _buffer, _buffer_warning_issued

        _buffer.append((timestamp, severity, json_str))
        current_count = len(_buffer)

        if not _buffer_warning_issued:
            print(
                f"[py-logger] stdout unavailable, buffering ({current_count} items)",
                file=sys.stderr,
            )
            _buffer_warning_issued = True

        if current_count >= BUFFER_HIGH_WATERMARK:
            self._evict_buffer()

    def _evict_buffer(self) -> None:
        """按 SEVERITY_EVICTION_ORDER 优先级逐级淘汰缓冲区条目。

        第一级全部移除，后续级别逐个移除至 BUFFER_LOW_WATERMARK。
        """
        global _buffer
        target = BUFFER_LOW_WATERMARK

        # 第一级：全部移除该等级条目
        evict_severity = SEVERITY_EVICTION_ORDER[0]
        result: collections.deque[tuple[str, str, str]] = collections.deque()
        for ts, sev, js in _buffer:
            if sev == evict_severity:
                print(
                    f"[py-logger] buffer evicted {evict_severity} at {ts}",
                    file=sys.stderr,
                )
            else:
                result.append((ts, sev, js))
        _buffer = result

        # 后续级别：逐个移除直到低于 target
        for evict_severity in SEVERITY_EVICTION_ORDER[1:]:
            if len(_buffer) <= target:
                break
            to_remove = len(_buffer) - target
            result = collections.deque()
            for ts, sev, js in _buffer:
                if sev == evict_severity and to_remove > 0:
                    print(
                        f"[py-logger] buffer evicted {evict_severity} at {ts}",
                        file=sys.stderr,
                    )
                    to_remove -= 1
                else:
                    result.append((ts, sev, js))
            _buffer = result

    def _flush_buffer(self) -> None:
        """stdout 恢复后将缓冲区日志刷出。"""
        global _buffer, _buffer_warning_issued

        if not _buffer:
            return

        try:
            sorted_entries = sorted(_buffer, key=lambda x: x[0])
            count = len(sorted_entries)
            for _, _, json_str in sorted_entries:
                sys.stdout.write(json_str + "\n")
            sys.stdout.flush()
            _buffer.clear()
            _buffer_warning_issued = False
            print(
                f"[py-logger] stdout recovered, flushed {count} logs",
                file=sys.stderr,
            )
        except (OSError, BrokenPipeError):
            pass


# ============================================================================
# 模块加载时初始化
# ============================================================================

_init_log_file_path()

logger = StructuredLogger()
"""全局日志记录器单例。"""


def setup_logging() -> None:
    """显式初始化 py-logger 的日志输出配置。

    应在应用启动最早期调用（在 uvicorn 等框架接管 stdout 之前），
    确保 logging 体系正确注册 stdout handler。
    本函数幂等，重复调用安全。
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG,
        force=True,
    )
    logger._ensure_handler()
