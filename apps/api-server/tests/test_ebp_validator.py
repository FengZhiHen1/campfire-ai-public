"""CASE-01 EBP 标签一致性校验 — 单元测试。"""

from __future__ import annotations

from app.modules.cases.review.ebp_validator import check_ebp_consistency


class TestCheckEbpConsistency:
    def test_ncaep_level_with_valid_labels(self):
        result = check_ebp_consistency("NCAEP循证实践", ["强化", "消退"])
        assert result is None

    def test_ncaep_level_with_non_ncaep_label(self):
        result = check_ebp_consistency("NCAEP循证实践", ["强化", "自定义方法"])
        assert result is not None
        assert "自定义方法" in result

    def test_non_ncaep_level_with_ncaep_labels(self):
        result = check_ebp_consistency("机构经验总结", ["视觉支持", "强化"])
        assert result is not None
        assert "视觉支持" in result or "强化" in result

    def test_non_ncaep_level_with_non_ncaep_labels(self):
        result = check_ebp_consistency("个案观察记录", ["自定义方法"])
        assert result is None

    def test_empty_labels(self):
        result = check_ebp_consistency("NCAEP循证实践", [])
        assert result is None

    def test_empty_evidence_level(self):
        result = check_ebp_consistency("", ["强化"])
        assert result is None

    def test_non_list_input(self):
        result = check_ebp_consistency("NCAEP循证实践", None)  # type: ignore[arg-type]
        assert result is None

    def test_all_ncaep_labels_valid(self):
        result = check_ebp_consistency("NCAEP循证实践", ["强化", "消退", "任务分析", "视觉支持"])
        assert result is None
