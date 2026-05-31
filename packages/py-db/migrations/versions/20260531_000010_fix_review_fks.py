"""CASE-03: 修复 case_reviews / review_audit_logs 外键。

cases 表已重命名为 cases_backup → FK 指向已失效。
将 FK 改为指向 case_narratives.narrative_id（UUID 类型）。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260531_000010"
down_revision: Union[str, None] = "20260530_000030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # case_reviews: 删除旧 FK，改为指向 case_narratives
    op.execute("ALTER TABLE case_reviews DROP CONSTRAINT IF EXISTS case_reviews_case_id_fkey")
    op.execute("""
        ALTER TABLE case_reviews
        ADD CONSTRAINT case_reviews_case_id_fkey
        FOREIGN KEY (case_id) REFERENCES case_narratives(narrative_id) ON DELETE CASCADE
    """)

    # review_audit_logs: 删除旧 FK，改为指向 case_narratives
    op.execute("ALTER TABLE review_audit_logs DROP CONSTRAINT IF EXISTS review_audit_logs_case_id_fkey")
    op.execute("""
        ALTER TABLE review_audit_logs
        ADD CONSTRAINT review_audit_logs_case_id_fkey
        FOREIGN KEY (case_id) REFERENCES case_narratives(narrative_id) ON DELETE CASCADE
    """)


def downgrade() -> None:
    # 恢复旧的 FK（指向 cases_backup，因为 cases 已被重命名）
    op.execute("ALTER TABLE case_reviews DROP CONSTRAINT IF EXISTS case_reviews_case_id_fkey")
    op.execute("""
        ALTER TABLE case_reviews
        ADD CONSTRAINT case_reviews_case_id_fkey
        FOREIGN KEY (case_id) REFERENCES cases_backup(case_id) ON DELETE CASCADE
    """)

    op.execute("ALTER TABLE review_audit_logs DROP CONSTRAINT IF EXISTS review_audit_logs_case_id_fkey")
    op.execute("""
        ALTER TABLE review_audit_logs
        ADD CONSTRAINT review_audit_logs_case_id_fkey
        FOREIGN KEY (case_id) REFERENCES cases_backup(case_id) ON DELETE CASCADE
    """)
