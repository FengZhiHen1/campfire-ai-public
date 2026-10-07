"""从真实会话里抽出「流式输出」所需的文本(助手正文 + 思考段),追加到 fixture。

S5 要演的是「逐 token 输出」——流的必须是真实文本,不是编的。
来源:177f965b(有档案)的助手正文消息。
"""
import asyncio
import io
import json
from pathlib import Path

import asyncpg

DSN = "postgresql://campfire:changeme@127.0.0.1:5432/campfire"
OUT = Path("marketing/promo-shotcraft/src/fixtures/stream.generated.ts")
SID_ARCHIVE = "177f965b83ee4a13bb81186899b5df17"
SID_NO_ARCHIVE = "b897534e95b74aa99fdf23fe535248d7"


def parse(d):
    if isinstance(d, str):
        try:
            return json.loads(d)
        except Exception:
            return {"raw": d}
    return d


async def extract(conn, sid: str) -> dict:
    rows = await conn.fetch(
        "SELECT message_data FROM agent_messages WHERE session_id=$1 ORDER BY created_at", sid
    )
    texts: list[str] = []
    reasoning: list[str] = []
    for r in rows:
        m = parse(r["message_data"])
        if not isinstance(m, dict):
            continue
        # 助手正文:content 是 [{type:'output_text'|..., text:...}, ...]
        c = m.get("content")
        if isinstance(c, list):
            for blk in c:
                if isinstance(blk, dict) and blk.get("text"):
                    t = str(blk["text"])
                    if t.strip():
                        texts.append(t)
        # 思考段:summary 里的 text
        s = m.get("summary")
        if isinstance(s, list):
            for blk in s:
                if isinstance(blk, dict) and blk.get("text"):
                    t = str(blk["text"])
                    if t.strip():
                        reasoning.append(t)
    return {"assistantTexts": texts, "reasoningTexts": reasoning}


async def main() -> None:
    conn = await asyncpg.connect(DSN)
    archive = await extract(conn, SID_ARCHIVE)
    noarch = await extract(conn, SID_NO_ARCHIVE)
    await conn.close()

    payload = {"archive": archive, "noArchive": noarch}
    ts = (
        "// ⚠️ 自动生成,请勿手改 —— 由 .tmp/export-stream.py 从本地数据库导出。\n"
        "// S5 逐 token 流式演出用的真实文本(助手正文 + 思考段)。\n\n"
        "export const STREAM_TEXT = " + json.dumps(payload, ensure_ascii=False, indent=2) + " as const;\n"
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(ts, encoding="utf-8")

    rep = []
    for k, v in payload.items():
        rep.append(f"[{k}] 正文 {len(v['assistantTexts'])} 段 | 思考 {len(v['reasoningTexts'])} 段")
        for i, t in enumerate(v["assistantTexts"][:3]):
            rep.append(f"   正文[{i}] len={len(t)}: {t[:90]}")
        for i, t in enumerate(v["reasoningTexts"][:2]):
            rep.append(f"   思考[{i}] len={len(t)}: {t[:90]}")
    Path(".tmp/verify-stream.txt").write_text("\n".join(rep), encoding="utf-8")
    print(f"已写入 {OUT}")
    print("\n".join(rep))


asyncio.run(main())
