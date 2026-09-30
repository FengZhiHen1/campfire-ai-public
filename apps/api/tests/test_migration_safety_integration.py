"""迁移安全性：``--autogenerate`` 不得提议删除不归本项目管理的表。

## 这个用例为什么必须存在

它钉住的是一条**会静默摧毁数据**的缺陷，而不是一个风格问题。

**实测背景（2026-09-29）**：``migrations/env.py`` 原按**表名前缀**排除外部组件的表
（``supertokens_``、``agent_sessions``…）。启动 SuperTokens core 后实测：core 建的
表**一个前缀都没有**——本库有 **56 张无前缀表**（``session_info``、
``emailpassword_users``、``tenants``、``apps``、``webauthn_users``…）。
原实现在本库**完全失效**：``--autogenerate`` 会产出 **56 条 remove_table +
106 条 remove_index**，即一次自动生成摧毁全部身份与会话数据。这正是 AGENTS.md
明文禁止的（「不得让 --autogenerate 把 SuperTokens core 在自己库里建的表当成待删对象」）。

**为什么断言放在子进程上，而不是复刻过滤器逻辑**：复刻一份判据就等于放第二个真源——
过滤器的行为在 ``env.py`` 里，测试只有真正驱动 ``alembic`` 才证明「交付物本身」安全。
复刻版还有个具体风险：实测中它就与真实实现分开演化（探针用的是复刻逻辑，
一度给出与真实 ``alembic check`` 不同的结论）。

**判别性**（怎么确认这个用例不是永远通过）：把 ``env.py`` 的 ``include_object``
改回前缀排除，本用例立即失败——子进程输出里出现 ``remove_table``。实测已验证。

    docker compose up -d postgres supertokens
    uv run pytest -m integration apps/api/tests/test_migration_safety_integration.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from campfire.core.config import get_settings

pytestmark = pytest.mark.integration

#: 仓库根：本文件位于 <根>/apps/api/tests/，故 parents[3]。
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: 判定「有删表提议」的标志。alembic 的 autogenerate 差异以 repr 形式打印，
#: 表级删除表现为 ``remove_table``。
_DROP_MARKERS = ("remove_table", "drop_table")

#: 正向控制的探测列名。取一个明显不属业务命名的名字，便于在失败输出里辨认。
_PROBE_COLUMN = "migration_safety_probe"

#: 正向控制作用的表。选 ``campfire_pending_write``：它是我方表，加/删一个可空整数列
#: 对并发读取无害，且随即在 ``finally`` 里还原。
_PROBE_TABLE = "campfire_pending_write"


def _run_alembic_check() -> subprocess.CompletedProcess[str]:
    """在仓库根跑 ``alembic check``（不写任何文件）。

    两侧编码显式固定为 utf-8：``text=True`` 否则按 locale 解码（Windows 上是 GBK），
    而迁移与模型注释都是中文——与 ``test_cli_entry`` 踩过的是同一个坑。
    """
    return subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def _sql(statement: str) -> None:
    """对集成库执行一条 DDL（同步引擎，一次性连接）。

    Raises:
        RuntimeError: 未配置 ``DATABASE_URL``（调用方已用夹具拦住，这里是兜底）。
    """
    from sqlalchemy import create_engine, text

    from campfire.core.db import to_sync_url

    url = get_settings().database_url
    if not url:
        raise RuntimeError("未配置 DATABASE_URL")
    engine = create_engine(to_sync_url(url))
    try:
        with engine.begin() as connection:
            connection.execute(text(statement))
    finally:
        engine.dispose()


@pytest.fixture
def _require_database() -> None:
    """未配置 `DATABASE_URL` 时跳过——**不假装通过**（仓库既有集成测试的统一做法）。

    **刻意不是 ``autouse``**（2026-09-30 评审修正）：正向控制用例需要数据库，
    但它一旦是 autouse，未来任何纯元数据/纯静态断言都会被一并跳过，
    在无库环境（含 CI）里变成白写。谁需要库，谁显式声明。
    """
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")


@pytest.mark.usefixtures("_require_database")
def test_autogenerate_proposes_no_table_drops() -> None:
    """``alembic check`` 必须报告**无待执行操作**，且输出里不得出现删表提议。

    SuperTokens core 一旦运行过就会在库里留下 56 张表。若过滤器失效，本用例失败——
    这正是它要防的回归。
    """
    completed = _run_alembic_check()
    combined = completed.stdout + completed.stderr

    # 先给一条可读的失败信息：把输出尾部带上，否则失败时只有一句断言。
    assert completed.returncode == 0, (
        "alembic check 非零退出（通常意味着存在待执行的迁移差异）：\n"
        f"stdout:\n{completed.stdout[-4000:]}\n"
        f"stderr:\n{completed.stderr[-2000:]}"
    )

    offenders = [marker for marker in _DROP_MARKERS if marker in combined]
    assert not offenders, (
        f"autogenerate 提议了删除操作（命中 {offenders}）——这会摧毁不归本项目管理的表"
        f"（SuperTokens core 自建表无前缀，实测 56 张）。\n输出尾部：\n{combined[-4000:]}"
    )


@pytest.mark.usefixtures("_require_database")
def test_filter_still_sees_our_own_tables() -> None:
    """**正向控制**：过滤器必须是白名单，不能退化成「什么都不过滤」。

    ## 这条用例替代了什么（以及为什么原来的写法是错的）

    上一版是一条**纯元数据断言**（只看 ``metadata.tables`` 非空、表名前缀符合约定）。
    2026-09-30 评审实测：把 ``include_object`` 改成 ``return False``（一律拒绝）后
    **两条用例全都通过**——因为所有差异都被过滤掉，``alembic check`` 照样打印
    「No new upgrade operations detected」。那是一条**永远不会失败**的检查，
    AGENTS.md 明文禁止，而当时的 commit message 还声称它「堵住了那种廉价错误实现」
    ——该声明与实测不符，已随本次修正撤销。

    现在的做法是**黑盒正向控制**：真的往库里加一个我方模型里没有的列，然后驱动
    alembic。若过滤器仍在正常工作，它会看到这个差异并提议 ``remove_column``；
    若过滤器一律返回 False（或白名单误把我方表排除），则**什么都看不到**，用例失败。

    用 ``remove_column`` 而不是 ``add_table`` 作信号：加列是我方表上的差异，
    与「删外部表」走同一套比较路径但方向相反，因此它能同时证明
    「外部表被拦」与「我方表没被拦」两件事。
    """
    from sqlalchemy import create_engine, inspect

    from campfire.core.db import to_sync_url

    _sql(f"ALTER TABLE {_PROBE_TABLE} ADD COLUMN {_PROBE_COLUMN} integer")
    try:
        completed = _run_alembic_check()
        combined = completed.stdout + completed.stderr

        # 先确认库上真的多了这一列：否则下面的断言没有判别力——加列失败时，
        # 过滤器再正确也看不到差异，用例会以**错误的原因**通过或失败。
        url = get_settings().database_url
        assert url, "未配置 DATABASE_URL"
        engine = create_engine(to_sync_url(url))
        try:
            columns = {column["name"] for column in inspect(engine).get_columns(_PROBE_TABLE)}
        finally:
            engine.dispose()
        assert _PROBE_COLUMN in columns, (
            f"探测列 {_PROBE_COLUMN} 未能加到 {_PROBE_TABLE} 上——本次核对没有真的制造出差异"
        )

        assert "remove_column" in combined, (
            "过滤器没有看到我方表上的差异（未提议 remove_column）——它可能已退化成"
            "「一律返回 False」或把本项目自己的表也排除了；这两种情况都会让"
            "**新增与改列全部失明**（而删表用例反而会因此通过）。\n"
            f"stdout:\n{completed.stdout[-3000:]}\n"
            f"stderr:\n{completed.stderr[-2000:]}"
        )
    finally:
        # 无论如何都要还原：这是对**集成库**的真实改动，留着会污染后续用例与开发环境。
        _sql(f"ALTER TABLE {_PROBE_TABLE} DROP COLUMN IF EXISTS {_PROBE_COLUMN}")
