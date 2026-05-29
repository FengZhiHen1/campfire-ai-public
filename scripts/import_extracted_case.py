#!/usr/bin/env python3
"""导入已提取的案例（L1 叙事 + L2 卡片）到数据库和向量库。

从 case-extraction 输出目录读取 L1_*.md 和 L2_*.json 文件，
写入 case_narratives + case_cards，生成嵌入向量并写入 case_chunks。

用法:
    uv run scripts/import_extracted_case.py <extraction_dir>
    uv run scripts/import_extracted_case.py "E:/Project/Tool/speech-to-text/exports/case-extraction/2026-05-25_1448_respecting-pace-asd"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# ---------------------------------------------------------------------------
# 值映射
# ---------------------------------------------------------------------------

_SEVERITY_MAP: dict[str, str] = {
    "轻": "轻度",   # 轻 → 轻度
    "中": "中度",   # 中 → 中度
    "重": "重度",   # 重 → 重度
}

_EVIDENCE_MAP: dict[str, str] = {
    "INSTITUTIONAL": "机构经验总结",
    "NCAEP": "NCAEP循证实践",
    "CASE_OBSERVATION": "个案观察记录",
}


def _map_severity(raw: str) -> str:
    return _SEVERITY_MAP.get(raw, raw)


def _map_evidence(raw: str) -> str:
    return _EVIDENCE_MAP.get(raw, raw)


def _extract_title_from_md(md_path: str) -> str:
    """从 L1 markdown 文件的第一个 # 标题提取标题。"""
    with open(md_path, encoding="utf-8") as f:
        for line in f:
            match = re.match(r"^#\s+(.+)$", line)
            if match:
                return match.group(1).strip()
    return Path(md_path).stem


# ---------------------------------------------------------------------------
# SQL 语句
# ---------------------------------------------------------------------------

_INSERT_NARRATIVE = """
    INSERT INTO case_narratives (
        narrative_id, title, narrative, source_type, author_id,
        status, derived_card_ids, created_at, updated_at
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
"""

_INSERT_CARD = """
    INSERT INTO case_cards (
        card_id, narrative_id, title, scenario, behavior_type,
        age_range_min, age_range_max, severity, scene,
        ebp_labels, family_category,
        immediate_action, comforting_phrase,
        observation_metrics, medical_criteria,
        evidence_level, caution_notes, contraindications,
        is_template, excluded_population, attachment_refs,
        review_status, index_status, inferred_fields,
        created_at, updated_at
    ) VALUES (
        $1, $2, $3, $4, $5,
        $6, $7, $8, $9,
        $10, $11,
        $12, $13,
        $14, $15,
        $16, $17, $18,
        $19, $20, $21,
        $22, $23, $24,
        $25, $26
    )
"""

_INSERT_CHUNK = """
    INSERT INTO case_chunks (id, card_id, chunk_text, embedding, metadata, created_at)
    VALUES ($1, $2, $3, $4::vector(1024), $5::jsonb, $6)
"""

_UPDATE_INDEX_STATUS = """
    UPDATE case_cards SET index_status = $1, indexed_at = $2 WHERE card_id = $3
"""


# ---------------------------------------------------------------------------
# 文件发现
# ---------------------------------------------------------------------------


def find_case_files(extraction_dir: str) -> tuple[str, list[str]]:
    """扫描目录，返回 (L1_md_path, [L2_json_paths])。"""
    dir_path = Path(extraction_dir)
    if not dir_path.is_dir():
        print(f"ERROR: 目录不存在: {extraction_dir}", file=sys.stderr)
        sys.exit(1)

    l1_files = sorted(dir_path.glob("L1_*.md"))
    l2_files = sorted(dir_path.glob("L2_*.json"))

    if not l1_files:
        print("ERROR: 未找到 L1_*.md 文件", file=sys.stderr)
        sys.exit(1)
    if not l2_files:
        print("ERROR: 未找到 L2_*.json 文件", file=sys.stderr)
        sys.exit(1)

    return str(l1_files[0]), [str(p) for p in l2_files]


# ---------------------------------------------------------------------------
# 嵌入编码
# ---------------------------------------------------------------------------


async def _encode_chunk(chunk_text: str) -> list[float]:
    """调用 DashScope 嵌入 API 编码文本。"""
    from py_rag.embedding import encode_text

    return await encode_text(chunk_text, text_type="document")


