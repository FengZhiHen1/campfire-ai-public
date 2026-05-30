# @contract
"""py-auth 语法契约 — 语义类型与数据结构定义。

通过 NewType 防止认证域的核心语义类型在类型检查期被混淆:
- UserID: 用户标识，不应与 TokenHash 或 JtiToken 混用
- PlainPassword: 明文密码，标注为瞬态类型（使用后应立即丢弃）
- TokenHash: bcrypt 哈希串，不应与用户 ID 混用
- JtiToken: JWT 唯一标识符，用于黑名单和重放检测
"""

from __future__ import annotations

from typing import NewType

# ============================================================================
# 用户标识
# ============================================================================

# 前置: 外部传入的用户标识，格式为 UUID v4 字符串
# 后置: 用于日志记录、权限校验和数据库查询
# 输入约束: UUID v4 格式字符串 (36 字符，含 4 个 "-")
# 输出约束: 通过 NewType 防止与 TokenHash 或 DeviceID 混用
UserID = NewType("UserID", str)

# ============================================================================
# 密码相关
# ============================================================================

# 前置: 用户输入的明文密码，长度 8-64 字符
# 后置: 哈希后立即丢弃，不得持久化或记录到日志
# 输入约束: str 类型，长度 [8, 64]
# 输出约束: 禁止在日志中输出；禁止与 TokenHash 混用
PlainPassword = NewType("PlainPassword", str)

# 前置: bcrypt 哈希计算输出，格式 $2b$12$<22-char-salt><31-char-hash>
# 后置: 持久化到数据库，用于 verify_password 校验
# 输入约束: 以 $2b$ 或 $2a$ 开头的 bcrypt 哈希字符串
# 输出约束: 禁止与 PlainPassword 或 UserID 混用
TokenHash = NewType("TokenHash", str)

# ============================================================================
# Token 相关
# ============================================================================

# 前置: JWT 签发时由 uuid4() 生成，存入 jti claim
# 后置: 用于黑名单查询和 Refresh Token 单次使用检测
# 输入约束: UUID v4 格式字符串
# 输出约束: 防止与 UserID 混用——黑名单操作应以 JtiToken 为参数
JtiToken = NewType("JtiToken", str)

# ============================================================================
# 设备标识 (MVP 匿名认证阶段)
# ============================================================================

# 前置: 前端传入的 X-Device-Id 请求头，或由 secrets.token_urlsafe(12) 生成
# 后置: 通过 uuid5 确定性映射为 UUID，用于 MVP 阶段的无认证追踪
# 输入约束: URL-safe 字符串，长度 1-255
# 输出约束: 仅供 MVP 阶段使用，正式上线后移除
DeviceID = NewType("DeviceID", str)

__all__ = [
    "UserID",
    "PlainPassword",
    "TokenHash",
    "JtiToken",
    "DeviceID",
]
