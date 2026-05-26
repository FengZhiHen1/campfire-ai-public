"""SEC-05 输入校验防护 — security 子包。

提供输入校验防护的全部公共接口：
  - sanitize_html: HTML 实体转义清洗
  - validate_file: 文件上传安全校验
  - detect_security_threat: 安全威胁检测
  - 6 个 Pydantic v2 数据模型
"""

from __future__ import annotations

from py_schemas.security.file_validator import validate_file
from py_schemas.security.sanitizer import sanitize_html
from py_schemas.security.security_detector import detect_security_threat
from py_schemas.security.validation_schemas import (
    FileValidationResult,
    FileValidationRule,
    SecurityAuditLogEntry,
    SecurityDetectionType,
    ValidationErrorItem,
    ValidationErrorResponse,
)

__all__ = [
    # Functions
    "sanitize_html",
    "validate_file",
    "detect_security_threat",
    # Models
    "ValidationErrorItem",
    "ValidationErrorResponse",
    "FileValidationRule",
    "FileValidationResult",
    "SecurityAuditLogEntry",
    "SecurityDetectionType",
]
