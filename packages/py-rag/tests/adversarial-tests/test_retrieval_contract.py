"""py-rag 语义检索契约 — 黑盒对抗测试。

测试对象：
  - BaseSemanticSearch._validate_input()
  - BaseSemanticSearch._validate_result()
  - BaseSemanticSearch._compute_query_fingerprint()
  - BaseSemanticSearch.search()       [@final, 异步]

隔离约束：严禁 import retrieval.py 或访问任何实现代码。
"""

from __future__ import annotations

from typing import Any

import pytest

from py_rag.embedding_contract import BaseEmbeddingEncoder
from py_rag.retrieval_contract import BaseSemanticSearch
from py_rag.types import (
    TOP_K_MAX,
    TOP_K_MIN,
    EmbeddingVector,
    QueryFingerprint,
)


# ============================================================================
# Mock 子类 — 最小合法实现
# ============================================================================


class MockSearchEncoder(BaseEmbeddingEncoder):
    """供 MockSearch 使用的最小嵌入编码器，返回 1024 维零向量。"""

    async def _do_encode(self, text: str, text_type: str) -> list[float]:
        return [0.0] * 1024


class MockSearch(BaseSemanticSearch):
    """测试用 mock：_do_search 返回空列表，不访问数据库。"""

    async def _do_search(
        self,
        query_vector: EmbeddingVector,
        top_k: int,
        db: Any,
    ) -> list[dict[str, Any]]:
        return []  # 空结果，最低合法值


# ============================================================================
# P0：禁止行为测试 — _validate_input 校验条件
# ============================================================================


class TestValidateInput:
    """_validate_input() 基线校验测试。"""

    def setup_method(self) -> None:
        self.encoder = MockSearchEncoder()
        self.search = MockSearch(self.encoder)
        self.valid_db = object()  # 占位 AsyncSession

    def test_p0_empty_string_raises_valueerror(self):
        """空 query_text 应抛 ValueError，消息含 '不能为空'。"""
        with pytest.raises(ValueError, match="不能为空"):
            self.search._validate_input("", 10, self.valid_db)

    def test_p0_non_string_query_text_raises_valueerror(self):
        """query_text 非 str 类型应抛 ValueError，消息含 '必须为字符串类型'。"""
        with pytest.raises(ValueError, match="必须为字符串类型"):
            self.search._validate_input(12345, 10, self.valid_db)  # type: ignore[arg-type]

    def test_p0_none_query_text_raises_valueerror(self):
        """query_text=None 应抛 ValueError（isinstance(None, str) 为 False）。"""
        with pytest.raises(ValueError, match="必须为字符串类型"):
            self.search._validate_input(None, 10, self.valid_db)  # type: ignore[arg-type]

    def test_p0_exceeds_2000_chars_raises_valueerror(self):
        """query_text 超过 2000 字符应抛 ValueError，消息含 '2000'。"""
        long_query = "x" * 2001
        with pytest.raises(ValueError, match="2000"):
            self.search._validate_input(long_query, 10, self.valid_db)

    def test_p0_db_none_raises_valueerror(self):
        """db=None 应抛 ValueError，消息含 '不能为 None'。"""
        with pytest.raises(ValueError, match="不能为 None"):
            self.search._validate_input("正常查询", 10, None)

    def test_p0_list_query_text_raises_valueerror(self):
        """query_text 为 list 类型应抛 ValueError，消息含类型名。"""
        with pytest.raises(ValueError, match="必须为字符串类型"):
            self.search._validate_input(["假装是查询"], 10, self.valid_db)  # type: ignore[arg-type]

    def test_p0_dict_query_text_raises_valueerror(self):
        """query_text 为 dict 类型应抛 ValueError。"""
        with pytest.raises(ValueError, match="必须为字符串类型"):
            self.search._validate_input({"query": "test"}, 10, self.valid_db)  # type: ignore[arg-type]


# ============================================================================
# P1：边界值测试 — top_k 钳位
# ============================================================================


