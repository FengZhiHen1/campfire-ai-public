"""咨询面传输层的纯单元用例：SSE 帧、回答渲染、请求形状、续传头解析。

不连数据库、不连 Redis：这一层的行为（三行制、恒等映射、跳过可判定、422 的判据）
与外部依赖无关，用纯函数用例把判据钉死，集成用例才只需要覆盖「接起来之后还对不对」。

    uv run pytest apps/api/tests/test_consult_transport.py
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from campfire.agent.context import CitationRecord
from campfire.agent.runtime import (
    RunFailedEvent,
    RunFinishedEvent,
    RunStartedEvent,
    RunUsage,
    TextDeltaEvent,
)
from campfire.surfaces.consult.answers import (
    ANSWER_SEPARATOR,
    ANSWERS_HEADER,
    SKIPPED_MARK,
    AnswerItem,
    SendMessageRequest,
    render_answers,
    skipped_answer_ids,
)
from campfire.surfaces.consult.routes import parse_last_event_id
from campfire.surfaces.consult.runbus import (
    MAX_FRAME_CHARS,
    RUN_NOT_RESUMABLE,
    SESSION_BUSY,
    RunMeta,
    events_key,
    idempotency_key,
    meta_key,
    mutex_key,
)
from campfire.surfaces.consult.sse import (
    MAX_LAST_EVENT_ID,
    SSE_HEADERS,
    SSE_MEDIA_TYPE,
    decode_frame,
    encode_frame,
    event_name,
    event_payload,
    to_jsonable,
)

_RUN_ID = "run-0123456789abcdef"


def _started() -> RunStartedEvent:
    return RunStartedEvent(
        run_id=_RUN_ID,
        session_id="s-1",
        surface="consult",
        model="test-model",
        activated_skills=("daily-consulting",),
        injection_sources=("profile",),
        appended_messages=2,
    )


# --- SSE 帧 ----------------------------------------------------------------


def test_frame_is_three_lines_plus_blank_line() -> None:
    """三行制：`id` / `event` / `data` 各一行，帧以一个空行结束（契约 4.2）。"""
    frame = encode_frame(17, TextDeltaEvent(delta="你好"))
    assert frame == 'id: 17\nevent: text_delta\ndata: {"delta":"你好","type":"text_delta"}\n\n'
    assert frame.endswith("\n\n")


def test_event_name_equals_data_type() -> None:
    """`event` 与 `data.type` 恒等：两者取自同一字段，结构上不可能分叉。"""
    for event in (
        _started(),
        TextDeltaEvent(delta="x"),
        RunFinishedEvent(reason="completed", citations=(), usage=RunUsage(), elapsed_seconds=0.1),
    ):
        frame = encode_frame(1, event)
        _seq, name = decode_frame(frame)
        assert name == event_name(event)
        assert event_payload(event)["type"] == name


def test_russian_and_newlines_are_not_escaped() -> None:
    """中文与换行按原样进 `data`：转义成 \\uXXXX 会让线格式与抓包排障都难读。"""
    frame = encode_frame(3, TextDeltaEvent(delta="第一行\n第二行"))
    assert "第一行\\n第二行" in frame


def test_frame_round_trip() -> None:
    """编码与解码是同一份格式的两端，往返必须回到同一个序号与事件名。"""
    seq, name = decode_frame(encode_frame(42, _started()))
    assert (seq, name) == (42, "run_started")


@pytest.mark.parametrize("raw", ["", "id: 1\n", "seq: 1\nevent: x\ndata: {}\n", "id: x\nevent: y\ndata: {}\n"])
def test_decode_rejects_frames_it_did_not_write(raw: str) -> None:
    """认不出的原文显式报错——静默跳过会让续传从错误的序号开始。"""
    with pytest.raises(ValueError):
        decode_frame(raw)


def test_truncated_frame_is_rejected_instead_of_passing_as_half_a_json_frame() -> None:
    """超长帧被切片后必须解析失败：半截 JSON 一旦解析成功就会被原样送给客户端。

    判别性用例（`append_event` 的截断不动时会红）。两种切法都要盖住：

    - 切点落在 `data` 行中间——JSON 少了收尾大括号，解析必然失败；
    - 帧长恰好是上界 +1（切片只切掉最后一个换行），`data` 行本身仍然完整——
      这种切法只有「帧必须以空行收尾」这条校验才拦得住。
    """
    oversized = encode_frame(7, TextDeltaEvent(delta="x" * (2 * MAX_FRAME_CHARS)))
    assert len(oversized) > MAX_FRAME_CHARS
    with pytest.raises(ValueError):
        decode_frame(oversized[:MAX_FRAME_CHARS])

    overhead = len(encode_frame(7, TextDeltaEvent(delta="")))
    edge = encode_frame(7, TextDeltaEvent(delta="x" * (MAX_FRAME_CHARS + 1 - overhead)))
    assert len(edge) == MAX_FRAME_CHARS + 1
    with pytest.raises(ValueError):
        decode_frame(edge[:MAX_FRAME_CHARS])


def test_a_frame_at_the_bound_still_decodes_byte_for_byte() -> None:
    """正控：只是「大」而没超界的帧照常解析，字节与编码器输出逐字一致。

    这条是为「把大帧一律拒掉」的实现准备的：那种实现能让上一条用例通过，却会让恰好
    等于上界（`append_event` 不截断）的帧也送不出去。它同时钉住正常帧路径没被改动。
    """
    overhead = len(encode_frame(7, TextDeltaEvent(delta="")))
    frame = encode_frame(7, TextDeltaEvent(delta="x" * (MAX_FRAME_CHARS - overhead)))
    assert len(frame) == MAX_FRAME_CHARS
    assert decode_frame(frame) == (7, "text_delta")
    assert frame.startswith('id: 7\nevent: text_delta\ndata: {"delta":"xxx')
    assert frame.endswith('","type":"text_delta"}\n\n')


def test_unknown_payload_type_is_an_explicit_error() -> None:
    """认不出的载荷类型抛错，而不是 `str()` 成一段前端处理不了的文本（CORE-07）。"""
    with pytest.raises(TypeError):
        to_jsonable({"weird": {1, 2}})


def test_datetime_becomes_isoformat() -> None:
    """引用记录里的时间转 ISO 8601：`json.dumps` 遇到 `datetime` 会直接抛错。"""
    record = CitationRecord(
        citation_id="c-1",
        run_id=_RUN_ID,
        source="knowledge",
        reference="item-1",
        summary=None,
        recorded_at=datetime(2026, 10, 2, 3, 4, 5, tzinfo=UTC),
    )
    payload = to_jsonable(record)
    assert payload["recorded_at"] == "2026-10-02T03:04:05+00:00"
    assert payload["summary"] is None


def test_failed_event_serialises_with_code() -> None:
    """失败事件带上失败码（前端按码给文案，契约第 8 节）。"""
    payload = event_payload(
        RunFailedEvent(code="session_write_failed", detail="x", citations=(), usage=RunUsage(), elapsed_seconds=0.0)
    )
    assert payload["code"] == "session_write_failed"
    assert payload["type"] == "run_failed"


def test_stream_headers_follow_the_contract() -> None:
    """三个头逐字（编排器裁决 5）：媒体类型不含 charset 后缀。"""
    assert SSE_HEADERS["Content-Type"] == SSE_MEDIA_TYPE == "text/event-stream"
    assert SSE_HEADERS["Cache-Control"] == "no-cache"
    assert SSE_HEADERS["X-Accel-Buffering"] == "no"


def test_heartbeat_interval_is_fifteen_seconds() -> None:
    """心跳间隔 15 秒（契约 4.2）；集成用例把它改小才跑得动，数值本身在这里钉住。"""
    from campfire.surfaces.consult.sse import HEARTBEAT_FRAME, HEARTBEAT_INTERVAL_SECONDS

    assert HEARTBEAT_INTERVAL_SECONDS == 15.0
    assert HEARTBEAT_FRAME == ": ping\n\n"


# --- 一组回答 --------------------------------------------------------------


def test_answers_render_keeps_one_line_per_question() -> None:
    """渲染格式：一句表头 + 每题一行（编排器裁决 4）。"""
    text = render_answers(
        [
            AnswerItem(id="q1", value="会有"),
            AnswerItem(id="q2", skipped=True),
        ]
    )
    assert text == "\n".join([ANSWERS_HEADER, f"q1{ANSWER_SEPARATOR}会有", f"q2{ANSWER_SEPARATOR}{SKIPPED_MARK}"])


def test_skipped_is_a_server_side_fact() -> None:
    """跳过可判定：读回被跳过的题标识（契约 4.1 的硬要求）。"""
    text = render_answers([AnswerItem(id="q1", value="a"), AnswerItem(id="q2", skipped=True)])
    assert skipped_answer_ids(text) == ["q2"]


def test_free_text_containing_the_skip_mark_is_not_skip() -> None:
    """自由文本里出现跳过字样不算跳过——判据是整段作答逐字等于标记。"""
    text = render_answers([AnswerItem(id="q1", value=f"我选 {SKIPPED_MARK} 这个")])
    assert skipped_answer_ids(text) == []


# --- 请求形状 --------------------------------------------------------------


def test_plain_message_is_accepted() -> None:
    """普通消息形态（契约 4.1 第一式）。"""
    payload = SendMessageRequest(content="今天怎么样", client_message_id="c-1")
    assert payload.content == "今天怎么样"
    assert payload.answers is None


def test_two_shapes_are_mutually_exclusive_and_required() -> None:
    """两种形态二选一，服务端按字段判别（契约 4.1）。"""
    with pytest.raises(ValidationError):
        SendMessageRequest(content="x", answers=[AnswerItem(id="q", value="v")], client_message_id="c")
    with pytest.raises(ValidationError):
        SendMessageRequest(client_message_id="c")
    with pytest.raises(ValidationError):
        SendMessageRequest(content="   ", client_message_id="c")


def test_empty_answers_array_is_rejected() -> None:
    """空数组是一次「零道题的提交」，没有任何可落内容（对抗用例）。"""
    with pytest.raises(ValidationError):
        SendMessageRequest(answers=[], client_message_id="c")


def test_duplicate_answer_ids_are_rejected() -> None:
    """重复的题标识会让跳过的对应关系不再唯一。"""
    with pytest.raises(ValidationError):
        SendMessageRequest(
            answers=[AnswerItem(id="q", value="a"), AnswerItem(id="q", skipped=True)],
            client_message_id="c",
        )


def test_answer_needs_exactly_one_form() -> None:
    """`value` 与 `skipped` 互斥且必居其一；缺 id 拒绝。"""
    with pytest.raises(ValidationError):
        AnswerItem(id="q", value="a", skipped=True)
    with pytest.raises(ValidationError):
        AnswerItem(id="q")
    with pytest.raises(ValidationError):
        AnswerItem(id="  ", value="a")


def test_unknown_fields_are_rejected() -> None:
    """多给的字段是 422：静默忽略会让每次重发都变成一次新运行。"""
    with pytest.raises(ValidationError):
        SendMessageRequest.model_validate({"content": "x", "client_message_id": "c", "clientMessageId": "d"})


# --- 续传头 ----------------------------------------------------------------


def test_last_event_id_defaults_to_zero() -> None:
    """没有头就是从头开始（契约 4.2）。"""
    assert parse_last_event_id(None) == 0
    assert parse_last_event_id("") == 0
    assert parse_last_event_id("7") == 7


@pytest.mark.parametrize("raw", ["abc", "-1", "1.5", str(MAX_LAST_EVENT_ID + 1)])
def test_invalid_last_event_id_is_422(raw: str) -> None:
    """不合法的续传凭据是 422（对抗用例：超界值）。"""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        parse_last_event_id(raw)
    assert caught.value.status_code == 422


# --- 运行键与元数据 --------------------------------------------------------


def test_key_shapes_are_pinned() -> None:
    """三个键的形状（编排器裁决 1/2/3）：它们是缓冲、互斥与幂等的唯一定位方式。"""
    assert events_key("r1") == "run:r1:events"
    assert meta_key("r1") == "run:r1:meta"
    assert mutex_key("s1") == "session:s1:run"
    assert idempotency_key("s1", "c1") == "idem:s1:c1"
    assert (SESSION_BUSY, RUN_NOT_RESUMABLE) == ("session_busy", "run_not_resumable")


def test_run_meta_round_trip_and_rejection() -> None:
    """元数据往返一致；认不出的内容按「不存在」处理（fail-closed）。"""
    meta = RunMeta(run_id="r1", session_id="s1", account_id="a1", status="running")
    assert RunMeta.parse(meta.as_json()) == meta
    assert RunMeta.parse(None) is None
    assert RunMeta.parse("{}") is None
    assert RunMeta.parse("not json") is None
    assert RunMeta.parse('{"run_id":"r","session_id":"s","account_id":"a","status":"weird"}') is None
