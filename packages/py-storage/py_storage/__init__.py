"""py-storage — 对象存储共享包。

提供 MinIO 客户端（S3 兼容接口）与文件上传安全校验。
"""

from py_storage.file_security import FileValidationResult, validate_file
from py_storage.exceptions import FileTooLargeError

__all__ = [
    "validate_file",
    "FileValidationResult",
    "FileTooLargeError",
]