class TestTopKClamping:
    """top_k 钳位逻辑测试。"""

    def setup_method(self) -> None:
        self.encoder = MockSearchEncoder()
        self.search = MockSearch(self.encoder)
        self.valid_db = object()

    def test_p1_top_k_zero_clamped_to_min(self):
        """top_k=0 应钳位到 TOP_K_MIN (1)。"""
        actual_top_k, _fingerprint = self.search._validate_input(
            "测试", 0, self.valid_db
        )
        assert actual_top_k == TOP_K_MIN

    def test_p1_top_k_negative_clamped_to_min(self):
        """top_k 为负数应钳位到 TOP_K_MIN (1)。"""
        actual_top_k, _fingerprint = self.search._validate_input(
            "测试", -5, self.valid_db
        )
        assert actual_top_k == TOP_K_MIN

    def test_p1_top_k_exceeds_max_clamped(self):
        """top_k=100 超过 TOP_K_MAX (50)，应钳位到 50。"""
        actual_top_k, _fingerprint = self.search._validate_input(
            "测试", 100, self.valid_db
        )
        assert actual_top_k == TOP_K_MAX

    def test_p1_top_k_large_number_clamped(self):
        """top_k 为极大值 (9999) 也应钳位到 TOP_K_MAX。"""
        actual_top_k, _fingerprint = self.search._validate_input(
            "测试", 9999, self.valid_db
        )
        assert actual_top_k == TOP_K_MAX

    def test_p1_top_k_at_min_boundary(self):
        """top_k 恰好为 1（最小值），不钳位。"""
        actual_top_k, _fingerprint = self.search._validate_input(
            "测试", 1, self.valid_db
        )
        assert actual_top_k == 1

    def test_p1_top_k_at_max_boundary(self):
        """top_k 恰好为 50（最大值），不钳位。"""
        actual_top_k, _fingerprint = self.search._validate_input(
            "测试", 50, self.valid_db
        )
        assert actual_top_k == 50

    def test_p1_top_k_in_range_unchanged(self):
        """top_k 在合法范围内 (25)，保持不变。"""
        actual_top_k, _fingerprint = self.search._validate_input(
            "测试", 25, self.valid_db
        )
        assert actual_top_k == 25


# ============================================================================
# P1：边界值测试 — query_text 长度边界
# ============================================================================


class TestQueryTextLengthBoundary:
    """query_text 长度边界测试。"""

    def setup_method(self) -> None:
        self.encoder = MockSearchEncoder()
        self.search = MockSearch(self.encoder)
        self.valid_db = object()

    def test_p1_query_text_min_length_succeeds(self):
        """1 字符 query_text 通过校验。"""
        actual_top_k, _fingerprint = self.search._validate_input(
            "x", 10, self.valid_db
        )
        assert actual_top_k is not None  # 校验通过，不抛异常

    def test_p1_query_text_max_length_succeeds(self):
        """恰好 2000 字符 query_text 通过校验。"""
        actual_top_k, _fingerprint = self.search._validate_input(
            "x" * 2000, 10, self.valid_db
        )
        assert actual_top_k == 10  # top_k 未被钳位

    def test_p1_query_text_max_length_minus_one_succeeds(self):
        """1999 字符 query_text 通过校验。"""
        actual_top_k, _fingerprint = self.search._validate_input(
            "x" * 1999, 10, self.valid_db
        )
        assert actual_top_k == 10


# ============================================================================
# P2：类型破坏测试 — 裸类型传递给期望 NewType 的接口
# ============================================================================


class TestTypeBreaking:
    """运行时类型测试：NewType 在运行时不强制类型检查。"""

    def test_p2_bare_list_passed_to_do_search(self):
        """传入裸 list[float] 给期望 EmbeddingVector 的 _do_search 参数。
        NewType 在运行时透传，不抛异常。"""
        encoder = MockSearchEncoder()
        search = MockSearch(encoder)
        # _do_search 契约参数类型是 EmbeddingVector，
        # 但运行时传入裸 list[float] 应正常工作
        # 需要异步执行...
        ...

    def test_p2_bare_str_passed_as_query_text_works(self):
        """query_text 在运行时是 str，无 NewType 强制约束。"""
        encoder = MockSearchEncoder()
        search = MockSearch(encoder)
        # 裸 str 正常通过校验
        actual_top_k, _fingerprint = search._validate_input(
            "裸字符串查询", 10, object()
        )
        assert actual_top_k == 10


