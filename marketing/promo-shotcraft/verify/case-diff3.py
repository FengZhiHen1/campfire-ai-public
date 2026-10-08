"""逐字段比对(fixture 用 snake_case,上版用错键名导致假不一致)。

同时回答一个关键问题:真实页面渲染的「来源」行包含 interview_at(访谈时间)
与 review_status(项目所有者核准),而 fixture 只有 9 个键 ——
**fixture 是否缺字段?** 缺了就会导致影片展示的来源行比真实页面短。
"""
import asyncio
import json
import re
from pathlib import Path

import asyncpg

DSN = "postgresql://campfire:changeme@127.0.0.1:5432/campfire"
FIX = Path("marketing/promo-shotcraft/src/fixtures/data.generated.ts")
OUT = Path(".tmp/case-diff3.txt")


def fixture_cases() -> list[dict]:
    text = FIX.read_text(encoding="utf-8")
    m = re.search(r'"cases":\s*\[', text)
    i = text.find("[", m.end() - 1)
    depth, end = 0, i
    for pos in range(i, len(text)):
        if text[pos] == "[":
            depth += 1
        elif text[pos] == "]":
            depth -= 1
            if depth == 0:
                end = pos
                break
    return json.loads(text[i:end + 1])


async def main() -> None:
    fx = fixture_cases()
    conn = await asyncpg.connect(DSN)
    try:
        rows = await conn.fetch(
            """SELECT title, source, "authorization", applicable_scope, source_type,
                      evidence_level, review_status, interview_at, status
               FROM campfire_case_item ORDER BY created_at DESC"""
        )
    finally:
        await conn.close()

    by_title = {r["title"]: r for r in rows}
    lines = ["=" * 78, "fixture cases vs DB(snake_case 对齐)", "=" * 78, ""]

    # ① fixture 有哪些键 / DB 有哪些列
    fk = set(fx[0].keys())
    dk = {"title", "source", "authorization", "applicable_scope", "source_type",
          "evidence_level", "review_status", "interview_at", "status"}
    lines.append(f"① fixture 的键 ({len(fk)}): {sorted(fk)}")
    lines.append(f"   DB 用来比对的列 ({len(dk)}): {sorted(dk)}")
    lines.append(f"   ★ fixture 缺少: {sorted(dk - fk) or '(无)'}")
    lines.append(f"   fixture 独有  : {sorted(fk - dk) or '(无)'}")
    lines.append("")

    # ② 逐条逐字段
    mismatch = 0
    for it in fx:
        t = it.get("title", "")
        r = by_title.get(t)
        lines.append(f"--- {t[:60]} ---")
        if r is None:
            lines.append("   ★ DB 里没有同标题行")
            mismatch += 1
            continue
        for name in ("source", "authorization", "applicable_scope", "source_type",
                     "evidence_level", "status"):
            fv = it.get(name)
            dv = r[name]
            same = str(fv) == str(dv)
            if not same:
                mismatch += 1
                lines.append(f"   ★ {name} 不一致")
                lines.append(f"        fixture: {str(fv)[:140]}")
                lines.append(f"        DB     : {str(dv)[:140]}")
            else:
                lines.append(f"   ✓ {name}")
        lines.append("")

    lines.append("=" * 78)
    lines.append(f"不一致字段数: {mismatch}")
    lines.append("")
    lines.append("③ 关键结论:真实页面「来源」行会渲染 interview_at 与 review_status。")
    lines.append("   fixture 若不含 interview_at ⇒ 影片的来源行必然比真实页面**短**。")
    lines.append(f"   fixture 是否含 interview_at: {'是' if 'interview_at' in fk else '否'}")
    lines.append(f"   真实页面的 review_status 值: {by_title[list(by_title)[0]]['review_status'] if by_title else '?'}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("written", OUT)


asyncio.run(main())
