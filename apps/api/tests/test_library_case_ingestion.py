"""案例摄取的纯函数单元测试（不连库）：节点元数据的 `withdrawn` 投影自条目实体。

来源（D-16）：`withdrawn` 曾在两个 metadata 构造函数里硬编码字面量 `"false"`，
于是撤下过的条目被重新摄取时，写回的节点会声称自己未撤下——向量路的
`withdrawn` 过滤对它就失效，撤下只剩装配层二次过滤兜底。

写入侧现在还会跳过已撤下条目的节点写入，因此这条投影在正常流程里恒为
`"false"`；这里直接断言纯函数，是为了让「元数据投影自条目状态、不是常量」
有独立、可判别的检查——把 `"true" if withdrawn else "false"` 改回字面量，
本用例即失败。

落库行为（撤下后重新摄取不重建节点、元数据与条目表一致）由
`test_library_case_integration.py` 覆盖。
"""

from __future__ import annotations

from datetime import datetime, timezone

from campfire.modules.library.case_ingestion import _card_metadata, _narrative_metadata
from campfire.modules.library.case_schema import CaseManifest
from campfire.modules.library.chunking import Chunk


def _manifest() -> CaseManifest:
    """一个形状合法的最小 manifest（值全部虚构，仅用于元数据投影）。"""
    return CaseManifest(
        external_key="2099-01-01_0000_unit",
        title="虚构案例：元数据投影",
        source_type="专家访谈转写",
        subject_type="家长",
        interview_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        consent_scope="ai_retrieval_and_advice",
        evidence_level="INSTITUTIONAL",
        review_status="owner",
        authorization="虚构样例（无真实来源）",
        narrative_file="L1_x.md",
        card_files=("L2_x_01.json",),
    )


def _card() -> dict[str, object]:
    """投影只读这几个键的最小卡片。"""
    return {
        "title": "虚构卡片",
        "evidence_level": "INSTITUTIONAL",
        "age_range": ["3", "6"],
        "severity_level": "轻",
        "behavior_type": "其他",
        "ebp_tags": ["视觉支持(VS)"],
        "parent_category": "环境调整",
    }


def test_node_metadata_withdrawn_is_derived_from_item_state() -> None:
    """`withdrawn` 元数据随条目状态取 `"true"` / `"false"`，不得是常量。"""
    manifest = _manifest()
    card = _card()
    chunk = Chunk(text="虚构正文", header_path="/", locator="/场景背景/", chunk_index=0)

    card_active = _card_metadata(
        manifest, "item-1", card, "2099-01-01_0000_unit#01", locator="虚构卡片", withdrawn=False
    )
    card_withdrawn = _card_metadata(
        manifest, "item-1", card, "2099-01-01_0000_unit#01", locator="虚构卡片", withdrawn=True
    )
    narrative_active = _narrative_metadata(manifest, "item-1", chunk, makes_claims_high_risk=False, withdrawn=False)
    narrative_withdrawn = _narrative_metadata(manifest, "item-1", chunk, makes_claims_high_risk=False, withdrawn=True)

    assert card_active["withdrawn"] == "false"
    assert card_withdrawn["withdrawn"] == "true", "卡片节点元数据的 withdrawn 未从条目状态派生"
    assert narrative_active["withdrawn"] == "false"
    assert narrative_withdrawn["withdrawn"] == "true", "叙事节点元数据的 withdrawn 未从条目状态派生"
