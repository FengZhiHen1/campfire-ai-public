"""cases 模块语法契约 — 语义类型与数据结构定义。

通过 NewType 防止案例域的语义类型在类型检查期被混淆。
每个语义类型只在此处定义一次，模块内所有签名必须使用这些语义类型，
禁止裸用 str/int/list 等原始类型表示领域概念。
"""

from __future__ import annotations

from typing import NewType

# ============================================================================
# 案例域语义类型
# ============================================================================

# === CaseId ===
# 前置: 格式为 "CASE-YYYY-NNNN"，由数据库序列 case_id_seq 生成
# 后置: 用于案例查询、状态变更、日志记录和跨模块引用
# 输入约束: "CASE-" + 4位年份 + "-" + 4位序号，如 "CASE-2026-0001"
# 输出约束: 通过 NewType 防止被误当作 UUID 或普通字符串传递
# 注意: Case 模型已退役，CaseId 仅作为遗留品牌类型保留，待完全迁移后移除
CaseId = NewType("CaseId", str)

# === NarrativeId ===
# 前置: UUID v4 格式字符串，由 uuid.uuid4() 生成
# 后置: 用于 L1 叙事查询和 L2 卡片关联
# 输入约束: 36 字符 UUID v4 字符串（含连字符）
# 输出约束: 防止与 CaseId 或 CardId 混用
NarrativeId = NewType("NarrativeId", str)

# === CardId ===
# 前置: UUID v4 格式字符串，由 uuid.uuid4() 生成
# 后置: 用于 L2 卡片查询、索引触发和专家微调
# 输入约束: 36 字符 UUID v4 字符串（含连字符）
# 输出约束: 防止与 NarrativeId 或 CaseId 混用
CardId = NewType("CardId", str)

# === ReviewerId ===
# 前置: 审核人的用户标识，取自 JWT payload 的 sub 字段
# 后置: 用于审核记录、审计日志和禁止自审校验
# 输入约束: 非空字符串
# 输出约束: 防止与 author_id 混用——审核人不能是案例提交者
ReviewerId = NewType("ReviewerId", str)

# === AuthorId ===
# 前置: 案例/叙事作者的标识，取自 JWT payload 的 sub 字段或匿名用户映射
# 后置: 用于所有权校验（is_owner）、按作者筛选和审计日志
# 输入约束: 非空字符串
# 输出约束: 防止与 ReviewerId 混用
AuthorId = NewType("AuthorId", str)

# === ReviewRound ===
# 前置: 审核轮次序号，从 1 开始递增
# 后置: 用于审核记录排序和 override 链追溯
# 输入约束: 正整数（>= 1）
# 输出约束: 防止被误当作普通 int 传递
ReviewRound = NewType("ReviewRound", int)

# === PiiConfirmation ===
# 前置: 用户是否确认已处理 PII 警告，布尔标志
# 后置: 为 True 时记录 pii_confirmed 审计日志
# 输入约束: True 表示用户确认处理，False 表示未确认（仅生成 warnings 不阻断）
# 输出约束: 防止被误当作普通 bool 传递
PiiConfirmation = NewType("PiiConfirmation", bool)
