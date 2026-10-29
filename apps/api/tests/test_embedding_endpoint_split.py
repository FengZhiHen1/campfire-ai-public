"""嵌入端点与对话端点的分离配置（2026-10-28）。

## 为什么需要这条判据

对话模型可以换成本机/自建的 OpenAI 兼容网关，而**嵌入不能跟着换**：嵌入模型与向量维度
是绑死的（`EMBEDDING_DIM` 是常量，换模型要整库重建）。而本机实测的那个网关只提供
`/chat/completions`，`/embeddings` 直接 404。

如果两者共用 `tokenhub_base_url`，那么「换对话端点」这一件事会静默打断检索——而在产品里
检索失败的表现是「没有资料」，那是最难被发现的一种故障形态（页面看起来一切正常）。

因此配置层要给一个**可选的**分家口：`EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` 留空时
回落原来的 TokenHub 一套（默认形态不变），显式配置时才分家。这三条用例钉的就是这个语义。
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from campfire.core.config import Settings


def _settings(**overrides: object) -> Settings:
    """构造一份**不受仓库根 `.env` 影响**的配置。

    `_env_file=None` 是 pydantic-settings 的官方开关，但它不在合成的 `__init__` 签名里，
    所以只能加 `type: ignore`（同 `test_health.py` 的既有做法）。不隔离的话，
    「默认值回落」这条判据会随宿主机 `.env` 变化：本机绿、CI 红，或者反过来。
    """
    # 两个 ignore 各管一件事：`call-arg` 是 `_env_file` 不在合成签名里，
    # `arg-type` 是 `**dict[str, object]` 交给 pydantic 在运行期收敛（同 `test_library_embedding._settings`）。
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg, arg-type]


def test_embedding_endpoint_falls_back_to_the_chat_endpoint() -> None:
    """留空 ⇒ 回落 `tokenhub_*`：默认部署形态必须一字不变（不引入第二套凭据）。

    构造时显式 `_env_file=None`：仓库根的 `.env` 会覆盖未传入的字段，不隔离的话
    「默认值」这条判据在本机看着绿、在 CI（无 `.env`）或换了 `.env` 之后变红——
    而它要验的恰恰是**默认值**本身。
    """
    settings = Settings(
        _env_file=None, tokenhub_base_url="https://example.test/v1", tokenhub_api_key=SecretStr("chat-key")
    )

    assert settings.resolved_embedding_base_url == "https://example.test/v1"
    assert settings.resolved_embedding_api_key is not None
    assert settings.resolved_embedding_api_key.get_secret_value() == "chat-key"


def test_embedding_endpoint_can_be_split_from_the_chat_endpoint() -> None:
    """显式配置 ⇒ 分家：对话走本地网关、嵌入仍走原厂。"""
    settings = Settings(
        _env_file=None,
        tokenhub_base_url="http://127.0.0.1:7863/v1",
        tokenhub_api_key=SecretStr("gateway-key"),
        embedding_base_url="https://tokenhub.example.test/v1",
        embedding_api_key=SecretStr("embedding-key"),
    )

    assert settings.resolved_embedding_base_url == "https://tokenhub.example.test/v1"
    assert settings.resolved_embedding_api_key is not None
    assert settings.resolved_embedding_api_key.get_secret_value() == "embedding-key"


def test_blank_embedding_base_url_is_treated_as_unset() -> None:
    """`.env` 里写成空串与根本没写等价：空串不是「指向空地址」，不许把它当成配置值用。"""
    settings = _settings(tokenhub_base_url="https://example.test/v1", embedding_base_url="   ")

    assert settings.resolved_embedding_base_url == "https://example.test/v1"


@pytest.mark.parametrize("consumer", ["library", "memory"])
def test_both_embedding_consumers_use_the_resolved_endpoint(consumer: str) -> None:
    """资料库摄取/查询与记忆侧两个消费者都必须用解析后的端点。

    只测配置属性是不够的：漏改其中一个消费者，就会出现「一半走原厂、一半走本地网关」，
    而那种不一致比全错更难查（检索命中率时高时低，看不出规律）。
    """
    settings = Settings(
        _env_file=None,
        tokenhub_base_url="http://127.0.0.1:7863/v1",
        tokenhub_api_key=SecretStr("gateway-key"),
        embedding_base_url="https://tokenhub.example.test/v1",
        embedding_api_key=SecretStr("embedding-key"),
    )

    if consumer == "library":
        from campfire.modules.library.embedding import build_embedding

        embedder = build_embedding(settings)
        assert "tokenhub.example.test" in str(getattr(embedder, "api_base", ""))
        return

    from campfire.modules.memory.graph import build_memory_embedder

    memory_embedder = build_memory_embedder(settings)
    assert "tokenhub.example.test" in str(memory_embedder.client.base_url)
