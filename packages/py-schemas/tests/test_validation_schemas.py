"""SEC-05 输入校验防护 — Pydantic v2 数据模型单元测试。

覆盖 SecurityDetectionType、ValidationErrorItem、ValidationErrorResponse、
FileValidationRule、FileValidationResult、SecurityAuditLogEntry。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from py_schemas.security.validation_schemas import (
    FileValidationResult,
    FileValidationRule,
    SecurityAuditLogEntry,
    SecurityDetectionType,
    ValidationErrorItem,
    ValidationErrorResponse,
)


class TestSecurityDetectionType:
    def test_values(self):
        assert SecurityDetectionType.sql_injection == "sql_injection"
        assert SecurityDetectionType.xss_payload == "xss_payload"
        assert SecurityDetectionType.malformed_request == "malformed_request"


class TestValidationErrorItem:
    def test_valid(self):
        item = ValidationErrorItem(field="username", reason="too_short", constraint="最少4个字符")
        assert item.field == "username"

    def test_empty_field(self):
        with pytest.raises(ValidationError):
            ValidationErrorItem(field="", reason="error", constraint="必须")


class TestValidationErrorResponse:
    def test_valid_single_error(self):
        item = ValidationErrorItem(field="username", reason="too_short", constraint="最少4个字符")
        resp = ValidationErrorResponse(errors=[item])
        assert len(resp.errors) == 1

    def test_empty_errors(self):
        with pytest.raises(ValidationError):
            ValidationErrorResponse(errors=[])


class TestFileValidationRule:
    def test_valid(self):
        rule = FileValidationRule(
            allowed_mime_types=["image/jpeg", "image/png"],
            allowed_extensions=[".jpg", ".jpeg", ".png"],
            max_size_bytes=10485760,
        )
        assert "image/jpeg" in rule.allowed_mime_types

    def test_empty_mime_types(self):
        with pytest.raises(ValidationError):
            FileValidationRule(allowed_mime_types=[], allowed_extensions=[".jpg"], max_size_bytes=1024)

    def test_zero_max_size(self):
        with pytest.raises(ValidationError):
            FileValidationRule(allowed_mime_types=["image/jpeg"], allowed_extensions=[".jpg"], max_size_bytes=0)


class TestFileValidationResult:
    def test_valid_pass(self):
        result = FileValidationResult(
            is_valid=True,
            detected_mime_type="image/jpeg",
            file_size_bytes=1024,
        )
        assert result.is_valid is True
        assert result.error_message is None

    def test_valid_fail(self):
        result = FileValidationResult(
            is_valid=False,
            error_message="文件类型不允许",
            detected_mime_type="application/octet-stream",
            file_size_bytes=1024,
        )
        assert result.is_valid is False
        assert result.error_message == "文件类型不允许"


class TestSecurityAuditLogEntry:
    def test_valid(self):
        entry = SecurityAuditLogEntry(
            trace_id="trace-abc-123",
            event_type=SecurityDetectionType.xss_payload,
            detection_detail="在 query 参数中检测到 XSS 载荷",
            timestamp="2026-05-28T10:30:00Z",
        )
        assert entry.event_type == SecurityDetectionType.xss_payload
