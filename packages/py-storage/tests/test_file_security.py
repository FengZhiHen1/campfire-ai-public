"""py-storage 文件安全校验 — 单元测试。

覆盖 DefaultFileValidator.validate()：四层递进校验、边界输入、异常传播。
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from py_storage.exceptions import (
    FileContentTooShortError,
    FileExtensionNotAllowedError,
    FileInputValidationError,
    FileMagicSignatureMismatchError,
    FileMimeDetectionError,
    FileMimeTypeNotAllowedError,
    FileTooLargeError,
    FileValidationError,
)
from py_storage.file_security import DefaultFileValidator
from py_storage.types import (
    FileContent,
    FileName,
    FileValidationInput,
    FileValidationResult,
)

# ---------------------------------------------------------------------------
# 测试固定文件内容
# ---------------------------------------------------------------------------

_VALID_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
_VALID_PDF = b"%PDF-1.4" + b"\x00" * 100
_VALID_DOCX = b"PK\x03\x04" + b"\x00" * 100


def _set_allowed_extensions(extensions: list[str]) -> None:
    """快捷方式：设置允许的扩展名白名单。"""
    sys.modules["py_config.security"].get_security_config.return_value.ALLOWED_FILE_EXTENSIONS = extensions


def _set_magic_mime(mime: str) -> None:
    """快捷方式：设置 python-magic 返回值。"""
    sys.modules["magic"].from_buffer.return_value = mime


def _set_magic_error(exc: Exception) -> None:
    """快捷方式：让 python-magic 抛出异常。"""
    sys.modules["magic"].from_buffer.side_effect = exc


class TestDefaultFileValidator:

    # ---- 全部通过 ----

    def test_validate_png_passes(self):
        _set_allowed_extensions(["png", "jpg", "pdf"])
        _set_magic_mime("image/png")

        validator = DefaultFileValidator()
        result = validator.validate(
            FileValidationInput(
                filename=FileName("photo.png"),
                content=FileContent(_VALID_PNG),
            )
        )
        assert result.is_valid is True
        assert result.reason is None

    def test_validate_pdf_passes(self):
        _set_allowed_extensions(["pdf", "docx"])
        _set_magic_mime("application/pdf")

        validator = DefaultFileValidator()
        result = validator.validate(
            FileValidationInput(
                filename=FileName("report.pdf"),
                content=FileContent(_VALID_PDF),
            )
        )
        assert result.is_valid is True

    # ---- 第 1 层：扩展名校验 ----

    def test_reject_disallowed_extension(self):
        _set_allowed_extensions(["pdf", "docx"])

        validator = DefaultFileValidator()
        with pytest.raises(FileExtensionNotAllowedError) as exc_info:
            validator.validate(
                FileValidationInput(
                    filename=FileName("photo.png"),
                    content=FileContent(_VALID_PNG),
                )
            )
        assert exc_info.value.extension == "png"

    def test_reject_no_extension(self):
        _set_allowed_extensions(["pdf"])

        validator = DefaultFileValidator()
        with pytest.raises(FileInputValidationError, match="无法识别文件扩展名"):
            validator.validate(
                FileValidationInput(
                    filename=FileName("noextension"),
                    content=FileContent(_VALID_PDF),
                )
            )

    # ---- 第 2 层：文件大小校验 ----

    def test_reject_oversized_image(self):
        _set_allowed_extensions(["png", "jpg"])
        _set_magic_mime("image/png")

        validator = DefaultFileValidator()
        huge = FileContent(b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 1))
        with pytest.raises(FileTooLargeError) as exc_info:
            validator.validate(
                FileValidationInput(
                    filename=FileName("big.png"),
                    content=huge,
                )
            )
        assert exc_info.value.category == "image"

    # ---- 第 3 层：MIME 类型检测 ----

    def test_reject_wrong_mime_type(self):
        _set_allowed_extensions(["png"])
        _set_magic_mime("text/html")

        validator = DefaultFileValidator()
        with pytest.raises(FileMimeTypeNotAllowedError) as exc_info:
            validator.validate(
                FileValidationInput(
                    filename=FileName("page.png"),
                    content=FileContent(_VALID_PNG),
                )
            )
        assert exc_info.value.detected_mime == "text/html"

    def test_reject_mime_detection_failure(self):
        _set_allowed_extensions(["png"])
        _set_magic_error(RuntimeError("magic library error"))

        validator = DefaultFileValidator()
        with pytest.raises(FileMimeDetectionError, match="magic library error"):
            validator.validate(
                FileValidationInput(
                    filename=FileName("photo.png"),
                    content=FileContent(_VALID_PNG),
                )
            )

    # ---- 第 4 层：魔数校验 ----

    def test_reject_wrong_magic_bytes(self):
        _set_allowed_extensions(["png"])
        _set_magic_mime("image/png")

        validator = DefaultFileValidator()
        with pytest.raises(FileMagicSignatureMismatchError) as exc_info:
            validator.validate(
                FileValidationInput(
                    filename=FileName("photo.png"),
                    content=FileContent(b"GIF89a" + b"\x00" * 100),
                )
            )
        assert exc_info.value.extension == "png"

    def test_reject_content_too_short(self):
        _set_allowed_extensions(["png"])
        _set_magic_mime("image/png")

        validator = DefaultFileValidator()
        with pytest.raises(FileContentTooShortError) as exc_info:
            validator.validate(
                FileValidationInput(
                    filename=FileName("tiny.png"),
                    content=FileContent(b"\x89PN"),
                )
            )
        assert exc_info.value.actual_bytes == 3

    # ---- 前置校验 ----

    def test_reject_empty_filename(self):
        _set_allowed_extensions(["pdf"])

        validator = DefaultFileValidator()
        with pytest.raises(FileInputValidationError, match="filename 不能为空"):
            validator.validate(
                FileValidationInput(
                    filename=FileName(""),
                    content=FileContent(_VALID_PDF),
                )
            )

    # ---- 跳过魔数校验 ----

    def test_skip_magic_check_when_no_signature(self):
        """扩展名在白名单但无对应魔数签名时，跳过魔数校验。"""
        _set_allowed_extensions(["docx"])
        _set_magic_mime(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

        validator = DefaultFileValidator()
        result = validator.validate(
            FileValidationInput(
                filename=FileName("doc.docx"),
                content=FileContent(_VALID_DOCX),
            )
        )
        assert result.is_valid is True


class TestFileValidationInput:

    def test_frozen_dataclass(self):
        inp = FileValidationInput(
            filename=FileName("test.pdf"),
            content=FileContent(b"%PDF-1.4"),
        )
        with pytest.raises(Exception):
            inp.filename = FileName("other.pdf")  # type: ignore[misc]


class TestExceptionHierarchy:

    def test_file_too_large_error_fields(self):
        err = FileTooLargeError(
            actual_bytes=6 * 1024 * 1024,
            limit_bytes=5 * 1024 * 1024,
            category="图片",
        )
        assert "图片" in str(err)
        assert "6.0MB" in str(err)
        assert "5MB" in str(err)

    def test_file_extension_not_allowed_fields(self):
        err = FileExtensionNotAllowedError("exe", frozenset({"pdf", "png"}))
        assert err.extension == "exe"
        assert "pdf" in str(err)

    def test_base_exception_catch_all(self):
        err = FileTooLargeError(100, 50, "文件")
        assert isinstance(err, FileValidationError)
