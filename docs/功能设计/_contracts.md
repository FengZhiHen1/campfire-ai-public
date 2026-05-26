# 模块接口契约索引

## SEC-05 - 输入校验防护
- **输入**: 请求体`dict | None`（由各接口 Pydantic Schema 定义）、查询参数`dict[str,str]`、路径参数`dict[str,str]`、上传文件 `UploadedFile | None`
- **输出**: `ValidationResult {is_valid: bool, validated_data: T | None, errors: list[FieldError] | None, sanitized_content: str | None, secure_query: str}`
- **状态机**: 无（同步无状态操作）
- **模块依赖**: AUTH-04 (JWT认证上下文, Depends链上游)
- **外部依赖**: FastAPI (依赖注入), Pydantic v2 (Schema校验), SQLAlchemy 2.0 async (参数化查询), Python html (实体转义), py-logger (安全审计日志)
- **技术栈**: pydantic>=2.0, fastapi>=0.115, sqlalchemy>=2.0, html (stdlib)
- **契约文件**: `docs/contracts/SEC-05/ValidationErrorResponse.json`, `docs/contracts/SEC-05/ValidationErrorItem.json`, `docs/contracts/SEC-05/FileValidationRule.json`, `docs/contracts/SEC-05/FileValidationResult.json`, `docs/contracts/SEC-05/SecurityAuditLogEntry.json`, `docs/contracts/SEC-05/sanitize_html.json`, `docs/contracts/SEC-05/validate_file.json`, `docs/contracts/SEC-05/SecurityDetectionType.json`
- **更新时间**: `2026-05-26 17:21:10`
