"""LLM 案例提取 JSON 容错修复测试。"""

from __future__ import annotations

import json

import pytest
from app.modules.cases.extraction.service import (
    ExtractionService,
    _escape_internal_quotes,
    _repair_json,
)


class TestRepairJson:
    """测试 _repair_json 对 LLM 常见 JSON 缺陷的修复能力。"""

    def test_removes_markdown_fences(self) -> None:
        raw = '```json\n{"cards": []}\n```'
        repaired = _repair_json(raw)
        assert json.loads(repaired) == {"cards": []}

    def test_repairs_unescaped_quotes_inside_strings(self) -> None:
        """字符串值内部未转义的 ASCII 双引号应被转义。"""
        raw = (
            r'{"cards": [{"title": "示例 - 场景", '
            r'"comforting_phrase": ""慢慢来，我们再试一次。"", '
            r'"immediate_action": "分别标注"我""你""他"。", '
            r'"observation_metrics": "正确使用"你我他"的次数", '
            r'"medical_criteria": "无", "severity_level": "轻度", '
            r'"setting": "家庭", "behavior_type": "其他", '
            r'"parent_category": "沟通替代", "ebp_tags": ["提示"], '
            r'"age_range": [6, 12]}]}'
        )
        repaired = _repair_json(raw)
        data = json.loads(repaired)
        card = data["cards"][0]
        assert card["comforting_phrase"] == '"慢慢来，我们再试一次。"'
        assert '分别标注"我""你""他"。' in card["immediate_action"]
        assert '正确使用"你我他"的次数' in card["observation_metrics"]

    def test_preserves_already_escaped_quotes(self) -> None:
        """已经正确转义的引号不应被破坏。"""
        raw = r'{"cards": [{"comforting_phrase": "\"你好\""}]}'
        repaired = _repair_json(raw)
        data = json.loads(repaired)
        assert data["cards"][0]["comforting_phrase"] == '"你好"'

    def test_removes_trailing_commas(self) -> None:
        raw = '{"cards": [{"title": "a",},],}'
        repaired = _repair_json(raw)
        assert json.loads(repaired) == {"cards": [{"title": "a"}]}

    def test_real_llm_output_from_issue(self) -> None:
        """复现用户提供的失败原始输出，修复后必须能解析。"""
        raw = (
            r'{ "cards": [ { "title": "耐心教授人称代词 - 言语混淆场景", '
            r'"scenario": "ASD青少年在日常交流中出现人称代词"你我他"混淆的现象。", '
            r'"behavior_type": "其他", "age_range": ["15"], "severity_level": "轻度", '
            r'"setting": "不限", "ebp_tags": ["语言训练(表达)", "提示", "练习与复习"], '
            r'"parent_category": "沟通替代", '
            r'"immediate_action": "1. 准备视觉提示卡片，分别标注"我""你""他"。\n'
            r'2. 在日常对话中，放慢语速，用手指向自己说"我"，指向对方说"你"，指向他人说"他"。", '
            r'"comforting_phrase": ""慢慢来，我们再试一次，你做得很好。"", '
            r'"observation_metrics": "1. 在每日10次结构化的对话练习中，正确使用"你我他"的次数从2次以下提升到8次以上。", '
            r'"medical_criteria": "1. 持续耐心教授3个月后，人称代词混淆无任何改善。", '
            r'"evidence_level": "机构经验总结", "caution_notes": "避免在孩子说错时责备或取笑。", '
            r'"contraindications": "无", "is_template": false, '
            r'"_inferred": { "behavior_type": "叙事描述'"'"'说话你我他分不清'"'"'，推断为'"'"'其他'"'"'", '
            r'"parent_category_candidates": "候选1: 沟通替代；候选2: 行为塑造" } } ] }'
        )
        repaired = _repair_json(raw)
        data = json.loads(repaired)
        assert len(data["cards"]) == 1
        card = data["cards"][0]
        assert '"慢慢来，我们再试一次，你做得很好。"' in card["comforting_phrase"]


class TestNormalizeAgeRange:
    """测试 _normalize_age_range 的归一化能力。"""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ([6, 12], [6, 12]),
            (["6", "12"], [6, 12]),
            ([15], [15, 15]),
            (["15"], [15, 15]),
            ("6-12", [6, 12]),
            ("6岁-12岁", [6, 12]),
            ("15", [15, 15]),
            ("[6, 12]", [6, 12]),
            ("[15]", [15, 15]),
            ({"min": 4, "max": 10}, [4, 10]),
        ],
    )
    def test_normalize_valid(self, value: object, expected: list[int]) -> None:
        assert ExtractionService._normalize_age_range(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            None,
            [],
            [1, 2, 3],
            "abc",
            "6-12-18",
        ],
    )
    def test_normalize_invalid_returns_none(self, value: object) -> None:
        assert ExtractionService._normalize_age_range(value) is None


class TestEscapeInternalQuotes:
    """直接测试引号转义状态机。"""

    def test_internal_quote_before_comma(self) -> None:
        raw = r'{"key": "a"b", "other": 1}'
        repaired = _escape_internal_quotes(raw)
        assert json.loads(repaired)["key"] == 'a"b'

    def test_escaped_quote_unchanged(self) -> None:
        raw = r'{"key": "a\"b"}'
        repaired = _escape_internal_quotes(raw)
        assert json.loads(repaired)["key"] == 'a"b'
