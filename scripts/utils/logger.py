"""py-logger 桥接 — 确保 scripts 目录可导入项目结构化日志模块。

Usage:
    from utils.logger import logger
    logger.info(service="scripts", message="...", op_type="startup")
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保 py-logger 包在 sys.path 中（scripts/ 不直接依赖 workspace packages）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PY_LOGGER_PATH = str(_PROJECT_ROOT / "packages" / "py-logger")
if _PY_LOGGER_PATH not in sys.path:
    sys.path.insert(0, _PY_LOGGER_PATH)

from py_logger import logger  # noqa: E402, F401

__all__ = ["logger"]
