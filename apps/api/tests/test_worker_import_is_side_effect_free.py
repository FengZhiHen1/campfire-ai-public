"""`import campfire.worker` 不得改变全局装配状态（QA-04 的回归守卫）。

## 为什么需要这个文件

`main.py` 为了拿投递函数会 `from campfire.worker import dispatch_pending_write_to_queue`。
此前 `worker.py` 在**模块顶层**调 `set_dispatch_hook(...)`，于是「import 本模块」在**任何**
进程里都把真钩子装上——包括测试进程。后果是集成测试真的把任务投进 Redis，另一端若有 Worker
（尤其孤儿 Worker）在消费，记录被它置 `done`，测试自己的模拟消费就领不到，表现为「同一组合
跑出不同失败项、单跑各文件全绿」的间歇性假失败（2026-10-06 实测：无 Worker 时 5 次全绿，
有真 Worker 时 5 次全失败）。

2026-10-28 起钩子改在 `WORKER_STARTUP` 事件里装。这条判据必须由**独立子进程**验证：
本进程里早就有别的模块装过钩子（`TestClient(app)` 的 lifespan 会装），在同一个进程里
断言「import 之后钩子是 None」根本证明不了 import 有没有副作用。

边界：只跑 `python -c`，不连数据库/Redis/队列——判据是「装没装」，不是「投递通不通」。
"""

from __future__ import annotations

import subprocess
import sys

# 判据脚本：导入模块后直接读 `core/jobs` 的装配位。
# 该模块只提供 setter、没有 getter，因此这里读私有字段——判据就是「这个私有装配位有没有被
# import 碰到」，用公开 API 反而看不到。
PROBE = """
import campfire.worker  # noqa: F401 —— 被测的就是这行 import 的副作用
from campfire.core import jobs
print("hook-is-none" if jobs._dispatch_hook is None else "hook-is-set")
"""


def test_importing_worker_does_not_install_the_dispatch_hook() -> None:
    """import 之后钩子必须仍是未设置状态：装配是入口的事，不是 import 的事。"""
    result = subprocess.run(  # noqa: S603 —— 参数固定，不拼接任何外部输入
        [sys.executable, "-c", PROBE],
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )

    assert result.stdout.strip() == "hook-is-none", (
        "import campfire.worker 装了投递钩子：集成测试会因此真的把任务投进队列，"
        f"与消费方竞速后表现为间歇性假失败（实测见本文件模块说明）。实际输出：{result.stdout!r}"
        f" 标准错误：{result.stderr!r}"
    )


def test_worker_startup_event_still_installs_the_hook() -> None:
    """挪位置不等于漏装：Worker 启动事件里必须真的把钩子装回去。

    判据直接调那个 startup 处理函数（不需要真的拉起 Taskiq），然后看装配位。
    这条是上一条的对照臂：只证明「import 不装」而忘了「启动要装」，
    Worker 进程里就没有投递能力，兜底扫描重投全部落进 warning。
    """
    probe = """
import asyncio, inspect
import campfire.worker as worker
from campfire.core import jobs

handler = worker._install_dispatch_hook
asyncio.run(handler(object()))
print("hook-is-set" if jobs._dispatch_hook is not None else "hook-is-none")
"""
    result = subprocess.run(  # noqa: S603 —— 参数固定，不拼接任何外部输入
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )

    assert result.stdout.strip() == "hook-is-set", (
        f"Worker 启动后没有装投递钩子，兜底扫描将无法重投。实际输出：{result.stdout!r} 标准错误：{result.stderr!r}"
    )
