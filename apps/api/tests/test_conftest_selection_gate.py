"""真实模型门禁与「本轮到底选了什么」的一致性（纯函数，不连网、不调模型）。

`test_live_model_gate.py` 只回答「环境是否具备」；这里补另一半：本轮会不会真的跑
真模型用例。两者脱节时，一个导出过 `CAMPFIRE_LIVE_MODEL=1` 的 shell 会让带
`-m "not live_model"` 的确定性门禁在收集期失败。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from . import conftest as conftest_module
from .conftest import enforce_live_model_environment


class _Config:
    """`pytest.Config` 的最小替身：只实现 `--live-model` 与 `-m`（markexpr）。"""

    def __init__(self, *, live_model: bool = False, markexpr: str = "") -> None:
        self._live_model = live_model
        self.option = SimpleNamespace(markexpr=markexpr)

    def getoption(self, name: str) -> bool:
        """只实现 `--live-model`；其它选项一律报错，避免替身悄悄兜底。"""
        assert name == "--live-model", f"替身未实现选项 {name}"
        return self._live_model


def _config(**kwargs: Any) -> _Config:  # noqa: ANN401 —— 仅转发到上面的关键字参数
    """构造替身配置（保持类型注解可读）。"""
    return _Config(**kwargs)


def test_gate_is_silent_when_live_model_is_not_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """没开启时即便环境什么都没有也不失败：默认门禁不因「本机没 key」变红。"""
    monkeypatch.setattr(conftest_module, "_live_model_environment_problem", lambda: "缺凭据")

    enforce_live_model_environment(_config(live_model=False))  # type: ignore[arg-type]


def test_gate_fails_when_enabled_and_environment_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式开启且没有排除 marker 时，缺环境必须失败（退出码非 0、消息点名缺什么）。"""
    monkeypatch.setattr(
        conftest_module,
        "_live_model_environment_problem",
        lambda: "未配置 TOKENHUB_API_KEY",
    )

    with pytest.raises(pytest.UsageError, match="TOKENHUB_API_KEY"):
        enforce_live_model_environment(_config(live_model=True))  # type: ignore[arg-type]


def test_gate_defers_to_an_explicit_mark_exclusion(monkeypatch: pytest.MonkeyPatch) -> None:
    """`-m "not live_model"` 时不再校验环境：这一轮本来就不跑真模型用例。

    这正是 `checks.py quick/full` 与 CI 的形态。修好它之前，一个导出过
    `CAMPFIRE_LIVE_MODEL=1` 的 shell 会让确定性门禁在收集期就失败。
    """
    monkeypatch.setattr(
        conftest_module,
        "_live_model_environment_problem",
        lambda: "未配置 TOKENHUB_API_KEY",
    )

    enforce_live_model_environment(_config(live_model=True, markexpr="not live_model"))  # type: ignore[arg-type]


@pytest.mark.parametrize("markexpr", [" not live_model ", "(not live_model)"])
def test_gate_accepts_only_the_exact_exclusion_with_optional_parens(
    markexpr: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """允许首尾空白与外层括号，其余不改写。"""
    monkeypatch.setattr(conftest_module, "_live_model_environment_problem", lambda: "缺凭据")

    enforce_live_model_environment(_config(live_model=True, markexpr=markexpr))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "markexpr",
    [
        pytest.param("integration", id="unrelated-expression"),
        pytest.param("not slow", id="not-with-another-marker"),
        # 只选真模型用例（正向选择，不是排除）：仍然需要环境。id 刻意不叫 `live_model`
        # ——pytest 把参数 id 也塞进 `item.keywords`，同名会让本例被跳过钩子静默 skip。
        pytest.param("live_model", id="only-live-model"),
        pytest.param("not live_model or live_model", id="exclusion-then-selection"),
        pytest.param("other and not live_model or live_model", id="mixed-precedence"),
        pytest.param("not not live_model", id="double-negation"),
    ],
)
def test_gate_still_enforces_for_expressions_it_does_not_recognise(
    markexpr: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """只认「显式排除 `live_model`」这一种写法；其它表达式照常校验（不猜语义）。"""
    monkeypatch.setattr(
        conftest_module,
        "_live_model_environment_problem",
        lambda: "未配置 TOKENHUB_API_KEY",
    )

    with pytest.raises(pytest.UsageError):
        enforce_live_model_environment(_config(live_model=True, markexpr=markexpr))  # type: ignore[arg-type]


def test_gate_passes_a_ready_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """正向对照：环境齐全时开启真模型不报错（否则上面几条会被「永远失败」蒙住）。"""
    monkeypatch.setattr(conftest_module, "_live_model_environment_problem", lambda: None)

    enforce_live_model_environment(_config(live_model=True))  # type: ignore[arg-type]
