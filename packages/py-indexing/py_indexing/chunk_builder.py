"""CASE-04 文本组装模块。

负责将审核通过案例的四段式文本字段拼接为向量化所需最终文本，
并执行 PII 最终防线校验（身份证号、手机号、家庭住址正则扫描）。

对外接口：
    - build_chunk_text(case_data: dict) -> tuple[str, dict]
"""

from __future__ import annotations

import re

from py_logger import logger

from py_indexing.exceptions import ChunkBuildError, PIIRejectionError
from py_indexing.models import ChunkMetadata

# ============================================================================
# 常量
# ============================================================================

# PII 检测正则模式 — 复用 SEC-03 的检测规则作为最终防线
_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "phone_number": re.compile(r"1[3-9]\d{9}"),
    "id_card": re.compile(r"[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]"),
    "address": re.compile(r"([一-龥]{2,}(市|区|县|镇|路|街|号|弄|小区|栋|单元|室)){2,}"),
}

# 四要素字段名（检查顺序）
_REQUIRED_FIELDS: list[str] = [
    "scene_description",
    "behavior_manifestation",
    "intervention_action",
    "result_feedback",
]

# 严重程度映射表（emotion_level → severity）
_SEVERITY_MAP: dict[str, str] = {
    "mild": "轻度",
    "moderate": "中度",
    "severe": "重度",
}

_MIN_FIELD_LENGTH: int = 10
"""四要素字段最小长度阈值（去除首尾空格后）。"""


# ============================================================================
# 公开接口
# ============================================================================


def build_chunk_text(case_data: dict) -> tuple[str, ChunkMetadata]:
    """将审核通过案例的四段式文本拼接为向量切片的 chunk_text。

    执行顺序：
    1. 四要素字段非空校验（任一字段为空或 < 10 字符则抛出 ChunkBuildError）
    2. 模板拼接：f"场景：{}\n行为：{}\n干预：{}\n结果：{}"
    3. 免责声明处理：将 disclaimer 追加到 chunk_text 末尾，格式为 "\n免责声明：{}"
    4. PII 最终防线校验（正则扫描）
    5. 构造 ChunkMetadata 对象

    Args:
        case_data: 案例数据库行字典，包含以下键：
            - scene_description (str)
            - behavior_manifestation (str)
            - intervention_action (str)
            - result_feedback (str)
            - behavior_type (str)
            - emotion_level (str | None)
            - applicable_population (dict | None)
            - evidence_level (str | None)
            - disclaimer (str | None)

    Returns:
        (chunk_text, metadata) 元组：
        - chunk_text: 拼接后的完整文本
        - metadata: ChunkMetadata 对象（用于写入 case_chunks.metadata JSONB）

    Raises:
        ChunkBuildError: 四段式字段不完整或免责声明丢失。
        PIIRejectionError: PII 最终防线检测到未脱敏的个人信息。
    """
    case_id: str = str(case_data.get("id", ""))

    # ------------------------------------------------------------------
    # 步骤 1：四要素字段非空校验
    # ------------------------------------------------------------------
    missing_fields: list[str] = []
    for field in _REQUIRED_FIELDS:
        value = case_data.get(field)
        if value is None or not isinstance(value, str) or len(value.strip()) < _MIN_FIELD_LENGTH:
            missing_fields.append(field)

    if missing_fields:
        error_msg = "四段式字段不完整"
        logger.error(
            "py-indexing",
            error_msg,
            op_type="chunk_build_failed",
            extra={
                "case_id": case_id,
                "missing_fields": missing_fields,
                "reason": "incomplete_fields",
                "phase": "build_chunk_text",
            },
        )
        raise ChunkBuildError(
            error_msg,
            missing_fields=missing_fields,
            case_id=case_id,
        )

    # ------------------------------------------------------------------
    # 步骤 2：模板拼接
    # ------------------------------------------------------------------
    scene: str = case_data["scene_description"].strip()
    behavior: str = case_data["behavior_manifestation"].strip()
    intervention: str = case_data["intervention_action"].strip()
    result: str = case_data["result_feedback"].strip()

    chunk_text: str = f"场景：{scene}\n行为：{behavior}\n干预：{intervention}\n结果：{result}"

    # ------------------------------------------------------------------
    # 步骤 3：免责声明完整性检查
    # ------------------------------------------------------------------
    disclaimer: str | None = case_data.get("disclaimer")
    if disclaimer:
        disclaimer_stripped: str = disclaimer.strip()
        if disclaimer_stripped:
            # 将免责声明追加到 chunk_text 末尾
            chunk_text += f"\n免责声明：{disclaimer_stripped}"
            # 完整性检查：拼接后的文本中必须包含 disclaimer 字段的内容
            if disclaimer_stripped not in chunk_text:
                logger.error(
                    "py-indexing",
                    "免责声明在文本组装过程中丢失",
                    op_type="chunk_build_failed",
                    extra={
                        "case_id": case_id,
                        "reason": "disclaimer_missing",
                        "phase": "build_chunk_text",
                    },
                )
                raise ChunkBuildError(
                    "免责声明在文本组装过程中丢失",
                    case_id=case_id,
                )

    # ------------------------------------------------------------------
    # 步骤 4：PII 最终防线校验
    # ------------------------------------------------------------------
    patterns_matched: list[str] = []
    first_match_offset: int | None = None

    for pattern_name, pattern in _PII_PATTERNS.items():
        match = pattern.search(chunk_text)
        if match:
            patterns_matched.append(pattern_name)
            if first_match_offset is None:
                first_match_offset = match.start()

    if patterns_matched:
        # 记录告警日志，对匹配段做掩码处理
        safe_sample: str = chunk_text
        for pattern_name, pattern in _PII_PATTERNS.items():
            safe_sample = pattern.sub("***", safe_sample)

        logger.warning(
            "py-indexing",
            "PII 最终防线检测到未脱敏的个人信息",
            op_type="pii_rejection",
            extra={
                "case_id": case_id,
                "patterns_matched": patterns_matched,
                "sample_text": safe_sample[
                    max(0, (first_match_offset or 0) - 20) : (first_match_offset or 0) + 20
                ],
                "phase": "build_chunk_text",
            },
        )
        raise PIIRejectionError(
            "PII 最终防线检测到未脱敏的个人信息",
            patterns_matched=patterns_matched,
            sample_offset=first_match_offset,
        )

    # ------------------------------------------------------------------
    # 步骤 5：构造 ChunkMetadata 对象
    # ------------------------------------------------------------------
    metadata: ChunkMetadata = _build_metadata(case_data)

    return chunk_text, metadata


