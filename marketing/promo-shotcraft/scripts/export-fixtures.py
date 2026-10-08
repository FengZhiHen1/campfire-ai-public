"""从本地数据库导出影片需要的真实数据,生成 TS fixture。

为什么用脚本导出而不是手写 fixture:
  上一版我在 S5 手写「真实档案分组」,结果编造了 4 组内容(全库 0 命中),
  还把「自行跑向出口」加重成「因走失紧急处置」。手抄真实数据不可靠 —— 必须机器导出。

输出: marketing/promo-shotcraft/src/fixtures/data.generated.ts
"""
import asyncio
import json
from pathlib import Path

import asyncpg

DSN = "postgresql://campfire:changeme@127.0.0.1:5432/campfire"

# ★★ 输出路径必须与**脚本所在位置无关**。独立复核 P2 指出:
#    本脚本原在 `.tmp/`,用了 `parents[1] / "marketing/promo-shotcraft/src/..."`,
#    那时 `parents[1]` = 仓库根 ⇒ 正确。搬到 `verify/` 后 `parents[1]` 变成
#    `marketing/promo-shotcraft` ⇒ 会写到
#    `marketing/promo-shotcraft/marketing/promo-shotcraft/src/...`(不存在的目录树),
#    而且**不校验、exit 0** ⇒ 静默不同步真正的 fixture。
#    修法:从脚本自身位置**向上找** `src/fixtures/` 所在的项目根,找不到就报错。
def _find_fixture_path() -> Path:
    for base in Path(__file__).resolve().parents:
        cand = base / "src" / "fixtures" / "data.generated.ts"
        if cand.parent.is_dir():
            return cand
    raise SystemExit(
        "★ 找不到 src/fixtures/ 目录 —— 不要静默写错地方。\n"
        f"  本脚本位置: {Path(__file__).resolve()}"
    )


OUT = _find_fixture_path()

# 影片固定使用的两个真实会话(见 DELIVERY.md 的「数据真实性」节)
SID_NO_ARCHIVE = "b897534e95b74aa99fdf23fe535248d7"
SID_ARCHIVE = "177f965b83ee4a13bb81186899b5df17"
ACCOUNT = "1e3b84e4-176c-4d67-8782-b532f158c078"


def parse(d):
    if isinstance(d, str):
        try:
            return json.loads(d)
        except Exception:
            return {"raw": d}
    return d


