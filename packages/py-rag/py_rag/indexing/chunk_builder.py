"""CASE-04 文本组装模块（索引管线步骤 6）。

负责将审核通过案例的四段式文本字段拼接为向量化所需最终文本，
并执行 PII 最终防线校验（身份证号、手机号、家庭住址正则扫描）。
"""

from __future__ import annotations

import re

from typing import Any

from py_logger import logger

from py_rag.exceptions import ChunkBuildError, PIIRejectionError
from py_rag.models import ChunkMetadata

# ============================================================================
# 常量
# ============================================================================

_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "phone_number": re.compile(r"1[3-9]\d{9}"),
    "id_card": re.compile(
        r"[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]"
    ),
    "address": re.compile(
        r"([一-龥]{2,}(市|区|县|镇|路|街|号|弄|小区|栋|单元|室)){2,}"
    ),
}

_REQUIRED_FIELDS: list[str] = [
    "immediate_action",
    "comforting_phrase",
    "observation_metrics",
    "medical_criteria",
]

_MIN_FIELD_LENGTH: int = 10


# ============================================================================
# 公开接口
# ============================================================================


def build_chunk_text(case_data: dict[str, Any]) -> tuple[str, ChunkMetadata]:
    """将审核通过案例的四段式文本拼接为向量切片的 chunk_text。

    执行顺序：
    1. 四要素字段非空校验
    2. 模板拼接：f"场景：{}\n行为：{}\n干预：{}\n结果：{}"
    3. 免责声明追加：chunk_text += f"\n免责声明：{disclaimer}"
    4. PII 最终防线校验（正则扫描）
    5. 构造 ChunkMetadata 对象

    Args:
        case_data: 案例数据库行字典。

    Returns:
        (chunk_text, metadata) 元组。

    Raises:
        ChunkBuildError: 四段式字段不完整或免责声明丢失。
        PIIRejectionError: PII 最终防线检测到未脱敏的个人信息。
    """
    case_id: str = str(case_data.get("case_id", ""))

    # ------------------------------------------------------------------
    # 步骤 1：四要素字段非空校验
    # ------------------------------------------------------------------
    missing_fields: list[str] = []
    for field in _REQUIRED_FIELDS:
        value = case_data.get(field)
        if (
            value is None
            or not isinstance(value, str)
            or len(value.strip()) < _MIN_FIELD_LENGTH
        ):
            missing_fields.append(field)

    if missing_fields:
        logger.error(
            "py-rag",
            "四段式字段不完整",
            op_type="chunk_build_failed",
            extra={
                "case_id": case_id,
                "missing_fields": missing_fields,
                "reason": "incomplete_fields",
                "phase": "build_chunk_text",
            },
        )
        raise ChunkBuildError(
            "四段式字段不完整",
            missing_fields=missing_fields,
            case_id=case_id,
        )

    # ------------------------------------------------------------------
    # 步骤 2：模板拼接
    # ------------------------------------------------------------------
    scene = case_data.get("scene", "")
    intervention = case_data["immediate_action"].strip()
    behavior = case_data["comforting_phrase"].strip()
    result = case_data["observation_metrics"].strip()
    medical = case_data["medical_criteria"].strip()

    chunk_text = (
        f"场景：{scene}\n"
        f"行为：{behavior}\n"
        f"干预：{intervention}\n"
        f"结果：{result}\n"
        f"就医判断：{medical}"
    )

    # ------------------------------------------------------------------
    # 步骤 3：免责声明处理 — 追加到 chunk_text 末尾
    # ------------------------------------------------------------------
    disclaimer: str | None = case_data.get("disclaimer")
    if disclaimer:
        disclaimer_stripped = disclaimer.strip()
        if disclaimer_stripped:
            chunk_text += f"\n免责声明：{disclaimer_stripped}"

            if disclaimer_stripped not in chunk_text:
                logger.error(
                    "py-rag",
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
        safe_sample = chunk_text
        for pattern_name, pattern in _PII_PATTERNS.items():
            safe_sample = pattern.sub("***", safe_sample)

        logger.warning(
            "py-rag",
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
    metadata = _build_metadata(case_data)

    return chunk_text, metadata


# ============================================================================
# 内部函数
# ============================================================================


def _build_metadata(case_data: dict[str, Any]) -> ChunkMetadata:
    behavior_type = str(case_data.get("behavior_type", ""))
    age_min = case_data.get("age_range_min")
    age_max = case_data.get("age_range_max")
    age_range = f"{age_min}-{age_max}" if (age_min is not None and age_max is not None) else ""
    severity = str(case_data.get("severity", ""))
    evidence_level = str(case_data.get("evidence_level", ""))
    case_title = str(case_data.get("title", "")) or None
    source = str(case_data.get("source_type", "")) or None

    return ChunkMetadata(
        behavior_type=behavior_type,
        age_range=age_range,
        severity=severity,
        evidence_level=evidence_level,
        case_title=case_title,
        source=source,
    )