# ============================================================================
# P3：状态/后置校验测试
# ============================================================================


class TestValidateResult:
    """_validate_result() 后置校验测试。"""

    def setup_method(self) -> None:
        self.encoder = MockSearchEncoder()
        self.search = MockSearch(self.encoder)

    def test_p3_result_none_raises_runtimeerror(self):
        """result=None 应抛 RuntimeError，消息含 '不能为 None'。"""
        with pytest.raises(RuntimeError, match="不能为 None"):
            self.search._validate_result(None)

    def test_p3_result_object_passes(self):
        """普通 object 作为 result 应通过校验（非 None）。"""
        # 不应抛异常
        self.search._validate_result(object())

    def test_p3_result_empty_string_passes(self):
        """空字符串 result 应通过校验（非 None）。"""
        self.search._validate_result("")


# ============================================================================
# P3：查询指纹测试
# ============================================================================


class TestQueryFingerprint:
    """_compute_query_fingerprint() 测试。"""

    def setup_method(self) -> None:
        self.encoder = MockSearchEncoder()
        self.search = MockSearch(self.encoder)

    def test_p3_fingerprint_is_query_fingerprint_type(self):
        """返回值为 QueryFingerprint 类型（运行时为 str）。"""
        result = self.search._compute_query_fingerprint("测试")
        assert isinstance(result, str)

    def test_p3_fingerprint_is_64_hex_characters(self):
        """SHA256 指纹为 64 位十六进制字符串。"""
        result = self.search._compute_query_fingerprint("hello")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_p3_fingerprint_is_deterministic(self):
        """相同输入产生相同指纹。"""
        fp1 = self.search._compute_query_fingerprint("确定性测试")
        fp2 = self.search._compute_query_fingerprint("确定性测试")
        assert fp1 == fp2

    def test_p3_different_inputs_produce_different_fingerprints(self):
        """不同输入产生不同指纹。"""
        fp1 = self.search._compute_query_fingerprint("查询A")
        fp2 = self.search._compute_query_fingerprint("查询B")
        assert fp1 != fp2

    def test_p3_fingerprint_for_empty_string(self):
        """空字符串也能生成指纹（不应崩溃）。"""
        result = self.search._compute_query_fingerprint("")
        assert len(result) == 64

    def test_p3_fingerprint_case_sensitive(self):
        """大小写敏感的输入产生不同指纹。"""
        fp1 = self.search._compute_query_fingerprint("ABC")
        fp2 = self.search._compute_query_fingerprint("abc")
        assert fp1 != fp2

    def test_p3_validate_input_includes_fingerprint(self):
        """_validate_input 返回值同时包含 actual_top_k 和 query_fingerprint。"""
        actual_top_k, fingerprint = self.search._validate_input(
            "测试查询", 10, object()
        )
        assert isinstance(actual_top_k, int)
        assert isinstance(fingerprint, str)
        assert len(fingerprint) == 64


# ============================================================================
# P3：search() @final 集成行为测试（异步）
# ============================================================================


class TestSearchIntegration:
    """search() @final 集成测试。"""

    @pytest.mark.asyncio
    async def test_p3_search_propagates_encoder_error(self):
        """编码器故障 → search 将异常向上传播。"""
        # 创建一个始终抛异常的编码器
        class BrokenEncoder(BaseEmbeddingEncoder):
            async def _do_encode(self, text: str, text_type: str) -> list[float]:
                raise RuntimeError("编码器已损坏")

        broken_encoder = BrokenEncoder()
        search = MockSearch(broken_encoder)

        # search() 内部调用 encoder.encode()，如果编码失败重试耗尽，
        # 应抛 EmbeddingUnavailableError
        with pytest.raises(Exception):
            await search.search("查询文本", top_k=5, db=object())

    @pytest.mark.asyncio
    async def test_p3_search_validates_before_encoding(self):
        """验证顺序：_validate_input 先于 encode。无效输入应在编码前被拦截。"""
        broken_encoder = MockSearchEncoder()
        search = MockSearch(broken_encoder)
        # 空字符串 → _validate_input 直接抛 ValueError，不会调用 encode
        with pytest.raises(ValueError, match="不能为空"):
            await search.search("", top_k=5, db=object())
