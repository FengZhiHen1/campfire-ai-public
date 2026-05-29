"""SEC-05 输入校验防护 — Pydantic v2 数据模型。

本模块定义输入校验防护所需的全部 Pydantic v2 数据模型，
字段名、类型、必填性与 docs/contracts/SEC-05/ 下的 JSON Schema 契约完全一致。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from py_schemas.base import CampfireBaseModel


class SecurityDetectionType(StrEnum):
    """安全检测事件类型枚举。

    与 docs/contracts/SEC-05/SecurityDetectionType.json 契约一致。
    """

    sql_injection = "sql_injection"
    xss_payload = "xss_payload"
    malformed_request = "malformed_request"


class ValidationErrorItem(CampfireBaseModel):
    """字段级校验错误明细。

    与 docs/contracts/SEC-05/ValidationErrorItem.json 契约一致。
    全部字段必填，禁止额外属性。
    """

    field: str = Field(..., min_length=1, description="校验失败的字段名")
    reason: str = Field(..., min_length=1, description="不通过原因的机器可读标识")
    constraint: str = Field(..., min_length=1, description="期望的约束条件，面向调用方的可读说明")


class ValidationErrorResponse(CampfireBaseModel):
    """校验失败时的 HTTP 响应体。

    与 docs/contracts/SEC-05/ValidationErrorResponse.json 契约一致。
    覆盖 FastAPI 默认 422 格式，errors 列表至少包含 1 项。
    """

    errors: list[ValidationErrorItem] = Field(
        ..., min_length=1, description="校验失败的错误明细列表，至少包含 1 项"
    )


class FileValidationRule(CampfireBaseModel):
    """文件校验规则配置。

    与 docs/contracts/SEC-05/FileValidationRule.json 契约一致。
    定义允许的文件类型白名单和大小上限。
    """

    allowed_mime_types: list[str] = Field(
        ..., min_length=1, description="允许的 MIME 类型白名单"
    )
    allowed_extensions: list[str] = Field(
        ..., min_length=1, description="允许的文件扩展名白名单"
    )
    max_size_bytes: int = Field(
        ..., ge=1, description="文件大小上限（字节）"
    )


class FileValidationResult(CampfireBaseModel):
    """文件校验结果。

    与 docs/contracts/SEC-05/FileValidationResult.json 契约一致。
    包含通过/拒绝状态、检测到的 MIME 类型、文件大小。
    """

    is_valid: bool = Field(..., description="文件是否通过校验")
    error_message: str | None = Field(
        default=None, description="校验失败时的错误说明，仅 is_valid=False 时有值"
    )
    detected_mime_type: str = Field(
        ..., min_length=1, description="通过文件头魔数检测到的真实 MIME 类型"
    )
    file_size_bytes: int = Field(
        ..., ge=1, description="文件大小（字节）"
    )


class SecurityAuditLogEntry(CampfireBaseModel):
    """安全审计日志条目。

    与 docs/contracts/SEC-05/SecurityAuditLogEntry.json 契约一致。
    记录校验异常和安全检测事件。
    """

    trace_id: str = Field(..., min_length=1, description="请求链路追踪 ID")
    event_type: SecurityDetectionType = Field(
        ..., description="安全事件类型标识"
    )
    detection_detail: str = Field(
        ..., min_length=1, description="检测详情，不得包含用户原始输入全文"
    )
    timestamp: str = Field(..., description="事件发生时间（ISO 8601 格式）")
