"""CASE-03: 删除 case_reviews / review_audit_logs 中已失效的 FK。

cases 表已拆分为 case_narratives + case_cards，旧 FK 指向不存在的表。
旧数据 (CASE-YYYY-NNNN) 与新主键 (UUID) 类型不兼容，直接删除 FK 不重建。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260531_000010"
down_revision: Union[str, None] = "20260530_000030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE case_reviews DROP CONSTRAINT IF EXISTS case_reviews_case_id_fkey")
    op.execute("ALTER TABLE review_audit_logs DROP CONSTRAINT IF EXISTS review_audit_logs_case_id_fkey")


def downgrade() -> None:
    op.execute("""
        ALTER TABLE case_reviews
        ADD CONSTRAINT case_reviews_case_id_fkey
        FOREIGN KEY (case_id) REFERENCES cases_backup(case_id) ON DELETE CASCADE
    """)
    op.execute("""
        ALTER TABLE review_audit_logs
        ADD CONSTRAINT review_audit_logs_case_id_fkey
        FOREIGN KEY (case_id) REFERENCES cases_backup(case_id) ON DELETE CASCADE
    """)
