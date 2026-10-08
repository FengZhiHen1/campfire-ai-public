"""P1/P2：⑤a 载荷（annotations, type="citation"）能否落库读回保真，且对模型输入零扰动。

P1: SQLAlchemySession(sqlite in-memory) 落库 → get_items 读回，六个字段逐字保真；
P2: Converter.items_to_messages 对带 annotations 的历史与不带的历史**逐字节相同**。
"""
from __future__ import annotations

import asyncio
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy.ext.asyncio import create_async_engine

from agents.extensions.memory.sqlalchemy_session import SQLAlchemySession
from agents.models.chatcmpl_converter import Converter

PAYLOAD = {
    "type": "citation",
    "citation_id": "c0ffee",
    "run_id": "r-1",
    "source": "knowledge",
    "reference": "knowledge:item-1",
    "recorded_at": "2026-10-07T12:00:00+00:00",
    "summary": "规范",
}

BARE = {
    "type": "message",
    "id": "__fake_id__",
    "role": "assistant",
    "status": "completed",
    "content": [{"type": "output_text", "text": "建议尽早评估。", "annotations": [], "logprobs": []}],
}

ANNOTATED = json.loads(json.dumps(BARE))
ANNOTATED["content"][0]["annotations"] = [PAYLOAD]


async def main() -> int:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    s = SQLAlchemySession("probe-5a-t38", engine=engine, create_tables=True)
    await s.add_items([BARE, ANNOTATED])
    items = await s.get_items()
    print("P1 read back items:", len(items))
    got = items[1]["content"][0]["annotations"]  # type: ignore[index]
    same = json.dumps(got, ensure_ascii=False, sort_keys=True) == json.dumps([PAYLOAD], ensure_ascii=False, sort_keys=True)
    print("P1 annotations 逐字保真:", same)
    print("   raw:", json.dumps(got, ensure_ascii=False))

    hist = [{"role": "user", "content": "三岁还不太会说话"},
            {"type": "message", "role": "user", "content": "三岁还不太会说话"},
            items[0], items[1]]
    a = Converter.items_to_messages(list(hist), model="deepseek-v4.1-flash")
    hist_bare = [*hist[:3], BARE]
    b = Converter.items_to_messages(list(hist_bare), model="deepseek-v4.1-flash")
    sa = json.dumps(a, ensure_ascii=False, sort_keys=True, default=str)
    sb = json.dumps(b, ensure_ascii=False, sort_keys=True, default=str)
    print("P2 转换结果与基线逐字节相同:", sa == sb)
    if sa != sb:
        print("   A:", sa[:600])
        print("   B:", sb[:600])
    print("P2 转换结果里是否出现 citation_id / reference:", "citation_id" in sa, "knowledge:item-1" in sa)
    await engine.dispose()
    return 0 if (same and sa == sb) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
