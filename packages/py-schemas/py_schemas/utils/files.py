"""文件上传安全校验。

提供 validate_file() 异步函数，对上传文件执行 MIME 类型白名单和大小上限双重校验。
通过文件头魔数（magic bytes）检测文件的真实类型，结合扩展名双重验证。
"""

from __future__ import annotations

import os
from typing import Any

from py_schemas.security.validation_schemas import FileValidationResult, FileValidationRule

# ---------------------------------------------------------------------------
# 魔数映射表：文件头字节 → MIME 类型
# ---------------------------------------------------------------------------

_MAGIC_BYTES_TABLE: list[tuple[int, bytes, str]] = [
    (0, b"\xFF\xD8\xFF", "image/jpeg"),
    (0, b"\x89\x50\x4E\x47", "image/png"),
    (0, "%PDF-".encode("ascii"), "application/pdf"),
    (0, b"MZ", "application/x-msdownload"),
    (0, b"PK\x03\x04", "application/zip"),
    (0, b"RIFF", "image/webp"),
]

_MP4_BRAND_PATTERN: tuple[int, bytes, str] = (4, b"ftyp", "video/mp4")


def _detect_mime_type(header: bytes) -> str:
    """通过文件头魔数检测真实 MIME 类型。"""
    if len(header) < 4:
        return "application/octet-stream"

    for offset, magic, mime_type in _MAGIC_BYTES_TABLE:
        end = offset + len(magic)
        if len(header) >= end and header[offset:end] == magic:
            if mime_type == "image/webp":
                if len(header) >= 12 and header[8:12] == b"WEBP":
                    return mime_type
                continue
            if mime_type == "application/zip" and len(header) > 30:
                content_types_marker = b"[Content_Types].xml"
                if content_types_marker in header[:256]:
                    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            return mime_type

    offset, magic, mime_type = _MP4_BRAND_PATTERN
    end = offset + len(magic)
    if len(header) >= end and header[offset:end] == magic:
        return mime_type

    return "application/octet-stream"


def _extract_extension(filename: str) -> str:
    """从文件名提取小写扩展名（含点号前缀）。"""
    _, ext = os.path.splitext(filename)
    return ext.lower()


async def validate_file(
    file: Any,
    rules: FileValidationRule,
) -> FileValidationResult:
    """对用户上传的文件执行类型白名单和大小上限双重校验。

    校验流程：
      1. 检查 file.size 是否超过 rules.max_size_bytes
      2. 读取文件头 256 字节检测魔数（magic bytes）确定真实 MIME 类型
      3. 比对真实 MIME 类型是否在 rules.allowed_mime_types 白名单中
      4. 比对文件扩展名是否在 rules.allowed_extensions 白名单中
      5. MIME 类型和扩展名均匹配 → is_valid=True，否则 is_valid=False
      6. 魔数检测失败 → detected_mime_type="application/octet-stream", is_valid=False
      7. 校验完成后将文件游标归零

    Args:
        file: 文件对象（兼容 FastAPI UploadFile）。
        rules: 文件校验规则配置。

    Returns:
        FileValidationResult: 校验结果。

    Raises:
        IOError: 文件读取失败。
    """
    file_size = getattr(file, "size", 0)
    filename = getattr(file, "filename", "")

    if file_size == 0:
        return FileValidationResult(
            is_valid=False,
            error_message="文件为空，不允许上传",
            detected_mime_type="application/octet-stream",
            file_size_bytes=1,
        )

    if file_size > rules.max_size_bytes:
        return FileValidationResult(
            is_valid=False,
            error_message=(
                f"文件大小超出限制（{file_size} 字节），"
                f"最大允许 {rules.max_size_bytes} 字节"
            ),
            detected_mime_type="application/octet-stream",
            file_size_bytes=file_size,
        )

    try:
        header = await file.read(256)
    except Exception:
        raise IOError(f"无法读取文件 '{filename}' 的文件头以进行魔数检测")

    detected_mime = _detect_mime_type(header) if header else "application/octet-stream"

    file_ext = _extract_extension(filename)

    mime_match = detected_mime in rules.allowed_mime_types
    ext_match = file_ext in rules.allowed_extensions

    is_valid = mime_match and ext_match
    error_message: str | None = None

    if not is_valid:
        allowed_exts = ", ".join(rules.allowed_extensions)
        error_message = f"文件类型不允许，仅支持：{allowed_exts}"

    try:
        await file.seek(0)
    except Exception:
        raise IOError(
            f"无法将文件 '{filename}' 的读取游标归零，文件可能已关闭"
        )

    return FileValidationResult(
        is_valid=is_valid,
        error_message=error_message,
        detected_mime_type=detected_mime,
        file_size_bytes=file_size,
    )
