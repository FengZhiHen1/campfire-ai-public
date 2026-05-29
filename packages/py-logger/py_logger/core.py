"""
结构化日志核心模块。

提供 JSONFormatter、Logger 单例及 5 个公共日志方法：
debug / info / warning / error / critical。

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
    将绝对路径输出到 stderr 以便定位。
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
    """结构化日志记录器单例。

    通过 ``from py_logger import logger`` 导入全局唯一实例。
    """

    def __init__(self) -> None:
        self._logging_logger = logging.getLogger("py-logger")
        self._logging_logger.setLevel(logging.DEBUG)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def debug(self, service: str, message: str,
              op_type: str | None = None,
              extra: dict[str, object] | None = None) -> None:
        self._write("DEBUG", service, message, op_type, extra)

    def info(self, service: str, message: str,
             op_type: str | None = None,
             extra: dict[str, object] | None = None) -> None:
        self._write("INFO", service, message, op_type, extra)

    def warning(self, service: str, message: str,
                op_type: str | None = None,
                extra: dict[str, object] | None = None) -> None:
        self._write("WARNING", service, message, op_type, extra)

    def error(self, service: str, message: str,
              op_type: str | None = None,
              extra: dict[str, object] | None = None) -> None:
        self._write("ERROR", service, message, op_type, extra)

    def critical(self, service: str, message: str,
                 op_type: str,
                 extra: dict[str, object] | None = None) -> None:
        if not op_type or not op_type.strip():
            raise ValueError("op_type is required for critical audit log")
        self._write("INFO", service, message, op_type, extra)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _write(self, severity: str, service: str, message: str,
               op_type: str | None, extra: dict[str, object] | None) -> None:
        try:
            trace_id = get_trace_id()
            extra_dict: dict[str, object] = {}

            if extra is not None:
                extra_dict = dict(extra)

            if not trace_id:
                trace_id = uuid.uuid4().hex
                extra_dict["_trace_missing"] = True

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

            try:
                json_str = json.dumps(log_entry, default=_default_handler, ensure_ascii=False)
            except (TypeError, ValueError):
                json_str = self._build_fallback(service, trace_id, message, extra_dict)
                print(f"[py-logger] serialization failed: {message[:200]}", file=sys.stderr)

            self._write_stdout(json_str, severity, timestamp)

        except Exception as exc:
            print(f"[py-logger] _write crashed: {exc}", file=sys.stderr)

    def _build_fallback(self, service: str, trace_id: str,
                        message: str, extra: dict[str, object]) -> str:
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

    def _write_stdout(self, json_str: str, severity: str, timestamp: str) -> None:
        global _buffer_warning_issued

        # 本地文件
        _write_file_line(json_str)

        # stdout
        try:
            self._flush_buffer()
            sys.stdout.write(json_str + "\n")
            sys.stdout.flush()
        except (OSError, BrokenPipeError):
            self._buffer_log(timestamp, severity, json_str)

    def _buffer_log(self, timestamp: str, severity: str, json_str: str) -> None:
        global _buffer, _buffer_warning_issued

        _buffer.append((timestamp, severity, json_str))
        current_count = len(_buffer)

        if not _buffer_warning_issued:
            print(f"[py-logger] stdout unavailable, buffering ({current_count} items)", file=sys.stderr)
            _buffer_warning_issued = True

        if current_count >= BUFFER_HIGH_WATERMARK:
            self._evict_buffer()

    def _evict_buffer(self) -> None:
        global _buffer
        target = BUFFER_LOW_WATERMARK

        new_buffer: collections.deque[tuple[str, str, str]] = collections.deque()
        for ts, sev, js in _buffer:
            if sev == "DEBUG":
                print(f"[py-logger] buffer evicted DEBUG at {ts}", file=sys.stderr)
            else:
                new_buffer.append((ts, sev, js))
        _buffer = new_buffer

        if len(_buffer) > target:
            to_remove = len(_buffer) - target
            result: collections.deque[tuple[str, str, str]] = collections.deque()
            for ts, sev, js in _buffer:
                if sev == "INFO" and to_remove > 0:
                    print(f"[py-logger] buffer evicted INFO at {ts}", file=sys.stderr)
                    to_remove -= 1
                else:
                    result.append((ts, sev, js))
            _buffer = result

    def _flush_buffer(self) -> None:
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
            print(f"[py-logger] stdout recovered, flushed {count} logs", file=sys.stderr)
        except (OSError, BrokenPipeError):
            pass


# ============================================================================
# 模块加载时初始化
# ============================================================================

_init_log_file_path()

logger = _Logger()
"""全局日志记录器单例。"""
