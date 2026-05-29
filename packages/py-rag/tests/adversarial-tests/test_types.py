"""py-rag 语义类型 — 黑盒对抗测试。

测试对象：
  - EmbeddingVector: NewType 包装 list[float]
  - EmbeddingModelName: NewType 包装 str
  - CaseIdStr: NewType 包装 str
  - TraceIdStr: NewType 包装 str
  - ChunkIdStr: NewType 包装 str
  - QueryFingerprint: NewType 包装 str
  - SimilarityScore: NewType 包装 float
  - CompositeScore: NewType 包装 float
  - TOP_K_MIN, TOP_K_MAX, EMBEDDING_DIMENSION: 常量

隔离约束：严禁访问任何实现代码。
注意：NewType 是纯静态类型构造，运行时无任何开销或校验。
      这些测试验证运行时的实际行为（与底层类型一致）。
"""

from __future__ import annotations

import hashlib
import uuid as uuid_lib

import pytest

from py_rag.types import (
    EMBEDDING_DIMENSION,
    TOP_K_MAX,
    TOP_K_MIN,
    CaseIdStr,
    ChunkIdStr,
    CompositeScore,
    EmbeddingModelName,
    EmbeddingVector,
    QueryFingerprint,
    SimilarityScore,
    TraceIdStr,
)


# ============================================================================
# P1：EmbeddingVector 运行时行为
# ============================================================================


class TestEmbeddingVector:
    """EmbeddingVector = NewType("EmbeddingVector", list[float])"""

    def test_p1_is_list_at_runtime(self):
        """EmbeddingVector 在运行时是 list[float] 的子类型。"""
        vec = EmbeddingVector([0.1, 0.2, 0.3])
        assert isinstance(vec, list)

    def test_p1_supports_len(self):
        """支持 len() 操作。"""
        vec = EmbeddingVector([0.0] * EMBEDDING_DIMENSION)
        assert len(vec) == EMBEDDING_DIMENSION

    def test_p1_supports_indexing(self):
        """支持下标访问。"""
        vec = EmbeddingVector([1.0, 2.0, 3.0])
        assert vec[0] == 1.0
        assert vec[-1] == 3.0

    def test_p1_supports_iteration(self):
        """支持 for 迭代。"""
        vec = EmbeddingVector([0.1, 0.2, 0.3])
        items = [x for x in vec]
        assert items == [0.1, 0.2, 0.3]

    def test_p1_accepts_valid_dimension(self):
        """接受恰好 1024 维的 float 列表构造。"""
        vec = EmbeddingVector([float(i) for i in range(EMBEDDING_DIMENSION)])
        assert len(vec) == EMBEDDING_DIMENSION

    def test_p1_newtype_no_runtime_enforcement(self):
        """NewType 在运行时是透传的——任何 list[float] 都可被当作 EmbeddingVector。"""
        # 运行时 EmbeddingVector 就是 list[float]，无额外校验
        raw_list = [0.0] * 512
        # 这不会抛异常——NewType 是静态类型系统概念
        vec = EmbeddingVector(raw_list)
        assert len(vec) == 512  # 运行时仅做透传


# ============================================================================
# P1：CaseIdStr 运行时行为
# ============================================================================


class TestCaseIdStr:
    """CaseIdStr = NewType("CaseIdStr", str)"""

    def test_p1_is_str_at_runtime(self):
        """CaseIdStr 在运行时是 str 的子类型。"""
        cid = CaseIdStr("550e8400-e29b-41d4-a716-446655440000")
        assert isinstance(cid, str)

    def test_p1_supports_string_operations(self):
        """支持 str 的常见操作。"""
        cid = CaseIdStr("550e8400-e29b-41d4-a716-446655440000")
        assert cid.startswith("550e84")
        assert len(cid) == 36
        assert "e29b" in cid

    def test_p1_accepts_valid_uuid_v4_format(self):
        """接受标准 UUID v4 格式字符串。"""
        cid = CaseIdStr(str(uuid_lib.uuid4()))
        # uuid.UUID 解析不抛异常
        uuid_lib.UUID(cid)
        assert True

    def test_p1_accepts_any_string_at_runtime(self):
        """运行时接受任意字符串（NewType 无校验）。"""
        cid = CaseIdStr("not-a-uuid-really")
        assert cid == "not-a-uuid-really"


# ============================================================================
# P1：TraceIdStr 运行时行为
# ============================================================================


