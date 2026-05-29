"""py-rag 嵌入编码行为契约 — ABC 模板方法。

模块: py_rag.embedding_contract
职责: 定义文本嵌入编码器的契约骨架。调用者走 @final 公共入口，
      实现者只能覆写 _do_ 前缀的钩子。
数据来源:
  - DashScope API: MUST — 阿里云 text-embedding-v4 嵌入服务
  - AppSettings (py_config): MUST — DASHSCOPE_API_KEY、EMBEDDING_MODEL 配置
边界:
  - 依赖: py_config（环境配置）、py_infra.exceptions（EmbeddingUnavailableError）
  - 被依赖: embedding.py（DashScope 实现）、retrieval.py（编码查询向量）
  - 被依赖: indexing/worker.py（索引入库时编码文档文本）
禁止行为:
  - 禁止在契约中硬编码 API 端点 URL
  - 禁止在 _do_encode 钩子中自行实现重试逻辑（重试由 @final encode 统一处理）
  - 禁止绕过 _validate_text 前置校验直接调用 _do_encode
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Literal, final

from py_rag.types import EMBEDDING_DIMENSION, EmbeddingVector

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_MAX_RETRY_COUNT: int = 2  # 共 3 次尝试（1 主 + 2 重试）
_RETRY_INTERVALS: list[float] = [1.0, 3.0]
_MAX_CONSECUTIVE_FAILURES: int = 5
_CIRCUIT_BREAKER_SLEEP: float = 30.0


class BaseEmbeddingEncoder(ABC):
    """文本嵌入编码器契约。

    实现者只能覆写 _do_ 前缀的钩子。
    调用者只能使用 @final 标记的公共方法。
    """

    def __init__(self) -> None:
        self._failure_count: int = 0

    # === @final 公共方法：唯一外部入口 ===

    @final
    async def encode(
        self,
        text: str,
        text_type: Literal["document", "query"] = "document",
    ) -> EmbeddingVector:
        """将文本编码为嵌入向量。

        前置校验 → 带重试的钩子调用 → 后置校验 → 熔断器检查。
        此方法不可覆写（@final）。重试逻辑在此统一实现。

        前置:
          - text 为非空字符串（至少包含一个非空白字符）
          - text_type 为 "document" 或 "query"
        后置:
          - 返回长度 = EMBEDDING_DIMENSION（1024）的向量
          - self._failure_count 在成功时归零
        输入约束:
          - text: 1-8192 字符（DashScope text-embedding-v4 限制）
          - text_type: "document"（索引入库）| "query"（检索查询）
        输出约束:
          - EmbeddingVector: 1024 维 float 列表
        异常:
          - EmbeddingUnavailableError: 所有重试耗尽后仍失败
          - ValueError: text 为空或仅空白字符
        """
        self._validate_text(text)

        last_error: Exception | None = None

        for attempt in range(_MAX_RETRY_COUNT + 1):
            try:
                embedding_list = await self._do_encode(text, text_type)
                self._validate_embedding(embedding_list)
                self._failure_count = 0
                return EmbeddingVector(embedding_list)

            except Exception as exc:
                last_error = exc
                self._failure_count += 1

                if attempt < _MAX_RETRY_COUNT:
                    wait_time = _RETRY_INTERVALS[attempt]
                    await asyncio.sleep(wait_time)

        # 熔断器检查
        if self._failure_count >= _MAX_CONSECUTIVE_FAILURES:
            await asyncio.sleep(_CIRCUIT_BREAKER_SLEEP)
            self._failure_count = 0

        from py_infra.exceptions import EmbeddingUnavailableError

        raise EmbeddingUnavailableError(
            message="向量编码服务暂时不可用，请稍后重试",
            retry_count=_MAX_RETRY_COUNT + 1,
            last_error=str(last_error),
        )

    def reset_failure_count(self) -> None:
        """重置嵌入服务失败计数器（用于测试和手动恢复）。

        非模板方法——工具函数，不需要 _do_ 钩子。
        """
        self._failure_count = 0

    # === @abstractmethod 钩子：实现者必填 ===

    @abstractmethod
    async def _do_encode(
        self,
        text: str,
        text_type: Literal["document", "query"],
    ) -> list[float]:
        """执行单次嵌入 API 调用。

        实现者在此填写 HTTP 请求 + 响应解析逻辑。
        不需要关心重试和校验——@final encode 已处理。

        输入约束:
          - text 已通过 _validate_text 校验
          - text_type 已由调用方明确指定
        输出约束:
          - 返回原始 list[float]（由 encode 包装为 EmbeddingVector）
        异常:
          - httpx.HTTPStatusError: API 返回非 2xx
          - httpx.TimeoutException: 请求超时
          - KeyError: 响应缺少 embedding 字段
          - ValueError: embedding 维度不符合预期
        """
        ...

    # === 校验器方法：模板提供基线校验 ===

    def _validate_text(self, text: str) -> None:
        """基线前置校验：文本非空且不超过最大长度。

        子类可通过 super() 叠加业务级校验（如敏感词过滤）。
        """
        if not text or not text.strip():
            raise ValueError("编码文本不能为空")
        if len(text) > 8192:
            raise ValueError(f"编码文本超过最大长度限制（8192），实际 {len(text)}")

    def _validate_embedding(self, embedding: list[float]) -> None:
        """基线后置校验：向量维度正确。

        子类可通过 super() 叠加业务级校验（如向量范数检查）。
        """
        if len(embedding) != EMBEDDING_DIMENSION:
            raise RuntimeError(
                f"嵌入向量维度异常：期望 {EMBEDDING_DIMENSION}，实际 {len(embedding)}"
            )
