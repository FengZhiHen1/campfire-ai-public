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
#: 表级删除表现为 ``remove_table``，索引级为 ``remove_index``。
_DROP_MARKERS = ("remove_table", "remove_index", "drop_table", "drop_index")


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


@pytest.fixture(autouse=True)
def _require_database() -> None:
    """未配置 `DATABASE_URL` 时跳过——**不假装通过**（仓库既有集成测试的统一做法）。

    ``alembic check`` 必须连库才有意义：它比较的是「我方元数据」与「数据库现状」，
    没有数据库就没有可比对象。
    """
    if not get_settings().database_url:
        pytest.skip("未配置 DATABASE_URL——集成测试需要 docker compose up -d postgres")


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

    # 正向断言：确认「无差异」是**真的比对过**，而不是检查没跑到。
    assert "No new upgrade operations detected" in combined, (
        "未看到 alembic 的『无新操作』结论——本用例可能没有真正完成比对"
        f"（空跑会让它永远通过）。\n输出尾部：\n{combined[-2000:]}"
    )


def test_filter_keeps_our_own_tables_in_scope() -> None:
    """反向守卫：过滤器是**白名单**，但不得把本项目自己的表排除掉。

    「不删外部表」有个廉价的错误实现——把 ``include_object`` 写成一律返回 False。
    那样上面那条用例会通过（没有删表提议），却同时让**新增与改列全部失明**。
    这里断言我方元数据非空且都在比较范围内，堵住那种实现。
    """
    # 我方元数据里的表（由 env.py 导入各模块模型时注册）。
    from campfire.core import pending_write as _pending_write  # noqa: F401
    from campfire.core.db import metadata
    from campfire.modules.library import models as _library  # noqa: F401
    from campfire.modules.memory import models as _memory  # noqa: F401

    ours = set(metadata.tables)
    assert ours, "我方元数据为空——过滤器会把本项目自己的表也当成外部表"

    # 每张我方表都必须能通过白名单判据（``reflected=True`` 时按名字放行）。
    external_names = {name for name in ours if not name.startswith(("campfire_", "data_"))}
    assert not external_names, f"我方表名不符合前缀约定，白名单判据可能失准：{sorted(external_names)}"
