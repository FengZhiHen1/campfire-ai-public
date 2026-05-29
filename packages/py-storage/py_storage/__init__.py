"""py-storage — 对象存储共享包。

模块: py_storage
职责: 提供文件上传安全校验（四层递进：扩展名 → 大小 → MIME → 魔数）。
      通过 ABC 模板方法将校验管线与具体策略解耦，
      调用方依赖契约而非具体校验器。
数据来源:
  - py_config.security: 读取允许的文件扩展名白名单
  - python-magic: MIME 类型检测
边界:
  - 依赖: py-config（共享配置）、python-magic（MIME 检测）
  - 被依赖: api-server 文件上传路由、CASE-02 案例附件上传
"""

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
from py_storage.file_validation_contract import BaseFileValidator
from py_storage.types import (
    FileCategory,
    FileContent,
    FileExtension,
    FileName,
    FileValidationInput,
    FileValidationResult,
    MimeType,
    ValidationStep,
)

__all__ = [
    # 契约
    "BaseFileValidator",
    # 实现
    "DefaultFileValidator",
    # 类型
    "FileExtension",
    "FileName",
    "FileContent",
    "MimeType",
    "FileCategory",
    "ValidationStep",
    "FileValidationInput",
    "FileValidationResult",
    # 异常
    "FileValidationError",
    "FileInputValidationError",
    "FileExtensionNotAllowedError",
    "FileTooLargeError",
    "FileMimeTypeNotAllowedError",
    "FileMimeDetectionError",
    "FileContentTooShortError",
    "FileMagicSignatureMismatchError",
]