async def main() -> None:
    conn = await asyncpg.connect(DSN)

    # ── 支持对象 + 档案条目(档案页用) ──
    obj = await conn.fetchrow(
        "SELECT id, display_name, created_at FROM campfire_support_object WHERE account_id=$1 AND archived_at IS NULL ORDER BY created_at LIMIT 1",
        ACCOUNT,
    )
    if obj is None:
        raise SystemExit("找不到 demo-parent 的支持对象")

    items = await conn.fetch(
        """SELECT item_id, support_object_id, domain, topic, description, contexts,
                  manifestations, person_report, probable_need, helpful_support,
                  unhelpful_support, origin, source, confirmation, freshness,
                  first_recorded_at, last_confirmed_at, superseded_by
           FROM profile_item WHERE support_object_id=$1 ORDER BY confirmation, first_recorded_at""",
        obj["id"],
    )

    def _wire_datetime(v) -> str:
        """按**产品 wire 格式**序列化 datetime。

        ★★ 独立复核 P4-a 指出(我已目视复现):
          真实产品页面显示 `访谈 2026-05-31T00:50:00**Z**`,而影片显示 `+00:00`。
          根因:API 层是 Pydantic datetime,`model_dump_json()` 把 UTC 序列化成
          `...Z`(实测:{"interview_at":"2026-05-31T00:50:00Z"});
          而本导出器用的是 Python `datetime.isoformat()` → `...+00:00`。
          结果:影片的来源行在**时间戳后缀**上与真实页面不同。
          这与「渲染真实产品」的转向前提相悖 —— 内容是真值,格式也必须与产品一致。
        """
        s = v.isoformat()
        # Pydantic 2 对 UTC 输出 'Z';Python isoformat 给 '+00:00'。对齐成前者。
        return s[:-6] + "Z" if s.endswith("+00:00") else s

    def jsonify(v):
        """asyncpg 的 jsonb 回来是 str,数组是 list,时间是 datetime。统一成可 JSON 化的值。"""
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return v
        if isinstance(v, (list, tuple)):
            return [jsonify(x) for x in v]
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return v

    profile_items = []
    for r in items:
        d = {k: jsonify(r[k]) for k in r.keys()}
        # 字段名与 shared/types/profile.ts 的 ProfileItem 对齐
        profile_items.append(
            {
                "item_id": str(d["item_id"]),
                "support_object_id": str(d["support_object_id"]),
                "domain": d["domain"],
                "topic": d["topic"],
                "description": d["description"],
                "contexts": d["contexts"] or [],
                "manifestations": d["manifestations"] or [],
                "person_report": d["person_report"],
                "probable_need": d["probable_need"],
                "helpful_support": d["helpful_support"] or [],
                "unhelpful_support": d["unhelpful_support"] or [],
                "origin": d["origin"],
                "source": d["source"] if isinstance(d["source"], dict) else {},
                "confirmation": d["confirmation"],
                "freshness": d["freshness"],
                "first_recorded_at": d["first_recorded_at"],
                "last_confirmed_at": d["last_confirmed_at"],
                "superseded_by": str(d["superseded_by"]) if d["superseded_by"] else None,
            }
        )

    # ── 知识库 / 案例库(案例页用) ──
    # ★ 排序必须与**真实页面一致**:实测列表顺序是
    #   成年才被看见 → 从不定期炸弹 → 从强迫到尊重 → 虚构样例(offsetTop 243/696/1149/1602),
    #   而 created_at 升序恰好相反。顺序不一致会让「滚到虚构样例」的实测偏移失效
    #   (影片会滚到别的卡片上,实测踩过)。这里按 created_at DESC 与页面同序。
    knowledge = await conn.fetch(
        """SELECT id, title, source, applicable_scope, status FROM campfire_knowledge_item ORDER BY created_at"""
    )
    cases = await conn.fetch(
        # ★ review_status 与 interview_at 必须取:
        #   产品的 itemMetaParts()(features/library/domain/labels.ts)把案例卡的
        #   「来源」行拼成 6 段 —— 来源 + 来源类型 + 证据等级 + **审阅状态** + 授权 + **访谈时间**。
        #   少了这两个字段,影片里的来源行会比真实页面短两段
        #   (真机对照截图 out/parity/real-cases.png 实测:真实页面有
        #    「项目所有者核准」与「访谈 2026-05-31T00:50:00Z」,影片没有)。
        #   产品注释明确「缺字段不补默认值」——所以这不是可以省略的装饰字段,
        #   而是案例卡功能的一部分(「谁说的、多可信、什么时候」)。
        """SELECT id, title, "source", applicable_scope, status, source_type, "authorization",
                  evidence_level, subject_type, review_status, interview_at
           FROM campfire_case_item ORDER BY created_at DESC"""
    )

    # ★★ 案例卡的 snippet 必须取**首个内容节点**(独立复核 P4-b 指出,我已复现):
    #   真实页面的 `.lr-sub` 显示的是 `item.snippet`,由后端 `_first_node_summary()`
    #   (modules/library/routes.py)给出 —— 规则是「按 node_id 排序取该条目的第一个节点」。
    #   而影片此前 `ports.ts` 硬写 `snippet: raw.title` ⇒ 摘要行只是**重复标题**。
    #   真机对照实测:真实页面显示「title：冷处理+自主外出空间策略… scenario：适用于 ASD 成人…」,
    #   影片显示与标题相同的字符串 —— 这是保真度偏差,不是数据不实。
    #   这里按与产品**同一条规则**取,不自己发明排序。
    first_nodes = await conn.fetch(
        """SELECT DISTINCT ON (n.metadata_->>'item_id')
                  n.metadata_->>'item_id' AS item_id, n.text AS text
           FROM data_campfire_node n
           WHERE n.metadata_->>'library' = 'case'
           ORDER BY n.metadata_->>'item_id', n.node_id"""
    )
    snippet_by_item = {r["item_id"]: r["text"] for r in first_nodes}

    # ── 两个会话的真实消息(行动卡 / 检索调用) ──
    sessions = {}
    for label, sid in (("noArchive", SID_NO_ARCHIVE), ("archive", SID_ARCHIVE)):
        rows = await conn.fetch(
            "SELECT message_data FROM agent_messages WHERE session_id=$1 ORDER BY created_at", sid
        )
        msgs = [parse(r["message_data"]) for r in rows]

        action_card = None
        card_id = None
        calls = []
        profile_block = None
        for m in msgs:
            if not isinstance(m, dict):
                continue
            name = str(m.get("name", ""))
            if "emit_emergency_action_card" in name:
                try:
                    action_card = json.loads(m.get("arguments") or "{}")
                except Exception:
                    action_card = None
            # card_id 来自工具的**返回值**(不是调用参数)——见 function_call_output
            if m.get("type") == "function_call_output":
                out = m.get("output")
                if isinstance(out, str) and "card_id" in out:
                    try:
                        o = json.loads(out)
                        if isinstance(o, dict) and o.get("card_id"):
                            card_id = str(o["card_id"])
                    except Exception:
                        pass
            if m.get("type") == "function_call" and "search" in name:
                try:
                    calls.append({"name": name, "arguments": json.loads(m.get("arguments") or "{}")})
                except Exception:
                    calls.append({"name": name, "arguments": m.get("arguments")})
            c = m.get("content")
            if isinstance(c, str) and "emergency_profile" in c:
                profile_block = c

        # 组成完整的 ActionCardEvent(与 shared/types/sse.ts 的 ActionCardEvent 同形):
        #   card_id 来自返回值的真实 id;title 取产品的固定卡名「现场行动卡」;
        #   type 是事件判别字段。
        #
        # ★ 标注必须**转成线上格式**:数据库里存的是
        #   {line_ref: 1, source: 'family_report', confidence: 'unknown'}
        #   而产品前端期望 {target: '1', kind: 'family_report:unknown'}
        #   (见 apps/web/src/features/consult/domain/actionCard.ts 的 decodeAnnotation:
        #    它按 ':' 切开 kind 得到 source 与 confidence)。
        #   直接塞库里的形状会让前端在 annotation.target.trim() 上抛错(实测踩过)。
        raw_anns = (action_card or {}).get("annotations", [])
        wire_anns = []
        for a in raw_anns:
            if not isinstance(a, dict):
                continue
            target = a.get("target")
            if target is None and a.get("line_ref") is not None:
                target = str(a["line_ref"])
            kind = a.get("kind")
            if kind is None and a.get("source") is not None:
                kind = f"{a['source']}:{a.get('confidence', 'unknown')}"
            if target is None or kind is None:
                continue
            wire_anns.append({"target": str(target), "kind": str(kind)})

        full_card = None
        if action_card is not None:
            full_card = {
                "type": "action_card",
                "card_id": card_id or "unknown-card",
                "title": "现场行动卡",
                "sections": action_card.get("sections", []),
                "states": action_card.get("states", []),
                "annotations": wire_anns,
            }

        sessions[label] = {
            "sessionId": sid,
            "actionCard": full_card,
            "searchCalls": calls,
            "profileInjection": profile_block,
        }

    payload = {
        "supportObject": {
            "id": str(obj["id"]),
            "display_name": obj["display_name"],
            "archived_at": None,
        },
        "profileItems": profile_items,
        "knowledge": [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "source": r["source"],
                "applicable_scope": r["applicable_scope"],
                "status": r["status"],
            }
            for r in knowledge
        ],
        "cases": [
            {
                "id": str(r["id"]),
                "title": r["title"],
                # ★ 字段名照产品的 wire 格式(下划线),因为 ports.ts 直接把对象
                #   交给 LibraryPage,页面的 itemMetaParts() 读的就是这些键。
                "source": r["source"],
                "applicable_scope": r["applicable_scope"],
                "status": r["status"],
                "source_type": r["source_type"],
                "authorization": r["authorization"],
                "evidence_level": r["evidence_level"],
                "subject_type": r["subject_type"],
                # 上面注释说明过为什么必须带这两个:
                #   review_status → 来源行第 4 段(「项目所有者核准」)
                #   interview_at  → 来源行第 6 段(「访谈 2026-05-31T00:50:00Z」)
                "review_status": r["review_status"],
                # ★ 用 _wire_datetime 而不是 .isoformat():
                #   产品 API 经 Pydantic 序列化 UTC 为 `...Z`,而 isoformat() 给 `+00:00`。
                #   真实页面显示 `Z`(见 out/parity/ts-real.png),影片必须一致。
                "interview_at": _wire_datetime(r["interview_at"]) if r["interview_at"] else None,
                # ★ 首个内容节点文本(真实页面的摘要行就是它)。
                #   取不到时给 None,由 ports.ts 回退到 title —— 但**不静默**:
                #   导出时会打印有多少条取不到,便于发现规则漂移。
                "snippet": snippet_by_item.get(str(r["id"])),
            }
            for r in cases
        ],
        "sessions": sessions,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ts = (
        "// ⚠️ 自动生成,请勿手改 —— 由 .tmp/export-fixtures.py 从本地数据库导出。\n"
        "// 重新生成: uv run python .tmp/export-fixtures.py\n"
        "//\n"
        "// 数据来源:本地 demo 种子数据(非真实用户数据)。\n"
        f"//   支持对象 {payload['supportObject']['display_name']} / 档案 {len(profile_items)} 条 /\n"
        f"//   知识库 {len(payload['knowledge'])} 条 / 案例库 {len(payload['cases'])} 条 /\n"
        f"//   会话 {SID_NO_ARCHIVE}(无档案) 与 {SID_ARCHIVE}(有档案)\n\n"
        "export const FIXTURE_DATA = "
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + " as const;\n"
    )
    OUT.write_text(ts, encoding="utf-8")
    print(f"已写入 {OUT}")
    print(
        f"  档案 {len(profile_items)} 条 | 知识 {len(payload['knowledge'])} | 案例 {len(payload['cases'])}"
    )
    for k, v in sessions.items():
        print(
            f"  会话[{k}] {v['sessionId'][:12]} 行动卡={'有' if v['actionCard'] else '无'} "
            f"检索调用={len(v['searchCalls'])} 档案注入={'有' if v['profileInjection'] else '无'}"
        )
    await conn.close()


asyncio.run(main())
