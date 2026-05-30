"""consultation 语法契约 — 语义类型与数据结构定义。

模块: app.modules.consultation.types
职责: 定义咨询域所有公开接口使用的语义类型（NewType）、枚举与数据模型。
      每个语义概念只在此处定义一次，禁止裸用原始类型。
数据来源:
  - 无外部数据来源（纯类型定义层）
边界:
  - 依赖: Python 标准库 typing、uuid
  - 被依赖: consultation 模块内所有子域（plan_generation、consult、history）
禁止行为:
  - 禁止在此文件中定义任何业务逻辑或外部 I/O
  - 禁止裸用 str/int/float 表示咨询域概念（必须使用此处定义的 NewType）
  - 禁止定义不属于咨询域的类型
"""

from __future__ import annotations

from typing import NewType

# ============================================================================
# 会话与请求标识
# ============================================================================

# === SessionId ===
# 前置: SSE 会话创建时由 start_consultation() 生成
# 后置: 用于 SSE 连接标识、重连校验、生成元数据存储
# 输入约束: 格式 "stream-{uuid4}"
# 输出约束: 通过 NewType 防止与 RequestId 或裸 str 混用
SessionId = NewType("SessionId", str)

# === RequestId ===
# 前置: 每次咨询请求开始时生成
# 后置: 用于全链路日志追踪、Prometheus 指标 label、幂等键
# 输入约束: UUID v4 格式字符串
# 输出约束: 通过 NewType 防止与 SessionId 或裸 str 混用
RequestId = NewType("RequestId", str)

# ============================================================================
# 内容类型
# ============================================================================

# === BehaviorDescription ===
# 前置: 家属输入的行为描述文本，经上游 SEC-03 PII 脱敏
# 后置: 作为 RAG 检索查询和 LLM Prompt 的关键输入
# 输入约束: 非空字符串，最大 2000 字符
# 输出约束: 通过 NewType 防止与 PlanText 或裸 str 混用
BehaviorDescription = NewType("BehaviorDescription", str)

# === PlanText ===
# 前置: LLM 生成的应急方案全文（JSON 格式）
# 后置: 经 CSLT-05 置信度校验后推送给前端
# 输入约束: 非空字符串（阻断场景可为空），最大 65536 字符
# 输出约束: 通过 NewType 防止与 BehaviorDescription 或裸 str 混用
PlanText = NewType("PlanText", str)

# === ProfileSummary ===
# 前置: 从 PROF-02 档案查询结果格式化为 Markdown
# 后置: 注入 LLM Prompt 作为患者背景上下文
# 输入约束: Markdown 格式字符串，最大 3000 字符
# 输出约束: 通过 NewType 防止与裸 str 混用
ProfileSummary = NewType("ProfileSummary", str)

# ============================================================================
# 度量类型
# ============================================================================

# === ConfidenceScore ===
# 前置: CSLT-05 置信度复合评分计算得出
# 后置: 决定 PASS / APPEND_WARNING / FORCE_BLOCK 判定
# 输入约束: 0.0–1.0 区间浮点数
# 输出约束: 通过 NewType 防止与耗时或 Token 数等裸 float 混用
ConfidenceScore = NewType("ConfidenceScore", float)

# === ElapsedMs ===
# 前置: time.monotonic() 差值计算
# 后置: 用于性能日志和 Prometheus Histogram 观测
# 输入约束: >= 0.0
# 输出约束: 通过 NewType 防止与 ConfidenceScore 或裸 float 混用
ElapsedMs = NewType("ElapsedMs", float)

__all__ = [
    "SessionId",
    "RequestId",
    "BehaviorDescription",
    "PlanText",
    "ProfileSummary",
    "ConfidenceScore",
    "ElapsedMs",
]
