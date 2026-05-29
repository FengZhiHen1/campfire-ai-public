"""py-storage 文件安全校验 — 默认实现。

模块: py_storage.file_security
职责: 基于 BaseFileValidator 契约，实现四层递进文件安全校验：
      扩展名白名单 → 文件大小上限 → MIME 类型检测 → 文件头魔数。
      扩展名白名单从 py-config 安全配置读取，其余规则在模块内定义。
数据来源:
  - py_config.security.get_security_config(): MUST — 允许的文件扩展名白名单
  - python-magic: MUST — MIME 类型检测
边界:
  - 依赖: py_storage.types、py_storage.file_validation_contract、py_storage.exceptions、py-config
  - 被依赖: api-server 文件上传路由（通过 BaseFileValidator 契约调用）
禁止行为:
  - 禁止覆盖 @final validate() 方法
  - 禁止跳过 _validate_* 校验器
  - 禁止以 return FileValidationResult(is_valid=False) 替代抛异常
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from py_logger import StructuredLogger

from py_storage.exceptions import (
    FileContentTooShortError,
    FileExtensionNotAllowedError,
    FileMagicSignatureMismatchError,
    FileMimeDetectionError,
    FileMimeTypeNotAllowedError,
    FileTooLargeError,
)
from py_storage.file_validation_contract import BaseFileValidator
from py_storage.types import FileCategory


def _get_logger() -> StructuredLogger:
    from py_logger import logger

    return logger

# ---------------------------------------------------------------------------
# 文件大小上限（字节）
# ---------------------------------------------------------------------------

_SIZE_LIMIT_IMAGE = 5 * 1024 * 1024       # 5 MB
_SIZE_LIMIT_DOCUMENT = 10 * 1024 * 1024    # 10 MB

# ---------------------------------------------------------------------------
# 文件类别 → 扩展名映射
# ---------------------------------------------------------------------------

_IMAGE_EXTENSIONS: frozenset[str] = frozenset({"jpg", "jpeg", "png"})
_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({"pdf", "docx"})

# ---------------------------------------------------------------------------
# 允许的 MIME 类型
# ---------------------------------------------------------------------------

_ALLOWED_MIME_TYPES: frozenset[str] = frozenset({
    "application/pdf",
    "image/jpeg",
    "image/png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
})

# ---------------------------------------------------------------------------
# 文件头魔数签名表
# ---------------------------------------------------------------------------

_MAGIC_SIGNATURES: dict[str, bytes] = {
    "pdf": b"%PDF",
    "jpg": b"\xff\xd8\xff",
    "jpeg": b"\xff\xd8\xff",
    "png": b"\x89PNG",
    "docx": b"PK\x03\x04",
}


class DefaultFileValidator(BaseFileValidator):
    """默认文件安全校验器。

    实现 BaseFileValidator 契约的四层递进校验：
    1. 扩展名白名单（从 py-config 安全配置读取）
    2. 文件大小上限（图片 5MB / 文档 10MB）
    3. MIME 类型检测（python-magic）
    4. 文件头魔数校验
    """

    # === 第 1 层：扩展名白名单 ===

    def _verify_extension(self, ext: str) -> None:
        from py_config.security import get_security_config

        config = get_security_config()
        allowed = frozenset(config.ALLOWED_FILE_EXTENSIONS)
        if ext not in allowed:
            _get_logger().warning(
                "py-storage",
                f"文件扩展名被拒: .{ext}",
                op_type="file_validate_blocked",
                extra={
                    "step": "extension",
                    "extension": ext,
                    "allowed": sorted(allowed),
                },
            )
            raise FileExtensionNotAllowedError(ext, allowed)

    # === 第 2 层：文件大小上限 ===

    def _verify_size(self, ext: str, content: bytes) -> None:
        content_size = len(content)

        if ext in _IMAGE_EXTENSIONS:
            size_limit = _SIZE_LIMIT_IMAGE
            category = FileCategory.IMAGE.value
        elif ext in _DOCUMENT_EXTENSIONS:
            size_limit = _SIZE_LIMIT_DOCUMENT
            category = FileCategory.DOCUMENT.value
        else:
            size_limit = _SIZE_LIMIT_DOCUMENT
            category = "文件"

        if content_size > size_limit:
            _get_logger().warning(
                "py-storage",
                f"文件大小超限: {content_size} > {size_limit} ({category})",
                op_type="file_validate_blocked",
                extra={
                    "step": "size",
                    "actual_bytes": content_size,
                    "limit_bytes": size_limit,
                    "category": category,
                },
            )
            raise FileTooLargeError(content_size, size_limit, category)

    # === 第 3 层：MIME 类型检测 ===

    def _verify_mime_type(self, content: bytes) -> None:
        import magic

        try:
            detected_mime = magic.from_buffer(content[:1024], mime=True)
        except Exception as exc:
            _get_logger().error(
                "py-storage",
                f"MIME 类型检测失败: {exc}",
                op_type="file_validate_error",
                extra={"step": "mime_type", "error": str(exc)},
            )
            raise FileMimeDetectionError(str(exc)) from exc

        if detected_mime not in _ALLOWED_MIME_TYPES:
            _get_logger().warning(
                "py-storage",
                f"MIME 类型被拒: {detected_mime}",
                op_type="file_validate_blocked",
                extra={
                    "step": "mime_type",
                    "detected_mime": detected_mime,
                    "allowed_mimes": sorted(_ALLOWED_MIME_TYPES),
                },
            )
            raise FileMimeTypeNotAllowedError(detected_mime, _ALLOWED_MIME_TYPES)

    # === 第 4 层：文件头魔数 ===

    def _verify_magic_bytes(self, ext: str, content: bytes) -> None:
        min_header = 4
        if len(content) < min_header:
            _get_logger().warning(
                "py-storage",
                f"文件内容过短，无法校验魔数: {len(content)} < {min_header}",
                op_type="file_validate_blocked",
                extra={
                    "step": "magic_bytes",
                    "actual_bytes": len(content),
                    "min_required": min_header,
                },
            )
            raise FileContentTooShortError(len(content), min_header)

        expected_magic = _MAGIC_SIGNATURES.get(ext)
        if expected_magic is None:
            # 扩展名在白名单但无对应魔数签名 → 跳过魔数校验
            return

        actual_header = content[:len(expected_magic)]
        if actual_header != expected_magic:
            actual_hex = " ".join(f"{b:02x}" for b in actual_header)
            expected_hex = " ".join(f"{b:02x}" for b in expected_magic)
            _get_logger().warning(
                "py-storage",
                f"文件头魔数不匹配: .{ext}",
                op_type="file_validate_blocked",
                extra={
                    "step": "magic_bytes",
                    "extension": ext,
                    "actual_hex": actual_hex,
                    "expected_hex": expected_hex,
                },
            )
            raise FileMagicSignatureMismatchError(ext, actual_hex)


__all__ = [
    "DefaultFileValidator",
]
