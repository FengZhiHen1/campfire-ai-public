"""真实 tracing 路径的 `no_proxy` 回归（独立进程，不联网）。

守的缺陷（2026-10-29 评测侧实测）：OpenAI Agents SDK 的迹导出器
（`agents/tracing/processors.py` 的 `BackendSpanExporter`）在**第一次产生 trace 时**
惰性构造 `httpx2.Client(timeout=...)`。该客户端 `trust_env` 默认开启，于是宿主机
`no_proxy` 含方括号 IPv6 字面量（如 `[::1]`）时，构造期直接抛
`InvalidURL: Invalid port: ':1]'`——**在第一次模型请求之前**，表现为「只发出
`run_started`，然后再无下文」。

`main.py` / `worker.py` 有模块导入期的 `apply_no_proxy_normalization()`，但**非 main 的
程序内装配**（评测、脚本、批处理）不经那两个入口模块。修复点在
`AgentRunner.run` 的第一句（幂等），它不依赖「调用方记得先做什么」。

为什么用独立进程：`agents.tracing` 的导出器/处理器是**进程级懒初始化单例**——在测试
进程里跑到这里时它早就被前面的用例建好过，测不出「首次构造」这条路径。子进程同时也
天然隔离了线程与全局状态。

为什么用真实链路而不是替身：这条缺陷只在 `httpx2.Client` 真的读环境、真的解析
`no_proxy` 时出现；把导出器换成替身等于把被测的那一步删掉。

离线保证：子进程里删掉 `OPENAI_API_KEY`，导出器因此不会发出任何请求
（`_export_with_deadline` 在没有 key 时直接跳过并打一条 warning）；脚本里的模型替身
一被请求就抛错，所以整条运行不会产生任何外部连接。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

#: 子进程脚本：以「坏 `no_proxy` + 模型替身」跑一次真实运行。
#:
#: 打印四行固定前缀的结果，供用例断言；不打印任何凭据或使用者内容。
_PROBE = '''
import asyncio
import os
import tempfile

# 宿主机形态：方括号 IPv6 字面量混在列表里（实测本机就是这一串）。
os.environ["no_proxy"] = "127.0.0.1,localhost,::1,[::1]"
os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1,[::1]"
os.environ.pop("OPENAI_API_KEY", None)  # 离线：导出器没有 key 就不会发请求

from agents import ModelSettings
from agents.memory.session import Session
from agents.models.interface import Model

from campfire.agent.model import ModelBinding
from campfire.agent.runtime import AgentRunner, RunRequest
from campfire.agent.skill_runtime import SkillRegistry
from campfire.agent.tools import ToolPool

print("BEFORE:", os.environ["no_proxy"])


class _ExplodingModel(Model):
    """模型替身：本脚本只关心「建 trace 那一步」，模型一被请求就结束运行。"""

    async def get_response(self, *args, **kwargs):
        raise RuntimeError("本脚本不调模型")

    def stream_response(self, *args, **kwargs):
        raise RuntimeError("本脚本不调模型")


class _FakeSession(Session):
    def __init__(self) -> None:
        self.session_id = "probe-session"
        self.session_settings = None
        self.items = []

    async def get_items(self, limit=None):
        return list(self.items)

    async def add_items(self, items):
        self.items.extend(items)

    async def pop_item(self):
        return self.items.pop() if self.items else None

    async def clear_session(self):
        self.items.clear()


class _FakeCitations:
    async def add(self, record):
        return None

    async def list_for_run(self, run_id):
        return []


async def _main() -> None:
    runner = AgentRunner(
        binding=ModelBinding(name="probe", model=_ExplodingModel(), settings=ModelSettings()),
        tools=ToolPool([]),
        skills=SkillRegistry.discover(tempfile.mkdtemp()),
        citations=_FakeCitations(),
        sessions=lambda session_id: _FakeSession(),
    )
    request = RunRequest(session_id="probe-session", surface=None, instructions="静态系统提示")
    events = [event async for event in runner.run(request)]

    import agents.tracing.processors as processors

    exporter = processors._global_exporter
    print("EXPORTER:", type(exporter).__name__ if exporter is not None else "None")
    print("AFTER:", os.environ["no_proxy"])
    print("EVENTS:", [type(event).__name__ for event in events])


asyncio.run(_main())
'''


def _run_probe(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """在独立进程里跑探针脚本（继承当前环境，脚本自己覆盖 `no_proxy`）。"""
    script = tmp_path / "tracing_probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=180,
        env=env,
    )


def test_run_normalises_no_proxy_before_the_tracing_exporter_is_built(tmp_path: Path) -> None:
    """一次运行结束后：环境已规范化、真实导出器已建成、事件流以带码失败收尾。

    三条断言各有用处：

    - `BEFORE` 含 `[::1]`：证明坏取值确实进入了子进程（否则本用例什么都没测到）；
    - `AFTER` 无方括号：规范化发生在 `run()` 内部，而不是父进程顺手代劳；
    - `EXPORTER: BackendSpanExporter`：真实 tracing 路径走通了——这条是缺陷本体的回归
      证据（修复前这里会以 `InvalidURL: Invalid port: ':1]'` 崩掉，且 `EVENTS` 只剩
      一个 `RunStartedEvent`）；
    - `EVENTS` 以 `RunFailedEvent` 收尾：运行没有「只开始不结束」。
    """
    result = _run_probe(tmp_path)

    assert result.returncode == 0, f"子进程失败：\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    lines = dict(line.split(":", 1) for line in result.stdout.splitlines() if ":" in line)

    assert "[::1]" in lines["BEFORE"], "探针没有拿到宿主机形态的 no_proxy，本用例失去判别力"
    assert "[" not in lines["AFTER"], "run() 必须在建 trace 之前把方括号 IPv6 规范化掉"
    assert "::1" in lines["AFTER"], "规范化只改词法：非方括号形式必须保留（否则豁免语义变了）"
    assert lines["EXPORTER"].strip() == "BackendSpanExporter", "真实迹导出器必须构造成功"
    assert lines["EVENTS"].strip() == "['RunStartedEvent', 'RunFailedEvent']", (
        "运行必须以带码失败结束，而不是只发出 run_started 就没了"
    )
