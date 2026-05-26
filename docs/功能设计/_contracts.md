# 模块接口契约索引

## SEC-01 - 传输存储安全
- **输入**: `hash_password(plain_password: str) -> str`, `verify_password(plain: str, hashed: str) -> bool`, `verify_token(token: str) -> dict|None`, `check_rate_limit(user_id: str|None, ip: str) -> bool`, `validate_file(filename: str, content: bytes) -> FileValidationResult`
- **输出**: `create_access_token(data: dict, expires_delta: timedelta|None) -> str`, `TokenPayload {sub, roles, kid, exp, iat}`, `FileValidationResult {is_valid: bool, reason: str|None}`, `RateLimitExceededResponse {detail: str, retry_after_seconds: int}`, `PhoneMaskedString {value: str}`
- **状态机**: 无
- **模块依赖**: AUTH-02 (JWT签发/校验), SEC-04 (限流基础设施), SEC-05 (输入校验防线互补), SEC-03 (PII检测下游协作)
- **外部依赖**: Nginx (HTTPS/TLS 1.3), Redis (滑动窗口限流), PostgreSQL (audit_logs 表), MinIO (预签名 URL)
- **技术栈**: python-jose>=3.3, passlib[bcrypt]>=1.7, redis>=5.0, pydantic>=2.0, pydantic-settings>=2.0
- **契约文件**: `docs/contracts/SEC-01/hash_password.json`, `docs/contracts/SEC-01/verify_password.json`, `docs/contracts/SEC-01/create_access_token.json`, `docs/contracts/SEC-01/verify_token.json`, `docs/contracts/SEC-01/check_rate_limit.json`, `docs/contracts/SEC-01/validate_file.json`, `docs/contracts/SEC-01/TokenPayload.json`, `docs/contracts/SEC-01/FileValidationResult.json`, `docs/contracts/SEC-01/RateLimitConfig.json`, `docs/contracts/SEC-01/SecurityConfig.json`, `docs/contracts/SEC-01/AuditLogEvent.json`, `docs/contracts/SEC-01/RateLimitExceededResponse.json`, `docs/contracts/SEC-01/PhoneMaskedString.json`
- **更新时间**: `2026-05-26 17:20:59`
