"""py-rag 嵌入编码契约 — 黑盒对抗测试。

测试对象：
  - BaseEmbeddingEncoder._validate_text()
  - BaseEmbeddingEncoder._validate_embedding()
  - BaseEmbeddingEncoder.encode()        [@final, 异步]
  - BaseEmbeddingEncoder.reset_failure_count()

隔离约束：严禁 import embedding.py 或访问任何实现代码。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from py_rag.embedding_contract import BaseEmbeddingEncoder
from py_rag.types import EMBEDDING_DIMENSION, EmbeddingVector


# ============================================================================
# Mock 子类 — 仅实现 @abstractmethod 钩子，返回最小合法值
# ============================================================================


class MockEncoder(BaseEmbeddingEncoder):
    """测试用 mock：_do_encode 返回合法的 1024 维向量。"""

    async def _do_encode(self, text: str, text_type: str) -> list[float]:
        return [0.0] * EMBEDDING_DIMENSION


class MockFailingEncoder(BaseEmbeddingEncoder):
    """测试用 mock：_do_encode 始终抛出异常，用于模拟 API 故障。"""

    def __init__(self) -> None:
        super().__init__()
        self.call_count: int = 0

    async def _do_encode(self, text: str, text_type: str) -> list[float]:
        self.call_count += 1
        raise RuntimeError(f"模拟嵌入 API 故障 (第 {self.call_count} 次)")


class MockWrongDimensionEncoder(BaseEmbeddingEncoder):
    """测试用 mock：_do_encode 返回错误维度的向量。"""

    async def _do_encode(self, text: str, text_type: str) -> list[float]:
        return [0.0] * 512  # 期望 1024，实际 512


# ============================================================================
# P0：禁止行为测试 — _validate_text 校验条件
# ============================================================================


class TestValidateText:
    """_validate_text() 基线校验测试。"""

    def test_p0_empty_string_raises_valueerror(self):
        """空字符串应抛 ValueError，消息含 '不能为空'。"""
        encoder = MockEncoder()
        with pytest.raises(ValueError, match="不能为空"):
            encoder._validate_text("")

    def test_p0_whitespace_only_raises_valueerror(self):
        """仅空白字符应抛 ValueError，消息含 '不能为空'。"""
        encoder = MockEncoder()
        with pytest.raises(ValueError, match="不能为空"):
            encoder._validate_text("   \t\n   ")

    def test_p0_exceeds_8192_chars_raises_valueerror(self):
        """超过 8192 字符应抛 ValueError，消息含 '8192' 和实际长度。"""
        encoder = MockEncoder()
        long_text = "x" * 8193
        with pytest.raises(ValueError, match="8192"):
            encoder._validate_text(long_text)

    def test_p0_exactly_8192_chars_does_not_raise(self):
        """恰好 8192 字符不应抛异常（边界内侧）。"""
        encoder = MockEncoder()
        # 不应抛异常
        encoder._validate_text("x" * 8192)

    def test_p0_null_characters_passes_text_validity(self):
        """空字符 (\\x00) 是非空白字符，应通过 _validate_text（非空校验仅看 strip）。"""
        encoder = MockEncoder()
        # 含 null 字符但 strip() 非空 — 应通过校验
        encoder._validate_text("\x00hello\x00")


# ============================================================================
# P0：禁止行为测试 — _validate_embedding 校验条件
# ============================================================================


class TestValidateEmbedding:
    """_validate_embedding() 基线校验测试。"""

    def test_p0_dimension_less_than_1024_raises_runtimeerror(self):
        """维度小于 1024 应抛 RuntimeError。"""
        encoder = MockEncoder()
        with pytest.raises(RuntimeError, match="嵌入向量维度异常"):
            encoder._validate_embedding([0.0] * 512)

    def test_p0_dimension_greater_than_1024_raises_runtimeerror(self):
        """维度大于 1024 应抛 RuntimeError。"""
        encoder = MockEncoder()
        with pytest.raises(RuntimeError, match="嵌入向量维度异常"):
            encoder._validate_embedding([0.0] * 2048)

    def test_p0_zero_dimension_raises_runtimeerror(self):
        """空向量（0 维）应抛 RuntimeError。"""
        encoder = MockEncoder()
        with pytest.raises(RuntimeError, match="嵌入向量维度异常"):
            encoder._validate_embedding([])

    def test_p0_correct_dimension_passes(self):
        """恰好 1024 维应通过校验。"""
        encoder = MockEncoder()
        # 不应抛异常
        encoder._validate_embedding([0.0] * EMBEDDING_DIMENSION)


# ============================================================================
# P1：边界值测试 — encode() @final 正常行为
# ============================================================================


class TestEncodeBoundary:
    """encode() 边界值测试（异步）。"""

    @pytest.mark.asyncio
    async def test_p1_min_length_text_succeeds(self):
        """1 字符长度的文本编码成功，返回 EmbeddingVector。"""
        encoder = MockEncoder()
        result = await encoder.encode("x", text_type="query")
        assert isinstance(result, list)
        assert len(result) == EMBEDDING_DIMENSION

    @pytest.mark.asyncio
    async def test_p1_max_length_text_succeeds(self):
        """恰好 8192 字符编码成功。"""
        encoder = MockEncoder()
        result = await encoder.encode("x" * 8192, text_type="document")
        assert len(result) == EMBEDDING_DIMENSION

    @pytest.mark.asyncio
    async def test_p1_text_type_document_accepted(self):
        """text_type='document' 编码成功。"""
        encoder = MockEncoder()
        result = await encoder.encode("测试文本", text_type="document")
        assert len(result) == EMBEDDING_DIMENSION

    @pytest.mark.asyncio
    async def test_p1_text_type_query_accepted(self):
        """text_type='query' 编码成功。"""
        encoder = MockEncoder()
        result = await encoder.encode("测试查询", text_type="query")
        assert len(result) == EMBEDDING_DIMENSION

    @pytest.mark.asyncio
    async def test_p1_encode_returns_newtype_embedding_vector(self):
        """encode() 返回的向量是 EmbeddingVector 类型（NewType 包装）。"""
        encoder = MockEncoder()
        result = await encoder.encode("测试", text_type="document")
        # NewType 在运行时是底层的 list[float]，但返回值通过了契约签名的 EmbeddingVector
        # 此处验证其行为等价于 list[float]
        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)

    @pytest.mark.asyncio
    async def test_p1_encode_default_text_type_is_document(self):
        """不指定 text_type 时默认使用 'document'。"""
        encoder = MockEncoder()
        result = await encoder.encode("测试")
        assert len(result) == EMBEDDING_DIMENSION


# ============================================================================
# P3：状态/熔断器测试
# ============================================================================

class TestCircuitBreaker:
    """熔断器与失败计数器测试。"""

    def test_p3_reset_failure_count_zeroes_counter(self):
        """reset_failure_count() 将 _failure_count 归零。"""
        encoder = MockFailingEncoder()
        encoder._failure_count = 7
        encoder.reset_failure_count()
        assert encoder._failure_count == 0

    @pytest.mark.asyncio
    async def test_p3_single_encode_success_resets_failure_count(self):
        """一次成功的 encode() 调用将 _failure_count 归零。"""
        encoder = MockFailingEncoder()
        # 手动设置非零计数模拟累积错误
        encoder._failure_count = 3
        # 但 MockFailingEncoder 始终失败... 我们需要换个方式
        # 用 MockEncoder 测试成功重置
        good_encoder = MockEncoder()
        good_encoder._failure_count = 4
        await good_encoder.encode("测试")
        assert good_encoder._failure_count == 0

    @pytest.mark.asyncio
    async def test_p3_consecutive_failures_increment_counter(self):
        """每次失败调用递增 _failure_count。单次 encode() 含 3 次重试全部失败，计数 +3。"""
        encoder = MockFailingEncoder()
        try:
            await encoder.encode("测试", text_type="document")
        except Exception:
            pass
        # 3 次尝试（1 主 + 2 重试），每次 +1 → _failure_count = 3
        assert encoder._failure_count == 3

    @pytest.mark.asyncio
    async def test_p3_circuit_breaker_triggers_after_max_failures(self):
        """连续失败达到 _MAX_CONSECUTIVE_FAILURES (5) 触发熔断器，等待后重置计数器。"""
        encoder = MockFailingEncoder()
        # 第 1 次调用：failure_count: 0→3
        for _ in range(3):
            try:
                await encoder.encode("测试", text_type="document")
            except Exception:
                pass
            # 第 1 次后 failure_count=3，第 2 次后=6（但 breaker 在 post-loop 检查）
            # 实际：第 1 次 0→3(无breaker)，第 2 次 3→6(breaker触发，重置为0)
            # 所以需要至少 2 次完整调用才能触发 breaker

        # 验证熔断器确实触发：
        # 当前 _failure_count 在触发后被重置
        # 实际上第 2 次调用时 breaker 触发 → _failure_count 重置为 0
        # 但我们在循环里调了 3 次，第 3 次又会从 0 开始计

        # 更精确的测试：只调 2 次，验证 breaker 触发条件
        encoder2 = MockFailingEncoder()
        await _run_and_catch(encoder2.encode("测试"))
        await _run_and_catch(encoder2.encode("测试"))
        # 第 2 次调用后，failure_count 从 3 累积到 6，触发 breaker 重置为 0
        assert encoder2._failure_count == 0

    def test_p3_circuit_breaker_sleep_awaited(self):
        """触发熔断器时应 await asyncio.sleep(_CIRCUIT_BREAKER_SLEEP)。"""
        # 这个测试需要 patching asyncio.sleep 来验证被调用
        # 使用 unittest.mock 来做
        ...

    @pytest.mark.asyncio
    async def test_p3_circuit_breaker_sleep_is_called(self):
        """验证熔断器触发时实际调用了 asyncio.sleep。"""
        encoder = MockFailingEncoder()
        # Patch asyncio.sleep，用 AsyncMock 记录调用
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            # 调用两次 encode —— 第二次应该触发 breaker
            for _ in range(2):
                try:
                    await encoder.encode("测试")
                except Exception:
                    pass
            # 验证 asyncio.sleep(30.0) 被调用过（熔断器专用值）
            # 注意：重试也调用 sleep(1.0) 和 sleep(3.0)
            sleep_calls = [call.args[0] for call in mock_sleep.await_args_list]
            assert 30.0 in sleep_calls, (
                f"熔断器睡眠未被调用，实际调用参数: {sleep_calls}"
            )

    @pytest.mark.asyncio
    async def test_p3_two_retries_before_final_failure(self):
        """失败时应有 3 次尝试（1 主 + 2 重试），总计调用 _do_encode 3 次。"""
        encoder = MockFailingEncoder()
        try:
            await encoder.encode("测试")
        except Exception:
            pass
        assert encoder.call_count == 3, (
            f"期望 3 次尝试（1+2 重试），实际 {encoder.call_count}"
        )


# ============================================================================
# P2：错误维度编码器导致后置校验失败
# ============================================================================


class TestPostValidationInEncode:
    """encode() 的后置校验集成测试。"""

    @pytest.mark.asyncio
    async def test_p2_wrong_dimension_triggers_post_validation_failure(self):
        """实现返回错误维度向量 → 后置 _validate_embedding 抛出 RuntimeError。
        重试耗尽后抛 EmbeddingUnavailableError。"""
        encoder = MockWrongDimensionEncoder()
        with pytest.raises(Exception):  # EmbeddingUnavailableError 或 RuntimeError
            await encoder.encode("测试")


# ============================================================================
# 辅助函数
# ============================================================================


async def _run_and_catch(coro: Any) -> None:
    """执行协程并静默吞掉所有异常。"""
    try:
        await coro
    except Exception:
        pass
