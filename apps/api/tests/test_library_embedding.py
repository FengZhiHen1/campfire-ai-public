"""嵌入适配的单元测试（不调用真实嵌入服务）。

锁定三件事：

1. **自定义模型名能装进框架适配器**——`model=` 会被枚举校验拒绝，必须用
   `model_name=`；这是接入 TokenHub 的前提（2026-09-29 实测）。
2. **缺凭据显式失败**，不静默降级。
3. **单条超限在送入之前就被拦下**——静默截断会制造错误的检索依据。
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
    return Settings(**base)  # type: ignore[arg-type]


def test_build_embedding_uses_custom_model_name() -> None:
    """TokenHub 的自定义模型名能装进框架适配器（走 model_name= 分支）。"""
    embedding = build_embedding(_settings())

    assert embedding.model_name == "kinfra-text-embedding-4b"


def test_build_embedding_batch_size_matches_interface_recommendation() -> None:
    """批量大小按接口建议值设定（≤128 条/请求）。"""
    embedding = build_embedding(_settings())

    assert embedding.embed_batch_size == RECOMMENDED_BATCH_SIZE


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
