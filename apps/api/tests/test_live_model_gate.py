"""真实模型开关（marker `live_model`）的判据本身。

为什么单独立一个文件：这个开关决定「默认门禁会不会偷偷去调外部供应商」，而一条
**永远不失败**的闸门等于没有闸门。这里把三条分支各自钉死：

1. 未显式开启 → 带 marker 的用例被跳过（默认门禁不因「本机没 key」变红）；
2. 显式开启但没凭据 → 报错（不是跳过，也不是「跑 0 条却绿」）；
3. 显式开启但凭据是 `.env.example` 的占位符 → 报错（占位符会让请求真发出去拿 401，
   那是环境未就绪冒充代码缺陷）。

用例全部离线：只调 `conftest` 里的纯函数，不发任何请求。
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from campfire.core.config import Settings

from .conftest import _live_model_environment_problem, live_model_enabled


def _settings(**overrides: object) -> Settings:
    """不受宿主机 `.env` 影响的配置（三个可拆分端点一并钉成未配置）。"""
    base: dict[str, object] = {
        "tokenhub_api_key": None,
        "embedding_api_key": None,
        "memory_llm_api_key": None,
        "embedding_base_url": "",
        "memory_llm_base_url": "",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg, arg-type]  # `_env_file` 不在合成签名里；`**base` 由 pydantic 收敛


class _Config:
    """`pytest.Config` 的最小替身：本文件只关心 `--live-model` 这一项。"""

    def __init__(self, live_model: bool) -> None:
        self._live_model = live_model

    def getoption(self, name: str) -> bool:
        """只实现 `--live-model`；其它选项一律报错，避免替身悄悄兜底。"""
        assert name == "--live-model", f"替身未实现选项 {name}"
        return self._live_model


def test_live_model_is_off_by_default() -> None:
    """不加参数、不设环境变量时开关为关——默认门禁不跑真模型。"""
    assert live_model_enabled(_Config(live_model=False)) is False  # type: ignore[arg-type]  # 最小替身，只实现 getoption


def test_live_model_can_be_enabled_by_flag() -> None:
    """`--live-model` 即开启。"""
    assert live_model_enabled(_Config(live_model=True)) is True  # type: ignore[arg-type]  # 同上


def test_live_model_can_be_enabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`CAMPFIRE_LIVE_MODEL=1` 与参数等价（CI / 不便加参数的场景）。"""
    monkeypatch.setenv("CAMPFIRE_LIVE_MODEL", "1")

    assert live_model_enabled(_Config(live_model=False)) is True  # type: ignore[arg-type]  # 同上


def test_missing_credentials_is_reported_not_skipped() -> None:
    """缺凭据必须给出可操作的问题描述（显式开启时据此在收集期失败）。"""
    problem = _live_model_environment_problem(_settings())

    assert problem is not None
    assert "TOKENHUB_API_KEY" in problem
    assert "跳过" in problem, "消息要说明「不能靠跳过冒充通过」，否则读者会以为 skip 是允许的"


def test_placeholder_credentials_are_reported() -> None:
    """`.env.example` 的占位符也算环境未就绪——它会让请求真发出去拿 401。"""
    problem = _live_model_environment_problem(_settings(tokenhub_api_key=SecretStr("sk-xxxx-not-a-real-key")))

    assert problem is not None
    assert "占位符" in problem


def test_real_looking_credentials_pass_the_gate() -> None:
    """形状正常（非空、非占位符）的凭据通过这道闸门。

    这里**不验证凭据有效**：有效性只能由真跑一次模型来回答，那是 `live_model`
    用例本身的事。闸门只回答「环境看起来具备了吗」。
    """
    problem = _live_model_environment_problem(_settings(tokenhub_api_key=SecretStr("sk-live-looking-key-1234567890")))

    assert problem is None
