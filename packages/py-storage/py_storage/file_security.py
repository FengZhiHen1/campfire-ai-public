"""SEC-01 文件上传安全校验。

三层递进校验：扩展名 → 文件大小 → MIME 类型 → 文件头魔数。
任一层失败即短路返回，不执行后续校验。

校验层级：
1. 扩展名白名单校验（最轻量，最早拦截）
2. 文件大小校验（按文件类型区分上限）
3. MIME 类型检测（python-magic，读取前 1024 字节）
4. 文件头魔数校验（读取前 4 字节比对已知签名）

公开函数：
  - validate_file: 三层递进文件安全校验（幂等）
  - FileValidationResult: 校验结果数据类
"""

from __future__ import annotations

from dataclasses import dataclass

import magic

from py_config.security import get_security_config
from py_storage.exceptions import FileTooLargeError

# 文件大小上限（字节）
_SIZE_LIMIT_IMAGE = 5 * 1024 * 1024       # 5 MB
_SIZE_LIMIT_DOCUMENT = 10 * 1024 * 1024    # 10 MB

# 文件扩展名资源类型映射
_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png"})
_DOCUMENT_EXTENSIONS = frozenset({"pdf", "docx"})

# 允许的 MIME 类型集合
_ALLOWED_MIME_TYPES: frozenset[str] = frozenset({
    "application/pdf",
    "image/jpeg",
    "image/png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
})

# 文件头魔数签名表（前 4 字节）
_MAGIC_SIGNATURES: dict[str, bytes] = {
    "pdf": b"%PDF",
    "jpg": b"\xff\xd8\xff",
    "jpeg": b"\xff\xd8\xff",
    "png": b"\x89PNG",
    "docx": b"PK\x03\x04",
}


@dataclass
class FileValidationResult:
    """文件安全校验结果。

    Attributes:
        is_valid: 文件是否通过三层递进校验。
        reason: 校验失败时的原因说明；通过时为 None。
    """

    is_valid: bool
    reason: str | None = None


def validate_file(filename: str, content: bytes) -> FileValidationResult:
    """三层递进文件安全校验：扩展名 → MIME 类型 → 文件头魔数。

    任一层校验失败 → 立即返回 FileValidationResult(is_valid=False, reason=...)
    不再执行后续层。

    Args:
        filename: 上传文件的原始文件名（含扩展名）。
        content: 上传文件的原始字节内容。

    Returns:
        FileValidationResult: 校验结果，含 ``is_valid`` 和失败时的 ``reason``。

    Raises:
        ValueError: filename 为空字符串。
        FileTooLargeError: 文件字节数超过类型大小上限。

    Side Effects:
        无。纯函数，不写数据库、不写文件系统。
    """
    # 前置：参数类型校验
    if not isinstance(content, bytes):
        raise TypeError(
            f"content 必须是 bytes 类型，实际为 {type(content).__name__}"
        )

    # 前置：空文件名检查
    if not filename or len(filename) == 0:
        raise ValueError("filename 不能为空")

    config = get_security_config()
    allowed_extensions = set(config.ALLOWED_FILE_EXTENSIONS)

    # ===== 第 1 层：扩展名校验 =====
    if "." not in filename:
        return FileValidationResult(
            is_valid=False,
            reason="无法识别文件扩展名",
        )

    ext = filename.rsplit(".", 1)[-1].lower()
    if ext == "":
        return FileValidationResult(
            is_valid=False,
            reason="无法识别文件扩展名",
        )

    if ext not in allowed_extensions:
        allowed_str = ", ".join(sorted(allowed_extensions))
        return FileValidationResult(
            is_valid=False,
            reason=f"文件扩展名 .{ext} 不在允许白名单中。允许的类型：{allowed_str}",
        )

    # ===== 第 2 层：文件大小校验 =====
    content_size = len(content)

    if ext in _IMAGE_EXTENSIONS:
        size_limit = _SIZE_LIMIT_IMAGE
        category = "图片"
    elif ext in _DOCUMENT_EXTENSIONS:
        size_limit = _SIZE_LIMIT_DOCUMENT
        category = "文档"
    else:
        # 理论上不会到达此处（扩展名已通过白名单校验）
        size_limit = _SIZE_LIMIT_DOCUMENT
        category = "文件"

    if content_size > size_limit:
        actual_mb = content_size / (1024 * 1024)
        limit_mb = size_limit / (1024 * 1024)
        raise FileTooLargeError(
            f"{category}大小 {actual_mb:.1f}MB 超过上限 {limit_mb:.0f}MB"
        )

    # ===== 第 3 层：MIME 类型检测 =====
    try:
        detected_mime = magic.from_buffer(content[:1024], mime=True)
    except Exception:
        return FileValidationResult(
            is_valid=False,
            reason="无法检测文件 MIME 类型",
        )

    if detected_mime not in _ALLOWED_MIME_TYPES:
        return FileValidationResult(
            is_valid=False,
            reason=f"文件类型 {detected_mime} 不在允许列表中。"
                   f"允许的类型：{', '.join(sorted(_ALLOWED_MIME_TYPES))}",
        )

    # ===== 第 4 层：文件头魔数校验 =====
    if len(content) < 4:
        return FileValidationResult(
            is_valid=False,
            reason="文件内容过短，无法校验文件头",
        )

    expected_magic = _MAGIC_SIGNATURES.get(ext)
    if expected_magic is None:
        return FileValidationResult(
            is_valid=False,
            reason=f"未知的文件类型 .{ext}，无法校验文件头",
        )

    actual_header = content[: len(expected_magic)]
    if actual_header != expected_magic:
        actual_hex = " ".join(f"{b:02x}" for b in actual_header)
        return FileValidationResult(
            is_valid=False,
            reason=f"文件头签名不匹配，实际为 {actual_hex}",
        )

    # 全部通过
    return FileValidationResult(is_valid=True, reason=None)


__all__ = [
    "FileValidationResult",
    "validate_file",
]
