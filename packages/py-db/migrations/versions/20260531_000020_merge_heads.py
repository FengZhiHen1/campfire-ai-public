"""merge: 合并 citation_count 与 fk_fix 两个 head。"""

from typing import Sequence, Union

revision: str = "20260531_000020"
down_revision: Union[str, Sequence[str], None] = ("20260528_190000", "20260531_000010")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
