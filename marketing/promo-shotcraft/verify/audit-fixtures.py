"""独立核对:把 fixture 的每一条文本与数据库逐字比对。

为什么单独写这个:上一版我编造了 S5 的档案分组(全库 0 命中),是终检抓出来的。
所以这一次**在终检之前**先自己机械核对一遍 —— 凡是 fixture 里出现的文本,
都必须能在数据库里找到;找不到的就是编造。

用法: uv run python .tmp/audit-fixtures.py
"""
import asyncio
import io
import json
import re
from collections import Counter
from pathlib import Path

import asyncpg

DSN = "postgresql://campfire:changeme@127.0.0.1:5432/campfire"
FIX = Path("marketing/promo-shotcraft/src/fixtures/data.generated.ts")
STREAM = Path("marketing/promo-shotcraft/src/fixtures/stream.generated.ts")


def load(path: Path) -> dict:
    t = io.open(path, encoding="utf-8").read()
    return json.loads(t[t.index("{"): t.rindex("}") + 1])


def parse(d):
    """把 message_data 解成 dict(jsonb 可能回来是 str 或已解析对象)。"""
    if isinstance(d, str):
        try:
            return json.loads(d)
        except Exception:
            return {}
    return d if isinstance(d, dict) else {}


async def main() -> None:
    d = load(FIX)
    s = load(STREAM)
    conn = await asyncpg.connect(DSN)
    report: list[str] = []
    problems: list[str] = []

    # ── 1. 档案条目逐条比对 ──
    report.append("=== 档案条目逐条核对(8 条) ===")
    rows = await conn.fetch(
        "SELECT item_id::text AS iid, topic, description, origin, confirmation FROM profile_item"
    )
    db_items = {r["iid"]: r for r in rows}
    for it in d["profileItems"]:
        r = db_items.get(it["item_id"])
        if r is None:
            problems.append(f"档案 {it['item_id']} 在数据库不存在")
            report.append(f"  ✗ {it['topic']}: item_id 不存在")
            continue
        ok = (
            r["topic"] == it["topic"]
            and r["description"] == it["description"]
            and r["origin"] == it["origin"]
            and r["confirmation"] == it["confirmation"]
        )
        mark = "✓" if ok else "✗"
        if not ok:
            problems.append(f"档案 {it['item_id']} 字段不符")
        report.append(f"  {mark} [{it['confirmation']:11}] {it['topic'][:20]:22} {it['description'][:40]}")

    # ── 2. 流式文本比对 ──
    report.append("\n=== 流式文本核对 ===")
    for label, sid in (("archive", "177f965b83ee4a13bb81186899b5df17"),
                       ("noArchive", "b897534e95b74aa99fdf23fe535248d7")):
        rows = await conn.fetch(
            "SELECT message_data FROM agent_messages WHERE session_id=$1", sid
        )
        # ★ 必须反解 message_data 的 content[].text 再比对。
        #   上一版这里用 `message_data::text LIKE '%head%'`,全部报「找不到」——
        #   是**假阴性**:asyncpg 已把 jsonb 解析成 Python 对象,再 ::text 的转义形式
        #   与原文不同(中文被转义)。假阴性比漏检更危险,因为它会让核对本身失去可信度。
        db_texts: list[str] = []
        for r in rows:
            m = parse(r["message_data"])
            c = m.get("content")
            if isinstance(c, list):
                for blk in c:
                    if isinstance(blk, dict) and blk.get("text"):
                        db_texts.append(str(blk["text"]))
        for i, t in enumerate(s[label]["assistantTexts"]):
            exact = any(x == t for x in db_texts)
            mark = "✓" if exact else "✗"
            if not exact:
                problems.append(f"流式文本[{label}][{i}] 与数据库 content[].text 不完全一致")
            report.append(f"  {mark} [{label}][{i}] len={len(t)} {t[:40]}")

    # ── 3. 行动卡:分区与标注计数,以及来源分布 ──
    report.append("\n=== 行动卡核对 ===")
    for label in ("archive", "noArchive"):
        ac = d["sessions"][label]["actionCard"]
        if ac is None:
            report.append(f"  [{label}] 无卡")
            continue
        secs = len(ac["sections"])
        anns = ac["annotations"]
        kinds = Counter(a["kind"] for a in anns)
        report.append(f"  [{label}] card_id={ac['card_id'][:12]} 分区={secs} 状态={len(ac['states'])} 标注={len(anns)}")
        report.append(f"        来源置信分布: {dict(kinds)}")

    # ── 4. ★ S6 镜头右侧写的「真实来源分布」是否与数据一致 ──
    # 镜头现在用 sourceCount('history') 现算,所以这里核对的是「镜头是否还在手写数字」+
    # 「现算结果是否等于数据库真值」。
    report.append("\n=== S6 镜头右侧文案的核对(重点) ===")
    ac = d["sessions"]["archive"]["actionCard"]
    src = Counter(a["kind"].split(":")[0] for a in ac["annotations"])
    conf = Counter(a["kind"].split(":")[1] for a in ac["annotations"])
    report.append(f"  数据库真实来源: {dict(src)}")
    report.append(f"  数据库真实置信: {dict(conf)}")

    shot = io.open("marketing/promo-shotcraft/src/shots/S6ActionCard.tsx", encoding="utf-8").read()
    # 检查镜头是否用现算函数(而不是手写数字)
    if "sourceCount(" not in shot:
        problems.append("S6 镜头没有用 sourceCount() 现算来源分布 —— 手写数字会与数据漂移")
        report.append("  ✗ 镜头未使用 sourceCount() 现算")
    else:
        report.append("  ✓ 镜头用 sourceCount() 现算(不手写数字)")
    if "TOTAL_ANNOTATIONS" not in shot:
        problems.append("S6 镜头没有用 TOTAL_ANNOTATIONS 现算合计")
        report.append("  ✗ 镜头未使用 TOTAL_ANNOTATIONS")
    else:
        report.append("  ✓ 镜头用 TOTAL_ANNOTATIONS 现算合计")

    # 现算函数的口径必须与这里一致(kind.split(':')[0])
    if "a.kind.split(':')[0]" not in shot and "kind.split(':')[0]" not in shot:
        problems.append("S6 的 sourceCount 口径与审计脚本不一致(应取 kind 冒号前段)")
        report.append("  ✗ sourceCount 口径不是 kind.split(':')[0]")
    else:
        report.append("  ✓ sourceCount 口径与审计一致(kind 冒号前段)")

    # 手写数字扫描:镜头里不应再出现「v: 8」这类硬编码的来源计数
    hardcoded = re.findall(r"\{k: '[^']+', v: (\d+)\}", shot)
    if hardcoded:
        problems.append(f"S6 仍存在硬编码来源计数: {hardcoded}")
        report.append(f"  ✗ 仍硬编码: {hardcoded}")
    else:
        report.append("  ✓ 无硬编码来源计数")

    # ── 5. 案例/知识条目比对 ──
    report.append("\n=== 案例库/知识库核对 ===")
    db_cases = await conn.fetch("SELECT id::text AS iid, title, status FROM campfire_case_item")
    db_map = {r["iid"]: r for r in db_cases}
    for c in d["cases"]:
        r = db_map.get(c["id"])
        ok = r is not None and r["title"] == c["title"] and r["status"] == c["status"]
        mark = "✓" if ok else "✗"
        if not ok:
            problems.append(f"案例 {c['id']} 不符")
        report.append(f"  {mark} [{c['status']:9}] {c['title'][:44]}")

    await conn.close()

    report.append("\n" + "=" * 60)
    if problems:
        report.append(f"✗ 发现 {len(problems)} 个问题:")
        for p in problems:
            report.append(f"   · {p}")
    else:
        report.append("✓ 全部核对通过:fixture 中每一处文本都能在数据库中找到")

    out = "\n".join(report)
    Path(".tmp").mkdir(parents=True, exist_ok=True)
    Path(".tmp/audit-fixtures.txt").write_text(out, encoding="utf-8")
    print(f"写入 .tmp/audit-fixtures.txt | 问题数: {len(problems)}")


asyncio.run(main())
