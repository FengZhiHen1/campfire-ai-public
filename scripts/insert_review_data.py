"""为专家审核台插入测试数据 —— 一条待审核叙事 + 一条审核记录。

用法：
  cd E:\Project\Web_Development\Campfire-AI
  python scripts/insert_review_data.py

连接串读取顺序：.env > .env.example > 内置默认值。
独立脚本，不依赖项目内部包。
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from datetime import datetime, timezone


def _load_database_url() -> str:
    """从项目根目录的 .env / .env.example 中提取 DATABASE_URL。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in (".env", ".env.example"):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"^\s*DATABASE_URL\s*=\s*(.+?)\s*$", line)
                if m:
                    return m.group(1).strip()
    return "postgresql+asyncpg://campfire:changeme@localhost:5432/campfire"


def _sync_url(url: str) -> str:
    """把 asyncpg 连接串转成同步 psycopg2 格式，方便直接用 raw SQL（如果项目中
    没有安装 psycopg2，也可以用 asyncpg 运行，见入口处的分支选择）。"""
    return url.replace("+asyncpg", "")


# ---------------------------------------------------------------------------
# 纯 asyncpg 实现 —— 零第三方依赖（除了 asyncpg）
# ---------------------------------------------------------------------------


async def insert_via_asyncpg(db_url: str) -> None:
    import asyncpg

    # asyncpg 只接受 postgresql:// 或 postgres://，去掉 SQLAlchemy 的 +asyncpg 后缀
    pg_url = db_url.replace("+asyncpg", "")
    conn = await asyncpg.connect(pg_url)

    try:
        # ---- 0. 扩宽遗留的 VARCHAR(20) 列 + 删除指向旧表的过时 FK ----
        await conn.execute(
            "ALTER TABLE case_reviews ALTER COLUMN case_id TYPE VARCHAR(36)"
        )
        await conn.execute(
            "ALTER TABLE review_audit_logs ALTER COLUMN case_id TYPE VARCHAR(36)"
        )
        # 删除指向已废弃 cases_backup 表的外键约束（存在则删，不存在则跳过）
        for tbl, fk in (
            ("case_reviews", "fk_case_reviews_case_id_cases"),
            ("review_audit_logs", "fk_review_audit_logs_case_id_cases"),
        ):
            try:
                await conn.execute(
                    f'ALTER TABLE {tbl} DROP CONSTRAINT {fk}'
                )
                print(f"[OK] 已删除 {tbl}.{fk}")
            except Exception:
                print(f"[SKIP] {tbl}.{fk} 不存在，跳过")

        # ---- 1. 插入一条 pending_review 的叙事 ----
        narrative_id = str(uuid.uuid4())
        author_id = "00000000-0000-0000-0000-000000000001"  # 虚拟专家
        now = datetime.now(timezone.utc)

        await conn.execute(
            """
            INSERT INTO case_narratives
                (narrative_id, title, narrative, source_type, author_id,
                 status, extraction_status, created_at, updated_at)
            VALUES
                ($1, $2, $3, $4, $5, 'pending_review', 'pending', $6, $6)
            """,
            narrative_id,
            "孩子在超市情绪崩溃的干预案例",
            "小明（化名），5岁，男，ASD确诊。某周六下午在超市购物时，"
            "因看到喜欢的玩具被拒绝购买，突然开始尖叫、拍打自己头部，"
            "持续约10分钟。母亲尝试抱抱安抚但被推开。"
            "最终由父亲带离超市，在安静的停车场逐渐平静下来。",
            "expert_written",
            author_id,
            now,
        )
        print(f"[OK] 已插入叙事 narrative_id={narrative_id}  (status=pending_review)")

        # ---- 2. 插入一条审核记录 ----
        review_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO case_reviews
                (id, case_id, review_round, ai_review_report, decision,
                 review_comment, reviewer_id, reviewed_at, is_override)
            VALUES
                ($1, $2, 1, $3::jsonb, 'approved',
                 'L1 叙事格式完整，无 PII 泄漏，通过审核。',
                 $4, $5, false)
            """,
            review_id,
            narrative_id,
            '{"format_check":{"status":"pass","details":"四段式字段完整","is_hard_gate":true},'
            '"pii_check":{"status":"pass","details":"未检测到可识别个人信息","is_hard_gate":true},'
            '"required_fields_check":{"status":"pass","details":"17 个必填字段均已填写","is_hard_gate":false},'
            '"ebp_check":{"status":"pass","details":"标签与 EBP 清单一致","is_hard_gate":false},'
            '"overall":"pass"}',
            author_id,
            now,
        )
        print(f"[OK] 已插入审核记录 review_id={review_id}  (decision=approved)")

        # ---- 3. 插入审计日志 ----
        await conn.execute(
            """
            INSERT INTO review_audit_logs
                (case_id, action, operator_id, operator_role, details, created_at)
            VALUES
                ($1, 'approved', $2, 'expert', $3::jsonb, $4)
            """,
            narrative_id,
            author_id,
            f'{{"narrative_id":"{narrative_id}","decision":"approved"}}',
            now,
        )
        print("[OK] 已插入审计日志")

        # ---- 4. 更新叙事状态为 approved ----
        await conn.execute(
            "UPDATE case_narratives SET status = 'approved' WHERE narrative_id = $1",
            narrative_id,
        )
        print("[OK] 叙事状态已更新为 approved")

        print("\n=====  插入完毕 =====")
        print(f"  narrative_id = {narrative_id}")
        print(f"  review_id    = {review_id}")
        print("  审核台现在可以看到已审核通过的数据（如果前端有展示）")

    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def main() -> None:
    raw = _load_database_url()
    sync = _sync_url(raw)
    print(f"数据库连接串: {sync}")

    try:
        asyncio.run(insert_via_asyncpg(raw))
    except ImportError:
        print("未安装 asyncpg，尝试用 psycopg2 ...")
        _fallback_sync(sync)


def _fallback_sync(sync_url: str) -> None:
    """备选：用 psycopg2 同步驱动直接插。"""
    import psycopg2

    narrative_id = str(uuid.uuid4())
    author_id = "00000000-0000-0000-0000-000000000001"
    now = datetime.now(timezone.utc)
    review_id = str(uuid.uuid4())

    with psycopg2.connect(sync_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO case_narratives
                    (narrative_id, title, narrative, source_type, author_id,
                     status, extraction_status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'pending_review', 'pending', %s, %s)
                """,
                (narrative_id, "孩子在超市情绪崩溃的干预案例",
                 "小明（化名），5岁，男，ASD确诊。某周六下午在超市购物时，"
                 "因看到喜欢的玩具被拒绝购买，突然开始尖叫、拍打自己头部。",
                 "expert_written", author_id, now, now),
            )
            print(f"[OK] 已插入叙事 narrative_id={narrative_id}")

            cur.execute(
                """
                INSERT INTO case_reviews
                    (id, case_id, review_round, ai_review_report, decision,
                     review_comment, reviewer_id, reviewed_at, is_override)
                VALUES (%s, %s, 1, %s::jsonb, 'approved', %s, %s, %s, false)
                """,
                (review_id, narrative_id,
                 '{"overall":"pass"}',
                 'L1 叙事格式完整，无 PII 泄漏，通过审核。',
                 author_id, now),
            )
            print(f"[OK] 已插入审核记录 review_id={review_id}")

            cur.execute(
                """
                INSERT INTO review_audit_logs
                    (case_id, action, operator_id, operator_role, details, created_at)
                VALUES (%s, 'approved', %s, 'expert', %s::jsonb, %s)
                """,
                (narrative_id, author_id,
                 f'{{"narrative_id":"{narrative_id}","decision":"approved"}}',
                 now),
            )
            print("[OK] 已插入审计日志")

            cur.execute(
                "UPDATE case_narratives SET status = 'approved' WHERE narrative_id = %s",
                (narrative_id,),
            )
            print("[OK] 叙事状态已更新为 approved")

        conn.commit()

    print(f"\n=====  插入完毕 =====")
    print(f"  narrative_id = {narrative_id}")
    print(f"  review_id    = {review_id}")


if __name__ == "__main__":
    main()
