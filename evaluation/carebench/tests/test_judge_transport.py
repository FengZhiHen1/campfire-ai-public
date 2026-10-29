"""评分协议在兼容端点省略system消息时仍可见，严格JSON校验继续保留。"""

from __future__ import annotations

import pytest

from evaluation.carebench.ai_review import (
    build_adjudication_request,
    build_request,
    default_adjudicator,
    default_judges,
)


@pytest.mark.parametrize("pass_no", [1, 2, 3])
def test_judge_request_repeats_only_own_frozen_protocol_in_user_message(pass_no: int) -> None:
    judges = default_judges("test-model")
    judge = judges[pass_no - 1] if pass_no < 3 else default_adjudicator("test-model")
    payload = {"blind_id": "case-X1", "turns": [{"output": "原始回答，不改写"}]}
    if pass_no == 3:
        request = build_adjudication_request(judge, payload, {"first": "score-one"}, {"second": "score-two"})
    else:
        request = build_request(judge, payload)
    assert [item["role"] for item in request["messages"]] == ["system", "user"]
    assert request["messages"][0]["content"] == judge.prompt_text
    user = request["messages"][1]["content"]
    assert judge.prompt_text in user
    assert "原始回答，不改写" in user
    assert request["response_format"] == {"type": "json_object"}
    for peer in (*judges, default_adjudicator("test-model")):
        if peer.pass_no != pass_no:
            assert peer.prompt_text not in user
    if pass_no < 3:
        assert "score-one" not in user and "score-two" not in user
