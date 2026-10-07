"""影片记忆素材:查看 / 生成账号级记忆 episode(走产品的真实写入路径)。

── 为什么需要这个脚本(2026-10-07,用户裁决「走 A:补真实记忆」)──
影片 S7 名义上叫「记忆与档案」,画面却只有 `/profile`(孩子档案);
产品另有账号级记忆页 `/settings/memory`「我提过的事」,影片从未展示。
而实测该账号在 FalkorDB 里 episode 数 = 0 ⇒ 记忆页是空态,导不出任何真实记忆。
本脚本用**产品自己的写入路径**(`core.pending_write.enqueue` →
`modules.memory.consumer.consume_memory_episode` → Graphiti `add_episode`)
把真实会话里使用者说过的原话写成记忆,使记忆页有真实内容可拍。

── 纪律 ──
· 正文必须是**真实会话里使用者说过的原话**(逐字),不得编造 —— 与本片
  「逐字来自真实记录」同一条纪律(见 DESIGN_SPEC 第 210 行)。
· 只走产品代码路径,不直接写 Cypher / 不手改图库。
· 幂等:`--key` 派生确定性 `pending_id`(uuid5),重复运行不会产生第二条 episode
  (`take_for_processing` 对 `done` 记录返回 None)。
· 生产上记忆由模型的 `write_memory` 工具调用产生(`tools/memory.py:261`);
  本脚本只跳过「模型决定记什么」这一步 —— 不会跳过任何写入/抽取/落库代码。

── 用法 ──
  uv run python marketing/promo-shotcraft/verify/memory-episodes.py report
  uv run python marketing/promo-shotcraft/verify/memory-episodes.py write \
      --key probe-1 --text-file .tmp/memory-text.txt \
      --occurred-at 2026-10-06T12:00:00+08:00 \
      --session-id 177f965b83ee4a13bb81186899b5df17
  # 探针:写入 → 回读 → 删除 → 再回读(验证三条路径后不留残留)
  uv run python marketing/promo-shotcraft/verify/memory-episodes.py probe \
      --key probe-1 --text-file .tmp/memory-text.txt \
      --occurred-at 2026-10-06T12:00:00+08:00 \
      --session-id 177f965b83ee4a13bb81186899b5df17

输出一律写 UTF-8 文件(终端是 GBK,不把中文打到 stdout),结果路径在 stdout 用 ASCII 回报。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

# ── 定位仓库根并让 `campfire` 可导入(不依赖调用时的 cwd)──
def _find_repo_root() -> Path:
    for base in Path(__file__).resolve().parents:
        if (base / "apps" / "api" / "src" / "campfire").is_dir():
            return base
    raise SystemExit(f"找不到仓库根(apps/api/src/campfire): 本脚本位于 {Path(__file__).resolve()}")


REPO = _find_repo_root()
SRC = REPO / "apps" / "api" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from campfire.core.config import get_settings  # noqa: E402
from campfire.core.db import session_scope  # noqa: E402
from campfire.core.pending_write import (  # noqa: E402
    KIND_MEMORY_EPISODE,
    ORIGIN_USER_STATEMENT,
    enqueue,
)
from campfire.modules.memory.consumer import consume_memory_episode  # noqa: E402
from campfire.modules.memory.deletion import delete_episode  # noqa: E402
from campfire.modules.memory.graph import (  # noqa: E402
    aclose_shared_memory_graph,
    get_shared_memory_graph,
)
from campfire.modules.memory.identity import (  # noqa: E402
    PendingId,
    derive_episode_uuid,
    to_account_id,
)
from campfire.modules.memory.store import read_timeline  # noqa: E402

#: 影片固定使用的账号(与 verify/export-fixtures.py 同源)。
ACCOUNT = "1e3b84e4-176c-4d67-8782-b532f158c078"
#: 影片固定使用的两个真实会话(同 export-fixtures.py)。
SESSION_IDS = (
    "b897534e95b74aa99fdf23fe535248d7",
    "177f965b83ee4a13bb81186899b5df17",
)
OUT_DIR = REPO / "marketing" / "promo-shotcraft" / ".tmp"
OUT_FILE = OUT_DIR / "memory-episodes.txt"
#: pending_id 的确定性派生命名空间(改它会换 uuid,等于另写一条)。
NS = uuid.UUID("6f1d9a54-6f4c-4a5b-9d2f-2f0a5c9b7c31")


def _pending_id(key: str) -> uuid.UUID:
    """由 `--key` 派生确定性 pending_id(幂等依据)。"""
    return uuid.uuid5(NS, f"campfire-film-memory:{key}")


def _parse_message(raw: object) -> dict:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            return {"_raw": raw}
        return parsed if isinstance(parsed, dict) else {"_raw": raw}
    return raw if isinstance(raw, dict) else {"_raw": raw}


async def _report(lines: list[str]) -> None:
    """只读:当前记忆条数 + 真实会话里的使用者原话(candidates)+ 消息形状。"""
    from sqlalchemy import text

    settings = get_settings()
    graph = get_shared_memory_graph(settings)
    account = to_account_id(ACCOUNT)

    async with session_scope(settings) as session:
        episodes = await read_timeline(session, graph, account, limit=50)
        lines.append(f"== 记忆 episode 现有条数: {len(episodes)} ==")
        for ep in episodes:
            lines.append(
                f"  · {ep.occurred_at.isoformat()} | {ep.content[:80]} | source={ep.source}"
            )
        lines.append("")

        lines.append("== 真实会话里的使用者原话(candidates) ==")
        for sid in SESSION_IDS:
            rows = (
                await session.execute(
                    text(
                        "SELECT message_data, created_at FROM agent_messages "
                        "WHERE session_id = :sid ORDER BY created_at"
                    ),
                    {"sid": sid},
                )
            ).all()
            lines.append(f"-- session {sid}: {len(rows)} 条消息")
            shapes: set[str] = set()
            for raw, created in rows:
                msg = _parse_message(raw)
                shapes.add(",".join(sorted(str(k) for k in msg)))
                role = str(msg.get("role", ""))
                content = msg.get("content")
                if role == "user" and isinstance(content, str):
                    lines.append(f"   [user {created}] {content}")
            lines.append(f"   消息键形状: {sorted(shapes)}")
        lines.append("")


async def _write(args: argparse.Namespace, lines: list[str]) -> int:
    """走真实写入路径写一条 episode,并用产品读路径回读确认。"""
    text = _resolve_text(args)
    if not text:
        lines.append("★ 正文为空:正文字段是记忆回看的唯一载体,拒绝写入。")
        return 2
    if not args.session_id:
        lines.append("★ 缺 --session-id:没有来源的记忆无法核对,消费者会拒绝。")
        return 2

    settings = get_settings()
    graph = get_shared_memory_graph(settings)
    account = to_account_id(ACCOUNT)
    pending_id = _pending_id(args.key)
    occurred_at = datetime.fromisoformat(args.occurred_at)

    async with session_scope(settings) as session:
        record = await enqueue(
            session,
            kind=KIND_MEMORY_EPISODE,
            account_id=ACCOUNT,
            origin=ORIGIN_USER_STATEMENT,
            payload={"content": text, "occurred_at": occurred_at.isoformat()},
            source={"session_id": args.session_id, "message_seq": args.message_seq},
            support_object_id=None,
            pending_id=pending_id,
        )
        lines.append(f"已入队 pending_id={record.id!r}(kind={KIND_MEMORY_EPISODE})")

    # 消费:新事务(与 worker 一致 —— 领取/写入/置 done 在同一事务)。
    async with session_scope(settings) as session:
        result = await consume_memory_episode(
            session, graph, pending_id=str(pending_id), lease_owner="film-probe"
        )
    lines.append(
        f"消费结果: written={result.written} discarded={result.discarded} "
        f"episode_uuid={result.episode_uuid}"
    )
    if not result.written:
        lines.append("★ 未写入(可能已存在同 key 的 done 记录)——幂等命中,不算失败。")

    # 回读:必须走产品读路径(read_timeline),证明时间线真能读到。
    async with session_scope(settings) as session:
        episodes = await read_timeline(session, graph, account, limit=50)
    hit = [e for e in episodes if e.content == text]
    lines.append(f"回读:时间线共 {len(episodes)} 条;匹配本条的 {len(hit)} 条")
    for ep in hit:
        lines.append(f"  ✓ {ep.occurred_at.isoformat()} | {ep.episode_uuid} | {ep.source}")
    if not hit:
        lines.append("★ 回读未命中 —— 写入未生效,不要当成成功。")
        return 1
    return 0


def _resolve_text(args: argparse.Namespace) -> str:
    """取正文:`--text-file`(UTF-8,推荐,绕开命令行编码)优先于 `--text`。"""
    path = getattr(args, "text_file", None)
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    return str(getattr(args, "text", "") or "").strip()


async def _probe(args: argparse.Namespace, lines: list[str]) -> int:
    """探针:验证写入 → 读取 → 删除三条路径,并**不留残留**。

    为什么探针要自带删除:
      契约(write_memory 第 1 节)规定记忆内容必须是「关于使用者自身」的经验。
      当前 demo 库里没有这类原话(两次会话都是应急采集,写工具被禁用),
      因此探针写入的是**临时验证文本**——它绝不能留在时间线里被当成影片素材。
      顺带把产品的删除路径也验证一遍(删除是记忆页的真实功能)。
    """
    rc = await _write(args, lines)
    if rc != 0:
        return rc

    text = _resolve_text(args)
    # 真实的 episode uuid 由 pending_id 派生(consumer._write_record_to_graph 同源),
    # 不自己拼字符串 —— 拼错会让删除删不掉另一条。
    episode_uuid = derive_episode_uuid(PendingId(str(_pending_id(args.key))))

    settings = get_settings()
    graph = get_shared_memory_graph(settings)
    account = to_account_id(ACCOUNT)

    async with session_scope(settings) as session:
        result = await delete_episode(session, account_id=account, episode_key=episode_uuid)
    lines.append(
        f"删除: newly_deleted={result.newly_deleted} reason={result.reason} key={episode_uuid}"
    )

    async with session_scope(settings) as session:
        after = await read_timeline(session, graph, account, limit=50)
    still = [e for e in after if e.content == text]
    lines.append(f"删除后回读:时间线共 {len(after)} 条;仍能读到本条的 {len(still)} 条")
    if still:
        lines.append("★ 删除后仍能读到 —— 删除路径未生效,不要当成成功。")
        return 1
    lines.append("✓ 三条路径(写入/读取/删除)均按产品语义生效,且无残留。")
    return 0


async def _export(args: argparse.Namespace, lines: list[str]) -> int:
    """导出记忆时间线为影片 fixture(TS)。

    必须走**产品读路径** `read_timeline`:它内部做删除账本过滤。裸查图库会把
    已删除的物理节点也算进来(本脚本的 probe 就留下过这样一个节点),那是错的。
    """
    settings = get_settings()
    graph = get_shared_memory_graph(settings)
    account = to_account_id(ACCOUNT)

    async with session_scope(settings) as session:
        episodes = await read_timeline(session, graph, account, limit=50)

    if not episodes:
        lines.append("★ 时间线为空 —— 导出空 fixture 会让记忆页拍成空态,拒绝写出。")
        return 1

    rows = []
    for ep in episodes:
        # source_description 形如 `session=<sid> message=<n> pending=<uuid>`(见 consumer)。
        sid = ""
        for part in str(ep.source).split():
            if part.startswith("session="):
                sid = part.split("=", 1)[1]
        rows.append(
            "  {\n"
            f"    episode_key: {json.dumps(str(ep.episode_uuid))},\n"
            f"    occurred_at: {json.dumps(ep.occurred_at.isoformat())},\n"
            f"    content: {json.dumps(ep.content, ensure_ascii=False)},\n"
            f"    source_session_id: {json.dumps(sid)},\n"
            "  },"
        )

    header = (
        "// ⚠️ 自动生成,请勿手改 —— 由 verify/memory-episodes.py export 导出。\n"
        "// 重新生成: uv run python marketing/promo-shotcraft/verify/memory-episodes.py export\n"
        "//\n"
        "// 数据来源:**本地 demo 种子数据**。这些条目由 verify/memory-episodes.py write\n"
        "// 经**产品的真实写入路径**(core.pending_write.enqueue →\n"
        "// modules.memory.consumer.consume_memory_episode → Graphiti add_episode)落库,\n"
        "// 其 source 自描述为 `session=fixture-memory-seed` —— 即它们是**演示用种子数据,\n"
        "// 不是真实使用者的记录**(与 data.generated.ts 的 demo 种子同一口径)。\n"
        "// 交付文档必须按同一口径登记,不得声称记忆段内容来自真实使用者。\n"
        "import type {MemoryEpisode} from '../../../../apps/web/src/shared/types/memory';\n"
        "\n"
        "export const MEMORY_EPISODES: readonly MemoryEpisode[] = [\n"
    )
    text = header + "\n".join(rows) + "\n];\n"
    out = REPO / "marketing" / "promo-shotcraft" / "src" / "fixtures" / "memory.generated.ts"
    out.write_text(text, encoding="utf-8")
    lines.append(f"已导出 {len(episodes)} 条 → {out.relative_to(REPO)}")
    for ep in episodes:
        lines.append(f"  · {ep.occurred_at.isoformat()} | {ep.content[:60]}")
    return 0


async def _main() -> int:
    parser = argparse.ArgumentParser(description="影片记忆素材:查看/生成记忆 episode")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("report", help="只读:现有记忆 + 真实会话里的使用者原话")
    sub.add_parser("export", help="导出记忆时间线 → src/fixtures/memory.generated.ts(走产品读路径)")
    for name, help_text in (
        ("write", "走真实写入路径写一条记忆"),
        ("probe", "写入 → 回读 → 删除 → 再回读(不留残留)"),
    ):
        w = sub.add_parser(name, help=help_text)
        w.add_argument("--key", required=True, help="幂等键(派生确定性 pending_id)")
        w.add_argument("--text", default="", help="正文(ASCII 便利项;中文请用 --text-file)")
        w.add_argument("--text-file", default=None, help="正文文件(UTF-8),优先于 --text")
        w.add_argument("--occurred-at", required=True, help="ISO 8601 带时区")
        w.add_argument("--session-id", required=True, help="来源会话 id")
        w.add_argument("--message-seq", type=int, default=None, help="来源消息序号(可选)")
    args = parser.parse_args()

    lines: list[str] = []
    rc = 0
    try:
        if args.cmd == "write":
            rc = await _write(args, lines)
        elif args.cmd == "probe":
            rc = await _probe(args, lines)
        elif args.cmd == "export":
            rc = await _export(args, lines)
        else:
            await _report(lines)
    finally:
        await aclose_shared_memory_graph()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written {OUT_FILE} lines={len(lines)} rc={rc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
