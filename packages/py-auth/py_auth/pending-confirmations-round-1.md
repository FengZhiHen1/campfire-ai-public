# SEC-01 修复说明 — Round 1

> 修复时间：2026-05-26
> 本轮修复：3 个实现漏洞（BUG-001 ~ BUG-003）

## BUG-001: verify_password 未处理 hashed_password=None

- **文件**：`packages/py-auth/py_auth/hashing.py`
- **修复**：在 `verify_password` 调用 `hashed_password.startswith(...)` 之前，新增 `isinstance(hashed_password, str)` 类型检查。若类型不匹配，抛出 `ValueError`。
- **契约对齐**：verify_password.json 要求 `hashed_password.type="string"`，违规输入现通过 ValueError 明确拒绝。

## BUG-002: verify_token 返回的 payload 缺少 kid 字段

- **文件**：`packages/py-auth/py_auth/jwt_utils.py`
- **修复**：在 `verify_token` 成功解码 JWT 后、return 之前，将 header 中提取的 `kid` 值注入 payload：`payload["kid"] = kid`。
- **契约对齐**：TokenPayload.json 的 required 字段包含 kid，现在返回的 dict 始终携带 kid。

## BUG-003: validate_file 未校验 content 参数类型

- **文件**：`packages/py-storage/py_storage/file_security.py`
- **修复**：在 `validate_file` 入口处，在空文件名检查之前，新增 `isinstance(content, bytes)` 类型检查。若不是 bytes，抛出 `TypeError(f"content 必须是 bytes 类型，实际为 {type(content).__name__}")`。
- **契约对齐**：validate_file.json 和落地规范均要求 `content: bytes`，违规输入现通过 TypeError 明确拒绝。
