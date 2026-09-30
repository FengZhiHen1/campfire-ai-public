"""SSE 传输编码：基座事件 → 线上的三行帧。

职责：把 `agent.runtime` 的事件对象编成 `id` / `event` / `data` 三行帧，并给出
响应头与心跳常量。
边界：只做编码，不做缓冲、不判归属、不管续传游标（那些归 `runbus` 与 `routes`）。
参考：docs/技术设计/面/consult/HTTP与SSE契约.md 第 4.2、7 节。

三条落在本模块的纪律：

`event` 与 `data.type` 恒等。契约第 4.2 节把事件到 SSE 的映射定为恒等映射
（不重命名、不合并）：前端按 `event` 分派，`data` 就是该事件对象的 JSON。
因此本模块不含任何「事件名 → 别的事件名」的表——一旦有了这张表，它就会成为
第二份契约，而基座改名时两边会分叉。

`id` 是运行内单调递增的序号。它是续传的唯一依据（第 4.2 节），因此由缓冲写入方
（`runbus`）在追加时排定，而不是由本模块现算——编码方看不到「这是第几条」。

未知类型的载荷显式报错。事件联合是 `agent/runtime/events.py` 的判别联合，
面层不认得的类型只可能是版本漂移；静默 `str()` 成一段乱码会让前端拿到一个
既分派不了、也看不出问题的帧（CORE-07）。
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from campfire.agent.runtime import RunEvent

#: SSE 的媒体类型。契约第 4.2 节：`Accept: text/event-stream`。
SSE_MEDIA_TYPE = "text/event-stream"

#: 流式响应的三个头（契约 4.2 与编排器裁决 5）。
#:
#: `Cache-Control: no-cache` 必给：缺少它时中间代理可能缓存整段流（一条对话被
#: 回放给另一个请求）。`X-Accel-Buffering: no` 是为将来的 Nginx 预留——默认它会把
#: 上游的流缓冲到一定字节才转发，心跳就失去了「防代理超时」的作用。
#: `Content-Type` 显式写进头而不是只靠 `media_type`：Starlette 会给 `text/*`
#: 自动补 `; charset=utf-8`，而契约第 4.2 节把媒体类型定为 `text/event-stream`。
#: 显式给出时 Starlette 不再追加（它发现 content-type 已在头里就跳过）。
SSE_HEADERS: dict[str, str] = {
    "Content-Type": SSE_MEDIA_TYPE,
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

#: 心跳间隔（秒）。契约第 4.2 节定为 15 秒。
HEARTBEAT_INTERVAL_SECONDS = 15.0

#: 心跳帧原文。空注释行，不承载语义（第 4.2 节）。
HEARTBEAT_FRAME = ": ping\n\n"

#: 终态事件名。出现其一即本次运行结束，服务端关流（第 4.2 节）。
TERMINAL_EVENT_TYPES: frozenset[str] = frozenset({"run_finished", "run_failed"})

#: 续传起点 `Last-Event-ID` 里 `id` 的上界（CORE-11）。
#:
#: 一次运行的序号不可能超过「运行内产出的事件条数」，而运行时长上限 180 秒
#: （基座第 2 节）与单条事件的产出速率一起给了它一个远小于此的值。设成
#: 2**31-1 是为了让「明显是伪造的巨值」在解析处就被拒，而不是拿去做 Redis 的
#: 区间下标——一个 `Last-Event-ID: 99999999999999999999` 会让 LRANGE 的
#: 下标溢出成奇怪的窗口。
MAX_LAST_EVENT_ID = 2**31 - 1


# quality-floor: ignore bare-any 返回值是任意 JSON 结构，静态类型表达不出来（递归联合），消费方是 json.dumps
def to_jsonable(value: object) -> Any:
    """把事件载荷递归转成 `json.dumps` 能处理的形状。

    认得三类：数据类（基座事件的载荷全是冻结数据类）、容器（列表/元组/字典）、
    标量与时标（`datetime` / `date` / `UUID` / 枚举转字符串或取值）。

    Raises:
        TypeError: 遇到认不出的类型。不静默 `str()` 它——那会让一个本该
            「前端拿到结构化载荷」的字段变成一段无法处理的文本。
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(entry) for entry in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(entry) for key, entry in value.items()}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    raise TypeError(f"事件载荷里出现了认不出的类型：{type(value).__name__}")


def event_name(event: RunEvent) -> str:
    """取事件名。判别字段就是 `type`，也是线上的 `event` 行。"""
    return event.type


# quality-floor: ignore bare-any 理由同 to_jsonable：键名由基座事件的字段决定，此处不重复声明一遍结构
def event_payload(event: RunEvent) -> dict[str, Any]:
    """把事件对象转成 `data` 行的 JSON 对象（含 `type` 字段）。

    `type` 留在载荷里是契约要求（第 4.2 节：`data` 即该事件对象的 JSON），
    且它派生的 `event` 行必须与它相等——两个值来自同一个字段，结构上不可能分叉。

    Raises:
        TypeError: 事件对象的顶层不是数据类（形状漂移）。
    """
    payload = to_jsonable(event)
    if not isinstance(payload, dict):
        raise TypeError(f"事件载荷必须是对象：{type(event).__name__}")
    return payload


def encode_frame(seq: int, event: RunEvent) -> str:
    """编一条 SSE 帧：`id` / `event` / `data` 三行 + 一个空行。

    `json.dumps` 用 `ensure_ascii=False`：中文正文若被转义成 `\\uXXXX`，
    前端虽仍能解析，但线格式断言与抓包排障都会变得难读；两端都是 UTF-8。
    分隔符收窄（`separators`）只是为了少几个字节，不承载语义。
    """
    name = event_name(event)
    data = json.dumps(event_payload(event), ensure_ascii=False, separators=(",", ":"))
    return f"id: {seq}\nevent: {name}\ndata: {data}\n\n"


def decode_frame(raw: str) -> tuple[int, str]:
    """从缓冲里取出的一条帧原文中读回 `(seq, event_name)`。

    缓冲里存的是帧原文（而不是单独的 seq 字段），续传路径需要按 seq 跳过已发送的
    部分，因此要从原文里把序号读回来。这条解析与 :func:`encode_frame` 是同一份
    格式的两端，放在同一个模块里——分开两处时，改了一处忘另一处会得到
    「续传从错误的序号开始」这种只在断线后出现的缺陷。

    Raises:
        ValueError: 原文不是本模块写出的三行帧。
    """
    lines = raw.split("\n")
    if len(lines) < 3 or not lines[0].startswith("id: "):
        raise ValueError("事件缓冲里出现了解析不出的帧")
    try:
        seq = int(lines[0][4:])
    except ValueError as exc:
        raise ValueError("事件帧的 id 行不是整数") from exc
    if not lines[1].startswith("event: "):
        raise ValueError("事件帧的第二行不是 event 行")
    return seq, lines[1][7:]
