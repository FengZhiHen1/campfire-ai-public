import asyncio, asyncpg
from pathlib import Path
DSN="postgresql://campfire:changeme@127.0.0.1:5432/campfire"
async def main():
    c=await asyncpg.connect(DSN)
    rows=await c.fetch("""SELECT title, source, "authorization", source_type, evidence_level,
                                 review_status, interview_at, applicable_scope
                          FROM campfire_case_item ORDER BY created_at DESC""")
    await c.close()
    # 产品 itemMetaParts() 的 6 段
    EV={"INSTITUTIONAL":"机构材料","OBSERVATIONAL":"观察性经验"}
    RS={"owner":"项目所有者核准","professional":"专业审阅","pending":"待审阅"}
    out=[]
    for r in rows:
        parts=[f"来源：{r['source']}"]
        if r['source_type']: parts.append(r['source_type'])
        if r['evidence_level']: parts.append(EV.get(r['evidence_level'], r['evidence_level']))
        if r['review_status']: parts.append(RS.get(r['review_status'], r['review_status']))
        if r['authorization']: parts.append(r['authorization'])
        if r['interview_at']: parts.append(f"访谈 {r['interview_at'].isoformat()}")
        line=" · ".join(parts)
        out.append(f"{r['title'][:34]}")
        out.append(f"   段数 {len(parts)}  总长 {len(line)} 字")
        out.append(f"   含「项目所有者核准」: {'项目所有者核准' in line}")
        out.append(f"   含「访谈」: {'访谈' in line}")
    Path(".tmp/six-parts.txt").write_text(chr(10).join(out),encoding="utf-8")
    print("ok")
asyncio.run(main())
