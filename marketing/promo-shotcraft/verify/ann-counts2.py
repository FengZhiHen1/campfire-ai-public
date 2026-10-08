"""核对画面上的来源分布断言(fixture 计数 + 数据库复核)。

从 fixture 直接数(那是影片实际渲染的数据),再用 DB 复核同一张卡的 annotations。
"""
import asyncio
import json
import re
from collections import Counter
from pathlib import Path

import asyncpg

DATA = Path("marketing/promo-shotcraft/src/fixtures/data.generated.ts")
DSN = "postgresql://campfire:changeme@127.0.0.1:5432/campfire"
OUT = Path(".tmp/ann-counts2.txt")


def fixture_counts() -> dict[str, dict]:
    """按 card_id 归集 fixture 里的 annotations 来源分布。"""
    text = DATA.read_text(encoding="utf-8")
    out: dict[str, Counter] = {}
    # 用 card_id 定位每张卡,然后在它之后的 annotations 数组里数 kind
    for m in re.finditer(r'"card_id":\s*"([0-9a-f]+)"', text):
        cid = m.group(1)
        j = text.find('"annotations"', m.end())
        if j < 0:
            continue
        k = text.find("[", j)
        depth, end = 0, k
        for pos in range(k, min(len(text), k + 80000)):
            if text[pos] == "[":
                depth += 1
            elif text[pos] == "]":
                depth -= 1
                if depth == 0:
                    end = pos
                    break
        arr = text[k:end + 1]
        c = Counter()
        for km in re.finditer(r'"kind":\s*"([a-z_]+):', arr):
            c[km.group(1)] += 1
        out.setdefault(cid, Counter()).update(c)
    return out


async def db_counts(session_id: str) -> Counter:
    conn = await asyncpg.connect(DSN)
    try:
        rows = await conn.fetch(
            "SELECT message_data FROM agent_messages WHERE session_id::text = $1 ORDER BY created_at",
            session_id,
        )
    finally:
        await conn.close()

    def find_anns(o):
        if isinstance(o, dict):
            if isinstance(o.get("annotations"), list):
                return o["annotations"]
            for v in o.values():
                got = find_anns(v)
                if got:
                    return got
        elif isinstance(o, list):
            for v in o:
                got = find_anns(v)
                if got:
                    return got
        return None

    c = Counter()
    for r in rows:
        raw = r["message_data"]
        data = json.loads(raw) if isinstance(raw, str) else raw
        anns = find_anns(data)
        if anns:
            for a in anns:
                c[str(a.get("kind", "")).split(":")[0]] += 1
            break
    return c


async def main() -> None:
    fx = fixture_counts()
    lines = [
        "=" * 74,
        "画面上的来源分布断言 vs fixture vs 数据库",
        "=" * 74,
        "",
        "① fixture 里每张卡的来源分布:",
    ]
    for cid, c in fx.items():
        tot = sum(c.values())
        lines.append(f"   card {cid[:12]}…  共 {tot} 条")
        for k, v in c.most_common():
            lines.append(f"       {k:22} {v}")

    lines.append("")
    lines.append("② 数据库复核(同一会话第一张卡):")
    for label, sid in (("有档案", "177f965b83ee4a13bb81186899b5df17"),
                       ("无档案", "b897534e95b74aa99fdf23fe535248d7")):
        c = await db_counts(sid)
        tot = sum(c.values())
        lines.append(f"   {label}: 共 {tot} 条")
        for k, v in c.most_common():
            lines.append(f"       {k:22} {v}")

    lines.append("")
    lines.append("③ 画面上写的:")
    lines.append("   S5「本次会话真实产生 33 条来源标注:历史记录 9 · AI 推断 20 · 家属报告 3 · 现场观察 1」")
    lines.append("   S6「有档案 33 条标注(含历史记录 9 条)」")
    lines.append("   S6「无档案 36 条标注(无历史记录 · 全是推断与观察)」")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("written", OUT)


asyncio.run(main())