class TestTraceIdStr:
    """TraceIdStr = NewType("TraceIdStr", str)"""

    def test_p1_is_str_at_runtime(self):
        """TraceIdStr 在运行时是 str。"""
        tid = TraceIdStr("aabbccdd11223344aabbccdd11223344")
        assert isinstance(tid, str)

    def test_p1_supports_hex_operations(self):
        """可以用 int(..., 16) 验证全十六进制。"""
        tid = TraceIdStr("aabbccdd11223344aabbccdd11223344")
        int(tid, 16)  # 不抛异常说明全是 hex 字符
        assert True

    def test_p1_length_32_chars_is_valid(self):
        """长度 32 字符是一个 secrets.token_hex(16) 的标准输出。"""
        tid = TraceIdStr("0123456789abcdef0123456789abcdef")
        assert len(tid) == 32


# ============================================================================
# P1：ChunkIdStr 运行时行为
# ============================================================================


class TestChunkIdStr:
    """ChunkIdStr = NewType("ChunkIdStr", str)"""

    def test_p1_is_str_at_runtime(self):
        """ChunkIdStr 在运行时是 str。"""
        chunk_id = ChunkIdStr(str(uuid_lib.uuid4()))
        assert isinstance(chunk_id, str)


# ============================================================================
# P1：EmbeddingModelName 运行时行为
# ============================================================================


class TestEmbeddingModelName:
    """EmbeddingModelName = NewType("EmbeddingModelName", str)"""

    def test_p1_is_str_at_runtime(self):
        """EmbeddingModelName 在运行时是 str。"""
        name = EmbeddingModelName("text-embedding-v4")
        assert isinstance(name, str)

    def test_p1_accepts_model_identifier(self):
        """接受模型名标识符字符串。"""
        name = EmbeddingModelName("text-embedding-v4")
        assert "embedding" in name


# ============================================================================
# P1：QueryFingerprint 运行时行为
# ============================================================================


class TestQueryFingerprint:
    """QueryFingerprint = NewType("QueryFingerprint", str)"""

    def test_p1_is_str_at_runtime(self):
        """QueryFingerprint 在运行时是 str。"""
        fingerprint = hashlib.sha256("test".encode()).hexdigest()
        qf = QueryFingerprint(fingerprint)
        assert isinstance(qf, str)

    def test_p1_from_sha256_has_64_chars(self):
        """SHA256 输出 64 位十六进制字符串。"""
        fingerprint = hashlib.sha256("hello".encode()).hexdigest()
        qf = QueryFingerprint(fingerprint)
        assert len(qf) == 64

    def test_p1_all_hex_characters(self):
        """SHA256 指纹仅含十六进制字符。"""
        fingerprint = hashlib.sha256("data".encode()).hexdigest()
        qf = QueryFingerprint(fingerprint)
        assert all(c in "0123456789abcdef" for c in qf)


# ============================================================================
# P1：SimilarityScore / CompositeScore 运行时行为
# ============================================================================


class TestScoreTypes:
    """SimilarityScore 和 CompositeScore 运行时行为。"""

    def test_p1_similarity_score_is_float(self):
        """SimilarityScore 在运行时是 float。"""
        score = SimilarityScore(0.8523)
        assert isinstance(score, float)

    def test_p1_composite_score_is_float(self):
        """CompositeScore 在运行时是 float。"""
        score = CompositeScore(0.7200)
        assert isinstance(score, float)

    def test_p1_scores_support_arithmetic(self):
        """分数类型支持浮点运算。"""
        s1 = SimilarityScore(0.5)
        s2 = SimilarityScore(0.3)
        assert s1 + s2 == 0.8
        assert s1 > s2

    def test_p1_composite_score_range_0_to_1(self):
        """CompositeScore 数学范围是 [0.0, 1.0]（运行时无强制）。"""
        score_min = CompositeScore(0.0)
        score_max = CompositeScore(1.0)
        assert 0.0 <= score_min <= score_max <= 1.0


# ============================================================================
# P1：常量值验证
# ============================================================================


class TestConstants:
    """验证模块级常量的值。"""

    def test_p1_top_k_min_is_one(self):
        """TOP_K_MIN 应为 1。"""
        assert TOP_K_MIN == 1

    def test_p1_top_k_max_is_fifty(self):
        """TOP_K_MAX 应为 50。"""
        assert TOP_K_MAX == 50

    def test_p1_embedding_dimension_is_1024(self):
        """EMBEDDING_DIMENSION 应为 1024（text-embedding-v4）。"""
        assert EMBEDDING_DIMENSION == 1024

    def test_p1_top_k_min_less_than_max(self):
        """TOP_K_MIN < TOP_K_MAX。"""
        assert TOP_K_MIN < TOP_K_MAX
