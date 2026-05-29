"""SEC-05 安全威胁检测（已迁移至 py_schemas.utils.security）。

原 detect_security_threat 实现已迁移至 py_schemas.utils.security。
本模块保留仅用于向后兼容，新代码请直接导入 py_schemas.utils。
"""

from __future__ import annotations

import warnings
from typing import Any

from py_schemas.security.validation_schemas import SecurityDetectionType
from py_schemas.utils.security import detect_security_threat as _detect_security_threat


def detect_security_threat(
    validated_data: dict[str, object],
) -> SecurityDetectionType | None:
    """已弃用：请使用 py_schemas.utils.security.detect_security_threat。"""
    warnings.warn(
        "py_schemas.security.security_detector.detect_security_threat is deprecated. "
        "Import from py_schemas.utils.security instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _detect_security_threat(validated_data)
