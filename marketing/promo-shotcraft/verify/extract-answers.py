"""提取两个会话的采集作答(从 agent_messages 里含 possible_pain 的行)。"""
import asyncio
import io
import json
import re
from pathlib import Path

import asyncpg

DSN = "postgresql://campfire:changeme@127.0.0.1:5432/campfire"
SESSIONS = {
    "177f965b (有档案,本片 S5/S6 来源)": "177f965b83ee4a13bb81186899b5df17",
    "b897534e (无档案)": "b897534e95b74aa99fdf23fe535248d7",
}
KEYS = [
    "medical_red_flags", "baseline_deviation", "communication", "distress",
    "sensory_environment", "what_happened", "primary_risk", "possible_pain",
]


def parse(d):
    if isinstance(d, str):
        try:
            return json.loads(d)
        except Exception:
            return {}
    return d if isinstance(d, dict) else {}


async def main() -> None:
    conn = await asyncpg.connect(DSN)
    out = []

    for label, sid in SESSIONS.items():
        out.append(f"═══ {label} ═══")
        rows = await conn.fetch(
            "SELECT message_data FROM agent_messages WHERE session_id=$1 ORDER BY created_at", sid
        )
        for i, r in enumerate(rows):
            s = json.dumps(parse(r["message_data"]), ensure_ascii=False)
            if "possible_pain" not in s:
                continue
            # 每个键的取值:形如 "medical_red_flags: obvious_pain" 或 "medical_red_flags": ...
            out.append(f"  --- 消息[{i}] 含采集数据 ---")
            for k in KEYS:
                # 匹配 「k: value」 或 「"k": "value"」 或 「k: 【...】」
                for pat in (rf"{k}[:：]\s*([^\\n,、;；]{{1,60}})", rf'"{k}"\s*:\s*"([^"]{{1,60}})"'):
                    for m in re.finditer(pat, s):
                        v = m.group(1).strip()
                        if v and v not in ("null", "unknown"):
                            out.append(f"      {k} = {v}")
                            break
        out.append("")

    await conn.close()
    txt = "\n".join(out)
    Path(".tmp/s4-answers.txt").write_text(txt, encoding="utf-8")
    print(f"写入 .tmp/s4-answers.txt ({len(txt)} 字符)")


asyncio.run(main())