def _build_chunk_text(card: dict) -> str:
    """拼接四段式文本用于向量化（card 为原始 L2 JSON dict）。"""
    return (
        f"场景：{card.get('setting', '')}\n"
        f"行为：{card['immediate_action']} {card['comforting_phrase']}\n"
        f"干预：{card['observation_metrics']}\n"
        f"结果：{card['medical_criteria']}"
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


async def import_case(extraction_dir: str, author_id: str = "seed-script") -> None:
    """导入一个提取目录中的所有案例文件。"""

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL 环境变量未设置", file=sys.stderr)
        sys.exit(1)

    l1_path, l2_paths = find_case_files(extraction_dir)
    print(f"L1 叙事: {l1_path}")
    for p in l2_paths:
        print(f"L2 卡片: {p}")

    # 读取文件内容
    with open(l1_path, encoding="utf-8") as f:
        l1_narrative_text = f.read()

    l1_title = _extract_title_from_md(l1_path)
    l2_cards: list[dict] = []
    for p in l2_paths:
        with open(p, encoding="utf-8") as f:
            l2_cards.append(json.load(f))

    # 连接数据库
    db_url = str(DATABASE_URL).replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_url)

    try:
        now = datetime.now(timezone.utc)

        # ---- 步骤 1：插入 L1 叙事 ----
        narrative_id = uuid.uuid4()
        card_uuids = [uuid.uuid4() for _ in l2_cards]
        derived_ids = [str(c) for c in card_uuids]

        await conn.execute(
            _INSERT_NARRATIVE,
            narrative_id,
            l1_title,
            l1_narrative_text,
            "专家撰写",
            author_id,
            "approved",
            json.dumps(derived_ids, ensure_ascii=False),
            now,
            now,
        )
        print(f"  L1 已插入: {narrative_id} — {l1_title}")

        # ---- 步骤 2：插入 L2 卡片 ----
        for i, (card_json, card_uuid) in enumerate(zip(l2_cards, card_uuids)):
            age_range = card_json.get("age_range", [0, 0])
            age_min = int(age_range[0]) if age_range else 0
            age_max = int(age_range[1]) if len(age_range) > 1 else age_min

            await conn.execute(
                _INSERT_CARD,
                card_uuid,
                narrative_id,
                card_json.get("title", ""),
                card_json.get("scenario", ""),
                card_json.get("behavior_type", "其他"),
                age_min,
                age_max,
                _map_severity(card_json.get("severity_level", "轻度")),
                card_json.get("setting", "不限"),
                json.dumps(card_json.get("ebp_tags", []), ensure_ascii=False),
                card_json.get("parent_category", "环境调整"),
                card_json.get("immediate_action", ""),
                card_json.get("comforting_phrase", ""),
                card_json.get("observation_metrics", ""),
                card_json.get("medical_criteria", ""),
                _map_evidence(card_json.get("evidence_level", "INSTITUTIONAL")),
                card_json.get("caution_notes", ""),
                card_json.get("contraindications", ""),
                card_json.get("is_template", False),
                card_json.get("excluded_population"),
                json.dumps(card_json.get("attachment_refs") or [], ensure_ascii=False),
                "approved",
                "pending",
                json.dumps(card_json.get("_inferred"), ensure_ascii=False) if card_json.get("_inferred") else None,
                now,
                now,
            )
            print(f"  L2 已插入: {card_uuid} — {card_json.get('title', '')}")

        # ---- 步骤 3：生成嵌入并写入 case_chunks ----
        for i, (card_json, card_uuid) in enumerate(zip(l2_cards, card_uuids)):
            chunk_text = _build_chunk_text(card_json)
            print(f"  正在编码 [{i + 1}/{len(l2_cards)}]: {card_json.get('title', '')} ...")

            try:
                embedding = await _encode_chunk(chunk_text)
            except Exception as exc:
                print(f"  WARNING: 嵌入编码失败: {exc}", file=sys.stderr)
                await conn.execute(_UPDATE_INDEX_STATUS, "indexing_failed", None, card_uuid)
                continue

            chunk_id = uuid.uuid4()
            metadata = {
                "behavior_type": card_json.get("behavior_type", ""),
                "age_range": f"{card_json.get('age_range', [0, 0])[0]}-{card_json.get('age_range', [0, 0])[1]}",
                "severity": _map_severity(card_json.get("severity_level", "")),
                "evidence_level": _map_evidence(card_json.get("evidence_level", "")),
                "case_title": card_json.get("title", ""),
                "source": "专家撰写",
                "status": "approved",
                "vectorized": True,
            }

            await conn.execute(
                _INSERT_CHUNK,
                chunk_id,
                card_uuid,
                chunk_text,
                json.dumps(embedding),
                json.dumps(metadata, ensure_ascii=False),
                now,
            )
            await conn.execute(_UPDATE_INDEX_STATUS, "indexed", now, card_uuid)
            print(f"  索引完成 [{i + 1}/{len(l2_cards)}]: {card_uuid} -> chunk {chunk_id}")

        print(f"\n导入完成: 1 条 L1 叙事 + {len(l2_cards)} 条 L2 卡片 + {len(l2_cards)} 条向量 chunk")

    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="导入已提取案例到数据库和向量库")
    parser.add_argument(
        "extraction_dir",
        help="case-extraction 输出目录路径",
    )
    parser.add_argument(
        "--author-id",
        default="seed-script",
        help="作者 ID（默认 seed-script）",
    )
    args = parser.parse_args()
    asyncio.run(import_case(args.extraction_dir, args.author_id))


if __name__ == "__main__":
    main()
