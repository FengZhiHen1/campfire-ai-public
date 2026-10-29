"""真实模型门禁与「本轮到底选了什么」的一致性。

为什么单独立一个文件：`conftest.py` 里的 `_live_model_environment_problem` 已有用例
（`test_live_model_gate.py`），但它只回答「环境是否具备」。缺的是另一半：
**这一轮到底会不会跑真模型用例**。两者脱节时的形态很具体——

`scripts/checks.py` 的 `quick`/`full` 与 CI 都带 `-m "not live_model"`，而门禁此前
只看「开关是否被显式打开」（`--live-model` 或 `CAMPFIRE_LIVE_MODEL=1`）。于是 shell
里恰好导出过 `CAMPFIRE_LIVE_MODEL=1` 的开发机，跑确定性门禁会在**收集期**因缺凭据
直接失败：那不是代码缺陷，是门禁把「要求跑真模型」误读成「这一轮要跑真模型」，
而命令行已经明确说了不跑。

这里把三条分支钉死，且**不连网、不调模型**：只调 conftest 里的纯函数。
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


@pytest.mark.parametrize(
    "markexpr",
    [
        pytest.param("integration", id="unrelated-expression"),
        pytest.param("not slow", id="not-with-another-marker"),
        # 只选真模型用例（正向选择，不是排除）：仍然需要环境。id 刻意不叫 `live_model`
        # ——pytest 会把参数 id 也塞进 `item.keywords`，而 conftest 的跳过钩子按关键字
        # 判断 marker，id 同名会让这条用例被静默 skip（本文件实测踩到）。
        pytest.param("live_model", id="only-live-model"),
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