# ============================================================================
# 内部函数
# ============================================================================


def _build_metadata(case_data: dict) -> ChunkMetadata:
    """构造 ChunkMetadata 对象。

    Args:
        case_data: 案例数据库行字典。

    Returns:
        包含 4 个维度的 ChunkMetadata 对象。
    """
    # behavior_type：直接映射
    behavior_type: str = str(case_data.get("behavior_type", ""))

    # age_range：从 applicable_population JSONB 中提取 min/max
    age_range: str = _extract_age_range(case_data.get("applicable_population"))

    # severity：映射 emotion_level → 中文枚举
    severity: str = _map_severity(case_data.get("emotion_level"))

    # evidence_level：直接映射
    evidence_level: str = str(case_data.get("evidence_level", ""))

    return ChunkMetadata(
        behavior_type=behavior_type,
        age_range=age_range,
        severity=severity,
        evidence_level=evidence_level,
    )


def _extract_age_range(applicable_population: object) -> str:
    """从 applicable_population JSONB 中提取年龄区间字符串。

    Args:
        applicable_population: cases 表的 applicable_population 字段值，
            预期为 dict 类型，包含 "min_age" 和 "max_age" 键。

    Returns:
        "min-max" 格式的年龄区间字符串。若提取失败则返回空字符串。
    """
    if not isinstance(applicable_population, dict):
        return ""

    min_age: object = applicable_population.get("min_age")
    max_age: object = applicable_population.get("max_age")

    if min_age is not None and max_age is not None:
        return f"{min_age}-{max_age}"
    if min_age is not None:
        return str(min_age)
    if max_age is not None:
        return f"0-{max_age}"

    return ""


def _map_severity(emotion_level: object) -> str:
    """将 emotion_level 枚举值映射为中文严重程度。

    Args:
        emotion_level: 数据库中的 emotion_level 值（mild/moderate/severe 或其中文对应）。

    Returns:
        中文严重程度字符串："轻度"、"中度"、"重度"。
        若无法映射，返回原值字符串表示。
    """
    if emotion_level is None:
        return ""

    emo_str: str = str(emotion_level).strip().lower()
    if emo_str in _SEVERITY_MAP:
        return _SEVERITY_MAP[emo_str]

    # 如果已经是中文，直接返回
    if emo_str in ("轻度", "中度", "重度"):
        return emo_str

    return emo_str
