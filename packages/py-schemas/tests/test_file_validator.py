"""SEC-05 文件上传安全校验 — validate_file 单元测试。

测试文件类型检测、大小校验、魔数匹配、扩展名校验。
"""

from __future__ import annotations

import io

import pytest

from py_schemas.utils.files import (
    _detect_mime_type,
    _extract_extension,
    validate_file,
)
from py_schemas.security.validation_schemas import FileValidationResult, FileValidationRule


class MockUploadFile:
    """模拟 FastAPI UploadFile 的最小接口。"""

    def __init__(self, filename: str, content: bytes, content_type: str = ""):
        self.filename = filename
        self.size = len(content)
        self.content_type = content_type
        self._content = content
        self._pos = 0

    async def read(self, n: int = -1) -> bytes:
        if self._pos >= len(self._content):
            return b""
        if n < 0:
            result = self._content[self._pos:]
        else:
            result = self._content[self._pos:self._pos + n]
        self._pos += len(result)
        return result

    async def seek(self, offset: int) -> None:
        self._pos = offset


_RULES = FileValidationRule(
    allowed_mime_types=["image/jpeg", "image/png", "application/pdf"],
    allowed_extensions=[".jpg", ".jpeg", ".png", ".pdf"],
    max_size_bytes=10 * 1024 * 1024,
)


class TestDetectMimeType:
    def test_jpeg(self):
        header = b"\xFF\xD8\xFF\xE0\x00\x10JFIF"
        assert _detect_mime_type(header) == "image/jpeg"

    def test_png(self):
        header = b"\x89\x50\x4E\x47\x0D\x0A\x1A\x0A"
        assert _detect_mime_type(header) == "image/png"

    def test_pdf(self):
        header = b"%PDF-1.4 some content"
        assert _detect_mime_type(header) == "application/pdf"

    def test_zip(self):
        header = b"PK\x03\x04" + b"\x00" * 26
        assert _detect_mime_type(header) == "application/zip"

    def test_exe(self):
        assert _detect_mime_type(b"MZ\x00\x01") == "application/x-msdownload"

    def test_unknown(self):
        assert _detect_mime_type(b"\x00\x00\x00\x00") == "application/octet-stream"

    def test_too_short(self):
        assert _detect_mime_type(b"ab") == "application/octet-stream"

    def test_mp4(self):
        header = b"\x00\x00\x00\x18ftypmp42"
        assert _detect_mime_type(header) == "video/mp4"

    def test_webp(self):
        header = b"RIFF\x00\x00\x00\x00WEBP"
        assert _detect_mime_type(header) == "image/webp"


class TestExtractExtension:
    def test_jpg(self):
        assert _extract_extension("photo.jpg") == ".jpg"

    def test_uppercase(self):
        assert _extract_extension("photo.JPG") == ".jpg"

    def test_no_extension(self):
        assert _extract_extension("README") == ""

    def test_double_extension(self):
        assert _extract_extension("archive.tar.gz") == ".gz"


class TestValidateFile:
    @pytest.mark.asyncio
    async def test_valid_jpeg(self):
        file = MockUploadFile("photo.jpg", b"\xFF\xD8\xFF\xE0\x00\x10JFIF")
        result = await validate_file(file, _RULES)
        assert result.is_valid is True
        assert result.error_message is None
        assert result.detected_mime_type == "image/jpeg"

    @pytest.mark.asyncio
    async def test_valid_png(self):
        file = MockUploadFile("icon.png", b"\x89\x50\x4E\x47\x0D\x0A\x1A\x0A")
        result = await validate_file(file, _RULES)
        assert result.is_valid is True
        assert result.detected_mime_type == "image/png"

    @pytest.mark.asyncio
    async def test_valid_pdf(self):
        file = MockUploadFile("doc.pdf", b"%PDF-1.4 content here")
        result = await validate_file(file, _RULES)
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_invalid_mime_type(self):
        file = MockUploadFile("program.exe", b"MZ\x00\x01" + b"\x00" * 100)
        result = await validate_file(file, _RULES)
        assert result.is_valid is False
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_invalid_extension(self):
        file = MockUploadFile("document.docx", b"%PDF-1.4 content")
        result = await validate_file(file, _RULES)
        assert result.is_valid is False

    @pytest.mark.asyncio
    async def test_file_too_large(self):
        large_content = b"\xFF\xD8\xFF" + b"x" * (11 * 1024 * 1024)
        file = MockUploadFile("big.jpg", large_content)
        result = await validate_file(file, _RULES)
        assert result.is_valid is False
        assert "大小超出限制" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_zero_byte_file(self):
        file = MockUploadFile("empty.jpg", b"")
        result = await validate_file(file, _RULES)
        assert result.is_valid is False
        assert result.error_message == "文件为空，不允许上传"

    @pytest.mark.asyncio
    async def test_unknown_mime_passes_if_extension_mismatches(self):
        file = MockUploadFile("data.bin", b"\x00\x00\x00\x00\x00\x00")
        result = await validate_file(file, _RULES)
        assert result.is_valid is False
