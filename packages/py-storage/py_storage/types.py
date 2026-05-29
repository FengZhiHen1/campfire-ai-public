"""py-storage 语法契约 — 语义类型与数据结构定义。

模块: py_storage.types
职责: 定义 py-storage 包所有公开接口使用的语义类型（NewType）、枚举与数据模型。
      每个语义概念只在此处定义一次，禁止裸用原始类型。
数据来源:
  - 无外部数据来源（纯类型定义层）
边界:
  - 依赖: Python 标准库 typing、dataclasses、enum
  - 被依赖: file_validation_contract.py（ABC 基类）、file_security.py（实现类）
禁止行为:
  - 禁止在类型定义文件中包含任何业务逻辑或 IO 操作
  - 禁止在公开接口中裸用 str/int/bytes 等原始类型替代此处的语义类型
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import NewType

# ---------------------------------------------------------------------------
# 语义类型（NewType）
# ---------------------------------------------------------------------------

FileExtension = NewType("FileExtension", str)
"""文件扩展名（不含点号），如 'pdf'、'jpg'。"""

FileName = NewType("FileName", str)
"""原始上传文件名（含扩展名）。"""

FileContent = NewType("FileContent", bytes)
"""文件原始字节内容。与普通 bytes 在类型层面区分。"""

MimeType = NewType("MimeType", str)
"""MIME 类型字符串，如 'application/pdf'。"""


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class FileCategory(str, Enum):
    """文件资源类别。

    决定文件大小上限和校验策略。
    """

    IMAGE = "image"
    """图片类：jpg、jpeg、png"""
    DOCUMENT = "document"
    """文档类：pdf、docx"""


class ValidationStep(str, Enum):
    """文件校验步骤枚举。

    四层递进校验的步骤标识，用于错误报告中定位失败位置。
    """

    EXTENSION = "extension"
    """第 1 层：扩展名白名单校验"""
    SIZE = "size"
    """第 2 层：文件大小上限校验"""
    MIME_TYPE = "mime_type"
    """第 3 层：MIME 类型检测（python-magic）"""
    MAGIC_BYTES = "magic_bytes"
    """第 4 层：文件头魔数校验"""


# ---------------------------------------------------------------------------
# 数据模型（frozen dataclass — 契约数据不可变）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileValidationInput:
    """文件校验输入。

    前置: filename 必须是非空字符串，含扩展名
    前置: content 必须是非空 bytes
    后置: 所有字段不可变（frozen=True）
    """

    filename: FileName
    """上传文件的原始文件名（含扩展名）"""
    content: FileContent
    """上传文件的原始字节内容"""


@dataclass(frozen=True)
class FileValidationResult:
    """文件安全校验结果。

    前置: is_valid 为 True 时 reason 必须为 None
    前置: is_valid 为 False 时 reason 必须为非空字符串
    前置: is_valid 为 False 时 failed_step 指示校验失败所在的步骤
    后置: 结果不可变（frozen=True）
    """

    is_valid: bool
    """文件是否通过全部校验"""
    reason: str | None = None
    """校验失败时的原因说明；通过时为 None"""
    failed_step: ValidationStep | None = None
    """校验失败时所在的步骤；通过时为 None"""


__all__ = [
    "FileExtension",
    "FileName",
    "FileContent",
    "MimeType",
    "FileCategory",
    "ValidationStep",
    "FileValidationInput",
    "FileValidationResult",
]
