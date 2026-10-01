"""嵌入适配的单元测试（不调用真实嵌入服务）。

锁定四件事：

1. **自定义模型名能装进框架适配器**——`model=` 会被枚举校验拒绝，必须用
   `model_name=`；这是接入 TokenHub 的前提（2026-09-29 实测）。
2. **缺凭据显式失败**，不静默降级。
3. **单条超限在送入之前就被拦下**——静默截断会制造错误的检索依据。
4. **送供应商的每次请求不超过建议批量**——案例摄取自己不分批，这条约束因此
   只在 `build_embedding` 落实（D-84）。
"""

from __future__ import annotations

import pytest

from campfire.core.config import Settings
from campfire.modules.library.embedding import (
    EMBEDDING_DIM,
    MAX_TEXT_CHARS,
    RECOMMENDED_BATCH_SIZE,
    EmbeddingConfigurationError,
    assert_text_within_limit,
    build_embedding,
)


def _settings(**overrides: object) -> Settings:
    """构造测试用配置；显式给凭据，避免依赖宿主机 .env。"""
    base: dict[str, object] = {
        "tokenhub_api_key": "test-key",  # noqa: S106 —— 测试占位符，非真实凭据
        "tokenhub_base_url": "https://tokenhub.example/v1",
        "embedding_model_name": "kinfra-text-embedding-4b",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]  # 夹具以 object 组合再交给 pydantic 收敛校验，静态类型看不出这层收敛


def test_build_embedding_uses_custom_model_name() -> None:
    """TokenHub 的自定义模型名能装进框架适配器（走 model_name= 分支）。"""
    embedding = build_embedding(_settings())

    assert embedding.model_name == "kinfra-text-embedding-4b"


def test_build_embedding_batch_size_matches_interface_recommendation() -> None:
    """批量大小按接口建议值设定（单请求 ≤128 条，RAG 策略第 10 节）。

    第一条断言写死字面值：只与常量互比是循环论证——常量被一起改大就无人察觉，
    而 128 是接口（供应商）侧的建议值，调大它须先有新的接口依据并同步设计文档。
    """
    embedding = build_embedding(_settings())

    assert RECOMMENDED_BATCH_SIZE == 128, "接口建议值被改大：请先确认供应商侧不再有 ≤128 条的建议"
    assert embedding.embed_batch_size == RECOMMENDED_BATCH_SIZE


@pytest.mark.asyncio
async def test_provider_requests_are_split_at_recommended_batch_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """送入供应商的每次请求都不超过 `RECOMMENDED_BATCH_SIZE`，且切片不丢文本（D-84）。

    为什么钉住框架行为：案例摄取把全部卡片与叙事块一次交给 `embed_texts`（自己
    不分批），「单请求建议 ≤128 条」这条约束因此完全落在 `build_embedding` 的
    `embed_batch_size=RECOMMENDED_BATCH_SIZE` 上——框架在 `aget_text_embedding_batch`
    里按它切片，每片一次供应商请求。若有人删掉那个参数、或升级框架后切片行为消失，
    本用例会失败，而不是等到某个大案例包被供应商拒绝、整包回滚时才发现。

    判别性（消融实测）：删掉 `build_embedding` 里的 `embed_batch_size=RECOMMENDED_BATCH_SIZE`
    后，框架回落到自己的默认值 10，请求分片变为 27 个 10 条，本用例失败。
    """
    embedder = build_embedding(_settings())
    batches: list[int] = []

    async def spy(_self: object, texts: list[str]) -> list[list[float]]:
        batches.append(len(texts))
        # 只断言切片形状，不建 2560 维数组（本用例不碰向量内容）。
        return [[0.0] for _ in texts]

    monkeypatch.setattr(type(embedder), "_aget_text_embeddings", spy)

    total = RECOMMENDED_BATCH_SIZE * 2 + 7
    vectors = await embedder.aget_text_embedding_batch([f"文本 {i}" for i in range(total)])

    assert batches == [RECOMMENDED_BATCH_SIZE, RECOMMENDED_BATCH_SIZE, 7], (
        f"框架未按 embed_batch_size 切片，供应商请求分片为 {batches}"
    )
    assert len(vectors) == total, "切片不得丢文本——条数错位会让向量与文本对不上"


def test_missing_credentials_fail_loudly() -> None:
    """缺凭据时显式报错，而不是构造出一个必然失败的嵌入器。"""
    with pytest.raises(EmbeddingConfigurationError):
        build_embedding(_settings(tokenhub_api_key=None))


def test_text_within_limit_passes() -> None:
    """恰好等于硬限的文本可以通过（边界包含）。"""
    assert_text_within_limit("字" * MAX_TEXT_CHARS)


def test_text_over_limit_is_rejected_before_calling_provider() -> None:
    """超限文本在送出之前就被拒绝，且错误信息带上实际长度。"""
    with pytest.raises(ValueError, match=str(MAX_TEXT_CHARS + 1)):
        assert_text_within_limit("字" * (MAX_TEXT_CHARS + 1))


def test_embedding_dim_is_fixed_constant() -> None:
    """维度是常量（2560），不是配置项——防止配错维度混库。"""
    assert EMBEDDING_DIM == 2560


def test_embedding_dim_has_a_single_source_of_truth() -> None:
    """维度只在一处定义：`core/config`，其余位置都是转出同一个对象。

    这是防漂移的**真实**闸门——本项目已因「同一事实两处定义」修过一次
    （search_knowledge 的合并规则）。2026-09-29 记忆侧落地时该常量从
    `modules/library` 移到 `core/config`：记忆侧（Graphiti 嵌入器）必须用同一维度，
    而 `modules/*` 之间不得互相 import（项目结构设计第 7 节），留在 library
    会逼出「越白名单导入」或「第二处定义」二选一。若有人日后另写一个数字，
    本用例会失败，而不是等到「维度配错、检索静默失准」才发现。
    """
    from campfire.modules.library import models

    assert models.EMBEDDING_DIM is EMBEDDING_DIM, (
        "models.EMBEDDING_DIM 与 core/config.EMBEDDING_DIM 不是同一个对象——维度出现了第二处定义"
    )
