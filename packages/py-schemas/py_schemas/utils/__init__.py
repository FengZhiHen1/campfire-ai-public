"""py-schemas 工具函数子包。

提供纯数据模型的辅助工具函数（HTML 清洗、安全检测、文件校验、档案计算）。
这些函数是运行时逻辑，独立于 Pydantic 数据模型。
"""

from __future__ import annotations

from py_schemas.utils.files import validate_file
from py_schemas.utils.html import sanitize_html
from py_schemas.utils.profiles import calculate_age_range
from py_schemas.utils.security import detect_security_threat

__all__ = [
    "sanitize_html",
    "detect_security_threat",
    "validate_file",
    "calculate_age_range",
]
