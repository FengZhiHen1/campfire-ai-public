"""真实模型开关只识别 marker，参数名称不能让普通测试静默跳过。"""

from __future__ import annotations

import pytest

from . import conftest


@pytest.mark.parametrize("marked", [False, True])
def test_collection_gate_distinguishes_a_marker_from_a_parameter_name(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, marked: bool
) -> None:
    item = pytest.Function.from_parent(request.node.parent, name="synthetic[live_model]", callobj=lambda: None)
    assert "live_model" not in item.keywords
    item.keywords["live_model"] = True
    if marked:
        item.add_marker(pytest.mark.live_model)
    monkeypatch.setattr(conftest, "live_model_enabled", lambda config: False)

    conftest.pytest_collection_modifyitems(request.config, [item])

    assert (item.get_closest_marker("skip") is not None) is marked
