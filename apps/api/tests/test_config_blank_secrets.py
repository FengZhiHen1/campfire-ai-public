"""空白密钥即未配置：`core/config` 把「空值」归一成 `None` 的判据。

缺陷形状（2026-10-29 实测）：`.env` 或环境里写 `TOKENHUB_API_KEY=`（空值）时，
`pydantic-settings` 给出的是 `SecretStr("")`——它**不是** `None`。于是所有
`if key is None` 的分支都判成「已配置」，空串被当凭据送进
`AsyncOpenAI(api_key="")`，构造期抛 `OpenAIError: Missing credentials`。
后果是「未配置」被报成**崩溃**：健康检查本该说 not_configured，实际却是 500。

这里的断言分三组：

1. 五个含密钥字段（`SECRET_FIELD_NAMES`）的空白值都归一成 `None`，显式非空值逐字保留；
2. 归一后回落语义自动正确（嵌入/记忆侧的独立凭据留空 ⇒ 回落到对话那套凭据）；
3. 缺凭据在**产品侧**被如实报告（模型端点探针报 not_configured，而不是崩溃）。

最后一条另有一个机械闸门：新增密钥字段必须登记进 `SECRET_FIELD_NAMES`，否则本组的
第一组断言不会覆盖它——那条闸门自己会红。
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from campfire.agent.model import check_model_endpoint
from campfire.core.config import SECRET_FIELD_NAMES, Settings


def _settings(**overrides: object) -> Settings:
    """不受宿主机 `.env` 影响的配置：所有密钥先置 `None`，再按用例覆盖。"""
    base: dict[str, object] = {name: None for name in SECRET_FIELD_NAMES}
    base["tokenhub_base_url"] = "https://tokenhub.example/v1"
    base["tokenhub_api_key"] = SecretStr("chat-key")
    base.update({"embedding_base_url": "", "memory_llm_base_url": ""})
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg, arg-type]  # `_env_file` 不在合成签名里；`**base` 由 pydantic 收敨


def _secret_fields_declared_as_secret() -> set[str]:
    """从 `Settings` 的字段声明里找出所有 `SecretStr` 字段（机械发现，不靠人工清单）。"""
    from typing import get_args

    found: set[str] = set()
    for name, field in Settings.model_fields.items():
        if field.annotation is SecretStr or SecretStr in get_args(field.annotation):
            found.add(name)
    return found


def test_every_secret_field_is_registered_for_normalisation() -> None:
    """新增 `SecretStr` 字段必须登记进 `SECRET_FIELD_NAMES`，否则空白归一漏掉它。

    这是一条会真的失败的闸门：漏登记时下面那组参数化用例根本不会覆盖新字段，
    而「覆盖不到」在报告上看起来和「全部通过」一样。
    """
    assert _secret_fields_declared_as_secret() == set(SECRET_FIELD_NAMES)


@pytest.mark.parametrize("field_name", SECRET_FIELD_NAMES)
@pytest.mark.parametrize("blank", ["", "   ", SecretStr(""), SecretStr(" \t ")])
def test_blank_secret_is_normalised_to_none(field_name: str, blank: object) -> None:
    """空串与纯空白（含 `SecretStr` 包装）一律归一成 `None`。"""
    settings = _settings(**{field_name: blank})

    assert getattr(settings, field_name) is None, (
        f"{field_name} 收到空白值后仍是 {getattr(settings, field_name)!r}——"
        "它会被下游当成有效凭据（实测形状：AsyncOpenAI(api_key='') 抛 Missing credentials）"
    )


@pytest.mark.parametrize("field_name", SECRET_FIELD_NAMES)
@pytest.mark.parametrize("kept", [SecretStr("keep-me-intact"), "keep-me-intact"])
def test_explicit_non_blank_secret_is_kept_verbatim(field_name: str, kept: object) -> None:
    """显式非空值原样保留：归一不是替使用者「清洗」凭据。"""
    settings = _settings(**{field_name: kept})

    value = getattr(settings, field_name)
    assert isinstance(value, SecretStr)
    assert value.get_secret_value() == "keep-me-intact"


@pytest.mark.parametrize("field_name", SECRET_FIELD_NAMES)
def test_blank_secret_from_environment_is_also_normalised(field_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量（而不只是构造参数）里的空白值同样归一——`.env` 与 shell 是同一条路。"""
    for name in SECRET_FIELD_NAMES:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv(field_name.upper(), "  ")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]  # `_env_file` 不在合成签名里

    assert getattr(settings, field_name) is None


def test_blank_split_keys_fall_back_to_the_chat_key() -> None:
    """嵌入/记忆侧凭据留空 ⇒ 回落到对话那套（默认部署形态不变）。"""
    settings = _settings(embedding_api_key="", memory_llm_api_key="   ")

    assert settings.resolved_embedding_api_key is settings.tokenhub_api_key
    assert settings.resolved_memory_llm_api_key is settings.tokenhub_api_key


def test_explicit_split_keys_do_not_fall_back() -> None:
    """显式给了独立凭据就不回落：回落只在「没配」时发生。"""
    settings = _settings(embedding_api_key=SecretStr("embedding-key"), memory_llm_api_key=SecretStr("memory-key"))

    embedding_key = settings.resolved_embedding_api_key
    memory_key = settings.resolved_memory_llm_api_key
    assert embedding_key is not None and embedding_key.get_secret_value() == "embedding-key"
    assert memory_key is not None and memory_key.get_secret_value() == "memory-key"


@pytest.mark.asyncio
async def test_blank_key_is_reported_as_not_configured_by_the_model_probe() -> None:
    """缺凭据在**产品侧**被如实报告：探针报 not_configured，而不是构造期崩。

    这是修复前最误导的形态：「`.env` 里写了一行空 key」看着像已配置，实际把空串当
    凭据用。归一之后，探针走的是它本来就写好的「未配置」分支。
    """
    report = await check_model_endpoint(_settings(tokenhub_api_key=""))

    assert report.configured is False
    assert report.reachable is False
    assert "TOKENHUB_API_KEY" in report.detail
